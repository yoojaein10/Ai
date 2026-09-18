"""db_writer.py — YJI_BankRequest 테이블 UPSERT 모듈
dbo.USP_YJI_BankRequest_Upsert SP 호출 방식
Docid 기준으로 존재하면 UPDATE, 없으면 INSERT
"""
import pyodbc


# ── 컬럼 최대 길이 (바이트 기준, Korean_Wansung_CI_AS 콜레이션) ───────────────
_MAX_BYTES = {
    'Docid':       30,
    'CustDocid':   50,
    'CustNm':      30,
    'CustNm_Sub':  30,
    'Purpose_Nm':  30,
    'Category_Nm': 30,
    'Reg':          4,
    'Eub':          4,
    'Bun1':         5,
    'Bun2':         5,
    'Addr':        350,
    'CustEmp':     30,
    'CustPhone':   30,
    'Debtor':      30,
    'Bigo':       1000,
}

_COLUMNS = list(_MAX_BYTES.keys())

_SP_NAME = 'dbo.USP_YJI_BankRequest_Upsert'


def _byte_trim(s: str, max_bytes: int) -> str:
    """CP949 인코딩 기준으로 max_bytes 이내로 자름 (Korean_Wansung 콜레이션 대응)"""
    encoded = s.encode('cp949', errors='ignore')
    if len(encoded) <= max_bytes:
        return s
    return encoded[:max_bytes].decode('cp949', errors='ignore')


def _prepare(data: dict) -> dict:
    """각 컬럼 값을 DB 최대 길이(바이트 기준)에 맞게 잘라냄"""
    result = {}
    for col in _COLUMNS:
        val = data.get(col) or ''
        result[col] = _byte_trim(str(val), _MAX_BYTES[col]) if val else None
    return result


def get_connection(cfg: dict) -> pyodbc.Connection:
    """config['mssql'] dict → pyodbc 연결 반환"""
    conn_str = (
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={cfg['server']};DATABASE={cfg['database']};"
        f"UID={cfg['username']};PWD={cfg['password']}"
    )
    return pyodbc.connect(conn_str)


def upsert(cursor: pyodbc.Cursor, data: dict) -> str:
    """SP 호출로 UPSERT. 반환값: 'inserted' | 'updated' | 'skipped'"""
    row = _prepare(data)

    cursor.execute(
        f"{{CALL {_SP_NAME} (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)}}",
        [
            row['Docid'],
            row['CustDocid'],
            row['CustNm'],
            row['CustNm_Sub'],
            row['Purpose_Nm'],
            row['Category_Nm'],
            row['Reg'],
            row['Eub'],
            row['Bun1'],
            row['Bun2'],
            row['Addr'],
            row['CustEmp'],
            row['CustPhone'],
            row['Debtor'],
            row['Bigo'],
        ]
    )
    r = cursor.fetchone()
    return r[0] if r else 'skipped'


def upsert_from_pdf(cfg: dict, pdf_path: str) -> str:
    """PDF 파싱 → SP UPSERT 원스텝 헬퍼. 반환값: 'inserted'|'updated'|'skipped'"""
    from bank_parser import parse_pdf
    data = parse_pdf(pdf_path)
    conn = get_connection(cfg)
    try:
        cursor = conn.cursor()
        result = upsert(cursor, data)
        conn.commit()
        return result
    finally:
        conn.close()
