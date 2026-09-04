"""Облачный запуск: webhook + cron-эндпоинты для расписания."""
import os

from flask import Flask, request

from bot_core import TelegramBot, env

app = Flask(__name__)
bot = TelegramBot()


@app.get("/")
def health():
    return "plan-bot ok", 200


@app.post(f"/webhook/{env('BOT_TOKEN')}")
def webhook():
    data = request.get_json(force=True, silent=True) or {}
    msg = data.get("message") or data.get("edited_message")
    if msg:
        bot.handle(msg)
    return "ok", 200


@app.post("/cron/evening")
def cron_evening():
    if request.headers.get("Authorization") != f"Bearer {env('CRON_SECRET')}":
        return "forbidden", 403
    try:
        return bot.send_evening_plan(), 200
    except Exception as exc:
        return str(exc), 500


@app.post("/cron/morning")
def cron_morning():
    if request.headers.get("Authorization") != f"Bearer {env('CRON_SECRET')}":
        return "forbidden", 403
    try:
        return bot.send_morning_greeting(), 200
    except Exception as exc:
        return str(exc), 500


def setup_webhook() -> None:
    url = env("WEBHOOK_URL") or env("RENDER_EXTERNAL_URL")
    if not url or not bot.token:
        return
    webhook_url = f"{url.rstrip('/')}/webhook/{bot.token}"
    bot.call("deleteWebhook")
    bot.call("setWebhook", url=webhook_url)
    print(f"Webhook: {webhook_url}")


if __name__ == "__main__":
    setup_webhook()
    port = int(env("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
