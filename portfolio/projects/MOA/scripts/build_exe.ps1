# A10 Bridge thin desktop client build script (PyInstaller onedir).
# Usage:
#   scripts\build_exe.ps1          # release build (no console window)
#   scripts\build_exe.ps1 -Debug   # debug build (console window with tracebacks)
param([switch]$Debug)

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

pip install -r requirements-desktop.txt

if ($Debug) {
    $env:A10_DEBUG_CONSOLE = "1"
    Write-Host "== DEBUG build (console enabled) =="
} else {
    $env:A10_DEBUG_CONSOLE = "0"
}

pyinstaller desktop\a10bridge_desktop.spec --noconfirm --distpath dist
if ($LASTEXITCODE -ne 0) { throw "pyinstaller failed with exit code $LASTEXITCODE" }

Copy-Item desktop\A10BridgeDesktop.ini.example dist\A10BridgeDesktop\A10BridgeDesktop.ini.example -Force

Write-Host ""
Write-Host "Build done: dist\A10BridgeDesktop\"
Write-Host "Deploy: zip the folder; on the target PC create A10BridgeDesktop.ini next to the exe"
Write-Host "(see docs\DESKTOP_APP.md / docs\APWORKS_LAUNCH.md)"
