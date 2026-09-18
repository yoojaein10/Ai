@echo off
rem == KrasFill: drag & drop xlsx files or a folder onto this file ==
cd /d "%~dp0"
if "%~1"=="" (
  echo.
  echo   Usage: drag xlsx files or a folder onto this bat file.
  echo.
  pause
  exit /b
)
python main.py %*
echo.
pause
