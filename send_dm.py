#!/usr/bin/env python3
import json
import sys

import httpx
from bot_core import env, load_config

username = sys.argv[1].lstrip("@")
text = sys.argv[2] if len(sys.argv) > 2 else "Привет!"

token = env("BOT_TOKEN")
api = env("TELEGRAM_API_URL", "https://api.telegram.org").rstrip("/")
secret = env("BOT_SECRET", "")
headers = {"X-Bot-Secret": secret} if secret and "workers.dev" in api else {}
client = httpx.Client(timeout=30, headers=headers)
base = f"{api}/bot{token}"


def find_user_id() -> int | None:
    r = client.post(f"{base}/getUpdates", json={"limit": 100})
    for upd in r.json().get("result", []):
        for key in ("message", "edited_message", "callback_query"):
            obj = upd.get(key)
            if not obj:
                continue
            frm = obj.get("from") or (obj.get("message") or {}).get("from")
            if frm and (frm.get("username") or "").lower() == username.lower():
                return frm["id"]

    cfg = load_config()
    chat_id = cfg.get("planning_chat_id") or env("CHAT_PLANNING_ID")
    if chat_id:
        admins = client.post(f"{base}/getChatAdministrators", json={"chat_id": chat_id}).json()
        for member in admins.get("result", []):
            user = member.get("user", {})
            if (user.get("username") or "").lower() == username.lower():
                return user["id"]
    return None


user_id = find_user_id()
if not user_id:
    print(f"Не нашёл @{username}. Пусть напишет /start боту @Vafikk_bot")
    sys.exit(1)

resp = client.post(
    f"{base}/sendMessage",
    json={"chat_id": user_id, "text": text},
).json()
print(json.dumps(resp, ensure_ascii=False, indent=2))
sys.exit(0 if resp.get("ok") else 1)
