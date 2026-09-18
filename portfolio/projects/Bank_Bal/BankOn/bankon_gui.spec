# -*- mode: python ; coding: utf-8 -*-
"""BankOn 단일 exe PyInstaller spec — 빌드: python -m PyInstaller --noconfirm bankon_gui.spec  → dist/BankOn.exe
2026-08-31 부터 러너(tools/*.py)·src/bankon·recon/*.md·gamexport.exe 를 **전부 번들**한다. 배포 = BankOn.exe + .env + gui_settings.ini.
큐 워커는 러너를 `BankOn.exe --runner <모듈> …` 로 자기 재호출한다(gui_bankon._run_bundled_runner). Python 설치 불필요.
관리자 매니페스트(uac_admin) 필수 — Bank24 가 elevated."""
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None
ROOT = r'D:\AI\Claude\Bank_Bal\BankOn'
a = Analysis(
    ['gui_bankon.py'],
    pathex=[ROOT, ROOT + r'\src', ROOT + r'\tools'],
    binaries=[],
    datas=[(ROOT + r'\recon\*.md', 'recon'),
           (ROOT + r'\delphi\delphi\gamexport.exe', r'delphi\delphi')],
    hiddenimports=['pyodbc', 'olefile', 'dotenv',
                   *collect_submodules('bankon'),
                   'run_queue_worker', 'run_shinhan_full', 'run_kb_full', 'run_ibk_full', 'run_nh_full', 'human_guard',
                   'run_ssb_full', 'run_hnb_full', 'run_wrb_full', 'run_mgb_full', 'bank_runner', 'autofill_slot',
                   'autofill_ssb', 'autofill_hnb', 'autofill_wrb', 'autofill_mgb',
                   'verify_fill_ssb', 'verify_fill_hnb', 'verify_fill_wrb', 'verify_fill_mgb',
                   'autofill_kb', 'autofill_shinhan', 'autofill_ibk', 'autofill_survey', 'autofill_nh', 'verify_fill_nh',
                   'verify_form', 'verify_fill', 'verify_fill_kb', 'verify_live',
                   'pywinauto', 'pywinauto.application', 'pywinauto.controls', 'pywinauto.controls.common_controls',
                   'pywinauto.controls.hwnd_controls', 'pywinauto.controls.uia_controls', 'pywinauto.controls.win32_controls',
                   'pywinauto.keyboard', 'pywinauto.findwindows', 'comtypes', 'comtypes.stream'],
    hookspath=[], runtime_hooks=[], cipher=block_cipher, noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
          name='BankOn', debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, uac_admin=True, icon=None)
