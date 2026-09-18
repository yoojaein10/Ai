"""발급 팝업 계정과목 기록 — 허용 코드 검증(기본 감정수수료)."""

import pytest
from pydantic import ValidationError

from app.routers.taxinvoice import IssueRequest


def _base(**over):
    kwargs = dict(
        doc_id="01-2607-3-2317",
        write_date="20260813",
        supply_cost=495000,
        tax=49500,
        receiver={"corp_num": 'REDACTED_CONFIGURE_LOCALLY7890'},
    )
    kwargs.update(over)
    return kwargs


def test_계정과목_기본값은_감정수수료():
    assert IssueRequest(**_base()).account_code == "4010001"


def test_실존_계정_5종만_허용():
    for code in ("4010001", "4010002", "4010003", "4010004", "4010005"):
        assert IssueRequest(**_base(account_code=code)).account_code == code
    with pytest.raises(ValidationError):
        IssueRequest(**_base(account_code="8110000"))
