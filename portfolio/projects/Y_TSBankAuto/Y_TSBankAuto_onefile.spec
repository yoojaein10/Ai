# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onefile spec for portable single-EXE distribution."""

block_cipher = None

hiddenimports = [
    "app_gui", "gui", "orchestrator", "bank24_adapter", "bank24_automation",
    "bank24_trust", "bank24_backend",
    "bank24_credentials", "pdf_worker", "pdf_download", "pipeline",
    "single_flight", "settings_integrity", "applog",
    "address_mapper", "config", "security", "models", "sp_spec", "ts_db_writer",
    "ro_query", "ro_config", "ro_connect", "ro_guards", "ro_metadata",
    "ro_lookups", "ro_pipeline", "ro_duplicate",
    "parsers", "parsers.base", "parsers.forest", "parsers.hana",
    "parsers.ibk", "parsers.imbank", "parsers.kookmin",
    "parsers.koreainvest", "parsers.nhcentral", "parsers.nonghyup",
    "parsers.saemaeul", "parsers.shinhan", "parsers.suhyup", "parsers.woori",
    "PyQt6", "PyQt6.QtCore", "PyQt6.QtGui", "PyQt6.QtWidgets", "PyQt6.sip",
    "fitz",
    "keyring", "keyring.backends", "keyring.backends.Windows",
    "win32api", "win32security", "win32event", "win32job", "win32process",
    "win32gui", "win32file", "win32con", "ntsecuritycon", "psutil",
    "pywintypes", "winerror",
    # pywinauto — 하위모듈을 명시(자동탐지 갭 방지; Y_BankAuto 검증 spec 동등)
    "pywinauto", "pywinauto.application",
    "pywinauto.controls", "pywinauto.controls.common_controls",
    "pywinauto.controls.hwnd_controls", "pywinauto.controls.uia_controls",
    "pywinauto.controls.win32_controls",
    "pywinauto.keyboard", "pywinauto.mouse", "pywinauto.findwindows",
    "pywinauto.win32_hooks", "pywinauto.base_wrapper",
    "pywinauto.uia_element_info", "pywinauto.win32_element_info",
    # comtypes — pywinauto 가 백엔드 등록 시 import(자동탐지가 놓칠 수 있음)
    "comtypes", "comtypes.client", "comtypes.server", "comtypes.typeinfo",
    "comtypes.automation", "comtypes._safearray", "comtypes.persist",
    "comtypes.stream", "comtypes.gen",
    # ★ 런타임 생성 모듈을 미리 번들 — 타깃 PC 에서 재생성 실패로 인한 ImportError 방지.
    #   uia_defines.GetModule('UIAutomationCore.dll') 가 win32 백엔드에서도 로드하는
    #   UIAutomationClient + 의존 typelib 래퍼(stdole/UIAutomation GUID 모듈).
    "comtypes.gen.UIAutomationClient", "comtypes.gen.stdole",
    "comtypes.gen._00020430_0000_0000_C000_000000000046_0_2_0",
    "comtypes.gen._944DE083_8FB8_45CF_BCB7_C477ACB2F897_0_1_0",
    # pyautogui / 클립보드 / 좌표 fallback 의존
    "pyautogui", "pyscreeze", "mouseinfo",
    "pyperclip", "pyperclip.handlers",
    "six", "packaging", "packaging.version",
]

excludes = [
    "tests", "pytest", "numpy", "pandas", "matplotlib", "scipy",
    "openpyxl", "PIL",
]

a = Analysis(
    ["main_app.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
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
    name="Y_TSBankAuto",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    # Bank24(C:\KADC\X11\Bank24.exe)는 관리자 권한(elevated)으로 실행되므로, 동일 무결성
    # 수준에서만 WM_SETTEXT/키보드 입력이 전달된다(UIPI). 일반 권한이면 로그인 필드 입력이
    # 조용히 차단됨. requireAdministrator 매니페스트로 실행 시 관리자 권한을 요청한다.
    uac_admin=True,
    disable_windowed_traceback=True,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
    version=None,
)
