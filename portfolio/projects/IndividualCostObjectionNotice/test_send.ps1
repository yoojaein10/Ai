$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe = Join-Path $ProjectDir ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $PythonExe)) {
    Write-Host "설치가 안 되어 있어 먼저 설치합니다..." -ForegroundColor Yellow
    & (Join-Path $ProjectDir "setup.ps1")
    if (-not (Test-Path -LiteralPath $PythonExe)) {
        Write-Host "설치에 실패했습니다. 1_install.bat을 먼저 실행하세요." -ForegroundColor Red
        exit 1
    }
}

foreach ($name in "SMS_DB_SERVER", "SMS_DB_NAME", "SMS_DB_USER", "SMS_DB_PASSWORD", "SMS_CALL_FROM", "SMS_TEST_PHONE") {
    if (-not (Get-Item -Path ("Env:" + $name) -ErrorAction SilentlyContinue)) {
        $saved = [Environment]::GetEnvironmentVariable($name, "User")
        if ($saved) { Set-Item -Path ("Env:" + $name) -Value $saved }
        else {
            Write-Host "$name 환경변수가 없습니다. 2_setup_env_and_test.bat을 먼저 실행하세요." -ForegroundColor Red
            exit 1
        }
    }
}

Write-Host "=== 테스트 발송 시작 (수신: 010-0000-0000) ===" -ForegroundColor Cyan
& $PythonExe (Join-Path $ProjectDir "app.py") test-send
$code = $LASTEXITCODE
if ($code -eq 0) {
    Write-Host ""
    Write-Host "테스트 발송 큐 등록 성공. 휴대폰으로 문자를 확인하세요." -ForegroundColor Green
}
else {
    Write-Host ""
    Write-Host "테스트 발송 실패. 위 오류 메시지와 logs\app.log를 확인하세요." -ForegroundColor Red
}
exit $code
