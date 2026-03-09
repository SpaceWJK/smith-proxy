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
set BOT_DIR=D:\Vibe Dev\Slack Bot\Slack Bot
set PYTHONW=D:\Vibe Dev\Slack Bot\venv\Scripts\pythonw.exe
set SCRIPT=%BOT_DIR%\slack_bot.py
set TASK_NAME=SlackQABot

echo [설정 확인]
echo   봇 경로: %BOT_DIR%
echo   Python : %PYTHONW%
echo   태스크 : %TASK_NAME%
echo.

REM ─── 기존 태스크 삭제 (있으면) ────────────────────────────────
schtasks /delete /tn "%TASK_NAME%" /f > nul 2>&1

REM ─── XML로 태스크 등록 (숨김 실행, 로그인 시 1분 후) ─────────
set XML_PATH=%TEMP%\slackbot_task.xml
(
echo ^<?xml version="1.0" encoding="UTF-16"?^>
echo ^<Task xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task"^>
echo   ^<Triggers^>
echo     ^<LogonTrigger^>
echo       ^<Enabled^>true^</Enabled^>
echo       ^<Delay^>PT1M^</Delay^>
echo     ^</LogonTrigger^>
echo   ^</Triggers^>
echo   ^<Actions^>
echo     ^<Exec^>
echo       ^<Command^>%PYTHONW%^</Command^>
echo       ^<Arguments^>"%SCRIPT%" --commands-only^</Arguments^>
echo       ^<WorkingDirectory^>%BOT_DIR%^</WorkingDirectory^>
echo     ^</Exec^>
echo   ^</Actions^>
echo   ^<Settings^>
echo     ^<MultipleInstancesPolicy^>IgnoreNew^</MultipleInstancesPolicy^>
echo     ^<DisallowStartIfOnBatteries^>false^</DisallowStartIfOnBatteries^>
echo     ^<StopIfGoingOnBatteries^>false^</StopIfGoingOnBatteries^>
echo     ^<ExecutionTimeLimit^>PT0S^</ExecutionTimeLimit^>
echo     ^<Priority^>7^</Priority^>
echo   ^</Settings^>
echo   ^<Principals^>
echo     ^<Principal^>
echo       ^<LogonType^>InteractiveToken^</LogonType^>
echo       ^<RunLevel^>HighestAvailable^</RunLevel^>
echo     ^</Principal^>
echo   ^</Principals^>
echo ^</Task^>
) > "%XML_PATH%"

schtasks /create /tn "%TASK_NAME%" /xml "%XML_PATH%" /f
del "%XML_PATH%" > nul 2>&1

if %errorlevel%==0 (
    echo.
    echo ✅ 등록 완료!
    echo    PC 로그인 시 1분 후 봇이 백그라운드에서 자동 시작됩니다.
    echo    로그: %BOT_DIR%\slack_bot.log
    echo.
    set /p START_NOW="지금 바로 시작할까요? (y/n): "
    if /i "%START_NOW%"=="y" (
        schtasks /run /tn "%TASK_NAME%"
        echo    봇이 백그라운드에서 실행 시작되었습니다.
    )
) else (
    echo.
    echo ❌ 등록 실패. 오류 코드: %errorlevel%
    echo    Task Scheduler 앱을 직접 열어 확인해보세요.
)

echo.
pause
