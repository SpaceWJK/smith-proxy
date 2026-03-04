@echo off
chcp 65001 > nul
echo.
echo ========================================
echo   Slack 알림봇 자동 시작 해제
echo ========================================
echo.

net session > nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ 관리자 권한이 필요합니다.
    echo    우클릭 → "관리자 권한으로 실행" 하세요.
    pause
    exit /b 1
)

set TASK_NAME=SlackQABot

REM 봇 프로세스 종료
taskkill /F /FI "WINDOWTITLE eq 봇*" > nul 2>&1

REM 태스크 삭제
schtasks /delete /tn "%TASK_NAME%" /f
if %errorlevel%==0 (
    echo ✅ 자동 시작 해제 완료.
) else (
    echo ⚠  태스크가 없거나 삭제 실패.
)
echo.
pause
