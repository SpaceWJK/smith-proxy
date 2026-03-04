@echo off
chcp 65001 > nul
echo.
echo [Slack Bot] 초기 설치
echo ========================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo Python 이 설치되어 있지 않습니다.
    echo https://python.org 에서 설치 후 다시 실행하세요.
    pause
    exit /b 1
)

echo 가상환경 생성 중...
python -m venv venv

echo 패키지 설치 중...
call venv\Scripts\activate.bat
pip install --upgrade pip -q
pip install -r requirements.txt

echo.
echo ============================
echo  설치 완료!
echo ============================
echo.
echo 다음 단계:
echo   1. .env 파일에서 SLACK_BOT_TOKEN 을 xoxb-... 로 설정하세요
echo   2. config.json 에서 channel ID 와 스케줄을 설정하세요
echo   3. run.bat 으로 봇을 실행하세요
echo.
pause
