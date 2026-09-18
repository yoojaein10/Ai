"""거래처 후보 목록의 중복 제거.

api16S11 이 같은 거래처를 여러 줄로 내려준다 — '신한은행 영동금융센터'는
거래처코드·상호·사업자번호가 똑같은 4줄이었다(2026-08-07, 01-2608-3-2454).
후보 목록에 같은 거래처가 여러 번 뜨면 담당자가 무엇이 다른지 찾느라 시간을 쓴다.
"""

from app.services.partners import _dedupe_by_code


def _p(code, name="상호", **over):
    return {"partner_code": code, "name": name, **over}


def test_같은_거래처코드는_한_줄로_접힌다():
    items = _dedupe_by_code([_p("0000023480") for _ in range(4)])
    assert len(items) == 1


def test_먼저_온_행을_남긴다():
    """뒤 행으로 덮으면 아마란스가 주는 정렬(주 사업장 우선)이 뒤집힌다."""
    items = _dedupe_by_code([_p("1", name="본점"), _p("1", name="지점")])
    assert [item["name"] for item in items] == ["본점"]


def test_다른_거래처는_그대로_남는다():
    items = _dedupe_by_code([_p("1"), _p("2"), _p("1"), _p("3")])
    assert [item["partner_code"] for item in items] == ["1", "2", "3"]


def test_코드가_없으면_접지_않는다():
    """코드가 비면 같은 거래처라고 볼 근거가 없다 — 지우면 후보가 사라진다."""
    items = _dedupe_by_code([_p(None, name="A"), _p("", name="B"), _p(None, name="C")])
    assert len(items) == 3


def test_코드_앞뒤_공백은_같은_것으로_본다():
    items = _dedupe_by_code([_p("0000023480"), _p(" 0000023480 ")])
    assert len(items) == 1


def test_목록_건수도_접은_뒤_기준이다():
    """count 가 접기 전 숫자면 화면이 '4건'이라 적고 1줄만 보여준다."""
    import inspect

    from app.services.partners import PartnerService

    source = inspect.getsource(PartnerService.list)
    assert "_dedupe_by_code" in source
    assert "len(items)" in source, "count 는 접은 뒤 목록으로 세야 한다"
