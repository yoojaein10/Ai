$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $VenvPython)) {
    python -m venv (Join-Path $ProjectDir ".venv")
}

& $VenvPython -m pip install --quiet --disable-pip-version-check -r (Join-Path $ProjectDir "requirements.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Python 패키지 설치에 실패했습니다."
}

$ConfigPath = Join-Path $ProjectDir "config.json"
if (-not (Test-Path -LiteralPath $ConfigPath)) {
    Copy-Item -LiteralPath (Join-Path $ProjectDir "config.example.json") -Destination $ConfigPath
}

Write-Host "설치 완료. 문자 DB 및 테스트 번호용 SMS_* 사용자 환경변수를 설정하세요."
