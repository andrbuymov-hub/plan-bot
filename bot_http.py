"""Локальный запуск: polling через Cloudflare Worker."""
import os
import time

from bot_core import TelegramBot, env, load_config, save_config


def main() -> None:
    if not env("BOT_TOKEN"):
        raise SystemExit("BOT_TOKEN пустой")
    if not env("TELEGRAM_API_URL"):
        raise SystemExit("Нужен TELEGRAM_API_URL в .env")

    cfg = load_config()
    if env("CHAT_PLANNING_ID") and not cfg.get("planning_chat_id"):
        cfg["planning_chat_id"] = int(env("CHAT_PLANNING_ID"))
    if env("CHAT_MORNING_ID") and not cfg.get("morning_chat_id"):
        cfg["morning_chat_id"] = int(env("CHAT_MORNING_ID"))
    if env("PLANNING_TOPIC_ID") and not cfg.get("planning_topic_id"):
        cfg["planning_topic_id"] = int(env("PLANNING_TOPIC_ID"))
    if env("MORNING_TOPIC_ID") and not cfg.get("morning_topic_id"):
        cfg["morning_topic_id"] = int(env("MORNING_TOPIC_ID"))
    save_config(cfg)

    bot = TelegramBot()
    offset = 0
    me = bot.call("getMe")["result"]
    print(f"Бот @{me['username']} запущен.")

    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    plan_time = env("PLAN_TIME", "18:00")
    morning_time = env("MORNING_TIME", "09:00")
    ph, pm = plan_time.split(":")
    mh, mm = morning_time.split(":")
    sched = BackgroundScheduler(timezone=bot.tz)
    sched.add_job(bot.send_evening_plan, CronTrigger(hour=int(ph), minute=int(pm), timezone=bot.tz))
    sched.add_job(bot.send_morning_greeting, CronTrigger(day_of_week="mon-fri", hour=int(mh), minute=int(mm), timezone=bot.tz))
    sched.start()
    print(f"Расписание: {plan_time} и {morning_time} пн-пт")

    while True:
        try:
            data = bot.call("getUpdates", timeout=30, offset=offset)
            for upd in data.get("result", []):
                offset = upd["update_id"] + 1
                msg = upd.get("message") or upd.get("edited_message")
                if msg:
                    bot.handle(msg)
        except Exception as exc:
            print(f"ошибка: {exc}")
            time.sleep(3)


if __name__ == "__main__":
    main()
