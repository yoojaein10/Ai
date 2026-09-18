"""감정서 LIST — 거래처명 위치와 '감정서별 비용 지급내역' (2026-08-21 사용자 요청).

지급 내역은 이미 받아 온 전표(`/api/appraisals/{doc}/vouchers`)에서 골라 낸다.
새로 조회하지 않으므로 화면이 느려지지 않는다.

비용 계정은 8 계열이다 (2026년 전표 전수 확인):
  8310000 지급수수료 161건 · 8600000 협회비 33건 · 8170000 세금과공과금 16건 ·
  8210000 보험료 13건. 카드·이체 수수료가 입금에서 떼인 것과 협회 심사비가 대부분이다.
"""

import re
from pathlib import Path

UI = Path(__file__).resolve().parent.parent / "desktop" / "ui"
HTML = (UI / "dashboard.html").read_text(encoding="utf-8")
JS = (UI / "dashboard.js").read_text(encoding="utf-8")


def _paid_fn() -> str:
    """renderPaid 본문만 — 파일 끝까지 자르면 다른 함수가 딸려 온다."""
    start = JS.index("function renderPaid(")
    return JS[start:JS.index("\n}", start)]


def _list_table() -> str:
    return HTML[HTML.index("<colgroup>"):HTML.index("</thead>")]


def test_거래처명이_감정서번호_바로_뒤다():
    heads = re.findall(r"<th[^>]*>([^<]+)</th>", _list_table())

    assert heads[:2] == ["감정서번호", "거래처명"], heads[:4]


def test_열_수가_맞는다():
    """머리글·너비·행 셋 중 하나만 어긋나도 표가 통째로 밀린다."""
    block = _list_table()
    cols = len(re.findall(r"<col\b", block))
    heads = len(re.findall(r"<th\b", block))

    assert cols == heads == 17

    start = JS.index("$('appraisalRows').innerHTML=data.items.map")
    row = JS[start:JS.index("document.querySelectorAll('#appraisalRows tr')", start)]
    assert len(re.findall(r"<td[^>]*>", row)) == 17


def test_채무자가_거래처명_바로_뒤다():
    """2026-08-26 사용자 요청 — APW_MASTEREX.Debtor(채무자)를 거래처명 다음에 보인다."""
    heads = re.findall(r"<th[^>]*>([^<]+)</th>", _list_table())
    assert heads[:3] == ["감정서번호", "거래처명", "채무자"], heads[:4]
    assert 'data-sort="debtor"' in _list_table(), "머리글 정렬도 돼야 한다"

    start = JS.index("$('appraisalRows').innerHTML=data.items.map")
    row = JS[start:JS.index("document.querySelectorAll('#appraisalRows tr')", start)]
    assert row.index("row.customer_name") < row.index("row.debtor") < row.index("row.cust_doc_id")
    assert "debtor:'채무자'" in JS, "정렬 라벨이 있어야 요약 문구에 이름이 뜬다"

    from pathlib import Path

    service = (Path(__file__).resolve().parent.parent / "app" / "services" / "appraisals.py").read_text(encoding="utf-8")
    assert "a.Debtor AS debtor," in service
    assert '"debtor": "Debtor",' in service


def test_계산서_발행_열이_입금현황과_같은_규칙으로_맨_오른쪽에_있다():
    """2026-08-27 사용자 요청 — 세금계산서/현금영수증 발행 여부를 감정서 LIST 에도 (입금현황과 같은 칸)."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    html = (root / "desktop" / "ui" / "dashboard.html").read_text(encoding="utf-8")
    heads = re.findall(r"<th[^>]*>([^<]+)</th>", _list_table())
    assert heads[-1] == "세금계산서/현금영수증", heads[-3:]
    assert "proofIssuedCell(row)" in JS and "row.tax_issued_slips" in JS
    assert ".tax-issued{" in html or ".tax-issued {" in html           # 발행 배지 스타일은 이 화면에도
    service = (root / "app" / "services" / "appraisals.py").read_text(encoding="utf-8")
    assert "attach_proof_issued(self.db, items)" in service
    router = (root / "app" / "routers" / "appraisals.py").read_text(encoding="utf-8")
    assert '("proof_issued", "세금계산서/현금영수증")' in router         # 엑셀도 같은 열
    assert "dashboard.js?v=20260827-2" in html


def test_행도_거래처명을_두_번째로_그린다():
    start = JS.index("$('appraisalRows').innerHTML=data.items.map")
    row = JS[start:JS.index("document.querySelectorAll('#appraisalRows tr')", start)]

    assert row.index("row.customer_name") < row.index("row.cust_doc_id"), (
        "머리글만 옮기고 행을 안 옮기면 값이 어긋난 칸에 들어간다"
    )
    assert row.index("row.doc_id") < row.index("row.customer_name")


def test_지급_내역_자리가_있다():
    assert "감정서별 비용 지급내역" in HTML
    assert 'id="paidList"' in HTML and 'id="paidEmpty"' in HTML
    # 세금계산서 다음에 온다 (사용자 요청 순서)
    assert HTML.index('id="taxList"') < HTML.index('id="paidList"')


def test_비용_계정_차변만_고른다():
    """대변까지 세면 지급이 아닌 것이 섞이고, 8 계열이 아니면 매출·예금이 들어온다."""
    block = _paid_fn()

    assert "PAID_ACCOUNT_PREFIX='8'" in JS
    assert "startsWith(PAID_ACCOUNT_PREFIX)" in block
    assert "==='3'" in block, "차변만"


def test_이_감정서의_줄만_고른다():
    """전표 목록은 감정서가 걸린 전표의 라인을 전부 내려준다. 회계가 여러 건의 지출을
    한 전표에 몰아 넣으므로 계정만 보고 고르면 남의 지출이 딸려 온다.

    실측 01-2605-3-1707: 그 감정서 줄은 가수금 27,500 하나뿐인데 같은 전표에
    여비교통비 20,000 · 광고선전비 80,091 · 소모품비 180,000 이 섞여 있다.
    8 계열 차변 12.7만 줄 중 관리번호가 붙은 것은 354줄뿐이다.
    """
    block = _paid_fn()

    assert "String(line.ctNb||line.maNb||'').trim()===mine" in block, (
        "관리번호로 안 좁히면 남의 지출이 이 감정서 것으로 보인다"
    )
    assert "renderPaid(items,docId);" in JS, "어느 감정서인지 넘겨야 한다"


def test_여비교통비도_관리번호가_붙으면_잡힌다():
    """8120000 은 8 계열이라 접두사 규칙에 이미 들어온다 — 관리번호만 붙으면 된다.

    2026-08-21 기준 여비교통비 5,864줄에 관리번호가 하나도 없다. 재무팀이 앞으로
    붙이기로 해서, 붙는 순간부터 따로 고칠 것 없이 나온다.
    """
    assert "8120000 여비교통비" in JS, "어떤 계정을 뜻하는지 남겨 둔다"
    # 계정 목록을 따로 열거하지 않는다 — 접두사 하나로 새 계정까지 자동으로 든다
    assert "PAID_ACCOUNT_PREFIX='8'" in JS


def test_새로_조회하지_않는다():
    """전표는 이미 받아 왔다 — 또 부르면 화면이 두 배로 느려진다."""
    block = _paid_fn()

    assert "fetch(" not in block
    assert "renderPaid(items,docId);" in JS, "전표를 그린 뒤 같은 자료로 그린다"


def test_합계를_보여_준다():
    block = _paid_fn()

    assert "<tfoot>" in block and "합계" in block


# ── 상세 패널 길이 (2026-08-21) ──────────────────────────────────────────

def test_긴_표는_그_안에서만_굴린다():
    """전표가 223줄인 감정서(01-2604-2-0035)는 패널이 13,025px = 창 13.7장이었다.

    구역마다 높이를 제한해 표 안에서만 굴리도록 했다 — 1,458px (1.5장) 로 줄었다.
    머리글·합계 줄은 굴러도 제자리에 붙여 둔다(sticky). 안 붙이면 아래로 굴렸을 때
    어느 칸이 무엇인지 알 수 없다.
    """
    css = (UI / "dashboard.css").read_text(encoding="utf-8")

    assert ".detail-panel .voucher-grid-wrap { max-height: 320px; overflow-y: auto;" in css
    assert ".detail-panel .voucher-grid thead th { position: sticky; top: 0;" in css
    assert ".detail-panel .voucher-grid tfoot th { position: sticky; bottom: 0;" in css


def test_세_표가_같은_규칙을_쓴다():
    """전표·계산서·지급이 모두 .voucher-grid-wrap 이라 한 곳만 고치면 된다."""
    assert JS.count('class="voucher-grid-wrap"') == 3
