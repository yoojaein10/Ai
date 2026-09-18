# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the A10 Bridge thin desktop client (onedir build).
# The central server hosts UI/API/DB; this exe is only a pywebview window.
# Debug build: set A10_DEBUG_CONSOLE=1 to get a console window with tracebacks.
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
    [],
    exclude_binaries=True,
    name='A10BridgeDesktop',
    debug=False,
    strip=False,
    upx=False,
    console=os.environ.get('A10_DEBUG_CONSOLE') == '1',
    disable_windowed_traceback=False,
    icon=os.path.join(SPECPATH, 'moa.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='A10BridgeDesktop',
)
