# -*- mode: python ; coding: utf-8 -*-
# 빌드: python -m PyInstaller KrasFill.spec --noconfirm --clean
# 산출: dist\KrasFill.exe (onefile, GUI). settings.ini는 exe 옆에 별도 배치.

a = Analysis(
    ["gui.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=["win32com", "win32com.client", "pythoncom", "pyodbc"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="KrasFill",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
