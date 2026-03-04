@echo off
chcp 65001 > nul
echo.
echo ========================================
echo   Slack 알림봇 자동 시작 설정
echo   (Windows 작업 스케줄러 등록)
echo ========================================
echo.

REM ─── 관리자 권한 확인 ──────────────────────────────────────────
net session > nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ 관리자 권한이 필요합니다.
    echo    이 파일을 우클릭 → "관리자 권한으로 실행" 하세요.
    echo.
    pause
    exit /b 1
)

REM ─── 경로 설정 ─────────────────────────────────────────────────
set BOT_DIR=D:\Vibe Dev\Slack Bot
set PYTHON=%BOT_DIR%\venv\Scripts\python.exe
set SCRIPT=%BOT_DIR%\slack_bot.py
set TASK_NAME=SlackQABot

echo [설정 확인]
echo   봇 경로: %BOT_DIR%
echo   Python : %PYTHON%
echo   태스크 : %TASK_NAME%
echo.

REM ─── 기존 태스크 삭제 (있으면) ────────────────────────────────
schtasks /delete /tn "%TASK_NAME%" /f > nul 2>&1

REM ─── 태스크 등록 ───────────────────────────────────────────────
REM 로그온 시 실행, 사용자 로그인 유지 필요 없음 (SYSTEM 계정 불가 - Slack Socket Mode 때문에)
schtasks /create ^
  /tn "%TASK_NAME%" ^
  /tr "\"%PYTHON%\" \"%SCRIPT%\"" ^
  /sc ONLOGON ^
  /delay 0001:00 ^
  /rl HIGHEST ^
  /f

if %errorlevel%==0 (
    echo.
    echo ✅ 등록 완료!
    echo    PC 로그인 시 1분 후 자동으로 봇이 시작됩니다.
    echo.
    echo [즉시 시작하려면]
    schtasks /run /tn "%TASK_NAME%"
    echo    봇이 백그라운드에서 실행 중입니다.
    echo.
    echo [등록 확인]
    schtasks /query /tn "%TASK_NAME%" /fo LIST
) else (
    echo.
    echo ❌ 등록 실패. 오류 코드: %errorlevel%
)

echo.
pause
