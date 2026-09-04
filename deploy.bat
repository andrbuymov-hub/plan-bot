@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo === Облачный деплой plan-bot ===
echo.

where gh >nul 2>&1
if errorlevel 1 (
  echo Установите GitHub CLI: winget install GitHub.cli
  pause
  exit /b 1
)

echo [1/4] Вход в GitHub (откроется браузер)...
gh auth login -h github.com -p https -w
if errorlevel 1 pause & exit /b 1

echo.
echo [2/4] Создание репозитория и push...
gh repo create plan-bot --public --source=. --remote=origin --push
if errorlevel 1 (
  echo Если repo уже есть — push вручную: git push -u origin master
)

echo.
echo [3/4] Секреты GitHub из .env ...
for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
  if "%%a"=="BOT_TOKEN" set BOT_TOKEN=%%b
)
if not defined BOT_TOKEN (
  echo BOT_TOKEN не найден в .env
  pause & exit /b 1
)
gh secret set BOT_TOKEN --body "%BOT_TOKEN%"
gh secret set CHAT_PLANNING_ID --body "-1002909461166"
gh secret set CHAT_MORNING_ID --body "-1002909461166"

echo.
echo [4/4] Render.com:
echo   1. https://dashboard.render.com/ -^> New -^> Blueprint
echo   2. Подключите GitHub repo plan-bot
echo   3. При деплое укажите BOT_TOKEN из .env
echo.
echo Готово:
echo   - GitHub Actions: план в 18:00, утро в 9:00 (без ПК)
echo   - Render: команды /plan когда ПК выключен
echo.
pause
