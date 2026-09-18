"""TAMS 현금영수증(TAX_CASH.DB) 표시 규칙.

세금계산서 표에 현금영수증을 함께 얹는다. 원본이 취소를 두 가지로 적고
(TRAN_TYPE=1, AUTH_NO='null'), MOA에서 직접 발급한 건은 승인번호가 같아
두 번 나올 수 있어 판정 규칙을 고정한다.
"""

import re
from pathlib import Path

from app.services.appraisals import _cash_receipt_status

ROOT = Path(__file__).resolve().parent.parent
SCREENS = ("receivables.js", "dashboard.js")


def test_국세청_신고된_건은_발행이다():
    assert _cash_receipt_status("0", "Y", "Z56541610") == ("발행", "Z56541610")


def test_신고_전이면_미신고다():
    """report_yn 이 아직 Y가 아니면 발행으로 보면 안 된다."""
    assert _cash_receipt_status("0", "N", "Z56541610") == ("미신고", "Z56541610")
    assert _cash_receipt_status("0", None, "Z56541610") == ("미신고", "Z56541610")


def test_거래유형_1은_취소다():
    status, approval = _cash_receipt_status("1", "Y", "Z56541610")
    assert status == "취소"
    # 취소 건이라도 승인번호는 남는다 — 어느 발행을 취소한 건지 봐야 한다.
    assert approval == "Z56541610"


def test_승인번호가_문자열_null_이면_취소다():
    """원본이 취소를 AUTH_NO='null' 로도 적는다. 대소문자가 섞여 들어와도 같다 —
    'NULL'을 그대로 두면 취소 건이 승인번호를 가진 정상 발행처럼 보인다."""
    for raw in ("null", "NULL", "Null", " null "):
        assert _cash_receipt_status("0", "Y", raw) == ("취소", None), raw


def test_승인번호가_비면_None_이다():
    """빈 문자열을 남기면 승인번호 없는 건끼리 서로 중복으로 걸러진다."""
    assert _cash_receipt_status("0", "Y", None)[1] is None
    assert _cash_receipt_status("0", "Y", "  ")[1] is None
    # 다만 비었다고 취소는 아니다 (취소 표시는 TRAN_TYPE 과 'null' 뿐이다).
    assert _cash_receipt_status("0", "Y", None)[0] == "발행"


def test_MOA_직접발급분과_중복을_거른다():
    """같은 승인번호가 MOA 발급분에도 있으면 한 번만 보여야 한다."""
    service = (ROOT / "app" / "services" / "appraisals.py").read_text(encoding="utf-8")
    assert "issued_approvals" in service
    assert "if approval_no and approval_no in issued_approvals:" in service


def test_계산서표_헤더와_colgroup과_셀_수가_같다():
    """열을 늘릴 때 셋 중 하나만 고치면 내용이 통째로 밀린다."""
    for name in SCREENS:
        script = (ROOT / "desktop" / "ui" / name).read_text(encoding="utf-8")
        start = script.index("$('taxList').innerHTML")
        block = script[start : script.index("</tbody>", start)]
        heads = re.findall(r"<th[ >]", block)  # <thead> 가 걸리지 않게 구분자까지 본다
        cols = re.findall(r"<col ", block)
        row = block[block.index("taxes.map") :]
        cells = re.findall(r"<td[ >]", row)
        assert len(heads) == len(cols) == len(cells), (
            f"{name}: 헤더 {len(heads)} / colgroup {len(cols)} / 셀 {len(cells)}"
        )


def test_승인번호_열이_발행유형_오른쪽에_있다():
    """예전에는 발행상태 칸에 'MOA·현금영수증 승인 12345' 처럼 섞어 적었다.
    유형과 승인번호를 갈랐으면 승인번호도 화면에 나와야 한다 — API 만 내려주고
    표에서 빠뜨리면 정보가 사라진다."""
    for name in SCREENS:
        script = (ROOT / "desktop" / "ui" / name).read_text(encoding="utf-8")
        start = script.index("$('taxList').innerHTML")
        block = script[start : script.index("</tbody>", start)]
        heads = re.findall(r"<th[^>]*>([^<]*)</th>", block)
        assert heads.index("승인번호") == heads.index("발행유형") + 1, heads
        assert "tax.approval_no" in block, f"{name}: 승인번호 값을 안 그린다"


def test_두_화면의_계산서표가_같다():
    """입금현황과 감정서 LIST 가 같은 표를 쓴다 — 한쪽만 고치면 어긋난다."""
    blocks = []
    for name in SCREENS:
        script = (ROOT / "desktop" / "ui" / name).read_text(encoding="utf-8")
        start = script.index("$('taxList').innerHTML")
        blocks.append(script[start : script.index("</tbody>", start)])
    assert blocks[0] == blocks[1]


def test_계산서표를_쓰는_화면은_캐시버스터가_있다():
    """JS 를 고쳐도 버전이 그대로면 브라우저가 옛 파일을 계속 쓴다."""
    for page, script in (("dashboard.html", "dashboard.js"), ("receivables.html", "receivables.js")):
        html = (ROOT / "desktop" / "ui" / page).read_text(encoding="utf-8")
        assert f"/ui/{script}?v=" in html, f"{page} 의 {script} 에 캐시버스터가 없다"
