# 앱을 외부 공개 URL로 노출 (Cloudflare Quick Tunnel)
# 사용법: 앱이 떠 있는 상태에서  .\share_url.ps1  실행 → 표시되는 trycloudflare.com 주소 공유
# 종료: 이 창을 닫으면 URL도 즉시 무효화된다 (시연 끝나면 꼭 닫을 것 — 로그인 없는 앱이므로)
$cloudflared = "$PSScriptRoot\..\cloudflared\cloudflared.exe"
if (-not (Test-Path $cloudflared)) {
    Write-Host "cloudflared.exe가 없습니다. 다운로드: https://github.com/cloudflare/cloudflared/releases"
    exit 1
}
Write-Host "공개 URL 생성 중... (아래 https://xxx.trycloudflare.com 주소를 공유하세요)"
& $cloudflared tunnel --url http://localhost:8501
