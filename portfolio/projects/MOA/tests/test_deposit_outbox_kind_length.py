"""전표 종류 문자열이 a10_deposit_outbox.voucher_kind 열 길이에 들어가는지 — 2026-08-25 MISC_INCOME(11자) 잘림으로 스캔이 섰다."""

import re
from pathlib import Path

from app.models.deposit_outbox import DepositOutbox

SOURCE = (Path(__file__).resolve().parents[1] / "app" / "services" / "deposit_vouchers.py").read_text(encoding="utf-8")


def test_voucher_kind_literals_fit_the_column():
    length = DepositOutbox.__table__.c.voucher_kind.type.length
    kinds = set(re.findall(r'voucher_kind\s*(?:==|=|!=)\s*"([A-Z_]+)"', SOURCE)) | set(re.findall(r'return "([A-Z_]+)", None', SOURCE))
    assert "MISC_INCOME" in kinds
    too_long = sorted(k for k in kinds if len(k) > length)
    assert too_long == [], f"voucher_kind VARCHAR({length}) 보다 긴 종류: {too_long}"
