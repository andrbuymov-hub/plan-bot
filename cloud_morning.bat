@echo off
chcp 65001 >nul
cd /d "%~dp0"
set TELEGRAM_API_URL=
"%LOCALAPPDATA%\Programs\Python\Python312\python.exe" run_cron.py morning >> cron.log 2>&1
