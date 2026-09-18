<#
.SYNOPSIS
  보수기준 사전생성(검토·점검 두 화면)을 Windows 작업 스케줄러에 등록한다.

.DESCRIPTION
  두 화면 모두 원천 조회가 느리고, 사전생성본이 있으면 0.05~0.3초에 나온다.
    보수기준 검토(fee-review)  월전체 306행 기준 원천 45~110초 → 캐시 0.2~0.33초
    보수기준 점검(fee-basis)   반월 137행 기준 원천 80초       → 캐시 0.05초

  등록되는 작업 4개 — 두 배치가 같은 원천 DB를 크게 훑으므로 시간을 엇갈리게 둔다.
    03:10  A10Bridge-FeeReviewPrepare-Nightly   검토 · 당월+직전 2개월 · 전 지사
    04:10  A10Bridge-FeeBasisPrepare-Nightly    점검 · 당월+직전 2개월 · 본사 · 상반+하반
    12:40  A10Bridge-FeeReviewPrepare-Midday    검토 · 당월만
    13:20  A10Bridge-FeeBasisPrepare-Midday     점검 · 당월만

  점검이 본사만인 이유: 본사 관리 화면이고, 18개 지사를 전부 돌리면 반월·개월수를
  곱해 두 시간을 넘긴다. 지사가 필요하면 -BasisOffice 로 지정한다.

  사전생성본 유효기간은 당월 6시간·마감월 30시간이다. 규칙 버전을 올리면 즉시 무효가
  되므로 규칙을 바꾼 날은 배치를 다시 돌린다.

  등록만 하고 즉시 실행하지는 않는다. 확인 후 -RunNow 로 한 번 돌려보면 된다.

.NOTES
  운영 서버 등록은 별도 승인 사항이다. 이 스크립트는 대상 컴퓨터에서 관리자 권한으로
  실행한 그 컴퓨터에만 작업을 만든다.
#>
[CmdletBinding()]
param(
  # param 기본값에서는 $PSScriptRoot·$MyInvocation 이 아직 비어 있다(PS 5.1).
  # 그래서 여기서 계산하지 않고 본문에서 채운다.
  [string]$ProjectRoot = '',
  [string]$ReviewNightlyTime = '03:10',
  [string]$BasisNightlyTime = '04:10',
  [string]$ReviewMiddayTime = '12:40',
  [string]$BasisMiddayTime = '13:20',
  [int]$MonthsBack = 2,
  # 보수기준 점검을 돌릴 지사. 생략하면 본사만.
  [string[]]$BasisOffice = @('10'),
  [string]$RunAsUser = "$env:USERDOMAIN\$env:USERNAME",
  [switch]$SkipMidday,
  [switch]$RunNow,
  [switch]$Remove
)

$ErrorActionPreference = 'Stop'

if (-not $ProjectRoot) {
  $ProjectRoot = Split-Path -Parent $PSScriptRoot
}

$python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$logDir = Join-Path $ProjectRoot 'logs'

$tasks = @(
  @{ Name = 'A10Bridge-FeeReviewPrepare-Nightly'; Time = $ReviewNightlyTime
     Module = 'app.batch.fee_review_prepare'; Back = $MonthsBack
     Log = 'fee_review_prepare_nightly.log'; Midday = $false; Basis = $false }
  @{ Name = 'A10Bridge-FeeBasisPrepare-Nightly'; Time = $BasisNightlyTime
     Module = 'app.services.fee_basis'; Back = $MonthsBack
     Log = 'fee_basis_prepare_nightly.log'; Midday = $false; Basis = $true }
  @{ Name = 'A10Bridge-FeeReviewPrepare-Midday'; Time = $ReviewMiddayTime
     Module = 'app.batch.fee_review_prepare'; Back = 0
     Log = 'fee_review_prepare_midday.log'; Midday = $true; Basis = $false }
  @{ Name = 'A10Bridge-FeeBasisPrepare-Midday'; Time = $BasisMiddayTime
     Module = 'app.services.fee_basis'; Back = 0
     Log = 'fee_basis_prepare_midday.log'; Midday = $true; Basis = $true }
)

if ($Remove) {
  foreach ($task in $tasks) {
    if (Get-ScheduledTask -TaskName $task.Name -ErrorAction SilentlyContinue) {
      Unregister-ScheduledTask -TaskName $task.Name -Confirm:$false
      "제거: $($task.Name)"
    }
  }
  return
}

if (-not (Test-Path $python)) {
  throw "가상환경 python을 찾을 수 없습니다: $python"
}
if (-not (Test-Path $logDir)) {
  New-Item -ItemType Directory -Path $logDir | Out-Null
}

foreach ($task in $tasks) {
  if ($SkipMidday -and $task.Midday) { continue }

  # 배치 모듈이 없는 서버(예: 보수기준 점검만 배포)에서는 그 작업을 등록하지 않는다.
  # 등록하면 매일 밤 ModuleNotFoundError 로 실패 이력만 쌓인다.
  $modulePath = Join-Path $ProjectRoot ($task.Module -replace '\.', '\')
  $modulePath = "$modulePath.py"
  if (-not (Test-Path $modulePath)) {
    "건너뜀(모듈 없음): $($task.Name) — $modulePath"
    continue
  }

  $arguments = "-m $($task.Module) --months-back $($task.Back)"
  if ($task.Basis) {
    foreach ($office in $BasisOffice) { $arguments += " --office $office" }
  }

  # cmd /c 로 감싸는 이유: 작업 스케줄러 액션은 파이프·리다이렉션을 직접 해석하지 못한다.
  $log = Join-Path $logDir $task.Log
  $inner = "`"$python`" $arguments"
  $action = New-ScheduledTaskAction -Execute 'cmd.exe' `
    -Argument "/c $inner >> `"$log`" 2>&1" `
    -WorkingDirectory $ProjectRoot
  $trigger = New-ScheduledTaskTrigger -Daily -At $task.Time
  # 지사 수 × 개월 수 × 반월만큼 도는 배치라 넉넉히 두고, 겹치면 새 회차를 버린다
  # (배치 자체도 sp_getapplock 으로 중복을 막는다).
  $settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -DontStopOnIdleEnd
  $principal = New-ScheduledTaskPrincipal -UserId $RunAsUser `
    -LogonType S4U -RunLevel Limited

  Register-ScheduledTask -TaskName $task.Name -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null
  "등록: $($task.Name) ($($task.Time), $arguments) → $log"
}

if ($RunNow) {
  foreach ($name in @('A10Bridge-FeeReviewPrepare-Nightly',
                      'A10Bridge-FeeBasisPrepare-Nightly')) {
    Start-ScheduledTask -TaskName $name
    "즉시 실행 요청: $name"
  }
  "진행 상황은 logs\fee_*_prepare_nightly.log 를 보세요."
}

Get-ScheduledTask -TaskName 'A10Bridge-Fee*' |
  Select-Object TaskName, State |
  Format-Table -AutoSize
