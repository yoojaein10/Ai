# AI 학습 도우미 — 로컬 전체 실행 스크립트
# Redis → Celery worker → FastAPI → Streamlit UI 순서로 띄운다.
# 사용법: PowerShell에서  .\run_all.ps1
$root = $PSScriptRoot

# 1) Redis (이미 떠 있으면 재사용)
$redisUp = Get-NetTCPConnection -LocalPort 6379 -State Listen -ErrorAction SilentlyContinue
if (-not $redisUp) {
    Start-Process -FilePath "$root\..\redis\redis-server.exe" -ArgumentList "--port 6379 --maxmemory 256mb" -WindowStyle Hidden
    Write-Host "Redis 시작 (포트 6379)"
} else {
    Write-Host "Redis 이미 실행 중"
}

# 2) Celery worker (Windows는 solo 풀) — 별도 창
Start-Process -FilePath "$root\.venv\Scripts\celery.exe" `
    -ArgumentList "-A worker.tasks worker --pool=solo --loglevel=info" `
    -WorkingDirectory $root
Write-Host "Celery worker 시작"

# 3) FastAPI (비동기 파이프라인 API, 포트 8000) — 별도 창
Start-Process -FilePath "$root\.venv\Scripts\uvicorn.exe" `
    -ArgumentList "api.main:app --port 8000" `
    -WorkingDirectory $root
Write-Host "FastAPI 시작 (http://localhost:8000/docs)"

# 4) Streamlit UI (포트 8501) — 현재 창, Ctrl+C로 종료
& "$root\.venv\Scripts\streamlit.exe" run "$root\app\streamlit_app.py"
