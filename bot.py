import asyncio
import csv
import html
import io
import json
import re
from datetime import date, timedelta
from pathlib import Path
from urllib.request import urlopen

from telethon import TelegramClient, events
from telethon.network import (
    ConnectionTcpMTProxyAbridged,
    ConnectionTcpMTProxyIntermediate,
    ConnectionTcpMTProxyRandomizedIntermediate,
)

ROOT = Path(__file__).resolve().parent


def load_dotenv() -> dict[str, str]:
    env: dict[str, str] = {}
    path = ROOT / ".env"
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip()
    return env


def load_users() -> dict[str, dict]:
    path = ROOT / "users.json"
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return {}
    data = json.loads(raw)
    return {k.lower(): v for k, v in data.items()}


def save_users(users: dict[str, dict]) -> None:
    ordered = {k: users[k] for k in sorted(users)}
    (ROOT / "users.json").write_text(
        json.dumps(ordered, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def parse_csv(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


def fetch_sheet(sheet_id: str, sheet_gid: str) -> list[list[str]]:
    url = (
        f"https://docs.google.com/spreadsheets/d/{sheet_id}/"
        f"gviz/tq?tqx=out:csv&gid={sheet_gid}"
    )
    with urlopen(url, timeout=30) as resp:
        return parse_csv(resp.read().decode("utf-8"))


def get_plan_for_date(sheet_id: str, sheet_gid: str, target: date) -> dict:
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
                if not names_cell and not addr:
                    continue
                surnames = [s.strip() for s in names_cell.split("\\") if s.strip()]
                if not surnames:
                    continue
                items.append({"surnames": surnames, "address": addr})
            return {"date": want, "items": items}

    return {"date": want, "items": items}


def mention(surname: str, users: dict[str, dict]) -> str:
    key = surname.lower()
    if key in users and users[key].get("id"):
        uid = users[key]["id"]
        return f'<a href="tg://user?id={uid}">{html.escape(surname)}</a>'
    return html.escape(surname)


def build_plan_message(plan: dict, users: dict[str, dict]) -> str:
    if not plan["items"]:
        return f"На {plan['date']} в вкладке «планирование» нет строк."

    lines = [f"<b>{html.escape(plan['date'])}</b>", ""]
    for item in plan["items"]:
        tags = ", ".join(mention(s, users) for s in item["surnames"])
        addr = item["address"]
        if addr:
            lines.append(f"{tags} — {html.escape(addr)}")
        else:
            lines.append(f"{tags} — адрес не указан")

    unbound: list[str] = []
    for item in plan["items"]:
        for s in item["surnames"]:
            if s.lower() not in users:
                unbound.append(s)
    unbound = sorted(set(unbound))
    if unbound:
        lines.extend(
            [
                "",
                "Не привязаны (напишите боту в личку <code>/bind Фамилия</code>): "
                + ", ".join(html.escape(x) for x in unbound),
            ]
        )
    return "\n".join(lines)


async def main() -> None:
    env = load_dotenv()
    token = env.get("BOT_TOKEN", "")
    sheet_id = env.get("SHEET_ID", "")
    sheet_gid = env.get("SHEET_GID", "")
    api_id = env.get("API_ID", "2040")
    api_hash = env.get("API_HASH", "b18441a1ff607e10a989891aafc2decb")

    if not token:
        raise SystemExit("BOT_TOKEN пустой в .env")

    proxy_host = env.get("MTPROXY_HOST", "ha9d3q.d0e-correo.com")
    proxy_port = int(env.get("MTPROXY_PORT", "443"))
    proxy_secret = env.get(
        "MTPROXY_SECRET",
        "ee45ebf73361ff34fd215fda4917ea27796175746f2e7275",
    )

    users = load_users()

    proxy = (proxy_host, proxy_port, proxy_secret)
    conn_types = [
        ("Randomized", ConnectionTcpMTProxyRandomizedIntermediate),
        ("Intermediate", ConnectionTcpMTProxyIntermediate),
        ("Abridged", ConnectionTcpMTProxyAbridged),
    ]

    client = None
    last_err = None
    for name, conn_cls in conn_types:
        try:
            print(f"Пробую MTProxy ({name})...")
            trial = TelegramClient(
                str(ROOT / "bot_session"),
                int(api_id),
                api_hash,
                connection=conn_cls,
                proxy=proxy,
            )
            await asyncio.wait_for(trial.connect(), timeout=20)
            if trial.is_connected():
                client = trial
                print(f"Подключено через {name}")
                break
            await trial.disconnect()
        except Exception as exc:
            last_err = exc
            print(f"  не вышло: {exc}")

    if not client:
        raise SystemExit(
            f"MTProto-прокси не подключился: {last_err}\n\n"
            "Вариант: задеплойте bot_webhook.py на Render.com (бесплатно) — "
            "там Telegram доступен без VPN.\n"
            "1) Залейте папку plan-bot на GitHub\n"
            "2) render.com → New → Blueprint → render.yaml\n"
            "3) Укажите BOT_TOKEN и WEBHOOK_URL=https://ваш-сервис.onrender.com"
        )

    await client.start(bot_token=token)
    me = await client.get_me()
    print(f"Бот @{me.username} запущен. В группе напишите /plan")

    @client.on(events.NewMessage(pattern=r"^/start(?:@\w+)?(?:\s|$)"))
    async def cmd_start(event: events.NewMessage.Event) -> None:
        await event.respond(
            "Привет. Я читаю вкладку «планирование» в Google Таблице.\n"
            "В группе: /plan — адреса на сегодня, /tomorrow — на завтра.\n"
            "В личке: /bind Фамилия — чтобы я мог тегать вас в чате.\n"
            f"Этот чат id: <code>{event.chat_id}</code>",
            parse_mode="html",
        )

    @client.on(events.NewMessage(pattern=r"^/chatid(?:@\w+)?(?:\s|$)"))
    async def cmd_chatid(event: events.NewMessage.Event) -> None:
        await event.respond(f"chat id: <code>{event.chat_id}</code>", parse_mode="html")

    @client.on(events.NewMessage(pattern=r"^/bind(?:@\w+)?(?:\s|$)"))
    async def cmd_bind(event: events.NewMessage.Event) -> None:
        text = (event.raw_text or "").strip()
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await event.respond("Напишите: /bind Иванов")
            return
        surname = parts[1].split()[0].strip()
        sender = await event.get_sender()
        users[surname.lower()] = {
            "id": sender.id,
            "username": getattr(sender, "username", "") or "",
            "first_name": getattr(sender, "first_name", "") or "",
        }
        save_users(users)
        await event.respond(
            f"Готово: <b>{html.escape(surname)}</b> → {mention(surname, users)}",
            parse_mode="html",
        )

    @client.on(events.NewMessage(pattern=r"^/who(?:@\w+)?(?:\s|$)"))
    async def cmd_who(event: events.NewMessage.Event) -> None:
        if not users:
            await event.respond("Пока никто не привязан. /bind Фамилия")
            return
        lines = []
        for key in sorted(users):
            u = users[key]
            un = f"@{u['username']}" if u.get("username") else u.get("first_name", "")
            lines.append(f"{html.escape(key)} — {html.escape(un)} (<code>{u['id']}</code>)")
        await event.respond("Привязки:\n" + "\n".join(lines), parse_mode="html")

    @client.on(events.NewMessage(pattern=r"^/unbind(?:@\w+)?(?:\s|$)"))
    async def cmd_unbind(event: events.NewMessage.Event) -> None:
        text = (event.raw_text or "").strip()
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await event.respond("Напишите: /unbind Иванов")
            return
        key = parts[1].split()[0].strip().lower()
        if key in users:
            del users[key]
            save_users(users)
            await event.respond(f"Снял привязку {html.escape(key)}", parse_mode="html")
        else:
            await event.respond("Такой фамилии нет в привязках")

    async def send_plan(event: events.NewMessage.Event, target: date) -> None:
        try:
            plan = get_plan_for_date(sheet_id, sheet_gid, target)
            await event.respond(build_plan_message(plan, users), parse_mode="html")
        except Exception as exc:
            await event.respond(
                f"Не смог прочитать таблицу: {html.escape(str(exc))}",
                parse_mode="html",
            )

    @client.on(events.NewMessage(pattern=r"^/(?:plan|today)(?:@\w+)?(?:\s|$)"))
    async def cmd_plan(event: events.NewMessage.Event) -> None:
        await send_plan(event, date.today())

    @client.on(events.NewMessage(pattern=r"^/tomorrow(?:@\w+)?(?:\s|$)"))
    async def cmd_tomorrow(event: events.NewMessage.Event) -> None:
        await send_plan(event, date.today() + timedelta(days=1))

    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
