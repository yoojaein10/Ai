@echo off
echo [Bank24] PyInstaller 빌드 시작...
pip install pyinstaller -q
pyinstaller --onefile --noconsole --name bank24_auto bank24_auto.py
pyinstaller --onefile --noconsole --name bank24_gui gui.py
echo [Bank24] 빌드 완료: dist\bank24_auto.exe
pause
