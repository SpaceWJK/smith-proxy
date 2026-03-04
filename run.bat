@echo off
chcp 65001 > nul
echo.
echo [Slack 알림 봇] 시작 중...
echo.

if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
)

python slack_bot.py %*

if errorlevel 1 (
    echo.
    echo 오류가 발생했습니다. slack_bot.log 를 확인하세요.
    pause
)
