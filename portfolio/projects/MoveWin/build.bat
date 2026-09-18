@echo off
chcp 65001 > nul
echo [1/3] 패키지 설치 중...
pip install -r requirements.txt -q

echo.
echo [2/3] EXE 빌드 중...
pyinstaller ^
  --onefile ^
  --windowed ^
  --name "Oct" ^
  --add-data "char.png;." ^
  --hidden-import "pynput.keyboard._win32" ^
  --hidden-import "pynput.mouse._win32" ^
  --hidden-import "PyQt5.sip" ^
  --hidden-import "PIL._imaging" ^
  --hidden-import "numpy" ^
  main.py

echo.
echo [3/3] 완료!
echo EXE 위치: dist\Oct.exe
echo.
pause
