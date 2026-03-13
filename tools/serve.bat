@echo off
chcp 65001 >nul 2>&1
title GDI S3 File Manager

echo.
echo  ╔══════════════════════════════════════╗
echo  ║     GDI S3 File Manager v1.0         ║
echo  ╚══════════════════════════════════════╝
echo.

:: Python 설치 확인
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  [오류] Python이 설치되어 있지 않습니다.
    echo.
    echo  Python 설치 방법:
    echo    1. https://www.python.org/downloads/ 접속
    echo    2. "Download Python 3.x" 버튼 클릭
    echo    3. 설치 시 "Add Python to PATH" 반드시 체크!
    echo    4. 설치 완료 후 이 파일을 다시 실행하세요.
    echo.
    echo  또는 함께 배포된 MANUAL.md 파일을 참고하세요.
    echo.
    pause
    exit /b 1
)

for /f "tokens=*" %%i in ('python --version 2^>^&1') do set PYVER=%%i
echo  [확인] %PYVER% 감지됨
echo.
echo  서버를 시작합니다...
echo  브라우저가 자동으로 열립니다.
echo  종료하려면 이 창을 닫거나 Ctrl+C를 누르세요.
echo.
echo  ─────────────────────────────────────────
echo.

python "%~dp0s3_server.py"
pause
