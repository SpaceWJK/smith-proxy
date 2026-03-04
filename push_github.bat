@echo off
chcp 65001 > nul
echo.
echo ========================================
echo   GitHub 원격 저장소 연결 및 Push
echo ========================================
echo.

REM ─── 설정: GitHub 저장소 URL 입력 ────────────────────────────────
REM  예시: https://github.com/yourname/slack-qa-bot.git
set REPO_URL=%1

if "%REPO_URL%"=="" (
    echo [사용법]  push_github.bat https://github.com/유저명/저장소명.git
    echo.
    echo  GitHub 에서 새 저장소를 먼저 만들어주세요:
    echo   1. https://github.com/new 접속
    echo   2. Repository name: slack-qa-bot  (Private 권장)
    echo   3. "Create repository" 클릭
    echo   4. 표시되는 HTTPS URL 복사 후 이 배치를 다시 실행
    echo.
    pause
    exit /b 1
)

REM ─── origin 이미 있으면 URL 업데이트, 없으면 추가 ──────────────
"C:\Program Files\Git\cmd\git.exe" remote get-url origin > nul 2>&1
if %errorlevel%==0 (
    echo [origin] URL 업데이트 중...
    "C:\Program Files\Git\cmd\git.exe" remote set-url origin %REPO_URL%
) else (
    echo [origin] 원격 저장소 추가 중...
    "C:\Program Files\Git\cmd\git.exe" remote add origin %REPO_URL%
)

REM ─── Push ──────────────────────────────────────────────────────
echo.
echo [Push] GitHub 에 업로드 중...
"C:\Program Files\Git\cmd\git.exe" push -u origin main

if %errorlevel%==0 (
    echo.
    echo ✅ 업로드 완료!
    echo    저장소: %REPO_URL%
) else (
    echo.
    echo ❌ Push 실패. 아래를 확인하세요:
    echo    - GitHub 로그인 여부 (git credential)
    echo    - 저장소 URL 정확성
    echo    - 저장소가 비어있는지 여부
)
echo.
pause
