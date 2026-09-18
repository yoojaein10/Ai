$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "=== 문자 발송 환경변수 설정 ===" -ForegroundColor Cyan
Write-Host "값을 입력하면 이 Windows 계정의 사용자 환경변수로 저장됩니다."
Write-Host "이미 저장된 값을 그대로 쓰려면 그냥 Enter를 누르세요."
Write-Host ""

$vars = @(
    @{ Name = "SMS_DB_SERVER";           Prompt = "문자 DB 서버 주소" },
    @{ Name = "SMS_DB_NAME";             Prompt = "문자 DB 이름" },
    @{ Name = "SMS_DB_USER";             Prompt = "DB 계정" },
    @{ Name = "SMS_DB_PASSWORD";         Prompt = "DB 비밀번호"; Secret = $true },
    @{ Name = "SMS_CALL_FROM";           Prompt = "발신번호" },
    @{ Name = "SMS_RECIPIENT_DB_NAME";   Prompt = "수신자 DB 이름(Seat_UserInfo가 있는 DB)" },
    @{ Name = "SMS_TEST_PHONE";          Prompt = "테스트 수신번호"; Default = "010-0000-0000" }
)

foreach ($v in $vars) {
    $current = [Environment]::GetEnvironmentVariable($v.Name, "User")
    $label = $v.Prompt
    if ($current) {
        if ($v.Secret) { $label += " [저장됨]" }
        else { $label += " [현재: $current]" }
    }
    elseif ($v.Default) {
        $label += " [기본값: $($v.Default)]"
    }

    $value = Read-Host $label
    if (-not $value) {
        if ($current) { $value = $current }
        elseif ($v.Default) { $value = $v.Default }
        else {
            Write-Host "$($v.Name) 값이 비어 있어 중단합니다." -ForegroundColor Red
            exit 1
        }
    }

    [Environment]::SetEnvironmentVariable($v.Name, $value, "User")
    Set-Item -Path ("Env:" + $v.Name) -Value $value
}

Write-Host ""
Write-Host "환경변수 저장 완료." -ForegroundColor Green
Write-Host ""

$answer = Read-Host "지금 바로 010-0000-0000으로 테스트 발송할까요? (Y/N)"
if ($answer -match '^[yY]') {
    & (Join-Path $ProjectDir "test_send.ps1")
    exit $LASTEXITCODE
}
Write-Host "테스트 발송은 3_test_send.bat을 더블클릭하면 됩니다."
