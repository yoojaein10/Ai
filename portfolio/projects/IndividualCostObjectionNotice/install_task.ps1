param(
    [string]$TaskName = "개별부담비용 이의신청 공지톡",
    [string]$At = "16:00"
)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ProjectDir "run_scheduled.ps1"

$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Runner`"" `
    -WorkingDirectory $ProjectDir
$Trigger = New-ScheduledTaskTrigger -Daily -At $At
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "매일 실행 후 마지막 영업일에만 개별부담비용 안내 문자 발송" `
    -Force

Write-Host "작업 스케줄러 등록 완료: $TaskName / 매일 $At"
