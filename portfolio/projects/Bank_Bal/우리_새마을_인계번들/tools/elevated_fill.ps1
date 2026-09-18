# 관리자(High integrity) 자식 프로세스로 autofill_ssb 를 실행한다.
# Medium 세션에서 High 권한 BANK24 폼에 쓰려면 이 우회가 필요하다(UAC 승인 1회).
# 사용: powershell -ExecutionPolicy Bypass -File tools\elevated_fill.ps1 <문서번호> [--live]
# ⚠️ --select(콤보 자동선택)는 감사 P0-D 로 봉인됨 — 여기서 전달하지 않는다(콤보는 사람이 선택).
param(
  [Parameter(Mandatory=$true)][string]$Doc,
  [switch]$Live
)
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$log  = Join-Path $root "scratch_elevated_fill.log"
$args = "$Doc"
if ($Live)   { $args += " --live" }
# 관리자 파이썬이 실행할 내부 명령: env 설정 + autofill_ssb + 로그로 캡처
$inner = "cd /d `"$root`" & set `"PYTHONUTF8=1`" & set `"PYTHONPATH=src;tools`" & python tools\autofill_ssb.py $args > `"$log`" 2>&1"
Remove-Item $log -ErrorAction SilentlyContinue
# RunAs 로 관리자 승격(UAC 팝업) → cmd 로 inner 실행 후 종료
Start-Process cmd.exe -ArgumentList "/c $inner" -Verb RunAs -WindowStyle Hidden -Wait
Write-Host "완료 — 로그: $log"
