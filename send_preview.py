"""Разовая отправка превью плана пользователю @Vafikk."""
import sys
from datetime import date
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from bot_http import build_plain_plan, get_plan, load_dotenv

env = load_dotenv()
token = env["BOT_TOKEN"]
api = env["TELEGRAM_API_URL"].rstrip("/")
secret = env["BOT_SECRET"]

# 06.09.2026 в 18:00 бот шлёт план на завтра = 07.09.2026
plan = get_plan(env["SHEET_ID"], env["SHEET_GID"], date(2026, 9, 7))
text = "Превью сообщения на 06.09.2026 в 18:00:\n\n" + build_plain_plan(plan)
print(text)
print("---")

client = httpx.Client(timeout=30, headers={"X-Bot-Secret": secret})
base = f"{api}/bot{token}"

uid = None
resp = client.post(f"{base}/getUpdates", json={"limit": 100}).json()
for upd in resp.get("result", []):
    msg = upd.get("message") or upd.get("edited_message") or {}
    user = msg.get("from") or {}
    if (user.get("username") or "").lower() == "vafikk":
        uid = user["id"]
        break

if not uid:
    print("Не нашёл @Vafikk — напишите боту /start в личке.")
    sys.exit(1)

send = client.post(f"{base}/sendMessage", json={"chat_id": uid, "text": text}).json()
if send.get("ok"):
    print(f"Отправлено @Vafikk (id {uid})")
else:
    print("Ошибка:", send)
    sys.exit(1)
