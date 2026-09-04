"""Общая логика бота (локально и в облаке)."""
import csv
import html
import io
import json
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.request import urlopen
from zoneinfo import ZoneInfo

import httpx

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
SENT_LOG_PATH = ROOT / "sent_log.json"
MORNING_TEXT = "Всем доброе утро, господа!\nХорошего рабочего дня"


def env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def load_config() -> dict:
    cfg = {}
    if CONFIG_PATH.exists():
        cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8") or "{}"))
    if env("CHAT_PLANNING_ID"):
        cfg["planning_chat_id"] = int(env("CHAT_PLANNING_ID"))
    if env("CHAT_MORNING_ID"):
        cfg["morning_chat_id"] = int(env("CHAT_MORNING_ID"))
    return cfg


def save_config(cfg: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def load_sent_log() -> dict:
    if SENT_LOG_PATH.exists():
        return json.loads(SENT_LOG_PATH.read_text(encoding="utf-8") or "{}")
    return {}


def save_sent_log(log: dict) -> None:
    SENT_LOG_PATH.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")


def already_sent(key: str) -> bool:
    return bool(load_sent_log().get(key))


def mark_sent(key: str) -> None:
    log = load_sent_log()
    log[key] = datetime.now().isoformat()
    save_sent_log(log)


def clear_sent(key: str) -> None:
    log = load_sent_log()
    log.pop(key, None)
    save_sent_log(log)


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
    return "\n".join(lines)


def build_plain_plan(plan: dict) -> str:
    lines = [f"На {plan['date']}"]
    for item in plan["items"]:
        names, addr = item["names"], item["address"]
        if names and addr:
            lines.append(f"{names} - {addr}")
        elif names:
            lines.append(names)
        elif addr:
            lines.append(addr)
    if len(lines) == 1:
        lines.append("(нет данных в таблице)")
    return "\n".join(lines)


class TelegramBot:
    def __init__(self):
        self.token = env("BOT_TOKEN")
        self.sheet_id = env("SHEET_ID", "1v1ckAB5VTzs2KpAgcJyPDg10c1u5INYo04Y-98j2FhA")
        self.sheet_gid = env("SHEET_GID", "1120480242")
        self.tz = ZoneInfo(env("TIMEZONE", "Asia/Novokuznetsk"))
        api_base = env("TELEGRAM_API_URL", "https://api.telegram.org").rstrip("/")
        headers = {}
        if secret := env("BOT_SECRET"):
            headers["X-Bot-Secret"] = secret
        self.api_base = api_base
        self.client = httpx.Client(timeout=60, headers=headers)
        self.config = load_config()
        self.users = load_users()

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

    def send_evening_plan(self) -> str:
        chat_id = self.config.get("planning_chat_id")
        if not chat_id:
            return "planning chat not set"
        tomorrow = datetime.now(self.tz).date() + timedelta(days=1)
        key = f"plan_{tomorrow.isoformat()}"
        if already_sent(key):
            return f"already sent plan for {tomorrow}"
        try:
            plan = get_plan(self.sheet_id, self.sheet_gid, tomorrow)
            self.send_plain(chat_id, build_plain_plan(plan))
            mark_sent(key)
            return f"sent plan for {plan['date']} to {chat_id}"
        except Exception as exc:
            clear_sent(key)
            raise exc

    def send_morning_greeting(self) -> str:
        chat_id = self.config.get("morning_chat_id")
        if not chat_id:
            return "morning chat not set"
        now = datetime.now(self.tz)
        if now.weekday() >= 5:
            return "weekend, skip"
        key = f"morning_{now.date().isoformat()}"
        if already_sent(key):
            return f"already sent morning for {now.date()}"
        try:
            self.send_plain(chat_id, MORNING_TEXT)
            mark_sent(key)
            return f"sent morning to {chat_id}"
        except Exception as exc:
            clear_sent(key)
            raise exc

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
                "Бот планирования (облако).\n/plan /tomorrow /planplain\n"
                "/bind /setplanning /setmorning /chatid\n"
                f"chat id: <code>{chat_id}</code>"
            ))
        elif cmd == "/chatid":
            self.send_html(chat_id, f"chat id: <code>{chat_id}</code>")
        elif cmd == "/setplanning":
            self.config["planning_chat_id"] = chat_id
            save_config(self.config)
            self.send_plain(chat_id, f"Чат планирования: {chat_id}")
        elif cmd == "/setmorning":
            self.config["morning_chat_id"] = chat_id
            save_config(self.config)
            self.send_plain(chat_id, f"Чат утра: {chat_id}")
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
            self.send_html(chat_id, build_tagged_message(get_plan(self.sheet_id, self.sheet_gid, date.today()), self.users))
        elif cmd == "/tomorrow":
            self.send_html(
                chat_id,
                build_tagged_message(get_plan(self.sheet_id, self.sheet_gid, date.today() + timedelta(days=1)), self.users),
            )
        elif cmd == "/planplain":
            target = date.today() + timedelta(days=1) if not arg else datetime.strptime(arg, "%d.%m.%Y").date()
            self.send_plain(chat_id, build_plain_plan(get_plan(self.sheet_id, self.sheet_gid, target)))
