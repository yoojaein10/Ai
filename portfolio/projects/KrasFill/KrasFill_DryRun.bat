@echo off
rem == KrasFill DRY-RUN: compare only, no writing ==
cd /d "%~dp0"
if "%~1"=="" (
  echo.
  echo   Usage: drag xlsx files or a folder onto this bat file.
  echo.
  pause
  exit /b
)
python main.py --dry-run %*
echo.
pause
