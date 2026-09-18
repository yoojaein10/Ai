# A10 Bridge 서버 재배포 (코드 업데이트용 - 서버에서 관리자 PowerShell로 실행)
#
# 사용법:
#   powershell -ExecutionPolicy Bypass -File scripts\server_redeploy.ps1 -ZipPath C:\Temp\A10Bridge_server.zip
#   (파일을 이미 수동으로 덮어쓴 경우 -ZipPath 생략 가능)
#
# 수행 내용: 감시 중지 -> 서버 중지 -> zip 반영(선택) -> pip install -> 테이블 생성
#           -> run_server.cmd 갱신(타임스탬프 로그) -> 감시 작업 등록/재개 -> 재기동 -> 헬스체크.
# 2026-07-22 장애 재발 방지: 새 의존성 미설치(openpyxl 등)와 재기동 누락을 절차로 차단한다.
param(
    [string]$InstallDir = "C:\A10Bridge",
    [string]$ZipPath = "",
    [int]$Port = 8010,
    [int]$SyncIntervalMinutes = 10,
    [int]$SyncDays = 3,
    [int]$YearSyncDays = 365,
    [string]$YearSyncTime = "23:00",
    [string]$PaymentSyncTime = "22:30",
    # 거래처 캐시 — 1~2분짜리라 야간 배치들과 겹치지 않는 시각에 둔다
    [string]$PartnerCacheTime = "04:20",
    [int]$FeeReviewIntervalMinutes = 120,
    [string]$FeeReviewHistoryTime = "00:30",
    # 보수기준 점검 사전생성 — 하루 한 번 23:00 에 최근 6개월(당월 포함)을 만든다.
    [string]$FeeBasisTime = "23:00",
    [int]$FeeBasisMonthsBack = 5,
    # 계정별원장 전기이월 해 넘기기 — 매년 1월 2일 이 시각에 한 번. 그날 만들어져야
    # 1월 첫 발송부터 전일이월이 맞는다(없으면 발송이 막힌다).
    [string]$AccountOpeningRollTime = "06:00"
)
$ErrorActionPreference = "Stop"
if ($SyncDays -lt 1 -or $SyncDays -gt 365) { throw "SyncDays는 1~365 사이여야 합니다." }
if ($YearSyncDays -lt 1 -or $YearSyncDays -gt 365) { throw "YearSyncDays는 1~365 사이여야 합니다." }
if ($FeeReviewIntervalMinutes -lt 1 -or $FeeReviewIntervalMinutes -gt 1439) {
    throw "FeeReviewIntervalMinutes는 1~1439 사이여야 합니다."
}
if ($FeeBasisMonthsBack -lt 0 -or $FeeBasisMonthsBack -gt 24) {
    throw "FeeBasisMonthsBack은 0~24 사이여야 합니다(app.services.fee_basis 의 --months-back 범위)."
}
if ($FeeBasisTime -notmatch '^([01]\d|2[0-3]):[0-5]\d$') {
    throw "FeeBasisTime은 HH:mm 형식이어야 합니다(예: 23:00)."
}
if ($AccountOpeningRollTime -notmatch '^([01]\d|2[0-3]):[0-5]\d$') {
    throw "AccountOpeningRollTime은 HH:mm 형식이어야 합니다(예: 06:00)."
}

function Get-A10Task([string]$TaskName) {
    return (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue)
}

function Disable-A10TaskIfExists([string]$TaskName) {
    if (Get-A10Task $TaskName) {
        Disable-ScheduledTask -TaskName $TaskName | Out-Null
    }
}

function Stop-A10TaskIfExists([string]$TaskName) {
    if (Get-A10Task $TaskName) {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    }
}

function Remove-A10TaskIfExists([string]$TaskName) {
    if (Get-A10Task $TaskName) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    }
}

# 0. 설치 폴더 검증 (zip을 엉뚱한 폴더에 푸는 사고 방지)
if (-not (Test-Path (Join-Path $InstallDir "requirements.txt"))) {
    throw "InstallDir($InstallDir)에 requirements.txt가 없습니다. 설치 폴더가 맞는지 확인하세요. 최초 설치는 scripts\server_setup.ps1 사용."
}
$py = Join-Path $InstallDir ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    throw ".venv가 없습니다. 최초 설치는 scripts\server_setup.ps1을 사용하세요."
}

# 1. 감시·신규 배치 시작을 일시 중지하고 서버 중지
Disable-A10TaskIfExists "A10Bridge_Watchdog"
Disable-A10TaskIfExists "A10Bridge_CacheSync"
Disable-A10TaskIfExists "A10Bridge_CacheSyncYear"
Disable-A10TaskIfExists "A10Bridge_PaymentSync"
Disable-A10TaskIfExists "A10Bridge_FeeReviewPrepare"
Disable-A10TaskIfExists "A10Bridge_FeeReviewPrepareHistory"
Disable-A10TaskIfExists "A10Bridge_FeeBasisPrepare"
Disable-A10TaskIfExists "A10Bridge_FeeBasisPrepareHistory"
Disable-A10TaskIfExists "A10Bridge_DepositVoucher"
Disable-A10TaskIfExists "A10Bridge_DepositVoucherYak"
Disable-A10TaskIfExists "A10Bridge_PartnerCache"
Disable-A10TaskIfExists "A10Bridge_AccountOpeningRoll"
Stop-A10TaskIfExists "A10Bridge_FeeReviewPrepare"
Stop-A10TaskIfExists "A10Bridge_FeeReviewPrepareHistory"
Stop-A10TaskIfExists "A10Bridge_FeeBasisPrepare"
Stop-A10TaskIfExists "A10Bridge_FeeBasisPrepareHistory"
Stop-A10TaskIfExists "A10Bridge_DepositVoucher"
Stop-A10TaskIfExists "A10Bridge_DepositVoucherYak"
Stop-A10TaskIfExists "A10Bridge_Server"
Start-Sleep -Seconds 2
Write-Host "[1/7] 감시 중지 + 서버 중지"

# 2. zip 반영 (zip 루트가 A10Bridge\ 폴더여도 자동 보정)
if ($ZipPath) {
    if (-not (Test-Path $ZipPath)) { throw "zip 파일을 찾을 수 없습니다: $ZipPath" }
    $stage = Join-Path $env:TEMP ("a10_redeploy_" + [guid]::NewGuid().ToString("N"))
    Expand-Archive -Path $ZipPath -DestinationPath $stage -Force
    $src = $stage
    if (-not (Test-Path (Join-Path $src "requirements.txt"))) {
        $inner = Get-ChildItem $stage -Directory | Where-Object { Test-Path (Join-Path $_.FullName "requirements.txt") } | Select-Object -First 1
        if ($null -eq $inner) { throw "zip 안에서 requirements.txt를 찾지 못했습니다. 서버 배포용 zip이 맞는지 확인하세요." }
        $src = $inner.FullName
    }
    # .env는 서버 것을 유지한다 (서버에 없을 때만 zip 것 사용)
    robocopy $src $InstallDir /E /XD .venv logs __pycache__ .git /XF .env | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy 실패 (exit $LASTEXITCODE)" }
    if (-not (Test-Path (Join-Path $InstallDir ".env")) -and (Test-Path (Join-Path $src ".env"))) {
        Copy-Item (Join-Path $src ".env") (Join-Path $InstallDir ".env")
    }
    Remove-Item -Recurse -Force $stage
    Write-Host "[2/7] 소스 반영: $ZipPath -> $InstallDir"
} else {
    Write-Host "[2/7] -ZipPath 미지정: 파일이 이미 덮어써진 상태로 간주하고 진행"
}

# 3. 의존성 설치 (requirements.txt 변경 여부와 무관하게 항상 실행 - 이미 설치돼 있으면 수 초에 끝남)
& $py -m pip install --quiet -r (Join-Path $InstallDir "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "pip install 실패 - 네트워크 상태와 requirements.txt를 확인하세요." }
Write-Host "[3/7] 의존성 설치 확인"

# 4. 테이블 생성 + 멱등 호환 마이그레이션(컬럼 확장·약식 분할입금 제약 변경)
Push-Location $InstallDir
try {
    & $py -m scripts.create_tables
    if ($LASTEXITCODE -ne 0) { throw "scripts.create_tables 실패" }
} finally {
    Pop-Location
}
Write-Host "[4/7] 테이블 확인"

# 5. 서버·동기화 실행 래퍼 갱신
New-Item -ItemType Directory -Force (Join-Path $InstallDir "logs") | Out-Null
$logCfg = Join-Path $InstallDir "scripts\uvicorn_log_config.json"
$logCfgArg = ""
if (Test-Path $logCfg) { $logCfgArg = " --log-config scripts\uvicorn_log_config.json" }
Set-Content -Path (Join-Path $InstallDir "scripts\run_server.cmd") -Encoding ascii -Value @(
    "@echo off",
    "cd /d $InstallDir",
    ".venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port $Port$logCfgArg >> logs\server.log 2>&1"
)
$runSync = Join-Path $InstallDir "scripts\run_cache_sync.cmd"
$runYearSync = Join-Path $InstallDir "scripts\run_cache_sync_year.cmd"
$runPayment = Join-Path $InstallDir "scripts\run_payment_sync.cmd"
$runFeeReview = Join-Path $InstallDir "scripts\run_fee_review_prepare.cmd"
$runFeeReviewHistory = Join-Path $InstallDir "scripts\run_fee_review_prepare_history.cmd"
$runFeeBasis = Join-Path $InstallDir "scripts\run_fee_basis_prepare.cmd"
$runDeposit = Join-Path $InstallDir "scripts\run_deposit_voucher.cmd"
$runDepositYak = Join-Path $InstallDir "scripts\run_deposit_voucher_yak.cmd"
$runPartnerCache = Join-Path $InstallDir "scripts\run_partner_cache.cmd"
$hasPartnerCache = Test-Path (Join-Path $InstallDir "app\batch\partner_cache_sync.py")
$runOpeningRoll = Join-Path $InstallDir "scripts\run_account_opening_roll.cmd"
$hasOpeningRoll = Test-Path (Join-Path $InstallDir "scripts\roll_account_opening.py")
$hasFeeReviewPrepare = Test-Path (Join-Path $InstallDir "app\batch\fee_review_prepare.py")
$hasFeeBasisPrepare = Test-Path (Join-Path $InstallDir "app\services\fee_basis.py")
$hasDepositVoucher = Test-Path (Join-Path $InstallDir "app\batch\deposit_voucher_sync.py")
Set-Content -Path $runSync -Encoding ascii -Value @(
    "@echo off",
    "cd /d $InstallDir",
    ".venv\Scripts\python.exe -m app.batch.voucher_cache_sync --days $SyncDays --partial-summary >> logs\cache_sync.log 2>&1"
)
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
if ($hasPartnerCache) {
    Set-Content -Path $runPartnerCache -Encoding ascii -Value @(
        "@echo off",
        "cd /d $InstallDir",
        ".venv\Scripts\python.exe -m app.batch.partner_cache_sync >> logs\partner_cache.log 2>&1"
    )
}
if ($hasOpeningRoll) {
    # 연도를 안 준다 — 스크립트가 올해로 본다. 1월 2일에 돌면 그 해 이월이 만들어진다.
    # 이미 값이 있으면 덮어쓰지 않는다(--force 없이는 건너뛴다).
    Set-Content -Path $runOpeningRoll -Encoding ascii -Value @(
        "@echo off",
        "cd /d $InstallDir",
        ".venv\Scripts\python.exe -m scripts.roll_account_opening >> logs\account_opening_roll.log 2>&1"
    )
}
if ($hasFeeReviewPrepare) {
    Set-Content -Path $runFeeReview -Encoding ascii -Value @(
        "@echo off",
        "cd /d $InstallDir",
        ".venv\Scripts\python.exe -m app.batch.fee_review_prepare >> logs\fee_review_prepare.log 2>&1"
    )
    Set-Content -Path $runFeeReviewHistory -Encoding ascii -Value @(
        "@echo off",
        "cd /d $InstallDir",
        ".venv\Scripts\python.exe -m app.batch.fee_review_prepare --months-back 1 >> logs\fee_review_prepare_history.log 2>&1"
    )
}
if ($hasFeeBasisPrepare) {
    # 하루 한 번이므로 최근 N개월을 한 번에 만든다(당월 포함 N+1개월).
    Set-Content -Path $runFeeBasis -Encoding ascii -Value @(
        "@echo off",
        "cd /d $InstallDir",
        ".venv\Scripts\python.exe -m app.services.fee_basis --months-back $FeeBasisMonthsBack >> logs\fee_basis_prepare.log 2>&1"
    )
}
if ($hasDepositVoucher) {
    # 반제·일반은 매시간, 약식 묶음(하루 1장)은 17:30 회차만 --include-yak.
    # --days 7: 주말·연휴에 쌓인 입금을 다음 실행이 한꺼번에 잡는다(멱등 재스캔).
    Set-Content -Path $runDeposit -Encoding ascii -Value @(
        "@echo off",
        "cd /d $InstallDir",
        ".venv\Scripts\python.exe -m app.batch.deposit_voucher_sync --days 7 --send >> logs\deposit_voucher.log 2>&1"
    )
    Set-Content -Path $runDepositYak -Encoding ascii -Value @(
        "@echo off",
        "cd /d $InstallDir",
        ".venv\Scripts\python.exe -m app.batch.deposit_voucher_sync --days 7 --send --include-yak >> logs\deposit_voucher_yak.log 2>&1"
    )
}
Write-Host "[5/7] 서버·동기화·사용 가능한 보수 배치 실행 래퍼 갱신"

# 6. 동기화 일정·감시 작업 등록/재개
$cacheTask = "A10Bridge_CacheSync"
$yearTask = "A10Bridge_CacheSyncYear"
schtasks /create /f /tn $cacheTask /sc minute /mo $SyncIntervalMinutes /ru SYSTEM /tr "`"$runSync`"" | Out-Null
Remove-A10TaskIfExists "A10Bridge_CacheSyncDeep_AM"
Remove-A10TaskIfExists "A10Bridge_CacheSyncDeep_PM"
schtasks /create /f /tn $yearTask /sc daily /st $YearSyncTime /ru SYSTEM /tr "`"$runYearSync`"" | Out-Null
schtasks /create /f /tn "A10Bridge_PaymentSync" /sc daily /st $PaymentSyncTime /ru SYSTEM /tr "`"$runPayment`"" | Out-Null
if ($hasPartnerCache) {
    # 거래처 캐시 — 카드전표 가맹점 조회를 우리 DB에서 끝내려고 하루 한 번 받아둔다.
    # 실패해도 화면은 아마란스에 직접 물어 동작한다(느릴 뿐이다).
    schtasks /create /f /tn "A10Bridge_PartnerCache" /sc daily /st $PartnerCacheTime /ru SYSTEM /tr "`"$runPartnerCache`"" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "A10Bridge_PartnerCache 예약 작업 등록 실패" }
    schtasks /change /tn "A10Bridge_PartnerCache" /enable | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "A10Bridge_PartnerCache 예약 작업 활성화 실패" }
}
if ($hasOpeningRoll) {
    # 계정별원장 전기이월 — 1년에 한 번, 1월 2일. 1월 1일은 휴일이라 전표가 없고,
    # 하루 뒤면 작년 12월 전표가 캐시에 다 들어와 있다.
    schtasks /create /f /tn "A10Bridge_AccountOpeningRoll" /sc monthly /m JAN /d 2 /st $AccountOpeningRollTime /ru SYSTEM /tr "`"$runOpeningRoll`"" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "A10Bridge_AccountOpeningRoll 예약 작업 등록 실패" }
    schtasks /change /tn "A10Bridge_AccountOpeningRoll" /enable | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "A10Bridge_AccountOpeningRoll 예약 작업 활성화 실패" }
}
if ($hasFeeReviewPrepare) {
    schtasks /create /f /tn "A10Bridge_FeeReviewPrepare" /sc minute /mo $FeeReviewIntervalMinutes /ru SYSTEM /tr "`"$runFeeReview`"" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "A10Bridge_FeeReviewPrepare 예약 작업 등록 실패" }
    schtasks /change /tn "A10Bridge_FeeReviewPrepare" /enable | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "A10Bridge_FeeReviewPrepare 예약 작업 활성화 실패" }
    schtasks /create /f /tn "A10Bridge_FeeReviewPrepareHistory" /sc daily /st $FeeReviewHistoryTime /ru SYSTEM /tr "`"$runFeeReviewHistory`"" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "A10Bridge_FeeReviewPrepareHistory 예약 작업 등록 실패" }
    schtasks /change /tn "A10Bridge_FeeReviewPrepareHistory" /enable | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "A10Bridge_FeeReviewPrepareHistory 예약 작업 활성화 실패" }
}
if ($hasFeeBasisPrepare) {
    # 하루 한 번 23:00 에 최근 N개월을 한꺼번에 만든다(2026-08-07 사용자 결정).
    # 예전에는 120분마다 당월만 + 00:30 에 전월까지였는데, 두 가지가 문제였다:
    #   · 2시간 주기인데 실제로는 하루 1~2회만 돌았다(스냅숏 생성 이력으로 확인)
    #   · 당월+전월만 커버해서 그보다 과거 반월은 조회할 때마다 130초를 기다렸다
    # 하나로 합쳐 밤에 몰아 만든다. 낮 시간대 부하도 사라진다.
    schtasks /create /f /tn "A10Bridge_FeeBasisPrepare" /sc daily /st $FeeBasisTime /ru SYSTEM /tr "`"$runFeeBasis`"" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "A10Bridge_FeeBasisPrepare 예약 작업 등록 실패" }
    schtasks /change /tn "A10Bridge_FeeBasisPrepare" /enable | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "A10Bridge_FeeBasisPrepare 예약 작업 활성화 실패" }
    # History 작업은 위 하나로 흡수됐다 — 남겨두면 00:30 에 같은 일을 좁게 또 한다.
    Remove-A10TaskIfExists "A10Bridge_FeeBasisPrepareHistory"
}
if ($hasDepositVoucher) {
    schtasks /create /f /tn "A10Bridge_DepositVoucher" /sc minute /mo 60 /ru SYSTEM /tr "`"$runDeposit`"" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "A10Bridge_DepositVoucher 예약 작업 등록 실패" }
    schtasks /change /tn "A10Bridge_DepositVoucher" /enable | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "A10Bridge_DepositVoucher 예약 작업 활성화 실패" }
    # 17:00 → 17:30 (2026-09-10 사용자): 사이버브랜치 수집이 16:30 이후 입금을 늦게 싣는다
    schtasks /create /f /tn "A10Bridge_DepositVoucherYak" /sc daily /st 17:30 /ru SYSTEM /tr "`"$runDepositYak`"" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "A10Bridge_DepositVoucherYak 예약 작업 등록 실패" }
    schtasks /change /tn "A10Bridge_DepositVoucherYak" /enable | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "A10Bridge_DepositVoucherYak 예약 작업 활성화 실패" }
}
$watchdogPs1 = Join-Path $InstallDir "scripts\server_watchdog.ps1"
if (Test-Path $watchdogPs1) {
    schtasks /create /f /tn "A10Bridge_Watchdog" /sc minute /mo 5 /ru SYSTEM /tr "powershell -NoProfile -ExecutionPolicy Bypass -File $watchdogPs1" | Out-Null
    schtasks /change /tn "A10Bridge_Watchdog" /enable | Out-Null
    Write-Host "[6/7] 동기화 일정 + 감시 작업 등록/재개"
} else {
    Write-Host "[6/7] scripts\server_watchdog.ps1 없음 - 감시 작업 건너뜀" -ForegroundColor Yellow
}

# 7. 재기동 + 헬스체크 (여기서 200이 안 나오면 배포 실패로 종료)
schtasks /run /tn "A10Bridge_Server" | Out-Null
$health = $null
foreach ($i in 1..10) {
    Start-Sleep -Seconds 3
    try {
        $resp = Invoke-WebRequest -Uri "http://localhost:$Port/health" -UseBasicParsing -TimeoutSec 5
        if ($resp.StatusCode -eq 200) { $health = $resp; break }
    } catch { }
}
if ($null -ne $health) {
    Write-Host "[7/7] 배포 성공 - HEALTH: $($health.Content)" -ForegroundColor Green
    if ($hasPartnerCache) {
        # 캐시가 36시간 지나면 화면이 안 믿고 아마란스에 직접 묻는다(카드내역 불러오기가
        # 2초 -> 2분). 다음 04:20 까지 기다리지 말고 배포하면서 한 번 채운다.
        schtasks /run /tn "A10Bridge_PartnerCache" | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "거래처 캐시 갱신을 비동기로 시작했습니다(1~2분). logs\partner_cache.log"
        } else {
            Write-Host "WARNING: 거래처 캐시 갱신 시작 실패 - 예약 작업과 logs\partner_cache.log를 확인하세요." -ForegroundColor Yellow
        }
    }
    if ($hasFeeReviewPrepare) {
        schtasks /run /tn "A10Bridge_FeeReviewPrepare" | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "보수검토 현재월 스냅숏 사전생성을 비동기로 시작했습니다."
        } else {
            Write-Host "WARNING: 보수검토 현재월 사전생성 시작 실패 - 예약 작업과 logs\fee_review_prepare.log를 확인하세요." -ForegroundColor Yellow
        }
    }
    if ($hasFeeBasisPrepare) {
        schtasks /run /tn "A10Bridge_FeeBasisPrepare" | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "보수기준 점검 현재월 스냅숏 사전생성을 비동기로 시작했습니다."
        } else {
            Write-Host "WARNING: 보수기준 점검 사전생성 시작 실패 - 예약 작업과 logs\fee_basis_prepare.log를 확인하세요." -ForegroundColor Yellow
        }
    }
} else {
    Write-Host "[7/7] 배포 실패: 30초 내 헬스체크 응답 없음. 최근 로그:" -ForegroundColor Red
    Get-Content (Join-Path $InstallDir "logs\server.log") -Tail 20
    exit 1
}
