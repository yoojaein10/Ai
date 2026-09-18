# 관리자(High integrity) 파이썬으로 verify_docs_live.py 를 실행한다 — BANK24 자동 열람·대조(읽기 전용).
# 사용: powershell -ExecutionPolicy Bypass -File tools\elevated_verify.ps1 -Bank ssb|hnb [-Recent 5] [-Docs "01-2609-3-2785 01-2609-3-2759"] [-Env <.env 경로>]
#   결과 로그: reports\verify_live_<bank>_<timestamp>.log (UAC 승인 1회, 도는 동안 마우스·키보드 건드리지 말 것)
#   -Env 생략 시 번들 루트의 .env 를 쓴다(.env.example 을 채워 저장해 둘 것).
# ※ 이 파일은 UTF-8 BOM 으로 저장돼 있어야 한다(Windows PowerShell 5.1 이 한글을 바로 읽으려면).
param(
  [ValidateSet("ssb","hnb","")][string]$Bank = "",
  [int]$Recent = 0,
  [string]$Docs = "",
  [string]$Env = "",
  [switch]$LocateOnly          # 폼 안 열고 문서가 어느 탭·어떤 행(의뢰일자 등)인지만 — 은행 무관
)
if (-not $LocateOnly -and $Bank -eq "") { throw "-Bank ssb|hnb 가 필요합니다(-LocateOnly 가 아니면)." }
$tag = if ($Bank -ne "") { $Bank } else { "locate" }
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$reports = Join-Path $root "reports"
if (-not (Test-Path $reports)) { New-Item -ItemType Directory -Path $reports | Out-Null }
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$log   = Join-Path $reports "verify_live_${tag}_$stamp.log"
$argline = ""
if ($Bank -ne "")  { $argline += " --bank $Bank" }
if ($LocateOnly)   { $argline += " --locate-only" }
if ($Recent -gt 0) { $argline += " --recent $Recent" }
if ($Env -ne "")   { $argline += " --env `"$Env`"" }
if ($Docs -ne "")  { $argline += " $Docs" }
$inner = "cd /d `"$root`" & set `"PYTHONUTF8=1`" & set `"PYTHONPATH=src;tools`" & python -u tools\verify_docs_live.py $argline > `"$log`" 2>&1"
Start-Process cmd.exe -ArgumentList "/c $inner" -Verb RunAs -WindowStyle Minimized -Wait
Write-Host "완료 [$tag] — 로그: $log"
if (Test-Path $log) {
  Get-Content $log -Encoding UTF8 | Select-String -Pattern '=====|^  --|Error|Traceback|SUMMARY|^  01-' | ForEach-Object { $_.Line }
}
