@echo off
chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion
title Knowledge Integration System

echo.
echo  ╔══════════════════════════════════════╗
echo  ║   Knowledge Integration System v2.0  ║
echo  ╚══════════════════════════════════════╝
echo.

:: ================================================================
::  1. Python 설치 확인 + 자동 설치
:: ================================================================

python --version >nul 2>&1
if %errorlevel% equ 0 (
    for /f "tokens=*" %%i in ('python --version 2^>^&1') do set PYVER=%%i
    echo  [OK] !PYVER! 감지됨
    goto :server_start
)

:: Python이 없으면 자동 설치 시도
echo  [!] Python이 감지되지 않았습니다.
echo.

:: 사내 네트워크 확인
echo  Python 3.13을 자동 설치합니다. (인터넷 연결 필요)
echo.

:: 1-1. 다운로드
set "INSTALLER=%TEMP%\python-3.13.2-amd64.exe"
set "PY_URL=https://www.python.org/ftp/python/3.13.2/python-3.13.2-amd64.exe"

echo  [1/4] Python 3.13.2 다운로드 중...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ProgressPreference='SilentlyContinue'; try { Invoke-WebRequest -Uri '%PY_URL%' -OutFile '%INSTALLER%' -TimeoutSec 120; exit 0 } catch { Write-Host $_.Exception.Message; exit 1 }"

if not exist "%INSTALLER%" (
    echo.
    echo  [실패] 다운로드에 실패했습니다.
    echo         수동 설치: https://www.python.org/downloads/
    echo         설치 시 "Add Python to PATH" 반드시 체크!
    echo.
    pause
    exit /b 1
)

:: 1-2. 설치 (현재 사용자, PATH 자동 등록, 진행바 표시)
echo  [2/4] Python 3.13.2 설치 중... (1~2분 소요)
"%INSTALLER%" /passive InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_pip=1

if %errorlevel% neq 0 (
    echo.
    echo  [실패] 설치에 실패했습니다.
    echo         수동 설치: https://www.python.org/downloads/
    echo.
    del "%INSTALLER%" >nul 2>&1
    pause
    exit /b 1
)

:: 1-3. 현재 세션 PATH 갱신
echo  [3/4] 환경변수 갱신 중...
set "PATH=%LOCALAPPDATA%\Programs\Python\Python313;%LOCALAPPDATA%\Programs\Python\Python313\Scripts;%PATH%"

:: 1-4. 설치 확인
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo  [실패] 설치 후에도 Python을 찾을 수 없습니다.
    echo         PC를 재시작한 후 다시 실행해주세요.
    echo.
    del "%INSTALLER%" >nul 2>&1
    pause
    exit /b 1
)

for /f "tokens=*" %%i in ('python --version 2^>^&1') do set PYVER=%%i
echo  [4/4] !PYVER! 설치 완료!

:: 임시 파일 정리
del "%INSTALLER%" >nul 2>&1
echo.

:: ================================================================
::  2. 패키지 설치 확인 (boto3)
:: ================================================================
:server_start

echo  [패키지] boto3 설치 확인 중...
python -m pip install boto3 -q --disable-pip-version-check >nul 2>&1
if %errorlevel% neq 0 (
    echo  [경고] boto3 설치에 실패했습니다. S3 기능이 제한될 수 있습니다.
) else (
    echo  [OK] boto3 준비 완료
)
echo.

:: 기존 서버 종료 (포트 9090 충돌 방지)
set "OLD_PID="
for /f "tokens=5" %%p in ('netstat -aon 2^>nul ^| findstr ":9090.*LISTENING"') do (
    set "OLD_PID=%%p"
)
if defined OLD_PID (
    echo  [정리] 기존 서버 종료 중... (PID: !OLD_PID!)
    taskkill /pid !OLD_PID! /f >nul 2>&1
    timeout /t 1 /nobreak >nul
)

:: 로그 파일 경로
set "LOG_FILE=%~dp0server.log"

:: 서버 백그라운드 실행 (최소화 창)
echo  [시작] 서버를 백그라운드로 실행합니다...
start "KIS_Server" /min python "%~dp0s3_server.py" 2>"%LOG_FILE%"

:: ================================================================
::  3. 서버 시작 대기 + 브라우저 열기
:: ================================================================

:: 최대 10초 대기
set "RETRIES=0"
:wait_loop
timeout /t 1 /nobreak >nul
set /a RETRIES+=1

:: 포트 응답 확인
netstat -aon 2>nul | findstr ":9090.*LISTENING" >nul 2>&1
if %errorlevel% equ 0 goto :server_ready

if %RETRIES% lss 10 goto :wait_loop

:: 10초 후에도 안 뜨면 경고 후 브라우저 열기
echo  [경고] 서버 응답 대기 시간 초과. 브라우저를 엽니다...
goto :open_browser

:server_ready
echo  [OK] 서버가 실행 중입니다. (포트 9090)

:open_browser
echo  [OK] 브라우저를 엽니다...
for /f %%t in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMddHHmmss"') do set CACHEBUST=%%t
start "" "http://localhost:9090/s3_manager.html?v=!CACHEBUST!"

echo.
echo  ═══════════════════════════════════════════
echo.
echo   KIS가 실행 중입니다.
echo   브라우저에서 페이지가 열렸습니다.
echo.
echo   서버 종료: 이 창을 닫거나 아무 키를 누르세요.
echo.
echo  ═══════════════════════════════════════════
echo.

:: ================================================================
::  4. 대기 → 종료 시 서버 정리
:: ================================================================

pause >nul

:: 서버 프로세스 종료
echo.
echo  서버를 종료합니다...
for /f "tokens=5" %%p in ('netstat -aon 2^>nul ^| findstr ":9090.*LISTENING"') do (
    taskkill /pid %%p /f >nul 2>&1
)

:: 최소화 창도 정리
taskkill /fi "WINDOWTITLE eq KIS_Server" /f >nul 2>&1

echo  [완료] 서버가 종료되었습니다.
timeout /t 2 /nobreak >nul
