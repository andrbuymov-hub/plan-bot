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
  echo Если repo уже есть: git remote add origin https://github.com/ВАШ_ЛОГИН/plan-bot.git
  echo git push -u origin master
  pause
)

echo.
echo [3/4] Секреты GitHub (расписание 18:00 и 9:00)...
gh secret set BOT_TOKEN --body "8682630427:AAGa4b1bQigM7QZN33EG2x4oR_09uzvrZh8"
gh secret set CHAT_PLANNING_ID --body "-1002909461166"
gh secret set CHAT_MORNING_ID --body "-1002909461166"

echo.
echo [4/4] Render.com:
echo   1. https://dashboard.render.com/ -^> New -^> Blueprint
echo   2. Подключите GitHub repo plan-bot
echo   3. Укажите BOT_TOKEN при деплое
echo   4. После деплоя бот сам настроит webhook
echo.
echo GitHub Actions отправляет план в 18:00 и утро в 9:00 без ПК.
echo Render принимает команды /plan когда ПК выключен.
echo.
pause
