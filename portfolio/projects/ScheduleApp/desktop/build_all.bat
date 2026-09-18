@echo off
cd /d "%~dp0"

echo [1/2] Building ScheduleApp.exe ...
pyinstaller ScheduleApp.spec --noconfirm
if errorlevel 1 (
    echo ERROR: ScheduleApp build failed.
    pause
    exit /b 1
)

echo.
echo [2/2] Building ScheduleLauncher.exe ...
pyinstaller ScheduleLauncher.spec --noconfirm
if errorlevel 1 (
    echo ERROR: ScheduleLauncher build failed.
    pause
    exit /b 1
)

echo.
echo ===== Build complete =====
echo.
echo Deploy the following files to:
echo   \\server\DATA1\전산\SEAT\ScheduleAppDeploy\
echo.
echo   dist\ScheduleApp.exe
echo   dist\ScheduleLauncher.exe
echo   version.txt
echo.
echo Update version.txt before deploying a new ScheduleApp.exe.
echo.
pause
