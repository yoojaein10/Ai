# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the MOA thin desktop client (onefile build).
# onedir(a10bridge_desktop.spec)과 동일 구성이나 단일 EXE로 묶는다.
# 실행 시 임시 폴더에 풀리므로 시작이 느릴 수 있으나(25~60초 관찰),
# 배포 단순성(EXE+ini 두 파일)을 위해 단일 EXE 배포 채택 (2026-07-22 사용자 결정).
import os

a = Analysis(
    [os.path.join(SPECPATH, 'main.py')],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        # pywebview loads its platform backend via dynamic import strings
        'webview.platforms.winforms',
        'webview.platforms.edgechromium',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # unrelated site-packages pulled in by broad hooks - not used by this app
        'PyQt5', 'matplotlib', 'numpy', 'pandas', 'scipy', 'pygame',
        'IPython', 'PIL', 'jedi', 'parso', 'tkinter',
        'sqlalchemy', 'pyodbc', 'uvicorn', 'fastapi', 'pydantic',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='A10BridgeDesktop_onefile',
    debug=False,
    strip=False,
    upx=False,
    console=os.environ.get('A10_DEBUG_CONSOLE') == '1',
    disable_windowed_traceback=False,
    icon=os.path.join(SPECPATH, 'moa.ico'),
)
