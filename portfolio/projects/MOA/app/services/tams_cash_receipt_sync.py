"""TAMS TAX_CASH.DB(Paradox) → 현금영수증 캐시 증분 동기화."""

import shutil
import tempfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.tams_tax_sync import _install_lenient_decode

DEFAULT_SOURCE = r"\\caps\TAMS\Data\TAX_CASH.DB"

# 주민(휴대)번호(SOCIAL_NO), 전화번호(TEL_NO), 사용자ID(USER_ID)는
# 화면 표시에 필요하지 않은 개인정보이므로 캐시에 저장하지 않는다.
_MAPPING = [
    ("send_date", "G_DATE", None),
    ("seq_no", "SEQ_NO", None),
    ("approval_no", "AUTH_NO", 20),
    ("user_type", "USER_TYPE", 2),
    ("transaction_type", "TRAN_TYPE", 2),
    ("transaction_date", "TRAN_DATE", None),
    ("transaction_time", "TRAN_TIME", 6),
    ("transaction_seq", "TRAN_SEQ", None),
    ("company_name", "CP_NAME", 100),
    ("business_no", "BUSINESS_NO", 20),
    ("total_amount", "TOTAL_AMT", None),
    ("supply_amount", "NET_AMT", None),
    ("vat_amount", "VAT_AMT", None),
    ("service_fee", "SERVICE_FREE", None),
    ("goods_name", "GOODS_NAME", 100),
    ("error_message", "ERR_MSG", 100),
    ("nts_status", "NTS_STATUS", 2),
    ("nts_response_at", "C_RES_DATE", 14),
    ("nts_error_message", "C_ERR_MSG", 100),
    ("appraisal_no", "GAM_NO", 30),
    ("original_approval_no", "ORG_AUTH_NO", 20),
    ("original_transaction_date", "ORG_TRAN_DATE", None),
    ("issue_type", "ISSU_TYPE", 2),
    ("gubun", "GUBUN", 2),
    ("report_yn", "SM_YN", 1),
]


def _clip(value: Any, limit: "int | None") -> Any:
    if value is None or limit is None:
        return value
    trimmed = str(value).strip()
    return trimmed[:limit] if trimmed else None


def read_source_rows(
    source_path: str = DEFAULT_SOURCE,
    progress: Callable[[str], None] = print,
) -> "list[tuple]":
    """운영 Paradox 파일을 임시 복사한 뒤 캐시 컬럼 순서로 읽는다."""
    from pypxlib import Table

    _install_lenient_decode()
    temp_path = Path(tempfile.gettempdir()) / "a10_tams_cash_receipt_sync.db"
    shutil.copyfile(source_path, temp_path)
    progress(f"원본 복사 완료: {temp_path}")
    table = Table(
        str(temp_path),
        encoding="cp949",
        px_encoding="cp949",
        px_decode_errors="replace",
    )
    try:
        loaded_at = datetime.now()
        return [
            tuple(_clip(getattr(record, field), limit) for _, field, limit in _MAPPING)
            + (loaded_at,)
            for record in table
        ]
    finally:
        table.close()
        temp_path.unlink(missing_ok=True)


def sync_tams_cash_receipts(
    db: Session,
    source_path: str = DEFAULT_SOURCE,
    progress: Callable[[str], None] = print,
) -> "dict[str, int]":
    rows = read_source_rows(source_path, progress)
    progress(f"원본 읽기 완료: {len(rows):,}건")
    if len(rows) < 1_000:
        raise RuntimeError(
            f"원본 행이 비정상적으로 적습니다({len(rows):,}건) — 동기화 중단"
        )

    columns = [name for name, _, _ in _MAPPING]
    stored_columns = columns + ["created_at"]
    insert_sql = (
        f"INSERT INTO dbo.a10_tams_cash_receipt_cache ({', '.join(stored_columns)}) "
        f"VALUES ({', '.join('?' for _ in stored_columns)})"
    )
    connection = db.connection().connection
    cursor = connection.cursor()
    cursor.fast_executemany = True

    current_rows = db.execute(
        text(
            f"SELECT {', '.join(columns)} "
            "FROM dbo.a10_tams_cash_receipt_cache"
        )
    ).all()
    send_date_index = columns.index("send_date")
    seq_no_index = columns.index("seq_no")

    def key(row: tuple) -> tuple:
        return row[send_date_index], row[seq_no_index]

    def normalized(value: Any) -> Any:
        if isinstance(value, Decimal):
            return value.quantize(Decimal("0.0001"))
        if isinstance(value, float):
            return Decimal(str(value)).quantize(Decimal("0.0001"))
        return value

    current = {key(tuple(row)): tuple(row) for row in current_rows}
    source = {key(row): row for row in rows}
    inserts = [row for source_key, row in source.items() if source_key not in current]
    updates = [
        row
        for source_key, row in source.items()
        if source_key in current
        and any(
            normalized(source_value) != normalized(current_value)
            for source_value, current_value in zip(row[:-1], current[source_key])
        )
    ]

    key_columns = {"send_date", "seq_no"}
    update_columns = [name for name in columns if name not in key_columns]
    update_sql = (
        "UPDATE dbo.a10_tams_cash_receipt_cache SET "
        + ", ".join(f"{name} = ?" for name in update_columns)
        + ", created_at = ? WHERE send_date = ? AND seq_no = ?"
    )
    update_indexes = [columns.index(name) for name in update_columns]
    update_values = [
        tuple(row[index] for index in update_indexes)
        + (row[-1], row[send_date_index], row[seq_no_index])
        for row in updates
    ]

    try:
        if update_values:
            cursor.executemany(update_sql, update_values)
            progress(f"변경 {len(update_values):,}건 UPDATE")
        if inserts:
            cursor.executemany(insert_sql, inserts)
            progress(f"신규 {len(inserts):,}건 INSERT")
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {
        "fetched": len(rows),
        "inserted": len(inserts),
        "updated": len(updates),
        "unchanged": len(rows) - len(inserts) - len(updates),
        "cache_only": len(current.keys() - source.keys()),
    }
