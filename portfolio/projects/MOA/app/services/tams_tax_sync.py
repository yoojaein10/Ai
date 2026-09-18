"""TAMS 부가세.DB(Paradox) → a10_tams_tax_cache 동기화.

TAMS는 파일 DB(Paradox, cp949)로 \\\\caps\\TAMS\\Data에 있다 (2026-07-22 사용자 확인).
pypxlib가 한글 경로를 못 열고 운영 파일을 잠그면 안 되므로, 임시 폴더에 ASCII 이름으로
복사한 뒤 읽는다. 컬럼 매핑은 기존 1회 적재분(2026-07-21)과 행 단위 대조로 확정:

    branch_code←매입매출  gubun←발행취소('발행'/'취소')  status_cd←영수청구('청구'/'영수')
    electronic_yn←부가세코드(0~9)  approval_no←전표번호  bal_date←계산서일자
"""

import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import text
from sqlalchemy.orm import Session

DEFAULT_SOURCE = r"\\caps\TAMS\Data\부가세.DB"

# (캐시 컬럼, 원본 필드, 최대 길이 — None이면 비문자)
_MAPPING = [
    ("branch_code", "매입매출", 4),
    ("bill_year", "년도", 4),
    ("seq_no", "일련번호", 6),
    ("bal_date", "계산서일자", None),
    ("gubun", "발행취소", 4),
    ("appraisal_no", "감정서번호", 15),
    ("tr_cd", "거래처코드", 10),
    ("reg_nb", "사업자등록번호", 14),
    ("company_nm", "상호", 50),
    ("ceo_nm", "성명", 20),
    ("addr", "사업장주소", 150),
    ("biz_type", "업태", 30),
    ("biz_item", "종목", 30),
    ("sup_am", "공급가합계", None),
    ("vat_am", "세액합계", None),
    ("total_am", "합계금액", None),
    ("item_cd_1", "품목코드1", 10),
    ("item_nm_1", "품목1", 30),
    ("sup_1", "공급가액1", None),
    ("vat_1", "세액1", None),
    ("item_cd_2", "품목코드2", 10),
    ("item_nm_2", "품목2", 30),
    ("sup_2", "공급가액2", None),
    ("vat_2", "세액2", None),
    ("status_cd", "영수청구", 4),
    ("approval_no", "전표번호", 12),
    ("electronic_yn", "부가세코드", 1),
]


def _clip(value: Any, limit: "int | None") -> Any:
    if value is None:
        return None
    if limit is None:
        return value
    trimmed = str(value).strip()
    return trimmed[:limit] if trimmed else None


def _install_lenient_decode() -> None:
    """레거시 행에 깨진 cp949 바이트가 있어 (2001년대 데이터) 대체 문자로 완화한다."""
    import inspect

    import pypxlib

    for _, cls in inspect.getmembers(pypxlib, inspect.isclass):
        method = cls.__dict__.get("_deserialize")
        if method is None or getattr(method, "_a10_lenient", False):
            continue

        def _make(original):
            def wrapper(self, value):
                try:
                    return original(self, value)
                except UnicodeDecodeError:
                    return value.str.val.data.decode(self.encoding, "replace")

            wrapper._a10_lenient = True
            return wrapper

        cls._deserialize = _make(method)


def read_source_rows(
    source_path: str = DEFAULT_SOURCE,
    progress: Callable[[str], None] = print,
) -> "list[tuple]":
    """Paradox 파일을 임시 복사 후 캐시 컬럼 순서의 튜플로 읽는다."""
    from pypxlib import Table  # 서버 전용 의존성 — 지연 임포트

    _install_lenient_decode()

    temp_path = Path(tempfile.gettempdir()) / "a10_tams_vat_sync.db"
    shutil.copyfile(source_path, temp_path)
    progress(f"원본 복사 완료: {temp_path}")
    table = Table(str(temp_path), encoding="cp949", px_encoding="cp949")
    try:
        rows = []
        for record in table:
            values = []
            for _, field, limit in _MAPPING:
                values.append(_clip(getattr(record, field), limit))
            values.append(datetime.now())  # created_at
            rows.append(tuple(values))
        return rows
    finally:
        table.close()
        temp_path.unlink(missing_ok=True)


def sync_tams_tax(
    db: Session,
    source_path: str = DEFAULT_SOURCE,
    progress: Callable[[str], None] = print,
) -> "dict[str, int]":
    rows = read_source_rows(source_path, progress)
    progress(f"원본 읽기 완료: {len(rows):,}건")
    if len(rows) < 100_000:
        # 원본이 갑자기 비거나 잘렸을 때 캐시를 날리지 않기 위한 하한선
        raise RuntimeError(f"원본 행이 비정상적으로 적습니다({len(rows):,}건) — 동기화 중단")

    columns = [name for name, _, _ in _MAPPING] + ["created_at"]
    insert_sql = (
        f"INSERT INTO dbo.a10_tams_tax_cache ({', '.join(columns)}) "
        f"VALUES ({', '.join('?' for _ in columns)})"
    )
    connection = db.connection().connection  # pyodbc
    cursor = connection.cursor()
    cursor.fast_executemany = True
    db.execute(text("DELETE FROM dbo.a10_tams_tax_cache"))
    chunk = 20_000
    for start in range(0, len(rows), chunk):
        cursor.executemany(insert_sql, rows[start:start + chunk])
        progress(f"적재 {min(start + chunk, len(rows)):,}/{len(rows):,}건")
    db.commit()
    return {"fetched": len(rows), "stored": len(rows)}
