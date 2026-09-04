@echo off
chcp 65001 >nul
cd /d "%~dp0"

set PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
if not exist "%PY%" set PY=python

echo Установка зависимостей...
"%PY%" -m pip install httpx flask telethon "python-socks[asyncio]" apscheduler -q

findstr /B "TELEGRAM_API_URL=" .env 2>nul | findstr /V "TELEGRAM_API_URL=$" >nul
if %errorlevel%==0 (
  echo Запуск через Cloudflare Worker...
  "%PY%" bot_http.py
) else (
  echo Запуск через MTProto-прокси...
  "%PY%" bot.py
)
pause
