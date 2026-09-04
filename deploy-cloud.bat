@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo === Деплой plan-bot на Cloudflare Workers ===
echo.

echo [1] KV namespace...
for /f "tokens=*" %%i in ('npx wrangler kv namespace create CONFIG -c wrangler-cloud.toml 2^>^&1 ^| findstr /i "id ="') do set KVLINE=%%i
echo %KVLINE%

echo.
echo Обновите id в wrangler-cloud.toml если нужно, затем:
echo [2] npx wrangler deploy -c wrangler-cloud.toml
echo [3] npx wrangler secret put BOT_TOKEN -c wrangler-cloud.toml
echo.
pause
