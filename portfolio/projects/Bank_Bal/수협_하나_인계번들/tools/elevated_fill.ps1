# 관리자(High integrity) 자식 프로세스로 autofill_<bank> 를 실행한다.
# Medium 세션에서 High 권한 BANK24 폼에 쓰려면 이 우회가 필요하다(UAC 승인 1회).
# 사용: powershell -ExecutionPolicy Bypass -File tools\elevated_fill.ps1 <문서번호> [-Bank ssb|hnb] [-Live] [-Overwrite] [-Env <.env 경로>]
#   -Bank ssb  수협(autofill_ssb.py, 기본)   -Bank hnb  하나(autofill_hnb.py, 단일물건)
#   -Live      실입력(없으면 드라이런)         -Overwrite 사람이 넣은 값도 덮어씀(기본 빈칸만)
#   -Env       .env 경로(생략 시 번들 루트 .env)
# ⚠️ --select(콤보 자동선택)·--all --live(하나 다물건 순회)는 감사 P0 로 봉인됨 — 여기서 전달하지 않는다.
# ※ 이 파일은 UTF-8 BOM 으로 저장돼 있어야 한다(Windows PowerShell 5.1 이 한글을 바로 읽으려면).
param(
  [Parameter(Mandatory=$true)][string]$Doc,
  [ValidateSet("ssb","hnb")][string]$Bank = "ssb",
  [switch]$Live,
  [switch]$Overwrite,
  [string]$Env = ""
)
$root   = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$script = "tools\autofill_$Bank.py"
if (-not (Test-Path (Join-Path $root $script))) { throw "없는 스크립트: $script" }
$log    = Join-Path $root "scratch_elevated_fill_$Bank.log"
$argline = "$Doc"
if ($Live)      { $argline += " --live" }
if ($Overwrite) { $argline += " --overwrite" }
if ($Env -ne "") { $argline += " --env `"$Env`"" }
# 관리자 파이썬이 실행할 내부 명령: env 설정 + autofill + 로그로 캡처(-u: 줄 단위 flush)
$inner = "cd /d `"$root`" & set `"PYTHONUTF8=1`" & set `"PYTHONPATH=src;tools`" & python -u $script $argline > `"$log`" 2>&1"
Remove-Item $log -ErrorAction SilentlyContinue
# RunAs 로 관리자 승격(UAC 팝업) → cmd 로 inner 실행 후 종료
Start-Process cmd.exe -ArgumentList "/c $inner" -Verb RunAs -WindowStyle Hidden -Wait
Write-Host "완료 [$Bank] — 로그: $log"
if (Test-Path $log) { Get-Content $log -Encoding UTF8 | Select-Object -Last 40 }
