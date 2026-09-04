"""Бот планирования: команды + расписание."""
import csv
import html
import io
import json
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.request import urlopen
from zoneinfo import ZoneInfo

import httpx
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
SENT_LOG_PATH = ROOT / "sent_log.json"

MORNING_TEXT = "Всем доброе утро, господа!\nХорошего рабочего дня"


def load_dotenv() -> dict[str, str]:
    env: dict[str, str] = {}
    path = ROOT / ".env"
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def load_config() -> dict:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8") or "{}")
    return {}


def save_config(cfg: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def load_sent_log() -> dict:
    if SENT_LOG_PATH.exists():
        return json.loads(SENT_LOG_PATH.read_text(encoding="utf-8") or "{}")
    return {}


def save_sent_log(log: dict) -> None:
    SENT_LOG_PATH.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")


def mark_sent(key: str) -> bool:
    """True если уже отправляли сегодня (ключ с датой)."""
    log = load_sent_log()
    if log.get(key):
        return True
    log[key] = datetime.now().isoformat()
    save_sent_log(log)
    return False


def load_users() -> dict[str, dict]:
    path = ROOT / "users.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8") or "{}")
    return {k.lower(): v for k, v in data.items()}


def save_users(users: dict[str, dict]) -> None:
    ordered = {k: users[k] for k in sorted(users)}
    (ROOT / "users.json").write_text(
        json.dumps(ordered, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def fetch_sheet(sheet_id: str, sheet_gid: str) -> list[list[str]]:
    url = (
        f"https://docs.google.com/spreadsheets/d/{sheet_id}/"
        f"gviz/tq?tqx=out:csv&gid={sheet_gid}"
    )
    with urlopen(url, timeout=30) as resp:
        return list(csv.reader(io.StringIO(resp.read().decode("utf-8"))))


def get_plan(sheet_id: str, sheet_gid: str, target: date) -> dict:
    want = target.strftime("%d.%m.%Y")
    rows = fetch_sheet(sheet_id, sheet_gid)
    items: list[dict] = []
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            if cell != want:
                continue
            addr_col = c + 1
            for nxt in rows[r + 1 :]:
                names_cell = nxt[c] if c < len(nxt) else ""
                if re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", names_cell or ""):
                    break
                addr = nxt[addr_col].strip() if addr_col < len(nxt) else ""
                names_cell = (names_cell or "").strip()
                if not names_cell and not addr:
                    continue
                items.append({"names": names_cell, "address": addr})
            return {"date": want, "items": items}
    return {"date": want, "items": items}


def mention(surname: str, users: dict[str, dict]) -> str:
    key = surname.lower()
    if key in users and users[key].get("id"):
        uid = users[key]["id"]
        return f'<a href="tg://user?id={uid}">{html.escape(surname)}</a>'
    return html.escape(surname)


def build_tagged_message(plan: dict, users: dict[str, dict]) -> str:
    if not plan["items"]:
        return f"На {plan['date']} в вкладке «планирование» нет строк."
    lines = [f"<b>{html.escape(plan['date'])}</b>", ""]
    for item in plan["items"]:
        surnames = [s.strip() for s in item["names"].split("\\") if s.strip()]
        tags = ", ".join(mention(s, users) for s in surnames) if surnames else html.escape(item["names"])
        addr = item["address"]
        lines.append(f"{tags} — {html.escape(addr) if addr else 'адрес не указан'}")
    unbound = sorted(
        {s for i in plan["items"] for s in i["names"].split("\\") if s.strip() and s.strip().lower() not in users}
    )
    if unbound:
        lines += ["", "Не привязаны (/bind Фамилия): " + ", ".join(html.escape(x) for x in unbound)]
    return "\n".join(lines)


def build_plain_plan(plan: dict) -> str:
    lines = [f"На {plan['date']}"]
    for item in plan["items"]:
        names = item["names"]
        addr = item["address"]
        if names and addr:
            lines.append(f"{names} - {addr}")
        elif names:
            lines.append(names)
        elif addr:
            lines.append(addr)
    if len(lines) == 1:
        lines.append("(нет данных в таблице)")
    return "\n".join(lines)


class Bot:
    def __init__(self, token: str, api_base: str, secret: str, sheet_id: str, sheet_gid: str, tz_name: str):
        self.token = token
        self.api_base = api_base.rstrip("/")
        self.secret = secret
        self.sheet_id = sheet_id
        self.sheet_gid = sheet_gid
        self.tz = ZoneInfo(tz_name)
        self.offset = 0
        self.users = load_users()
        self.config = load_config()
        self.client = httpx.Client(timeout=60, headers={"X-Bot-Secret": secret})
        self.scheduler = BackgroundScheduler(timezone=self.tz)

    def call(self, method: str, **kwargs) -> dict:
        url = f"{self.api_base}/bot{self.token}/{method}"
        r = self.client.post(url, json=kwargs)
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(data.get("description", "Telegram API error"))
        return data

    def send_html(self, chat_id: int, text: str) -> None:
        self.call("sendMessage", chat_id=chat_id, text=text, parse_mode="HTML")

    def send_plain(self, chat_id: int, text: str) -> None:
        self.call("sendMessage", chat_id=chat_id, text=text)

    def planning_chat_id(self) -> int | None:
        cid = self.config.get("planning_chat_id")
        return int(cid) if cid else None

    def morning_chat_id(self) -> int | None:
        cid = self.config.get("morning_chat_id")
        return int(cid) if cid else None

    def job_evening_plan(self) -> None:
        chat_id = self.planning_chat_id()
        if not chat_id:
            print("18:00 — чат планирования не задан (/setplanning в нужном чате)")
            return
        tomorrow = datetime.now(self.tz).date() + timedelta(days=1)
        key = f"plan_{tomorrow.isoformat()}"
        if mark_sent(key):
            return
        try:
            plan = get_plan(self.sheet_id, self.sheet_gid, tomorrow)
            text = build_plain_plan(plan)
            self.send_plain(chat_id, text)
            print(f"18:00 — отправлен план на {plan['date']} в {chat_id}")
        except Exception as exc:
            print(f"18:00 — ошибка: {exc}")
            log = load_sent_log()
            log.pop(key, None)
            save_sent_log(log)

    def job_morning_greeting(self) -> None:
        chat_id = self.morning_chat_id()
        if not chat_id:
            print("9:00 — чат «мужской чат» не задан (/setmorning в нужном чате)")
            return
        today = datetime.now(self.tz).date().isoformat()
        key = f"morning_{today}"
        if mark_sent(key):
            return
        try:
            self.send_plain(chat_id, MORNING_TEXT)
            print(f"9:00 — утреннее сообщение в {chat_id}")
        except Exception as exc:
            print(f"9:00 — ошибка: {exc}")
            log = load_sent_log()
            log.pop(key, None)
            save_sent_log(log)

    def setup_scheduler(self, plan_time: str, morning_time: str) -> None:
        ph, pm = plan_time.split(":")
        mh, mm = morning_time.split(":")
        self.scheduler.add_job(
            self.job_evening_plan,
            CronTrigger(hour=int(ph), minute=int(pm), timezone=self.tz),
            id="evening_plan",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.job_morning_greeting,
            CronTrigger(day_of_week="mon-fri", hour=int(mh), minute=int(mm), timezone=self.tz),
            id="morning_greeting",
            replace_existing=True,
        )
        self.scheduler.start()
        print(f"Расписание: план на завтра в {plan_time}, утро пн-пт в {morning_time} ({self.tz.key})")

    def handle(self, msg: dict) -> None:
        text = msg.get("text") or ""
        if not text.startswith("/"):
            return
        chat_id = msg["chat"]["id"]
        cmd = text.split()[0].split("@")[0].lower()
        arg = text.split(maxsplit=1)[1].strip() if " " in text else ""
        sender = msg.get("from", {})

        if cmd == "/start":
            self.send_html(chat_id, (
                "Бот планирования.\n"
                "/plan — сегодня (с тегами)\n"
                "/tomorrow — завтра (с тегами)\n"
                "/planplain — завтра plain (как в 18:00)\n"
                "/bind Фамилия — привязка\n"
                "/chatid — id этого чата\n"
                "/setplanning — назначить чат «планирование»\n"
                "/setmorning — назначить чат «мужской чат»\n"
                f"chat id: <code>{chat_id}</code>"
            ))
        elif cmd == "/chatid":
            self.send_html(chat_id, f"chat id: <code>{chat_id}</code>")
        elif cmd == "/setplanning":
            self.config["planning_chat_id"] = chat_id
            save_config(self.config)
            self.send_plain(chat_id, f"Чат планирования сохранён (id {chat_id})")
        elif cmd == "/setmorning":
            self.config["morning_chat_id"] = chat_id
            save_config(self.config)
            self.send_plain(chat_id, f"Чат утренних сообщений сохранён (id {chat_id})")
        elif cmd == "/bind" and arg:
            surname = arg.split()[0]
            self.users[surname.lower()] = {
                "id": sender["id"],
                "username": sender.get("username") or "",
                "first_name": sender.get("first_name") or "",
            }
            save_users(self.users)
            self.send_html(chat_id, f"Готово: <b>{html.escape(surname)}</b>")
        elif cmd in ("/plan", "/today"):
            try:
                self.send_html(chat_id, build_tagged_message(get_plan(self.sheet_id, self.sheet_gid, date.today()), self.users))
            except Exception as e:
                self.send_html(chat_id, f"Ошибка таблицы: {html.escape(str(e))}")
        elif cmd == "/tomorrow":
            try:
                self.send_html(
                    chat_id,
                    build_tagged_message(
                        get_plan(self.sheet_id, self.sheet_gid, date.today() + timedelta(days=1)),
                        self.users,
                    ),
                )
            except Exception as e:
                self.send_html(chat_id, f"Ошибка таблицы: {html.escape(str(e))}")
        elif cmd == "/planplain":
            try:
                target = date.today() + timedelta(days=1) if not arg else datetime.strptime(arg, "%d.%m.%Y").date()
                self.send_plain(chat_id, build_plain_plan(get_plan(self.sheet_id, self.sheet_gid, target)))
            except Exception as e:
                self.send_plain(chat_id, f"Ошибка: {e}")
        elif cmd == "/who":
            if not self.users:
                self.send_html(chat_id, "Никто не привязан")
            else:
                lines = [f"{html.escape(k)} — <code>{v['id']}</code>" for k, v in sorted(self.users.items())]
                self.send_html(chat_id, "Привязки:\n" + "\n".join(lines))

    def run(self, plan_time: str, morning_time: str) -> None:
        me = self.call("getMe")["result"]
        print(f"Бот @{me['username']} запущен.")
        self.setup_scheduler(plan_time, morning_time)
        pc, mc = self.planning_chat_id(), self.morning_chat_id()
        if pc:
            print(f"Чат планирования: {pc}")
        else:
            print("Чат планирования не задан — напишите /setplanning в «мужские домофоны - планирование»")
        if mc:
            print(f"Чат утра: {mc}")
        else:
            print("Чат утра не задан — напишите /setmorning в «мужские домофоны - мужской чат»")

        while True:
            try:
                data = self.call("getUpdates", timeout=30, offset=self.offset)
                for upd in data.get("result", []):
                    self.offset = upd["update_id"] + 1
                    msg = upd.get("message") or upd.get("edited_message")
                    if msg:
                        self.handle(msg)
            except Exception as exc:
                print(f"ошибка: {exc}")
                time.sleep(3)


def main() -> None:
    env = load_dotenv()
    token = env.get("BOT_TOKEN", "")
    api_base = env.get("TELEGRAM_API_URL", "").strip()
    secret = env.get("BOT_SECRET", "plan-bot-secret-change-me")
    sheet_id = env.get("SHEET_ID", "")
    sheet_gid = env.get("SHEET_GID", "")
    tz_name = env.get("TIMEZONE", "Asia/Novokuznetsk")
    plan_time = env.get("PLAN_TIME", "18:00")
    morning_time = env.get("MORNING_TIME", "09:00")

    if not token:
        raise SystemExit("BOT_TOKEN пустой")
    if not api_base:
        raise SystemExit("Нужен TELEGRAM_API_URL в .env")

    cfg = load_config()
    if env.get("CHAT_PLANNING_ID") and not cfg.get("planning_chat_id"):
        cfg["planning_chat_id"] = int(env["CHAT_PLANNING_ID"])
    if env.get("CHAT_MORNING_ID") and not cfg.get("morning_chat_id"):
        cfg["morning_chat_id"] = int(env["CHAT_MORNING_ID"])
    save_config(cfg)

    Bot(token, api_base, secret, sheet_id, sheet_gid, tz_name).run(plan_time, morning_time)


if __name__ == "__main__":
    main()
