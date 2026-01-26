﻿# Windows 작업 스케줄러 자동 등록 스크립트
# 매일 오전 10시에 게임 랭킹 데이터 입력 GUI를 자동으로 실행

# 관리자 권한 확인
$currentUser = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
$isAdmin = $currentUser.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host "⚠️  관리자 권한이 필요합니다!" -ForegroundColor Red
    Write-Host "PowerShell을 관리자 권한으로 실행해주세요." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "방법:" -ForegroundColor Cyan
    Write-Host "1. Windows 검색에서 'PowerShell' 검색" -ForegroundColor White
    Write-Host "2. 우클릭 → '관리자 권한으로 실행'" -ForegroundColor White
    Write-Host "3. 이 스크립트를 다시 실행" -ForegroundColor White
    pause
    exit
}

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  🎮 게임 랭킹 알림 시스템 스케줄러 설정" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# 작업 이름
$taskName = "MakerStoreRank-DailyInput"

# 기존 작업 확인 및 삭제
$existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existingTask) {
    Write-Host "기존 스케줄 작업을 삭제합니다..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

# 배치 파일 경로
$batchFile = "D:\Vibe Dev\Maker Store Rank\run_daily_input.bat"

# 배치 파일 존재 확인
if (-not (Test-Path $batchFile)) {
    Write-Host "❌ 오류: 배치 파일을 찾을 수 없습니다!" -ForegroundColor Red
    Write-Host "   경로: $batchFile" -ForegroundColor White
    pause
    exit
}

# 트리거 생성 (매주 목요일 오전 10시)
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Thursday -At "10:00AM"

# 액션 생성
$action = New-ScheduledTaskAction -Execute $batchFile

# 설정
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable:$false

# 사용자 계정 (현재 로그인한 사용자)
$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

# 작업 등록
try {
    Register-ScheduledTask `
        -TaskName $taskName `
        -Trigger $trigger `
        -Action $action `
        -Settings $settings `
        -Principal $principal `
        -Description "매주 목요일 오전 10시에 Google Play 게임 랭킹 데이터 입력 GUI를 자동으로 실행합니다." `
        -Force | Out-Null

    Write-Host "✅ 스케줄 작업이 성공적으로 등록되었습니다!" -ForegroundColor Green
    Write-Host ""
    Write-Host "📋 작업 정보:" -ForegroundColor Cyan
    Write-Host "   작업 이름: $taskName" -ForegroundColor White
    Write-Host "   실행 시간: 매주 목요일 오전 10:00" -ForegroundColor White
    Write-Host "   실행 파일: $batchFile" -ForegroundColor White
    Write-Host ""
    Write-Host "💡 확인 방법:" -ForegroundColor Yellow
    Write-Host "   1. Windows 검색 → '작업 스케줄러' 실행" -ForegroundColor White
    Write-Host "   2. 작업 스케줄러 라이브러리에서 '$taskName' 확인" -ForegroundColor White
    Write-Host ""
    Write-Host "🧪 지금 테스트:" -ForegroundColor Yellow
    Write-Host "   배치 파일을 더블클릭하여 GUI가 정상 작동하는지 확인하세요." -ForegroundColor White
    Write-Host "   파일 위치: $batchFile" -ForegroundColor White
    Write-Host ""
    Write-Host "⏰ 다음 실행 시간: 다음 주 목요일 오전 10:00" -ForegroundColor Green
    Write-Host ""

    # 작업 스케줄러 열기 제안
    $openScheduler = Read-Host "작업 스케줄러를 여시겠습니까? (Y/N)"
    if ($openScheduler -eq "Y" -or $openScheduler -eq "y") {
        Start-Process "taskschd.msc"
    }

} catch {
    Write-Host "❌ 오류: 스케줄 작업 등록 실패" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
}

Write-Host ""
Write-Host "아무 키나 눌러 종료..." -ForegroundColor Gray
pause
