@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo === Деплой прокси на Cloudflare (1 раз) ===
echo Откроется браузер — войдите в Cloudflare (регистрация по почте).
echo.

call npx --yes wrangler deploy 2>&1
if errorlevel 1 (
  echo.
  echo Если wrangler не смог — сделайте вручную:
  echo 1. dash.cloudflare.com -^> Workers -^> Create
  echo 2. Вставьте код из cloudflare-worker.js
  echo 3. Variables: BOT_SECRET = plan-bot-secret-change-me
  echo 4. В .env добавьте TELEGRAM_API_URL и BOT_SECRET
  pause
  exit /b 1
)

echo.
echo Worker задеплоен. Добавьте в .env строки:
echo TELEGRAM_API_URL=https://ВАШ-WORKER.workers.dev
echo BOT_SECRET=plan-bot-secret-change-me
echo.
echo Затем запустите start.bat
pause
