# Task Scheduler Registration Script
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Thursday -At "10:00AM"
$action = New-ScheduledTaskAction -Execute "D:\Vibe Dev\Maker Store Rank\run_daily_input.bat"
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName "MakerStoreRank-DailyInput" -Trigger $trigger -Action $action -Settings $settings -Description "Weekly game ranking data input every Thursday at 10:00 AM" -Force
Write-Host "Success! Scheduled task registered for every Thursday at 10:00 AM" -ForegroundColor Green
