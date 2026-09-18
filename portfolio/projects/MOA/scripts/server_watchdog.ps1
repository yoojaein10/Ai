# A10 Bridge 서버 감시 (A10Bridge_Watchdog 예약 작업이 5분마다 실행).
# /health가 응답하면 아무것도 하지 않고 종료(로그 없음 - 로그 비대 방지).
# 응답이 없으면 A10Bridge_Server를 재기동하고 logs\watchdog.log에 기록한다.
param(
    [string]$InstallDir = (Split-Path -Parent $PSScriptRoot),
    [int]$Port = 8010
)
$log = Join-Path $InstallDir "logs\watchdog.log"

try {
    $resp = Invoke-WebRequest -Uri "http://localhost:$Port/health" -UseBasicParsing -TimeoutSec 10
    if ($resp.StatusCode -eq 200) { exit 0 }
} catch { }

$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path $log -Value "$stamp 헬스체크 실패 - A10Bridge_Server 재기동 시도"

schtasks /end /tn "A10Bridge_Server" 2>$null | Out-Null
Start-Sleep -Seconds 3
schtasks /run /tn "A10Bridge_Server" | Out-Null
Start-Sleep -Seconds 15

$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
try {
    $resp = Invoke-WebRequest -Uri "http://localhost:$Port/health" -UseBasicParsing -TimeoutSec 10
    Add-Content -Path $log -Value "$stamp 재기동 성공 - health $($resp.StatusCode)"
} catch {
    Add-Content -Path $log -Value "$stamp 재기동 후에도 무응답 - logs\server.log 확인 필요"
}
