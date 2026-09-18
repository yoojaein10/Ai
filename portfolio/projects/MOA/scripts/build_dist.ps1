# 서버 배포 폴더(dist\A10Bridge_server) 생성 스크립트.
# 소스(app/desktop/docs/scripts)를 그대로 복사하고 캐시류만 제외한다.
# 사용법: 프로젝트 루트에서  powershell -ExecutionPolicy Bypass -File scripts\build_dist.ps1
# 만든 폴더를 통째로 서버 C:\A10Bridge 에 덮어쓰고 서비스 재시작하면 배포 끝.
#
# .env 규칙:
#  - dist에 .env가 이미 있으면 그대로 둔다 (서버용 설정을 보존)
#  - 없으면 루트 .env를 복사해주고 경고를 띄운다 (값 확인 필요)
#  - .env는 git에 올라가지 않으므로 새 PC에서는 값을 직접 받아 채워야 한다

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot   # scripts\ 의 부모 = 프로젝트 루트
$dist = Join-Path $root 'dist\A10Bridge_server'

Write-Host "== MOA 서버 배포 폴더 생성 =="
Write-Host "소스: $root"
Write-Host "대상: $dist"

if (-not (Test-Path (Join-Path $root 'app\main.py')) -and -not (Test-Path (Join-Path $root 'app'))) {
    throw "프로젝트 루트가 아닙니다: $root (app 폴더가 없음)"
}
New-Item -ItemType Directory -Force $dist | Out-Null

# 폴더 4개: /MIR = 소스와 동일하게 맞춤(dist 쪽 잉여 파일 제거), 캐시류 제외
$folders = 'app', 'desktop', 'docs', 'scripts'
foreach ($name in $folders) {
    $src = Join-Path $root $name
    $dst = Join-Path $dist $name
    robocopy $src $dst /MIR /NFL /NDL /NJH /NJS /XD __pycache__ .pytest_cache /XF *.pyc | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy 실패($name): 종료코드 $LASTEXITCODE" }
    Write-Host "  복사됨: $name"
}
# robocopy 종료코드는 0~7이 정상이므로 여기서 초기화 (이후 $LASTEXITCODE 오해 방지)
$global:LASTEXITCODE = 0

# 루트 파일
Copy-Item (Join-Path $root 'requirements.txt') $dist -Force
Copy-Item (Join-Path $root '.env.example') $dist -Force
Write-Host "  복사됨: requirements.txt, .env.example"

# .env 처리
$distEnv = Join-Path $dist '.env'
if (Test-Path $distEnv) {
    Write-Host "  유지됨: .env (기존 서버용 설정 보존)"
} elseif (Test-Path (Join-Path $root '.env')) {
    Copy-Item (Join-Path $root '.env') $distEnv
    Write-Host "  ⚠ .env가 없어 로컬 .env를 복사했습니다 — 서버용 값이 맞는지 확인하세요" -ForegroundColor Yellow
} else {
    Write-Host "  ⚠ .env가 없습니다 — .env.example을 참고해 만들어 넣으세요" -ForegroundColor Yellow
}

$count = (Get-ChildItem $dist -Recurse -File | Measure-Object).Count
Write-Host "== 완료: 파일 ${count}개 =="
Write-Host "다음 단계: dist\A10Bridge_server 폴더를 서버 C:\A10Bridge 에 덮어쓰기 → 서비스 재시작"
Write-Host "(주의: 서버의 C:\A10Bridge 바로 아래에 app 폴더가 오도록 — 한 단계 더 들어가면 안 됨)"
