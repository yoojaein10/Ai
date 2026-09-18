# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = ['win32com.client', 'win32com.server', 'pythoncom', 'pywintypes', 'PIL']

# PyMuPDF
tmp_ret = collect_all('pymupdf')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# wkhtmltopdf 내장
binaries += [(r'C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe', '.')]


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'torch', 'torchvision', 'torchaudio',
        'tensorflow', 'keras',
        'scipy', 'sklearn', 'skimage',
        'pandas', 'numpy',
        'matplotlib', 'seaborn',
        'cv2',
        'openpyxl', 'xlrd', 'xlwt',
        'sqlalchemy', 'alembic',
        'cryptography', 'OpenSSL',
        'jinja2', 'markupsafe',
        'IPython', 'ipykernel', 'notebook',
        'boto3', 'botocore',
        'fsspec', 'aiohttp',
        'pyarrow', 'dask', 'numba',
        'sympy', 'statsmodels',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='DocMerger',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[
        'chrome-headless-shell.exe',
        'node.exe',
        'wkhtmltopdf.exe',
    ],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
