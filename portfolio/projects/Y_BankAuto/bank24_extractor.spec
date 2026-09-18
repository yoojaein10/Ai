# -*- mode: python ; coding: utf-8 -*-
"""
Bank24 담보 데이터 추출기 PyInstaller spec
빌드: pyinstaller bank24_extractor.spec
"""

block_cipher = None

a = Analysis(
    ['gui_prototype.py'],
    pathex=[r'D:\AI\Claude\Y_BankAuto'],
    binaries=[],
    datas=[],
    hiddenimports=[
        # 로컬 모듈 (동적 import)
        'extract_shinhan',
        'db_writer',
        'pdf_parser',
        'print_manager',
        # 자동 인쇄 (지연 import) — win32 GDI/프린터 + PIL DIB
        'win32print',
        'win32ui',
        'PIL.ImageWin',
        # pyodbc
        'pyodbc',
        # PyMuPDF
        'fitz',
        'fitz.fitz',
        # pywinauto
        'pywinauto',
        'pywinauto.application',
        'pywinauto.controls',
        'pywinauto.controls.common_controls',
        'pywinauto.controls.hwnd_controls',
        'pywinauto.controls.uia_controls',
        'pywinauto.controls.win32_controls',
        'pywinauto.keyboard',
        'pywinauto.mouse',
        'pywinauto.findwindows',
        'pywinauto.win32_hooks',
        'pywinauto.base_wrapper',
        'pywinauto.uia_element_info',
        'pywinauto.win32_element_info',
        # comtypes (pywinauto UIA 백엔드)
        'comtypes',
        'comtypes.client',
        'comtypes.server',
        'comtypes.typeinfo',
        'comtypes.automation',
        'comtypes._safearray',
        'comtypes.persist',
        # pyautogui
        'pyautogui',
        'pyscreeze',
        'mouseinfo',
        # pyperclip
        'pyperclip',
        'pyperclip.handlers',
        # win32 (pywinauto 의존)
        'win32api',
        'win32con',
        'win32gui',
        'win32process',
        'win32security',
        'win32event',
        'win32file',
        'pywintypes',
        'winerror',
        # 기타
        'PIL',
        'PIL.Image',
        'six',
        'packaging',
        'packaging.version',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 충돌하는 Qt 바인딩 제거 (PyQt6만 사용)
        'PyQt5',
        'PyQt5.QtCore',
        'PyQt5.QtGui',
        'PyQt5.QtWidgets',
        'PySide2',
        'PySide6',
        # 불필요한 대형 패키지
        'tkinter',
        'matplotlib',
        'numpy',
        'scipy',
        'pandas',
        'IPython',
        'jupyter',
        'notebook',
        'cv2',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='bank24_extractor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,       # GUI 앱 — 콘솔 창 없음
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
    version=None,
)
