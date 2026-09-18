$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe = Join-Path $ProjectDir ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw "먼저 setup.ps1을 실행하세요."
}

& $PythonExe (Join-Path $ProjectDir "app.py") run
exit $LASTEXITCODE

