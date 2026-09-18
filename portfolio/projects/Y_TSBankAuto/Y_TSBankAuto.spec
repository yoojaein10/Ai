# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir 스펙 (지시 §17).

- onedir (COLLECT). onefile 아님(공용 TEMP 추출 회피). UPX 미사용.
- console=False(windowed). selftest 는 종료코드, PDF worker 는 전용 결과 파일 IPC 로
  결과를 전달한다(stdout 을 smoke 통신 수단으로 쓰지 않는다).
- 번들에 자격증명/실 settings.ini/allowlist 실값/PDF/CSV/Excel/로그/실데이터/
  fake fixture/테스트 모듈을 포함하지 않는다(datas=[], tests/settings 제외).
- 런타임 자격증명·allowlist·settings 는 번들 밖 디스크에서만 읽는다.
"""

block_cipher = None

hiddenimports = [
    # 로컬 모듈(지연 import 포함)
    "app_gui", "gui", "orchestrator", "bank24_adapter", "bank24_automation",
    "bank24_trust", "bank24_backend",
    "bank24_credentials", "pdf_worker", "pdf_download", "pipeline",
    "single_flight", "settings_integrity", "applog",
    "address_mapper", "config", "security", "models", "sp_spec", "ts_db_writer",
    "ro_query", "ro_config", "ro_connect", "ro_guards", "ro_metadata",
    "ro_lookups", "ro_pipeline", "ro_duplicate",
    "parsers", "parsers.base", "parsers.ibk", "parsers.kookmin",
    "parsers.koreainvest",
    "parsers.nonghyup", "parsers.saemaeul", "parsers.suhyup", "parsers.woori",
    # GUI (PyQt6) — PyInstaller PyQt6 훅이 플러그인/DLL 을 자동 수집
    "PyQt6", "PyQt6.QtCore", "PyQt6.QtGui", "PyQt6.QtWidgets", "PyQt6.sip",
    # 서드파티(fake/real adapter 및 검증에 필요)
    "fitz",
    "keyring", "keyring.backends", "keyring.backends.Windows",
    "win32api", "win32security", "win32event", "win32job", "win32process",
    "win32gui", "win32file", "win32con", "ntsecuritycon", "psutil",
    "pywinauto", "pyautogui",
]

excludes = [
    "tests", "pytest", "numpy", "pandas", "matplotlib", "scipy",
    "openpyxl", "PIL",
]

a = Analysis(
    ["main_app.py"],
    pathex=[],
    binaries=[],
    datas=[],                 # 번들에 데이터/설정/시크릿/fixture 미포함
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
    [],
    exclude_binaries=True,
    name="Y_TSBankAuto",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                # UPX 금지
    console=False,            # windowed. selftest=종료코드, worker=결과파일 IPC
    disable_windowed_traceback=True,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,                # UPX 금지
    upx_exclude=[],
    name="Y_TSBankAuto",
)
