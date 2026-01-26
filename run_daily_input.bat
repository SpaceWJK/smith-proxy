@echo off
REM 게임 랭킹 데이터 입력 GUI 실행 배치 파일
REM Windows 작업 스케줄러에서 매일 오전 9시에 자동 실행

cd /d "D:\Vibe Dev\Maker Store Rank"
python gui_data_input.py

REM 오류 발생 시 창 유지
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo 오류가 발생했습니다. 아무 키나 눌러 종료하세요...
    pause > nul
)
