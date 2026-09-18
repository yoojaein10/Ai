# -*- coding: utf-8 -*-
"""apworksdw APW_MasterEx에서 감정서번호(DocID)로 대표 소재지를 조회한다.

- 읽기전용 SELECT만 수행, 파라미터는 전부 ? 바인딩.
- 접속정보는 settings.ini [database] (비밀번호는 로그에 출력하지 않는다).
"""
import configparser
import sys
from pathlib import Path

import pyodbc

# PyInstaller exe에서는 exe 옆의 settings.ini를 읽는다
_BASE_DIR = (Path(sys.executable).parent if getattr(sys, "frozen", False)
             else Path(__file__).parent)
SETTINGS_CANDIDATES = [_BASE_DIR / "settings.ini"]


def load_db_config():
    for p in SETTINGS_CANDIDATES:
        if p.exists():
            cfg = configparser.ConfigParser()
            cfg.read(p, encoding="utf-8")
            if "database" in cfg:
                return dict(cfg["database"])
    raise FileNotFoundError("settings.ini [database] 설정을 찾을 수 없음")


def _conn_str(db):
    return (f"DRIVER={{{db.get('driver', 'ODBC Driver 17 for SQL Server')}}};"
            f"SERVER={db['server']},{db.get('port', '1433')};"
            f"DATABASE={db.get('database', 'apworksdw')};"
            f"UID={db['username']};PWD={db['password']};"
            f"TrustServerCertificate=yes;")


def fetch_master(docid):
    """감정서번호 -> 대표 소재지 dict 또는 None.

    반환: {umd_code(법정동10), san('1'|'2'), jibun('148-21'), addr, building, floor, ho}
    """
    db = load_db_config()
    conn = pyodbc.connect(_conn_str(db), timeout=10)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT REG, EUB, SAN, ADDR, BUN1, BUN2, Building, Floor, Ho "
            "FROM dbo.APW_MasterEx WHERE DocID = ?", (str(docid).strip(),))
        row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        return None
    reg, eub, san, addr, bun1, bun2, building, floor, ho = \
        (str(v).strip() if v is not None else "" for v in row)
    if not (reg and eub and bun1):
        return None
    bon = str(int(bun1)) if bun1.isdigit() else bun1
    bu = str(int(bun2)) if bun2.isdigit() else ""
    jibun = ("산" if san == "2" else "") + bon + (f"-{bu}" if bu and bu != "0" else "")
    return {
        "umd_code": (reg + eub)[:10],
        "san": san or "1",
        "jibun": jibun,
        "addr": addr,
        "building": building,
        "floor": floor,
        "ho": ho,
    }
