#!/usr/bin/env python3
"""Ручной запуск cron-задач (GitHub Actions / локально)."""
import sys

from bot_core import TelegramBot

if __name__ == "__main__":
    b = TelegramBot()
    task = sys.argv[1] if len(sys.argv) > 1 else "evening"
    if task == "evening":
        print(b.send_evening_plan())
    elif task == "morning":
        print(b.send_morning_greeting())
    else:
        raise SystemExit("usage: run_cron.py evening|morning")
