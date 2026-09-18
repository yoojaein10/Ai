# A10 Bridge central server setup (run ON the server, as Administrator).
# Prereqs: Python 3.13, "ODBC Driver 17/18 for SQL Server", source copied to $InstallDir, .env written.
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\server_setup.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\server_setup.ps1 -SyncIntervalMinutes 10 -SyncDays 3 -YearSyncDays 365
param(
    [string]$InstallDir = (Split-Path -Parent $PSScriptRoot),
    [int]$Port = 8010,
    # 2026-07-30 변경: 10분마다 최근 3일(바뀐 감정서만 요약 부분 재집계) +
    # 매일 23:00 최근 365일 전체 재집계. 입금 알림을 전표 입력 직후에 띄우려면
    # 짧은 주기가 필요하고, 야간 전체 재집계가 부분 갱신의 어긋남을 덮는다.
    [int]$SyncIntervalMinutes = 10,
    [int]$SyncDays = 3,
    [int]$YearSyncDays = 365,
    [string]$YearSyncTime = "23:00",
    [string]$PaymentSyncTime = "22:30",
    # TAMS 공유(\\caps) 접근 계정 — SYSTEM 예약 작업은 사용자 자격 증명을 못 쓰므로
    # cmd 래퍼에서 net use로 인증한다. 예: -TamsShareUser server -TamsSharePassword ****
    [string]$TamsShareUser = "",
    [string]$TamsSharePassword = ""
)

$ErrorActionPreference = "Stop"
if ($SyncDays -lt 1 -or $SyncDays -gt 365) { throw "SyncDays는 1~365 사이여야 합니다." }
if ($YearSyncDays -lt 1 -or $YearSyncDays -gt 365) { throw "YearSyncDays는 1~365 사이여야 합니다." }

function Remove-A10TaskIfExists([string]$TaskName) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    }
}

Set-Location $InstallDir
Write-Host "InstallDir: $InstallDir"

if (-not (Test-Path (Join-Path $InstallDir ".env"))) {
    Write-Host "ERROR: .env not found. Copy .env.example to .env and fill MSSQL_* first." -ForegroundColor Red
    exit 1
}

# 0. locate Python (PATH, py launcher, or common install dirs)
$bootstrapPy = $null
if (Get-Command python -ErrorAction SilentlyContinue) {
    $bootstrapPy = (Get-Command python).Source
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $bootstrapPy = "py"
} else {
    $candidates = @(
        "C:\Program Files\Python3*\python.exe",
        "C:\Python3*\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe"
    ) | ForEach-Object { Get-Item $_ -ErrorAction SilentlyContinue } | Sort-Object FullName -Descending
    if ($candidates) { $bootstrapPy = $candidates[0].FullName }
}
if (-not $bootstrapPy) {
    Write-Host "ERROR: Python not found." -ForegroundColor Red
    Write-Host "Install Python 3.13 from https://www.python.org/downloads/windows/" -ForegroundColor Yellow
    Write-Host "  - Check 'Add python.exe to PATH'" -ForegroundColor Yellow
    Write-Host "  - Use 'Customize installation' -> 'Install for all users'" -ForegroundColor Yellow
    Write-Host "Then re-run this script." -ForegroundColor Yellow
    exit 1
}
Write-Host "Python: $bootstrapPy"

# 1. venv + dependencies
if (-not (Test-Path ".venv")) {
    if ($bootstrapPy -eq "py") { py -3 -m venv .venv } else { & $bootstrapPy -m venv .venv }
}
$py = Join-Path $InstallDir ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "ERROR: venv creation failed (.venv\Scripts\python.exe missing)." -ForegroundColor Red
    exit 1
}
& $py -m pip install --quiet -r requirements.txt
Write-Host "dependencies installed"

# 2. tables + office map seed
& $py -m scripts.create_tables
& $py -m scripts.seed_office_map

# 3. wrapper scripts (schtasks has no working-directory option -> cd /d inside)
New-Item -ItemType Directory -Force (Join-Path $InstallDir "logs") | Out-Null
$runServer = Join-Path $InstallDir "scripts\run_server.cmd"
$runSync = Join-Path $InstallDir "scripts\run_cache_sync.cmd"
$runYearSync = Join-Path $InstallDir "scripts\run_cache_sync_year.cmd"
$runPayment = Join-Path $InstallDir "scripts\run_payment_sync.cmd"
$runTams = Join-Path $InstallDir "scripts\run_tams_sync.cmd"
$runPopbill = Join-Path $InstallDir "scripts\run_popbill_sync.cmd"
Set-Content -Path $runServer -Encoding ascii -Value @(
    "@echo off",
    "cd /d $InstallDir",
    ".venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port $Port --log-config scripts\uvicorn_log_config.json >> logs\server.log 2>&1"
)
Set-Content -Path $runSync -Encoding ascii -Value @(
    "@echo off",
    "cd /d $InstallDir",
    ".venv\Scripts\python.exe -m app.batch.voucher_cache_sync --days $SyncDays --partial-summary >> logs\cache_sync.log 2>&1"
)
# 장기 동기화: 최근 365일을 월별로 나눠 과거 전표 수정을 매일 따라잡는다.
Set-Content -Path $runYearSync -Encoding ascii -Value @(
    "@echo off",
    "cd /d $InstallDir",
    ".venv\Scripts\python.exe -m app.batch.voucher_cache_sync --days $YearSyncDays --monthly-chunks >> logs\cache_sync_year.log 2>&1"
)
Set-Content -Path $runPayment -Encoding ascii -Value @(
    "@echo off",
    "cd /d $InstallDir",
    ".venv\Scripts\python.exe -m app.batch.payment_status_sync >> logs\payment_sync.log 2>&1"
)
$tamsLines = @("@echo off", "cd /d $InstallDir")
if ($TamsShareUser) {
    # SYSTEM 계정으로 \\caps에 붙기 위한 인증. 실패해도 계속 진행(이미 연결돼 있으면 오류 무시).
    $tamsLines += "net use \\caps\TAMS /user:$TamsShareUser $TamsSharePassword >nul 2>&1"
}
$tamsLines += ".venv\Scripts\python.exe -m app.batch.tams_tax_sync >> logs\tams_sync.log 2>&1"
# TAMS 캐시 → 발급 원장(source=TAMS) 반영 (2026-09-09): 동기화 직후 그날 행을 원장에 붙인다.
$tamsLines += ".venv\Scripts\python.exe -m app.batch.tams_to_ledger >> logs\tams_sync.log 2>&1"
Set-Content -Path $runTams -Encoding ascii -Value $tamsLines
# 팝빌 → 발급 원장 동기화 (2026-09-09): 팝빌 사이트에서 직접 끊거나 취소한 건을 흡수한다.
$popbillLines = @("@echo off", "cd /d $InstallDir",
    ".venv\Scripts\python.exe -m app.batch.popbill_sync >> logs\popbill_sync.log 2>&1")
Set-Content -Path $runPopbill -Encoding ascii -Value $popbillLines

# 4. scheduled tasks (re-runnable: /f overwrites)
schtasks /create /f /tn "A10Bridge_Server" /sc onstart /ru SYSTEM /tr "`"$runServer`""
schtasks /create /f /tn "A10Bridge_CacheSync" /sc minute /mo $SyncIntervalMinutes /ru SYSTEM /tr "`"$runSync`""
Remove-A10TaskIfExists "A10Bridge_CacheSyncDeep_AM"
Remove-A10TaskIfExists "A10Bridge_CacheSyncDeep_PM"
schtasks /create /f /tn "A10Bridge_CacheSyncYear" /sc daily /st $YearSyncTime /ru SYSTEM /tr "`"$runYearSync`""
schtasks /create /f /tn "A10Bridge_PaymentSync" /sc daily /st $PaymentSyncTime /ru SYSTEM /tr "`"$runPayment`""
# TAMS 세금계산서 동기화 (매일 08:00).
# 주의: \\caps 공유 접근을 위해 run_tams_sync.cmd가 net use로 인증한다 (-TamsShareUser 필요).
schtasks /create /f /tn "A10Bridge_TamsSync" /sc daily /st 08:00 /ru SYSTEM /tr "`"$runTams`""
schtasks /create /f /tn "A10Bridge_PopbillSync" /sc daily /st 07:30 /ru SYSTEM /tr "`"$runPopbill`""
# 감시 작업: 5분마다 /health 확인, 무응답이면 A10Bridge_Server 재기동 (InstallDir에 공백 없어야 함)
$watchdogPs1 = Join-Path $InstallDir "scripts\server_watchdog.ps1"
schtasks /create /f /tn "A10Bridge_Watchdog" /sc minute /mo 5 /ru SYSTEM /tr "powershell -NoProfile -ExecutionPolicy Bypass -File $watchdogPs1"

# schtasks defaults to a 72h execution time limit, which kills the long-running server task.
$serverTask = Get-ScheduledTask "A10Bridge_Server"
$serverTask.Settings.ExecutionTimeLimit = "PT0S"
$serverTask.Settings.RestartCount = 3
$serverTask.Settings.RestartInterval = "PT1M"
Set-ScheduledTask $serverTask | Out-Null
Write-Host "A10Bridge_Server: 72h time limit removed, restart-on-failure enabled"

# 5. firewall
netsh advfirewall firewall delete rule name="A10Bridge $Port" | Out-Null
netsh advfirewall firewall add rule name="A10Bridge $Port" dir=in action=allow protocol=TCP localport=$Port

# 6. start now + health check
schtasks /run /tn "A10Bridge_Server"
Start-Sleep -Seconds 8
try {
    $health = Invoke-WebRequest -Uri "http://localhost:$Port/health" -UseBasicParsing -TimeoutSec 10
    Write-Host "HEALTH: $($health.Content)"
} catch {
    Write-Host "WARNING: health check failed - check logs\server.log" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Done. Tasks: A10Bridge_Server (onstart), A10Bridge_CacheSync (every $SyncIntervalMinutes min, --days $SyncDays), A10Bridge_CacheSyncYear (daily $YearSyncTime, --days $YearSyncDays), A10Bridge_PaymentSync (daily $PaymentSyncTime)"
Write-Host "First-time backfill (run once, manually):"
Write-Host "  .venv\Scripts\python.exe -m app.batch.voucher_cache_sync --days $YearSyncDays --monthly-chunks"
Write-Host "Change sync interval later: re-run this script with -SyncIntervalMinutes N"
