"""입금현황 선수금 두 칸.

  선수금(기) = 받은 금액 (전표 2590000 대변 합계)
  선수금     = 남은 잔액. 매출에 전액 상계됐으면 0

예전에는 두 칸 다 기간별 순액(대변-차변)을 찍었다. 상계한 날 차변이 잡히면
음수가 떠서 재무팀이 '선수금을 두 번 인식한다'고 읽었다(2026-08-02 문의).
받은 금액과 남은 잔액으로 나누면 둘 다 음수가 될 수 없고, 전액 상계된 건도
선수금(기)에 금액이 남아 '선수금이 아예 없던 건'과 구분된다.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SERVICE = ROOT / "app" / "services" / "receivables.py"
SCRIPT = ROOT / "desktop" / "ui" / "receivables.js"


def test_받은_선수금을_전표에서_따로_읽는다():
    """순액만 보면 전액 상계와 '이력 없음'이 똑같이 0이다."""
    service = SERVICE.read_text(encoding="utf-8")
    assert "def _advance_history(" in service
    assert "account_code = '2590000'" in service
    # 엑셀은 전 건을 한 번에 넘기므로 SQL Server 파라미터 2,100개 한계에 걸린다.
    assert "_DOC_CHUNK" in service


def test_선수금_잔액은_음수가_되지_않는다():
    """선수금 대변(받음)이 감정서번호 없이 잡히고 차변만 번호를 달고 오는 건이 있다.

    선수금은 감정서번호가 나오기 전에 받는 돈이라 그렇다. 실측 2건:
      01-2605-A-0079  차변 1,100,000  적요 '선수금 이첩>01-2605-A-0079'
      01-2602-7-0019  차변   500,000  적요 '선수금'
    그대로 두면 받음 0 · 상계 X 라 잔액이 -X 로 뜬다.
    """
    service = SERVICE.read_text(encoding="utf-8")
    assert "received = max(received, used)" in service, "상계액만큼은 받았던 돈이다"
    assert 'item["advance_amount"] = max(' in service, "잔액은 0 밑으로 안 내려간다"
    # 합계 바도 같은 기준이어야 페이지 합과 총계가 어긋나지 않는다.
    assert "CASE WHEN b.advance_amount > 0 THEN b.advance_amount ELSE 0 END" in service


def test_받은_선수금은_선수금_기_칸에_들어간다():
    """열을 옮기다 받은 금액과 잔액이 서로 바뀐 적이 있어 셀 대응을 고정한다."""
    script = SCRIPT.read_text(encoding="utf-8")
    row = next(
        line for line in script.splitlines()
        if "$('rows').innerHTML=data.items.map" in line
    )
    assert r'invoice_total||0)}</td><td class="number">${advanceReceivedCell(row)}' in row
    assert r'daily_received_amount||0)}</td><td class="number">${advanceCell(row)}' in row


def test_선수금_열_이름과_순서():
    """매출총액 → 선수금(기) → 입금액(기) → 입금액 → 선수금 → 미수금."""
    import re

    script = SCRIPT.read_text(encoding="utf-8")
    headers = re.findall(r"<th[^>]*>([^<]+)</th>", script)
    spots = [i for i, h in enumerate(headers) if h == "선수금(기)"]
    assert len(spots) == 2, f"선수금(기)가 {len(spots)}군데 (화면·인쇄 2군데여야 한다)"
    for index in spots:
        assert headers[index - 1 : index + 4] == [
            "매출총액", "선수금(기)", "입금액(기)", "입금액", "선수금",
        ], headers[index - 1 : index + 4]


def test_엑셀_열_순서가_화면과_같다():
    from app.routers.receivables import _RECEIVED_EXPORT_COLUMNS

    excel = [label for _, label in _RECEIVED_EXPORT_COLUMNS]
    index = excel.index("선수금(기)")
    assert excel[index - 1 : index + 5] == [
        "매출총액", "선수금(기)", "입금액(기)", "입금액", "선수금", "미수금",
    ], excel[index - 1 : index + 5]
    # 값이 어느 필드에서 오는지도 고정한다 (받은 금액 ↔ 잔액이 바뀐 적 있다).
    fields = {label: key for key, label in _RECEIVED_EXPORT_COLUMNS}
    assert fields["선수금(기)"] == "advance_received"
    assert fields["선수금"] == "advance_amount"


def test_전표_상세에_상계된_선수금_표시():
    """재무팀이 '두 번 인식한다'고 본 지점이라 받고-쓴 짝을 눈에 보이게 한다.

    판정은 서버(_mark_offset_lines)가 하고 화면은 그 표시만 그린다 —
    세 화면이 같은 규칙을 쓰도록 하려고 화면별 계산을 두지 않는다.
    """
    script = SCRIPT.read_text(encoding="utf-8")
    assert "line.offset" in script
    assert "offset-badge" in script
    css = (ROOT / "desktop" / "ui" / "dashboard.css").read_text(encoding="utf-8")
    assert "tr.offset td" in css
    assert "line-through" in css
    # 규칙이 receivables.css 에서 dashboard.css 로 옮겨 갔는데 이 화면의 링크에는
    # 버전이 없었다. 브라우저가 옛 CSS를 재사용하면 코드가 맞아도 취소선이 안 그려진다.
    page = (ROOT / "desktop" / "ui" / "receivables.html").read_text(encoding="utf-8")
    assert "dashboard.css?v=" in page, "입금현황이 링크한 dashboard.css 에 캐시버스터가 없다"


@pytest.mark.skipif(shutil.which("node") is None, reason="node 미설치 환경")
def test_열_수와_내용이_맞는지_node_검사():
    """헤더·셀 개수만 세면 내용이 서로 밀린 걸 못 잡는다 — 실제로 렌더링해서 본다."""
    checker = Path(__file__).resolve().parent / "check_receivable_columns.js"
    result = subprocess.run(
        ["node", str(checker)], capture_output=True, text=True, encoding="utf-8"
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_화면이_캐시되지_않는다():
    """HTML이 캐시되면 안에 적힌 ?v= 도 옛 값이라 새 JS를 영영 안 받는다."""
    main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    index = main.index("def desktop_receivables(")
    assert "no-cache" in main[index : index + 400]


def test_물건종류가_목적_오른쪽에_있다():
    """재무팀 요청(2026-08-03). 원본은 apw_masterex.LCategory (구분건물·토지건물·토지 등)."""
    import re

    script = SCRIPT.read_text(encoding="utf-8")
    headers = re.findall(r"<th[^>]*>([^<]+)</th>", script)
    spots = [i for i, h in enumerate(headers) if h == "물건종류"]
    assert len(spots) == 2, f"물건종류가 {len(spots)}군데 (화면·인쇄 2군데여야 한다)"
    for index in spots:
        assert headers[index - 1] == "목적", headers[index - 1 : index + 1]

    service = SERVICE.read_text(encoding="utf-8")
    assert "a.LCategory AS category" in service
    assert "LWorkinfo, LCategory," in service, "30건 보강 조회에도 있어야 한다"
    assert '"category": "a.LCategory"' in service, "정렬도 되어야 한다"


def test_물건종류_엑셀은_입금현황에만():
    """미수금현황은 열 구성을 그대로 둔다 (요청 범위가 입금현황이다)."""
    from app.routers.receivables import (
        _OUTSTANDING_EXPORT_COLUMNS,
        _RECEIVED_EXPORT_COLUMNS,
    )

    received = [label for _, label in _RECEIVED_EXPORT_COLUMNS]
    assert received[received.index("물건종류") - 1] == "목적"
    assert "물건종류" not in [label for _, label in _OUTSTANDING_EXPORT_COLUMNS]


def test_진행상태가_입금현황_맨_끝에_있다():
    """원본은 apw_masterex.LStatus (완료처리(발송)·접수완료(처리전) 등).

    인쇄표에도 '진행상태' 열이 있지만 그건 수금 상태(statusOf)라 이름만 같고 값이
    다르다. 그래서 화면 헤더 상수만 잘라서 본다 — 파일 전체에서 <th>를 세면
    인쇄표의 동명 열까지 걸린다.
    """
    import re

    script = SCRIPT.read_text(encoding="utf-8")
    received = re.search(r"const receivedHeaders='(.*?)';", script, re.S)
    assert received, "receivedHeaders 를 찾을 수 없다"
    headers = re.findall(r"<th[^>]*>([^<]+)</th>", received.group(1))
    # 2026-08-07 에 세금계산서 발행여부가, 2026-08-13 에 현금영수증까지 합쳐진
    # '세금계산서/현금영수증' 한 칸이 오른쪽에 붙었다. 진행상태는 여전히
    # 원장 정보의 마지막이고, 증빙 칸만 그 뒤에 온다.
    assert headers[-2:] == ["진행상태", "세금계산서/현금영수증"], headers[-3:]

    service = SERVICE.read_text(encoding="utf-8")
    assert "a.LStatus AS progress_status" in service
    assert "LCategory, LStatus," in service, "30건 보강 조회에도 있어야 한다"
    assert '"progress_status": "a.LStatus"' in service, "정렬도 되어야 한다"


def test_세금계산서_발행여부가_입금현황_맨_끝에_있다():
    """재무팀이 "이 건 계산서 나갔나"를 목록에서 바로 보게 한다 (2026-08-07 요청).

    넣는 값은 '발행' 하나뿐이다 — 아니면 빈칸으로 둔다 (2026-08-07 확정).
    남은 금액(순액)으로 판단하므로 끊었다 전액 취소한 건은 빠진다. 실측(2026년):
    계산서가 달린 감정서 1,780개 중 순액 양수 1,776(99.8%) · 순액 0 이 4건
    (01-2606-2-0074 등, 모두 2장짜리 취소 건)이다."""
    import re

    script = SCRIPT.read_text(encoding="utf-8")
    received = re.search(r"const receivedHeaders='(.*?)';", script, re.S)
    headers = re.findall(r"<th[^>]*>([^<]+)</th>", received.group(1))
    assert headers[-1] == "세금계산서/현금영수증", headers[-2:]
    # 칸 폭도 같이 늘어야 표가 밀리지 않는다
    cols = re.search(r"const receivedColumns='(.*?)';", script, re.S)
    assert cols.group(1).count("<col") == len(headers)

    assert "const proofIssuedCell=" in script, (
        "check_receivable_columns.js 가 const 선언만 자동으로 끌어온다")

    # 발행여부는 파이썬이 페이지 단위로 계산하는 값이라 SQL 정렬이 불가능하다 —
    # data-sort 를 달면 클릭 시 서버가 422 를 내고 조회가 깨진다(2026-08-13 실측).
    assert 'data-sort="tax_issued"' not in script
    assert 'data-sort="cash_issued"' not in script

    service = SERVICE.read_text(encoding="utf-8")
    # 장수를 세는 이유 — 순액 0 인 취소 건을 가려내려면 장수가 있어야 한다
    assert "SUM(m.slips) AS slips" in service
    assert 'item["tax_issued"] = "발행" if tax_amount > 0 else ""' in service
    # 부르는 곳은 탭당 하나뿐이다 (정의 1 + 입금현황 1 + 미수금현황 1 = 3.
    # 부르는 곳이 늘면 목록 조회가 그만큼 느려진다)
    assert service.count("_tax_invoice_totals(") == 3
    assert service.count("tax_totals = _tax_invoice_totals(") == 2


def test_현금영수증_발행여부는_세금계산서와_같은_규칙이다():
    """2026-08-13 요청 — 입금현황에 현금영수증 발행여부 칸.

    원천(a10_tams_cash_receipt_cache)의 함정 두 개를 그대로 물려받는다:
    ① 취소 표기가 둘(transaction_type='1' / approval_no='null')이고 취소행의
      부호가 혼재한다(양수 203·음수 42 실측) — -ABS() 로 접어야 순액이 맞다.
    ② 승인번호 000000000000·0원 자리표 행이 있어 장수는 0원 아닌 발행만 센다.
    회사 매출실적 화면과 같은 규칙이라 두 화면의 현금영수증 숫자가 일치한다.
    """
    service = SERVICE.read_text(encoding="utf-8")
    assert "def _cash_receipt_totals(" in service
    # 입금현황·미수금현황 두 탭이 각각 한 번씩 부른다.
    assert service.count("cash_totals = _cash_receipt_totals(") == 2
    cash = service.split("def _cash_receipt_totals(")[1].split("def ")[0]
    assert "transaction_type = '1'" in cash and "= 'null'" in cash
    assert "-ABS(" in cash
    assert "ISNULL(c.total_amount, 0) = 0" in cash  # 자리표는 장수에서 제외
    assert 'item["cash_issued"] = "발행" if cash_amount > 0 else ""' in service
    # 화면·엑셀은 한 칸이고 값은 '발행' 하나다 — 종류는 툴팁이 말한다.
    assert '"발행" if item["tax_issued"] or item["cash_issued"] else ""' in service


def test_미수금현황에도_증빙_칸이_있다():
    """선발행 미수(계산서·현금영수증은 나갔는데 미입금)를 미수금현황에서 골라낸다
    (2026-08-13 요청). 회사 매출실적 화면을 배포에서 뺀 대신 이 칸이 그 역할을
    한다 — 실측 312건 중 302건이 청구 전표가 있어 이 목록에 뜬다.
    """
    import re

    script = SCRIPT.read_text(encoding="utf-8")
    outstanding = re.search(r"const outstandingHeaders='(.*?)';", script, re.S)
    headers = re.findall(r"<th[^>]*>([^<]+)</th>", outstanding.group(1))
    assert headers[-1] == "세금계산서/현금영수증", headers[-2:]
    cols = re.search(r"const outstandingColumns='(.*?)';", script, re.S)
    assert cols.group(1).count("<col") == len(headers)
    # 미수금현황 행 템플릿도 같은 헬퍼를 부른다 (입금현황과 표시가 같아야 한다).
    assert script.count("proofIssuedCell(row)") == 2

    from app.routers.receivables import _OUTSTANDING_EXPORT_COLUMNS

    labels = [label for _, label in _OUTSTANDING_EXPORT_COLUMNS]
    assert labels[-1] == "세금계산서/현금영수증", labels[-2:]


def test_진행상태_엑셀도_입금현황에만():
    """미수금현황은 열 구성을 그대로 둔다 (요청 범위가 입금현황이다)."""
    from app.routers.receivables import (
        _OUTSTANDING_EXPORT_COLUMNS,
        _RECEIVED_EXPORT_COLUMNS,
    )

    labels = [label for _, label in _RECEIVED_EXPORT_COLUMNS]
    # 엑셀도 화면 목록과 같은 꼬리 구성 — 진행상태 뒤에 증빙 발행여부 한 칸.
    assert labels[-2:] == ["진행상태", "세금계산서/현금영수증"], labels[-3:]
    assert "진행상태" not in [label for _, label in _OUTSTANDING_EXPORT_COLUMNS]


def test_화면_헤더와_colgroup_열수가_같다():
    """열을 늘릴 때 colgroup 을 빠뜨리면 폭이 통째로 밀린다 (node 없이도 잡는다)."""
    import re

    script = SCRIPT.read_text(encoding="utf-8")
    for name, columns in (
        ("receivedHeaders", "receivedColumns"),
        ("outstandingHeaders", "outstandingColumns"),
    ):
        head = re.search(rf"const {name}='(.*?)';", script, re.S)
        col = re.search(rf"const {columns}='(.*?)';", script, re.S)
        assert head and col, f"{name}/{columns} 를 찾을 수 없다"
        assert head.group(1).count("<th") == col.group(1).count("<col"), (
            f"{name} {head.group(1).count('<th')}열 ≠ {columns} "
            f"{col.group(1).count('<col')}열"
        )


def test_로딩_스켈레톤_열수는_헤더에서_센다():
    """숫자를 박아두면 열을 늘릴 때마다 스켈레톤만 어긋난다."""
    script = SCRIPT.read_text(encoding="utf-8")
    index = script.index("function renderLoading()")
    body = script[index : index + 220]
    assert "receivedHeaders" in body and "outstandingHeaders" in body, body


def test_부가세_이중계상_보정은_네_조건을_모두_건다():
    """원장이 부가세를 한 번 더 붙인 건만 계산서 총액으로 바꾼다.

    조건을 하나라도 빼면 범위가 폭발한다 — '계산서가 있으면 계산서 기준'으로
    넓혔더니 4,628건이 바뀌고 정상 미수 146억이 사라졌다(2026-08-07 실측).
    특히 '차액이 정확히 원장 부가세'가 핵심이라 이게 빠지면 안 된다.
    """
    from app.services.receivables import _GROSS, _VAT_DOUBLED

    # 1) 계산서 총액 = 전표 청구액
    assert "ABS(ISNULL(t.tax_total, 0) - b.billed_amount)" in _VAT_DOUBLED
    # 2) 수금액 = 전표 청구액 (전액 회수된 건만)
    assert "ABS(ISNULL(b.received_amount, 0) - b.billed_amount)" in _VAT_DOUBLED
    # 3) 원장 매출총액 − 수금액 = 원장 부가세 (이게 이 보정의 핵심 조건이다)
    assert "ISNULL(a.[부가가치세], 0)) <=" in _VAT_DOUBLED
    # 4) 합산청구 계산서 제외 — 남의 몫이 섞이면 1)이 우연히 맞을 수 있다
    assert "ISNULL(t.own_sales, 0) * 1.02" in _VAT_DOUBLED

    # 기존 규칙(_TAX_OK)이 먼저 걸려야 한다 — 계산서가 원장보다 큰 건의
    # 판정을 이 보정이 가로채면 안 된다.
    assert _GROSS.index("t.own_sales") < _GROSS.index(_VAT_DOUBLED)
    # 원장 매출총액 분기보다는 앞에 와야 보정이 실제로 먹는다.
    assert _GROSS.index(_VAT_DOUBLED) < _GROSS.index("WHEN ISNULL(a.[매출총액], 0) > 0")


def test_부가세_보정은_입금현황에만_적용된다():
    """미수금현황은 effective_billed 를 쓰므로 이 보정이 닿지 않아야 한다."""
    service = SERVICE.read_text(encoding="utf-8")
    index = service.index("outstanding_expr = (")
    assert "_GROSS" not in service[index : index + 300]


def test_미수금은_매출총액에서_실제_수금액을_뺀다():
    """청구금액은 담당자가 '매출총액 − 선수금'으로 적는 관행이 있어 기준이 못 된다.

    2026년 본사 실측 38건. 선수금이 청구 차감과 입금액에 두 번 반영돼 완납 건이
    허위 과입금(24건)으로, 진행 건은 미수 과소로 나왔다.
    원장 [매출총액]은 담당자 입력과 무관하다. 수수료합계+부가세로 직접 더하면
    안 된다 — 저장값과 다른 건이 5건 있다(01-2602-3-0630 등).
    """
    service = SERVICE.read_text(encoding="utf-8")
    assert 'item.get("gross_total")' in service, "원장 [매출총액]을 써야 한다"
    assert "a.[매출총액] AS gross_total" in service
    assert "[매출총액] AS gross_total " in service, "30건 보강 조회에도 있어야 한다"
    assert "paid_total = received_total + settled_total" in service


def test_입금액에_안_잡힌_선수금을_수금으로_친다():
    """received_amount 는 같은 전표에 현금이 있어야 입금으로 센다.

    가수금→선수금 대체나 타 감정서 이첩은 현금이 없어 빠지고, 나중에 매출
    전표에서 상계될 때 입금액을 깎아 '허깨비 미수'를 만든다.
    (01-2601-4-0024 50만 · 01-2604-4-0163 20만 · 01-2607-A-0113 10만 실측)
    """
    service = SERVICE.read_text(encoding="utf-8")
    assert "def _advance_settlement(" in service
    # 이미 입금액에 든 것을 또 더하면 안 된다 — 세 가지 가드.
    assert "account_code IN ('1030000','1410001')" in service, "현금 동반 전표 제외"
    assert "account_code = '1080000'" in service, "외상매출금 차변 동반 제외 (0149 이중가산)"
    assert "cr_docs <= 1" in service, "일괄 정산 전표 제외 (4083 허위 과입금)"
    # 선수금 수령 전표의 부가세도 받은 돈이다 (1088: 현금 1,100만 중 선수금 1,000만만 계상).
    assert "account_code = '2550000'" in service


def test_합계바도_같은_기준이다():
    """합계 바는 페이지가 아니라 검색 결과 전체를 SQL로 낸다 — 목록과 식이 같아야 한다."""
    service = SERVICE.read_text(encoding="utf-8")
    assert "_SETTLE_CTE" in service and "LEFT JOIN settle s ON s.doc_id = b.doc_id" in service
    assert "a.[매출총액]" in service


def test_반올림_잔돈은_미수도_과입금도_아니다():
    """요약 테이블 입금액이 실제 입금보다 1~2원 큰 건이 있다.

    외상매출금 라인이 없는 전표는 부가세를 읽을 수 없어 ROUND(수수료 × 1.1)로
    역산한다(receivable_status_cte 의 direct_billed_delta·received_delta).
    01-2607-A-0105 는 통장에 4,700,000 이 들어왔는데 전표 수수료가 4,272,728 이라
    4,272,728 × 1.1 = 4,700,000.8 → 4,700,001 이 된다.
    전표당 최대 1원이라 2원까지만 흡수한다 — 1,000원으로 넓히면 근거 없는
    미수 550원(01-2602-3-0583)까지 지워진다.
    """
    service = SERVICE.read_text(encoding="utf-8")
    assert "_ROUND_NOISE = 2.0" in service
    assert "if abs(shortfall) <= _ROUND_NOISE:" in service
    # 합계 바도 같은 허용치여야 페이지 합과 총계가 어긋나지 않는다.
    assert "{_GROSS} - {_PAID} > {_ROUND_NOISE}" in service
    assert "{_PAID} - {_GROSS} > {_ROUND_NOISE}" in service


def test_우측_상태필터도_화면과_같은_기준():
    """필터가 요약 테이블 컬럼을 쓰면 화면 배지와 따로 논다.

    2026년 본사 실측: 화면에 '부분입금'인데 '부분입금' 필터에서 빠지는 건이 164건,
    전체 224건이 어긋났다. 미수 12,333,200 짜리(01-2602-3-0416)도 안 나왔다.
    미수금 범위 필터·미수금 정렬도 같은 이유로 옛 기준이었다.
    """
    service = SERVICE.read_text(encoding="utf-8")
    assert "_RECEIVED_STATUS_CONDITIONS = {" in service
    assert 'status_map = (\n            _RECEIVED_STATUS_CONDITIONS if mode == "received"' in service
    # 배지 우선순위(선수금 → 과입금 → 완납 → 부분입금 → 미입금)를 그대로 옮겼는지.
    for label in ("선수금", "과입금", "완납", "부분입금", "미입금"):
        assert f'"{label}":' in service
    # 범위 필터·정렬도 같은 식이어야 한다.
    assert "_OUTSTANDING_EXPR = (" in service
    assert "outstanding_expr = (\n            _OUTSTANDING_EXPR if mode == \"received\"" in service
    # s·t 를 참조하니 목록 쿼리에도 조인과 CTE가 붙어야 한다.
    assert "needs_settle = mode == \"received\" and bool(" in service
    assert "settle_join_sql = (" in service
    assert '{_SETTLE_CTE if needs_settle else ""}' in service


def test_상태판정도_매출총액_기준():
    from pathlib import Path

    router = (
        Path(__file__).resolve().parent.parent / "app" / "routers" / "receivables.py"
    ).read_text(encoding="utf-8")
    assert 'item.get("invoice_total")' in router
    assert 'item.get("settled_advance")' in router
    script = SCRIPT.read_text(encoding="utf-8")
    assert "row.invoice_total||row.assessed_billed" in script


def test_인쇄_열_개선_20260804():
    """재무팀 요청(2026-08-04 요청서): 인쇄에 발송일·진행상태 추가, 최근 입금일은
    맨 오른쪽, 조건 요약은 입금일만, 브라우저 머리말(주소·제목)은 여백 0으로 숨긴다.
    엑셀은 그대로 둔다 (사용자 확인 2026-08-05 — 인쇄만 바꾼다)."""
    import re

    # 인쇄 표 — 머리말 순서
    script = SCRIPT.read_text(encoding="utf-8")
    start = script.index("if(state.mode==='received'){", script.index("function buildPrintHtml"))
    chunk = script[start:script.index("</tfoot>", start)]
    heads = re.findall(r"<th[^>]*>([^<]+)</th>", chunk)
    assert heads[:6] == ["감정서번호", "목적", "물건종류", "거래처명", "유치자", "발송일"], heads[:6]
    assert heads[-3:] == ["미수금", "진행상태", "최근 입금일"], heads[-3:]

    # 조건 요약 — 입금일만 (구분·본지사·상태·검색어 미노출)
    cond_start = script.index("function printConditions()")
    cond = script[cond_start:script.index("}", script.index("return", cond_start)) + 1]
    for banned in ("본·지사", "상태:", "거래처명", "구분:"):
        assert banned not in cond, f"조건 요약에 {banned} 가 남아 있다"
    assert "입금일" in cond

    # 건수·출력시각 줄 제거 (2026-08-05) — 상한 잘림 경고만 남긴다
    build = script[script.index("function buildPrintHtml"):script.index("async function printList")]
    assert "· 출력" not in build, "출력시각 줄이 되살아났다"
    assert "만 인쇄 (상한" in build, "잘림 경고는 남겨야 한다"

    # 브라우저 머리말 숨김 — 이 화면만 여백 0 덮어쓰기
    page = (ROOT / "desktop" / "ui" / "receivables.html").read_text(encoding="utf-8")
    assert "margin: 0" in page and "@page" in page
    assert ".print-area{ padding" in page, "여백 0 대신 안쪽 패딩으로 가장자리를 확보한다"


def test_입금현황_기본_기간은_어제_하루다():
    """화면을 처음 열면 입금 시작일·종료일이 어제로 잡힌다 (2026-08-05 요청).

    미수금현황은 발송일 기준이라 최근 1개월 그대로 둔다 — 같은 블록에 있어
    한쪽만 고치다 다른 쪽을 건드리기 쉬우므로 둘 다 못 박는다.
    """
    script = SCRIPT.read_text(encoding="utf-8")
    block = script[script.index("// 기본 기간") : script.index("// 컬럼 폭 드래그 조절")]

    assert "yesterday.setDate(today.getDate()-1)" in block
    assert (
        "$('dateFrom').value=inputDate(yesterday);"
        "$('dateTo').value=inputDate(yesterday);" in block
    ), "입금현황 기본 기간이 어제 하루가 아니다"
    assert "$('dateFrom').value=inputDate(today);" not in block, "오늘 하루가 남아 있다"
    assert "inputDate(monthAgo)" in block, "미수금현황 최근 1개월은 그대로 둔다"
