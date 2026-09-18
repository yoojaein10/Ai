"""매출실적조회 — 평가사 개인 매출 대시보드.

기준을 기간별 매출실적(sales_stats)과 똑같이 맞춘다. 두 화면이 다른 기준을 쓰면
재무팀이 어느 숫자를 믿을지 알 수 없다 — 전표일자 구간의 401 계열 순액이다.
"""

import subprocess
from datetime import date
from pathlib import Path

import pytest

from app.routers import my_sales as my_sales_router
from app.services import my_sales

ROOT = Path(__file__).resolve().parent.parent
SERVICE = ROOT / "app" / "services" / "my_sales.py"
SCRIPT = ROOT / "desktop" / "ui" / "my-sales.js"
PAGE = ROOT / "desktop" / "ui" / "my-sales.html"


def test_전년_동기는_같은_월일로_잡는다():
    assert my_sales.previous_year_range(date(2026, 1, 1), date(2026, 7, 31)) == (
        date(2025, 1, 1), date(2025, 7, 31)
    )


def test_윤년_2월29일은_28일로_내린다():
    """전년에 2월 29일이 없어 그대로 replace 하면 ValueError 로 화면이 죽는다."""
    assert my_sales.previous_year_range(date(2024, 2, 29), date(2024, 2, 29)) == (
        date(2023, 2, 28), date(2023, 2, 28)
    )


def _row(manager, amount, doc="d1"):
    return {"doc_id": doc, "manager": manager, "amount": amount}


@pytest.mark.parametrize(
    "manager,expected",
    [
        ("고세욱", [("고세욱", 1000.0, "single")]),
        ("공(고세욱)", [("고세욱", 1000.0, "joint")]),
        ("공통", []),
        ("", []),
    ],
)
def test_한_명이_걸린_건은_그대로_귀속된다(manager, expected):
    assert my_sales._attribute(_row(manager, 1000.0), {}) == expected


def test_여럿이_걸린_건은_배분_비율대로_나눈다():
    """지분표(APW_Booking)의 사람별 비율로 나눈다.

    실측 01-2603-5-0044: 김형식 50% / 조근렬 25% / 강무진 25%.
    비율이 제각각이라 균등 배분으로 대신할 수 없다 — 같은 세 명인데 50/25/25 인
    건도 33/33/33 인 건도 있다. 값은 비율이라 합으로 정규화한다.
    """
    alloc = {"d1": {"김형식": 5000000.0, "조근렬": 2500000.0, "강무진": 2500000.0}}
    got = dict(
        (n, a) for n, a, k in my_sales._attribute(
            _row("조근렬,강무진,김형식", 10000.0), alloc
        ) if k == "single"
    )
    assert got == {"김형식": 5000.0, "조근렬": 2500.0, "강무진": 2500.0}


def test_배분이_없으면_금액을_지어내지_않는다():
    """51건 중 7건(3.9억)은 비율이 없다. 균등으로 채우면 틀린 숫자를 확정하게 된다."""
    got = my_sales._attribute(_row("조근렬,강무진,김형식", 10000.0), {})
    assert {k for _, _, k in got} == {"joint"}
    assert [a for _, a, _ in got] == [10000.0] * 3, "공동은 총액을 그대로 보여준다"


def test_지분표가_유치자_칸보다_우선한다():
    """유치자 칸과 지분표가 어긋나면 **지분표를 믿는다** (2026-08-08).

    칸은 사람을 가리키는 이름표일 뿐 금액의 근거가 아니고, 자주 빠지거나
    낡는다. 지분표는 감정서(MasterID)마다 사람별 한 줄로 관리된다.
    종전에는 칸에 있는데 배분표에 없는 이름에게 **건 전체 금액**을 공동으로
    줬는데, 그러면 한 건이 여러 사람 화면에 통째로 중복해 뜬다.
    """
    got = my_sales._attribute(
        _row("안창덕,조성국,이동호", 900.0), {"d1": {"이동호": 300.0}}
    )
    assert got == [("이동호", 900.0, "single")]


def test_칸에_한_명이어도_지분이_여럿이면_나눈다():
    """칸만 믿으면 한 사람에게 100% 를 몰아준다.

    실측: '공(이영은)' 처럼 한 명만 적힌 건이 592건이고, 그 건들도 지분표에는
    참여자가 들어 있다.
    """
    got = dict((n, a) for n, a, _ in my_sales._attribute(
        _row("공(이영은)", 1000.0), {"d1": {"이영은": 60.0, "김평가": 40.0}}
    ))
    assert got == {"이영은": 600.0, "김평가": 400.0}


def test_순위에_쉼표_이름이_남지_않는다():
    """배분 전에는 '조근렬,강무진,김형식'이 한 사람처럼 순위에 끼어 있었다."""
    rows = [_row("김철수", 300.0, "a"), _row("조근렬,강무진", 200.0, "b")]
    alloc = {"b": {"조근렬": 50.0, "강무진": 50.0}}
    result = my_sales._ranking(rows, alloc, "조근렬")
    assert result["total"] == 3, "김철수·조근렬·강무진 세 사람"
    totals = my_sales._single_totals(rows, alloc)
    assert not [n for n in totals if "," in n]
    assert totals["조근렬"] == 100.0 and totals["강무진"] == 100.0


def test_순위에서_공동과_공통은_뺀다():
    """'공(...)'·'공통'은 개인 순위의 모수가 아니다."""
    rows = [
        _row("김철수", 300.0, "a"), _row("고세욱", 200.0, "b"),
        _row("공(고세욱)", 999.0, "c"), _row("공통", 999.0, "d"), _row("", 50.0, "e"),
    ]
    result = my_sales._ranking(rows, {}, "고세욱")
    assert result["rank"] == 2
    assert result["total"] == 2, "공동·공통·빈칸은 모수에서 빠져야 한다"
    assert result["group_average"] == 250.0


def test_순위_모수에서_퇴사자를_뺀다():
    """운영 JSP 도 RTRM_FL<>'1' 로 뺀다. 실측(2026-01~07 본사) 82명 → 76명.

    등수는 아무도 안 바뀐다(퇴사자 6명이 전부 61위 이하). 바뀌는 건 평균이다
    — 180,537,390원 → 193,962,303원.
    """
    rows = [_row("재직자", 300.0, "a"), _row("퇴사자", 100.0, "b"),
            _row("나", 200.0, "c")]
    before = my_sales._ranking(rows, {}, "나")
    after = my_sales._ranking(rows, {}, "나", {"재직자", "나"})
    assert (before["total"], before["group_average"]) == (3, 200.0)
    assert (after["total"], after["group_average"]) == (2, 250.0)
    assert after["rank"] == 2


def test_보고_있는_사람이_퇴사자면_등수는_남긴다():
    """재무팀이 퇴사자 실적을 열어 봤을 때 순위 칸만 비면 고장으로 보인다."""
    rows = [_row("재직자", 300.0, "a"), _row("퇴사자", 100.0, "b")]
    result = my_sales._ranking(rows, {}, "퇴사자", {"재직자"})
    assert result["rank"] == 2 and result["total"] == 2


def test_재직자_조회에_실패해도_순위는_살아_있다():
    """active 를 안 넘기면 거르지 않는다 — 순위 카드가 통째로 사라지면 안 된다."""
    rows = [_row("재직자", 300.0, "a"), _row("퇴사자", 100.0, "b")]
    assert my_sales._ranking(rows, {}, "재직자")["total"] == 2


def test_재직_판정은_퇴사와_사용중지를_같이_본다():
    service = SERVICE.read_text(encoding="utf-8")
    index = service.index("_ACTIVE_SQL = ")
    body = service[index : index + 500]
    assert "RTRM_FL" in body and "USE_YN" in body


def test_순위는_남의_금액을_내보내지_않는다():
    """설계서 5장 '순위 블라인드' — 내 등수와 익명 평균선만 준다."""
    result = my_sales._ranking(
        [_row("김철수", 300.0, "a"), _row("고세욱", 200.0, "b")], {}, "고세욱"
    )
    assert set(result) == {
        "rank", "total", "percentile", "group_average", "group_label",
    }


def test_기준이_공급가액이다():
    """전표일자 + 401 계열 순액. 부가세는 곱하지 않는다.

    2026-08-10 사용자 확정 — 성과상여 정산·기간별 매출실적·옛 JSP 화면이 전부
    부가세 제외(순수수료)라서, 이 화면만 ×1.1 을 하면 회사에서 혼자 다른 숫자가
    된다. 한때 정산가이드를 따라 ×1.1 을 썼다가 되돌린 결정이니, 다시 부가세를
    곱하고 싶다면 그 실측(상여 In_Price·Basic_Susu 부가세 포함 일치 0건)을 먼저
    뒤집어야 한다.

    정산가이드가 진짜로 금지하는 것은 청구금액(선수금 차감 후)을 실적으로 쓰는
    것인데, 401 전표는 매출 인식 시점의 총액이라 애초에 그 문제가 없다. 실측상
    401 순액이 원장 SuSuSum(수수료합계)과 88.1% 정확히 일치했다.
    """
    service = SERVICE.read_text(encoding="utf-8")
    assert "account_code LIKE '401%'" in service
    assert "v.voucher_date BETWEEN" in service
    # 부가세 곱셈이 **매출 경로**에 되살아나면 안 된다 — 기간별과의 0원 대사가 깨진다.
    assert "VAT_MULTIPLIER" not in service
    assert "{vat}" not in service
    # 2026-08-10: 부가세 배수를 아예 걷었다. 미수 탭의 매출총액은 요약표의
    # 청구액(billed_amount)을 그대로 쓴다 — 미수금현황과 같은 값이고, ×1.1 로
    # 어림하면 부분 청구 건에서 틀린다(실측 8건 중 2건).
    assert "_VAT_GROSS" not in service, "추정 배수를 되살리지 말 것"
    assert service.count("* 1.1") == 0
    assert "s.billed_amount" in service, "매출총액은 요약표에서 온다"
    # 매출을 만드는 두 SQL 에는 어떤 배수도 없어야 한다.
    for name in ("_ROWS_SQL", "_YEARLY_SQL"):
        body = service[service.index(f"{name} = "):][:1500]
        assert "1.1" not in body and "vat" not in body.lower(), name
    # 청구금액을 **실적 금액으로 쓰면** 안 된다 — 선수금이 빠진 값이라 기간별과
    # 어긋난다. 2026-08-10 부터 미수 탭이 쓰려고 billed 를 같이 실어 오지만,
    # 금액(amount)은 여전히 401 순액이어야 한다.
    for name in ("_ROWS_SQL", "_YEARLY_SQL"):
        body = service[service.index(f"{name} = "):]
        body = body[: body.index('"""', body.index('"""') + 3)]
        assert "AS amount" in body or "AS net_amount" in body, name
        assert "billed_amount AS amount" not in body, f"{name}: 청구금액을 실적으로 쓰지 말 것"
        assert "billed_amount" not in body.split("AS amount")[0], (
            f"{name}: 금액 자리는 401 순액이어야 한다")


def test_항목마다_따로_질의하지_않는다():
    """카드·차트·순위를 따로 질의하면 같은 CTE를 여덟 번 돌아 2분이 넘었다(실측 141초).

    지금은 감정서 단위 집계(_fetch_rows)와 배분표(_allocations) 두 번만 읽고
    나머지는 파이썬에서 나눈다 — 4초로 줄었다.
    """
    service = SERVICE.read_text(encoding="utf-8")
    # 2026-08-07 연도별 추이(yearly_trend)와 재직자 조회(active_names)가 붙어 4가 됐고,
    # 2026-08-08 usr_seq→이름 표(_names_by_usr_seq)가 붙어 5가 됐다. 대시보드가
    # 쓰는 건 _fetch_rows·_allocations(+이름표)·active_names 이고 전부 1회씩이다
    # — 항목마다 부르는 게 아니다. 연도별은 아예 따로 부르는 화면이다.
    # 2026-08-10 원장 확정 폴백(_ledger_allocations)이 붙어 6이 됐다 — 공동 후보
    # 건에만 묻는 한 번짜리 질의라 항목별 반복이 아니다.
    # 2026-08-10 가변비 탭(variable_costs)이 붙어 7. 탭을 누를 때만 부르는
    # 별도 화면이라 대시보드 한 판의 질의 수는 그대로다.
    # 2026-08-10 회사 전체 보기의 연도별 전용 질의가 붙어 8 — yearly_trend 안에서
    # 개인/전체 중 **한 쪽만** 돈다(둘 다 도는 게 아니다).
    # 2026-08-11 소재지 분리(_addresses)가 붙어 9. 항목마다 부르는 게 아니라
    # **표에 실리는 건만** 한 번(200건씩) 묻는 것이다 — 아래 전용 테스트 참조.
    # 같은 날 읽기가 전부 _exec(교착 재시도)을 거치게 됐다. 세는 자리만 바뀐다.
    assert service.count("db.execute(") == 1, "재시도를 건너뛰는 읽기가 생겼다"
    # 2026-08-11 실적자 목록이 대시보드 질의를 빌려 쓰는 대신 전용 질의를 갖게 돼 11.
    # 2026-08-13 거래처별현황 개편으로 +3: 접수(_fetch_intake)·발송 미수
    # (_fetch_sent)·순위 그룹(_rank_groups). 접수·발송은 스레드로 본 질의와
    # 겹쳐 돌므로 벽시계 시간은 안 는다.
    # 2026-08-18 가변비 프로시저 교체로 +1: 상세 0건인 달만 상여 스냅숏과
    # 대조하는 _vc_bonus_hint(한 줄 SELECT, 프로시저 아님).
    assert service.count("_exec(") == 15   # 정의 1 + 호출 14
    for owner in ("def _fetch_rows(", "def _allocations(", "def _ledger_allocations("):
        index = service.index(owner)
        body = service[index : index + 2600]
        assert body.count("_exec(") == 1, owner
    # active_names 는 짧은 함수인데 바로 뒤에 순위 그룹 절(_rank_groups)이 붙어
    # 2600자 창을 쓰면 그쪽 _exec 까지 물린다 — 창을 좁혀 따로 본다.
    # 접수·발송·그룹도 각각 질의 한 번씩이다.
    for owner, span in (("def active_names(", 900), ("def _rank_groups(", 700),
                        ("def _fetch_intake(", 650), ("def _fetch_sent(", 500)):
        index = service.index(owner)
        assert service[index : index + span].count("_exec(") == 1, owner
    index = service.index("def yearly_trend(")
    assert service[index : index + 3200].count("_exec(") == 2, "개인 1 + 전체 1"

    # 이름표는 짧은 함수라 따로 본다 (2600자 창을 쓰면 뒤 함수까지 물린다).
    index = service.index("def _names_by_usr_seq(")
    assert service[index : index + 400].count("_exec(") == 1
    # 이름은 SQL 로 조인하지 않는다. 조인해 뒀더니 2개월 조회가 85초였다
    # (CAST 비교라 인덱스를 못 탄다). 몇백 행짜리 표를 한 번 읽어 파이썬에서 붙인다.
    assert "JOIN [{database}].dbo.TMWCMN_USR_BAC_INFO" not in service


def test_화면이_캐시되지_않는다():
    main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    index = main.index("def desktop_my_sales(")
    assert "no-cache" in main[index : index + 400]


def test_라우터가_배선되어_있다():
    main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert "from app.routers.my_sales import router as my_sales_router" in main
    assert "app.include_router(my_sales_router)" in main


def test_화면_구성이_설계서와_맞는다():
    """2026-08-08 전면개편(3안 합성 심사) 구조를 박제한다.

    히어로 1개 → 추이 카드(좌 월별·우 연도별 5년, 탭 없음) → **구성 탭 카드**
    → 당기 전건 표. 도넛은 제거됐다 — 근접값 비교 금지 형태인 데다 물건종류가
    두 번 읽히던 원흉이었다.

    2026-08-10: 매출 구성(mixBody)과 발주처(clientsBody) 두 카드를 한 카드로
    합치고 탭 다섯으로 갈랐다(mixTabs/tabBody).
    """
    page = PAGE.read_text(encoding="utf-8")
    for element in ("hero", "monthlyChart", "yearlyChart", "mixTabs",
                    "tabBody", "detailTable", "msTip"):
        assert f'id="{element}"' in page, element
    assert "donutChart" not in page, "도넛은 제거됐다 — 누적 막대가 대체한다"
    # 옛 두 카드는 없어졌다 — 껍데기를 남기면 다음 사람이 왜 있는지 모른다.
    for gone in ("clientsBody", "mixBody"):
        assert f'id="{gone}"' not in page, gone


def test_구성_탭이_넷이고_미수는_거래처별현황_밑이다():
    """매출·거래처별현황·상여·가변비 (2026-08-13 개편 — 미수 탭 삭제).

    미수는 거래처별현황의 하위 탭(미수 TOP)과 하단 '미수 내역' 표에서 본다.
    상여는 bonus_report 를 달마다 돌아 월당 3.7초(실측)라 대시보드에 얹지 않고
    탭을 누를 때 부른다 — 첫 화면이 이걸 기다리면 안 된다.
    """
    page = PAGE.read_text(encoding="utf-8")
    for key in ("sales", "clients", "bonus", "variable"):
        assert f'data-tab="{key}"' in page, key
    assert 'data-tab="receivable"' not in page, "미수 탭은 2026-08-13 에 뺐다"
    assert "거래처별현황" in page
    # 하위 탭 3개 — 매출·접수·미수 전부 거래처 축이다.
    script2 = SCRIPT.read_text(encoding="utf-8")
    for key in ("['sales','매출 TOP']", "['intake','접수 TOP']",
                "['recv','미수 TOP']"):
        assert key in script2, key
    script = SCRIPT.read_text(encoding="utf-8")
    assert "function renderTabBody(" in script and "function loadLate(" in script
    # 탭 본문을 그리다 터져도 카드가 비지 않아야 한다 (2026-08-10 실제 사고).
    guard = script[script.index("function renderTabBody("):]
    guard = guard[: guard.index("function renderTabBodyInner(")]
    assert "try{" in guard and "catch" in guard, "한 조각이 터지면 안내를 띄운다"
    # 탭이 부르는 그리기 함수가 하나라도 사라지면 화면이 죽는다 — 다 있는지 본다.
    for name in ("function donutChart(", "function tabChart(", "function tabTable(",
                 "function vcTable(", "function axisPicker(", "function split("):
        assert name in script, name
    # 사람·기간이 바뀌면 받아 둔 상여·가변비를 버려야 한다 — 남의 값이 남는다.
    assert "LATE={bonus:null,variable:null}" in script.replace(" ", "")
    # 상여·가변비를 **미리 받던 것을 뗐다** (2026-08-11 요청) — 둘 다 10초가
    # 넘는데 화면을 여는 사람 대부분은 매출 흐름을 보러 온다. 가변비는 추이
    # 차트의 체크를 켤 때, 탭은 그 탭을 누를 때 부른다.
    assert "await loadLate" not in script, "첫 화면이 무거운 계산을 기다리면 안 된다"
    assert 'id="axisTabs"' not in page and 'id="trendTabs"' not in page, (
        "탭 뒤에 숨은 정보는 없는 정보다 — 월별·연도별을 나란히 상시 노출한다")

    script = SCRIPT.read_text(encoding="utf-8")
    for renderer in ("renderHero", "renderMonthly", "renderYearly",
                     "renderClients", "renderMix", "renderTable"):
        assert renderer in script, renderer


def test_색은_실체에_고정된다():
    """사람·기간이 바뀌어도 담보는 파랑이다 — 순번 따라 색을 재배정하면
    '담보는 파랑'을 학습한 사용자를 속인다. 초과 축은 색을 만들지 않고
    회색 '기타'로 접는다."""
    script = SCRIPT.read_text(encoding="utf-8")
    assert "WORK_COLORS" in script and "PROP_COLORS" in script
    assert "'담보':['#2a78d6'" in script, "담보=파랑 고정이 깨졌다"
    assert "'토지건물':['#2a78d6'" in script


def test_전년_비교는_금액_기준이다():
    """건수 기준 증감은 가격자문(실측 62건 0.03억) 왜곡의 통로였다."""
    script = SCRIPT.read_text(encoding="utf-8")
    assert "prev_amount" in script
    assert "count_diff" not in script, "건수 증감 표시는 제거됐다"


def test_툴팁은_textContent_로만_채운다():
    """발주처명 등은 신뢰하지 않는 데이터다 — innerHTML 이면 XSS 통로가 된다."""
    script = SCRIPT.read_text(encoding="utf-8")
    block = script[script.index("function tipShow"):script.index("function tipHide")]
    assert "innerHTML" not in block
    assert "textContent" in block


def test_JS_구문이_깨지지_않았다():
    result = subprocess.run(
        ["node", "--check", str(SCRIPT)], capture_output=True, text=True, encoding="utf-8"
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_외부_차트_라이브러리를_받아오지_않는다():
    """내부망이라 CDN을 못 쓴다. 차트는 SVG로 직접 그린다."""
    page = PAGE.read_text(encoding="utf-8")
    assert "http://" not in page and "https://" not in page


# ── 권한: 남의 실적은 명단에 든 사람만 본다 ──────────────────────────────
#
# 이름만으로 사람을 가리는 게 안전한 근거(2026-08-07 실측):
#   · 2026 본사 유치자 표기 158종 중 단일 이름은 전부 사용자마스터 EMP 에 있다(불일치 0)
#   · 재직 중 동명이인 18명은 전원 소속 지사가 다르다 → (이름, 지사)면 유일하다


# 2026-08-11 권한 체계로 갈아탔다. 남 열람은 코드에 박힌 usr_seq 명단이 아니라
# 권한관리 화면에서 켜는 `view_other_users` 한 칸이 정한다 — 그래서 아래 가짜
# 사용자도 usr_seq 가 아니라 그 칸으로 갈린다.
def _user(**over):
    base = {
        # 기본은 **남을 못 보는** 사람이다 — 그래야 '권한 없는 사람' 을 가정한
        # 테스트가 뜻을 갖는다.
        "usr_seq": 999999, "usr_id": "hong", "emp_name": "홍길동", "office_id": "10",
        "view_all_offices": False, "view_other_users": False,
        "offices": [{"office_code": "10"}],
    }
    base.update(over)
    return base


def _viewer(**over):
    """남의 실적을 볼 수 있는 사람."""
    return _user(view_other_users=True, **over)


class _FakeDb:
    """이제 DB 를 보지 않는다 — 권한은 사용자 컨텍스트가 들고 온다."""


_DB = _FakeDb()


def test_권한이_없으면_남의_이름을_보내도_본인으로_바뀐다():
    got = my_sales_router._resolve_scope(_DB, _user(), "남의이름", "10")
    assert (got.name, got.office, got.allowed) == ("홍길동", "10", False)


def test_권한이_없으면_지사도_본인_소속으로_고정된다():
    """지사 사용자가 office_code=10 을 실어 보내도 본사 실적을 못 본다."""
    got = my_sales_router._resolve_scope(
        _DB, _user(office_id="20", offices=[{"office_code": "20"}]), None, "10"
    )
    assert (got.name, got.office) == ("홍길동", "20")


def test_권한이_있으면_남을_고를_수_있다():
    got = my_sales_router._resolve_scope(_DB, _viewer(), "김평가", "10")
    assert (got.name, got.office, got.allowed) == ("김평가", "10", True)


def test_권한이_있어도_권한_없는_지사는_못_본다():
    """명단은 '누구를' 볼지의 권한이지 '어느 지사를' 볼지의 권한이 아니다."""
    got = my_sales_router._resolve_scope(
        _DB, _viewer(office_id="20", offices=[{"office_code": "20"}]),
        "김평가", "13",
    )
    assert got.office == "20"


def test_권한이_있어도_전체지사는_지사권한이_있어야_한다():
    blocked = my_sales_router._resolve_scope(
        _DB, _viewer(office_id="20", view_all_offices=False,
                                    offices=[{"office_code": "20"}]), None, "all",
    )
    opened = my_sales_router._resolve_scope(
        _DB, _viewer(view_all_offices=True), None, "all"
    )
    assert blocked.office == "20" and opened.office is None


# ── 회사 전체 보기 (2026-08-10 요청) ──────────────────────────────────────
def test_권한이_없으면_전체를_보내도_본인으로_강등된다():
    """관문은 _resolve_scope 하나다. require_user 는 신원만 확인한다.

    거절(400)이 아니라 강등인 것은 이 화면의 원래 방식 그대로다 — 다만 강등
    결과가 '전체' 로 남으면 안 된다. 남의 총액이 그 길로 새면 설계 전제가 깨진다.
    """
    got = my_sales_router._resolve_scope(_DB, _user(), None, "10", "office")
    assert got.is_all is False
    assert (got.name, got.allowed) == ("홍길동", False)


def test_전체는_이름을_비워_보낸다():
    """센티널 이름('전체'·'__ALL__')을 쓰면 그 문자열이 프로시저의 @Manager,
    상여의 이름 비교, 화면의 select 값까지 흘러가 유령 평가사를 만든다."""
    got = my_sales_router._resolve_scope(_DB, _viewer(), "김평가", "10", "office")
    assert got.is_all is True and got.name is None and got.office == "10"


def test_전사_전체는_지사권한까지_있어야_한다():
    """전체(회사 통짜)는 남 열람 + 전 지사 열람 **둘 다** 통과해야 전사가 된다."""
    only_person = my_sales_router._resolve_scope(
        _DB, _viewer(office_id="20", view_all_offices=False,
                   offices=[{"office_code": "20"}]), None, "all", "office",
    )
    both = my_sales_router._resolve_scope(
        _DB, _viewer(view_all_offices=True), None, "all", "office"
    )
    assert only_person.is_all and only_person.office == "20", "자기 지사 통짜까지만"
    assert both.is_all and both.office is None, "전사 통짜"


def test_상여와_가변비는_전체를_거절한다():
    """이름 목록으로 루프를 돌리면 안 된다 — 가변비는 사람·달마다 프로시저
    한 번(3.5~5초)이라 8개월×82명이면 워커 4로도 10분이 넘고, 워커를 늘리면
    연결 풀에 막혀 다른 화면까지 같이 죽는다. 상여는 본사 전용 규칙이라
    지사 전체에서 숫자가 거짓말을 한다. 400 이 정직하다.
    """
    source = (ROOT / "app" / "routers" / "my_sales.py").read_text(encoding="utf-8")
    for tail in ('@router.get("/variable-cost"', '@router.get("/bonus"'):
        block = source[source.index(tail):]
        block = block[: block.index("return ApiResponse")]
        assert "if got.is_all:" in block and "SCOPE_NOT_SUPPORTED" in block, tail
    # AI 분석도 같다 — 사실표·프롬프트가 '평가사 한 명' 을 전제로 쓰여 있다.
    block = source[source.index('@router.get("/analyze"'):source.index('@router.get("/yearly"')]
    assert "SCOPE_NOT_SUPPORTED" in block


def test_전체는_배분_프레임을_건드리지_않는다():
    """가장 틀리기 쉬운 지점. '이름 조건만 지우자' 는 우회를 막는다.

    그러면 3인 공동 건이 3줄이 되어 금액 합은 우연히 보존되면서 건수만 참여자
    수만큼 부풀고, 참여자가 단독·공동으로 갈린 건은 두 카드에 동시에 든다.
    반대로 '전체 = 명단 전원의 개인 합' 도 양방향으로 틀린다 — 유치자 미등록
    몫이 통째로 빠지고(본사 3.6%, 지사 90~100%), 지분표 없이 이름만 여럿인
    건은 참여자 전원에게 건 전체 금액이 가서 같은 돈이 N번 세어진다.
    """
    service = SERVICE.read_text(encoding="utf-8")
    # dashboard 안의 if 가지만 잘라 본다 — 파일에는 yearly_trend 의 `if whole:`
    # 이 먼저 나오고, else 가지(개인 모드)는 당연히 mine() 을 쓴다.
    body = service[service.index("def dashboard("):]
    block = body[body.index("    if whole:"):]
    block = block[: block.index(chr(10) + "    else:")]
    # 주석에는 mine 이 나온다(왜 안 부르는지 적어 두었다) — **코드**만 본다.
    code = chr(10).join(
        line for line in block.splitlines() if not line.lstrip().startswith("#")
    )
    assert "mine(" not in code, "전체 금액 경로에 배분이 끼면 안 된다"
    assert "_attribute(" not in code, "배분은 커버리지 판정에만 쓴다"
    assert "cur_joint" in code and "[]" in code
    # 연도별도 같다 — SQL 의 이름 예선과 파이썬의 배분 결선은 한 몸이다.
    yearly = service[service.index("def yearly_trend("):]
    yearly = yearly[: yearly.index("def appraiser_names(")]
    whole_path = yearly[yearly.index("    if whole:"): yearly.index("    rows = [")]
    # 주석에는 이름이 나온다(왜 뺐는지 적어 두었다) — **호출**이 없어야 한다.
    assert "_attribute(" not in whole_path and "name_like" not in whole_path


def test_전체는_공동과_순위를_비운다():
    """전체 모드에선 모든 감정서가 이미 single 에 한 번 들어 있다.
    공동을 채우면 화면 어딘가에서 둘을 더해 정확히 두 배가 된다."""
    service = SERVICE.read_text(encoding="utf-8")
    assert '"ranking": None if whole or no_rank else _ranking(' in service
    body = service[service.index("def dashboard("):]
    block = body[body.index("    if whole:"):]
    block = block[: block.index(chr(10) + "    else:")]
    assert 'cur_joint: "list[dict[str, Any]]" = []' in block


def test_실적자_목록은_원장_폴백을_타지_않는다():
    """목록은 이름만 쓴다 — 1.9초짜리 폴백(_with_ledger_settlement)은 금액만
    바꾸고 명단을 안 바꾼다.

    실측: 2026-01~08 82명, 2025 전체 89명 모두 폴백 유무와 명단이 완전히 같았다
    (폴백으로만 나타나는 사람 0, 사라지는 사람 0). 그래서 목록에서는 뺐다 —
    3.6초 → 1.1초. 금액이 필요한 dashboard 는 여전히 탄다.
    """
    service = SERVICE.read_text(encoding="utf-8")
    body = service[service.index("def appraiser_names("):]
    body = body[: body.index("def dashboard(")]
    # 독스트링에도 이름이 나온다 — 닫는 따옴표 뒤의 코드만 본다.
    code = body[body.index('"""', body.index('"""') + 3) + 3:]
    assert "_with_ledger_settlement" not in code, "목록에 폴백을 되살리면 3배 느려진다"
    # 금액을 내는 쪽은 반드시 타야 한다.
    dash = service[service.index("def dashboard("):][:3000]
    assert "_with_ledger_settlement" in dash


def test_한_창짜리_SQL_을_만들지_않는다():
    """'전년이 필요 없으면 UNION 가지를 빼자' 는 최적화를 실측이 뒤집었다
    (2026-08-10).

        한 창(5,288행) 4.35초  ·  두 창(8,465행) 1.57초

    적게 긁는 쪽이 3배 느리다 — 열을 줄이고 조인을 빼자 실행계획이 나빠졌다.
    데이터가 적으니 빠를 것이라는 짐작을 믿지 말 것. 다시 만들지 않는다.
    """
    service = SERVICE.read_text(encoding="utf-8")
    assert "_ROWS_SQL_ONE" not in service
    assert service.count("_ROWS_SQL = ") == 1


def test_남_열람은_권한_한_칸이_정한다():
    """2026-08-11 권한 체계로 갈아탔다.

    그 전에는 usr_seq 여덟 개(원동하·엄기원·이일우·유재인·고정은·김경희·
    임정미·장세희)를 라우터에 **박아** 두었다. 명단을 고치려면 배포를 해야 했고,
    같은 판단이 코드와 표 두 곳에 흩어져 한쪽만 고쳐지기 마련이었다.

    이제 권한관리 화면에서 켜는 `view_other_users` 한 칸이 정한다 — 본사
    재무·집행부·전산정보팀과 지사 재무 담당자가 기본으로 갖는다
    (기본값 계산은 app/services/access_policy.py).
    """
    assert my_sales_router.can_view_others(_FakeDb(), _viewer()) is True
    assert my_sales_router.can_view_others(_FakeDb(), _user()) is False
    # 칸이 아예 없어도 열리지 않는다(fail-closed). 값 자체는 서버가 만드는
    # 불리언이라(access_policy.build_access_policy 가 bool() 로 확정한다)
    # 문자열 같은 게 여기까지 올 수 없다 — 없음·거짓만 확인한다.
    for falsy in (None, False, 0):
        got = my_sales_router.can_view_others(
            _FakeDb(), _user(view_other_users=falsy))
        assert got is False, falsy
    missing = dict(_user())
    missing.pop("view_other_users")
    assert my_sales_router.can_view_others(_FakeDb(), missing) is False
    # **코드에 박힌 명단이 되살아나면 안 된다.** 왜 걷었는지는 주석에 남아
    # 있으므로 대입문만 본다.
    source = (ROOT / "app" / "routers" / "my_sales.py").read_text(encoding="utf-8")
    assert "_VIEW_ALL_USERS = " not in source


def test_여섯_엔드포인트_전부_메뉴_관문을_지난다():
    """권한 체계에서는 화면 자체를 열고 닫는다 — 관문이 하나라도 빠지면
    메뉴에서 감춰도 주소를 직접 치면 열린다."""
    source = (ROOT / "app" / "routers" / "my_sales.py").read_text(encoding="utf-8")
    assert 'MENU_KEY = "mySales"' in source
    assert source.count("require_menu_access(user, MENU_KEY)") == 6


def test_모든_API가_신원을_요구한다():
    """require_user 가 빠진 엔드포인트가 하나라도 있으면 그리로 남의 실적이 샌다."""
    source = (ROOT / "app" / "routers" / "my_sales.py").read_text(encoding="utf-8")
    endpoints = source.count("@router.get(")
    # 2026-08-09 AI 분석(/analyze)이 붙어 4, 2026-08-10 상여·가변비 탭이 붙어 6.
    assert endpoints == 6, "엔드포인트가 늘었다 — 신원 확인을 붙였는지 같이 보라"
    assert source.count("Depends(require_user)") == endpoints
    # 권한 판정도 모든 엔드포인트가 거쳐야 한다.
    assert source.count("_resolve_scope(") == endpoints + 1, "정의 1 + 호출 4"


def test_목록_API가_권한_없는_사람에게_사내_명단을_주지_않는다():
    source = (ROOT / "app" / "routers" / "my_sales.py").read_text(encoding="utf-8")
    index = source.index("def list_appraisers(")
    body = source[index : source.index("def get_dashboard(")]
    assert 'data={"names": [user["emp_name"]], "count": 1' in body


def test_화면이_신원을_실어_보낸다():
    script = SCRIPT.read_text(encoding="utf-8")
    assert "params.set('usr_seq',window.A10_USR)" in script


def test_이름은_서버가_돌려준_값으로_그린다():
    """셀렉트 값으로 제목을 그리면 권한 없는 사람에게 남의 이름이 박힌다."""
    script = SCRIPT.read_text(encoding="utf-8")
    assert "${data.emp_name} 평가사" in script


# ── 메뉴 ────────────────────────────────────────────────────────────────


def test_좌측_메뉴에_걸려_있다():
    """URL 직접 입력으로만 들어가던 화면이다. 메뉴에 있어야 한다.

    2026-08-08 메뉴 통합 전에는 16개 화면 HTML 이 저마다 사이드바를 품어서
    16곳을 다 확인했다. 지금은 context.js 의 A10_MENU 한 곳이 원본이다.
    실측으로 이 화면은 통합 때 A10_MENU 에서 통째로 빠져 있었다 — 그대로
    뒀으면 볼 수 있는 84명의 사이드바에서 사라진다.
    """
    context = (ROOT / "desktop" / "ui" / "context.js").read_text(encoding="utf-8")
    menu = context[context.index("const A10_MENU"):context.index("function a10MenuActive")]
    assert "'/desktop/my-sales'" in menu, "A10_MENU 에 없다"


def test_메뉴는_지사에도_보인다():
    """본인 실적 화면이라 본사 전용이 아니다 — 지사 평가사도 기본으로 받는다."""
    from app.services.access_policy import APPRAISER_DEFAULT_MENU_KEYS

    assert "mySales" in APPRAISER_DEFAULT_MENU_KEYS


def test_메뉴는_지사에도_보인다():
    """본인 실적 화면이므로 hq-only 를 붙이면 안 된다."""
    for page in (ROOT / "desktop" / "ui").glob("*.html"):
        for line in page.read_text(encoding="utf-8").split("\n"):
            if '"/desktop/my-sales"' in line:
                assert "hq-only" not in line, page.name


# ── 연도별 추이 ──────────────────────────────────────────────────────────


def test_연도별은_탭이_아니라_상시_패널이다():
    """실적이 없는 해가 축에서 빠지면 '쉬었다'가 안 보이고 그래프가 거짓말을
    한다 — 서버(yearly_trend)가 빈 해를 채우는 건 그대로 두고, 화면은 탭 뒤가
    아니라 추이 카드 우측에 상시로 보여준다 (2026-08-08 개편)."""
    assert my_sales.yearly_trend.__doc__ is not None
    script = SCRIPT.read_text(encoding="utf-8")
    assert "renderYearly" in script
    assert "trendAxis" not in script, "축 전환 탭은 제거됐다"
    page = PAGE.read_text(encoding="utf-8")
    assert 'id="yearlyChart"' in page


def test_연도별은_이름으로_미리_거르되_귀속은_다시_가른다():
    """LIKE 는 예선일 뿐이다. '박중현' LIKE 가 '박중현우'를 물어도 떨어져야 한다."""
    service = SERVICE.read_text(encoding="utf-8")
    index = service.index("def yearly_trend(")
    body = service[index : index + 2600]
    assert "name_like" in body
    assert "if name != emp_name:" in body, "LIKE 결과를 그대로 쓰면 안 된다"


def test_연도별도_배분을_거친다():
    """월별과 다른 기준을 쓰면 두 탭의 숫자가 어긋난다."""
    service = SERVICE.read_text(encoding="utf-8")
    index = service.index("def yearly_trend(")
    body = service[index : index + 2600]
    assert "_allocations(db, _multi_docs(rows))" in body
    assert "_attribute(row, alloc)" in body


def test_화면은_공용_메뉴를_쓴다():
    """사이드바 자리만 두고 내용은 context.js 가 그린다 (2026-08-08 메뉴 통합).

    '지금 이 화면' 표시(aria-current)도 거기서 a10MenuActive 가 붙인다.
    """
    page = PAGE.read_text(encoding="utf-8")
    assert '<nav class="side-nav"></nav>' in page, "메뉴가 다시 HTML 에 박혔다"
    assert 'class="app-shell"' in page
    assert "/ui/context.js" in page, "공용 부트스트랩을 불러야 메뉴가 그려진다"


def test_전년이_음수면_증가율을_내지_않는다():
    """전표 취소가 인식분보다 많으면 전년 합계가 음수가 된다.

    실측: 김남수 2025-01~07 이 -5,438만이라 화면에 ▲952.7% 가 떴다. 음수를
    분모로 쓰면 부호까지 뒤집혀 '늘었다/줄었다'가 거꾸로 읽힌다.
    """
    service = SERVICE.read_text(encoding="utf-8")
    index = service.index("    rate = (")
    assert 'if single_prev["amount"] > 0 else None' in service[index : index + 220]

    script = SCRIPT.read_text(encoding="utf-8")
    assert "비교 불가" in script, "rate 가 None 이면 화면이 그렇게 말해야 한다"


def test_기본_기간은_그_해_1월_1일부터다():
    """toISOString() 은 UTC 로 바꾼다 — 한국시간 01-01 00:00 이 전년 12-31 15:00 이다.

    실측: 기본 시작일이 2025-12-31 로 떠서 월별 추이에 12월 막대가 한 칸 끼었다.
    종료일도 자정~오전 9시 사이에 같은 이유로 어제가 된다. 현지 날짜로 써야 한다.
    """
    script = SCRIPT.read_text(encoding="utf-8")
    # 2026-08-10: 기간을 연도 하나로 바꿨다. 날짜를 만드는 자리는 applyYear 다.
    body = script[script.index("function applyYear("):]
    body = body[: body.index("function initDates(")]
    # 주석에도 toISOString 이 나오므로 코드 줄만 본다.
    code = "\n".join(
        line for line in body.split("\n") if not line.strip().startswith("//")
    )
    assert "toISOString" not in code, "UTC 변환을 쓰면 기본 기간이 하루 밀린다"
    assert "padStart(2,'0')" in body
    assert "-01-01" in body, "시작은 그 해 1월 1일"
    # 올해를 고르면 끝은 오늘이다 — 12-31 로 두면 안 온 달이 0으로 그려져
    # 추이가 뚝 떨어진 것처럼 보인다.
    assert "getFullYear()" in body and "new Date(year,11,31)" in body


# ── 발주처·업무종류 집계 (2026-08-08 전면개편) ──────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        # 직함은 마지막 어절일 때만 벗긴다
        ("주택도시보증공사 사장", "주택도시보증공사"),
        ("주택도시보증공사", "주택도시보증공사"),
        ("서울지방국세청장", "서울지방국세청장"),
        # 기관명 자체가 '…장'으로 끝나면 안 건드린다 (한 어절)
        ("한남4재정비촉진구역주택재개발정비사업조합장", "한남4재정비촉진구역주택재개발정비사업조합장"),
        # 부서+직함 복합어는 어절째 떨군다 — 이걸 안 하면 주택도시보증공사가 두 줄이 된다
        ("주택도시보증공사 든든전세임대센터장", "주택도시보증공사"),
        ("잠실5단지아파트 주택재건축정비사업조합장", "잠실5단지아파트"),
        ("한국자산관리공사 서울지역본부", "한국자산관리공사"),
        # 금융기관은 지점·직함을 걷고 기관으로 묶는다
        ("기업은행 남동산단지점장", "기업은행"),
        ("국민은행 강남파이낸스지점장", "국민은행"),
        ("한국투자저축은행 금융10팀장", "한국투자저축은행"),
        # 법인 표기와 '외 N인' 꼬리
        ("(주)서한", "서한"),
        ("주식회사 한국스탠다드차타드은행", "한국스탠다드차타드은행"),
        ("한국투자증권 외", "한국투자증권"),
        ("한국투자증권(주)", "한국투자증권"),
        ("", "(미기재)"),
        (None, "(미기재)"),
    ],
)
def test_발주처_정규화(raw, expected):
    """원문 1,507종이 844종으로 묶인다(실측). 기업은행 304건 9.3억이 한 줄이 된다."""
    assert my_sales.normalize_customer(raw) == expected


def _crow(customer, amount, work="담보"):
    return {"customer_name": customer, "work_type": work, "amount": amount}


def test_발주처는_금액순_상위와_기타로_접는다():
    cur = [_crow("기업은행 A지점장", 100.0), _crow("기업은행 B지점장", 200.0),
           _crow("(주)서한", 500.0), _crow("가격자문사", 1.0), _crow("소액다건", 2.0)]
    got = my_sales._by_customer(cur, [], limit=2)

    assert [t["name"] for t in got["top"]] == ["서한", "기업은행"]
    assert got["top"][1]["count"] == 2 and got["top"][1]["amount"] == 300.0
    assert got["others"]["kinds"] == 2 and got["others"]["amount"] == 3.0


def test_발주처_신규와_식은_관계를_표시한다():
    """영업 관점의 핵심: 새로 생긴 관계(is_new)와 전년엔 있었는데 올해 없는 관계(gone)."""
    cur = [_crow("신한은행 A지점장", 100.0)]
    prev = [_crow("국민은행 B지점장", 900.0), _crow("신한은행 C지점장", 50.0)]
    got = my_sales._by_customer(cur, prev, limit=5)

    assert got["top"][0]["name"] == "신한은행"
    assert got["top"][0]["is_new"] is False
    assert got["top"][0]["prev_amount"] == 50.0
    assert got["gone"] == [{"name": "국민은행", "prev_amount": 900.0}]


def test_업무종류는_금액_정렬이다():
    """가격자문은 건수만 많고 금액이 미미하다(실측 62건 0.03억) — 건수 정렬은 왜곡."""
    cur = [_crow("a", 10.0, "가격자문"), _crow("b", 20.0, "가격자문"),
           _crow("c", 5000.0, "담보"), _crow("d", 900.0, "일반거래")]
    got = my_sales._by_work_type(cur, [_crow("e", 100.0, "담보")])

    assert [w["name"] for w in got] == ["담보", "일반거래", "가격자문"]
    assert got[0]["prev_amount"] == 100.0 and got[0]["prev_count"] == 1
    assert got[2]["count"] == 2


def test_기간_판정은_전표_줄_단위다():
    """기간별 매출실적과 같은 규칙이어야 두 화면이 원 단위로 대사된다.

    실측(2026-01~07 본사): 감정서의 마지막 전표일로 건 전체를 한 기간에 몰면
    연도에 걸친 12건의 작년 취소분 −1.37억이 올해로 흡수돼 기간별 합계와
    0.69% 어긋났다. 줄 단위로 가르면 차이가 정확히 0원이다(잔차 0 실측).
    """
    service = SERVICE.read_text(encoding="utf-8")
    # 2026-08-10: 뒤에 _ROWS_SQL_ONE 과 그 설명 주석이 붙었다 — SQL 문자열
    # 안쪽만 잘라서 센다(주석의 'UNION ALL' 이 세어지면 안 된다).
    index = service.index('_ROWS_SQL = """') + len('_ROWS_SQL = """')
    body = service[index : service.index('"""', index)]
    # 창마다 따로 긁어 상수 bucket 을 붙인다 — GROUP BY 에 CASE 식을 넣었더니
    # 실행계획이 무너져 0.9초짜리가 40초가 됐다(실측). UNION ALL 이 정답이다.
    assert body.count("UNION ALL") == 1
    assert "'cur' AS bucket" in body and "'prev'" in body
    assert "MAX(s.voucher_date) BETWEEN :cur_from" not in service, (
        "감정서 단위 버킷으로 되돌리면 연도 걸친 건이 기간을 넘어 이동한다")


def test_귀속_커버리지는_비율만_내려보낸다():
    """유치자 미등록 몫이 크면 화면이 스스로 알린다(실측: 본사 4%, 울산 100%).

    금액이 아니라 비율만 — 지사 총액은 이 화면 이용자 전원이 볼 권한이 있는
    숫자가 아니다. 지사 명단 하드코딩 금지: 등록 관행이 좋아지면 안내도
    저절로 사라져야 한다.
    """
    service = SERVICE.read_text(encoding="utf-8")
    block = service[service.index('"coverage": {'):]
    block = block[: block.index("}")]
    assert "unassigned_ratio" in block
    # 2026-08-10 전체 보기 — 같은 숫자의 뜻이 모드마다 뒤집혀 basis 를 같이 준다.
    assert '"basis"' in block
    # 금액은 여전히 안 내려간다.
    assert "unassigned_amount" not in service and "office_total" not in block
    assert "unassigned_amount" not in service, "금액은 내려보내지 않는다"

    script = SCRIPT.read_text(encoding="utf-8")
    assert "unassigned_ratio" in script
    assert "covRatio>0.15" in script, "정상 범위(본사 4%)에서는 조용해야 한다"


def test_지분표의_공동계정_몫은_실명_공동대기로_벗긴다():
    """지분표(APW_Booking)가 '공(장재원)' 공동계정 usr_seq 를 가리키는 건이
    실재한다(2026-01~07 본사 16건·2.55억). 그대로 두면 유령 이름으로 귀속돼
    장재원 본인 화면 어디에도 안 잡히고, 실적자 목록·순위에 유령이 낀다.

    공동계정의 뜻 자체가 수기정산 대상이므로: 실명으로 벗기고, 공동 대기로,
    이때만은 건 전체가 아니라 정확한 지분 몫으로 귀속한다.
    """
    got = my_sales._attribute(
        _row("박중현,공(장재원)", 1000.0),
        {"d1": {"박중현": 40.0, "공(장재원)": 60.0}},
    )
    assert ("박중현", 400.0, "single") in got
    assert ("장재원", 600.0, "joint") in got
    assert not any(n.startswith("공(") for n, _, _ in got), "유령 이름 금지"


def test_연도별도_전표_줄_단위_연도_판정이다():
    """대시보드와 같은 규칙이어야 같은 해에 같은 숫자가 나온다.

    감정서 단위로 몰면 연도에 걸친 건이 마지막 전표의 해로 통째로 이동한다
    (실측: 안창덕 2026 연도별이 대시보드보다 117만원 크게 나왔다 → 수정 후 0원).
    """
    service = SERVICE.read_text(encoding="utf-8")
    index = service.index("_YEARLY_SQL = ")
    body = service[index:index + 1600]
    assert "GROUP BY s.management_no, YEAR(s.voucher_date)" in body


# ── AI 분석 (2026-08-09) ─────────────────────────────────────────────────


def test_AI분석은_서버_사실표만_준다():
    """예전 자동 브리핑(40cb09f)을 뺐던 교훈 그대로: 모델에게 계산을 시키면
    숫자를 지어낸다. 숫자는 전부 서버가 계산·포맷해 사실표로 주고, 모델의
    일은 서술뿐이다. thinking 토큰도 끈다 — 느리고 비싼데 품질 차가 없었다.
    """
    service = SERVICE.read_text(encoding="utf-8")
    assert "사실표에 적힌 수치만 그대로 인용" in service
    assert '"thinkingBudget": 0' in service
    assert "def briefing_facts(" in service


def test_AI분석_사실표에_핵심_신호가_들어간다():
    data = {
        "emp_name": "홍길동",
        "period": {"from": "2026-01-01", "to": "2026-07-31"},
        "prev_period": {"from": "2025-01-01", "to": "2025-07-31"},
        "kpi": {
            "single": {"amount": 250000000.0, "count": 10},
            "joint": {"amount": 0.0, "count": 0},
            "growth": {"amount": 250000000.0, "prev_amount": 200000000.0,
                       "prev_count": 8, "diff": 50000000.0, "rate": 25.0,
                       "is_positive": True},
            "ranking": {"rank": 3, "total": 40, "percentile": 8,
                        "group_average": 1.0},
        },
        "monthly": {"current": [{"month": "2026-01", "amount": 250000000.0,
                                 "count": 10}]},
        "work_types": [{"name": "담보", "amount": 250000000.0, "count": 10,
                        "prev_amount": 150000000.0, "prev_count": 6}],
        "prop_types": [],
        "customers": {
            "top": [{"name": "기업은행", "amount": 250000000.0, "count": 10,
                     "prev_amount": 100000000.0, "is_new": False}],
            "others": {"count": 0, "amount": 0.0, "kinds": 0},
            "gone": [{"name": "대조피에프브이", "prev_amount": 100000000.0}],
        },
    }
    facts = my_sales.briefing_facts(data, [{"year": 2026, "single": 250000000.0,
                                            "joint": 0.0}])
    assert "홍길동" in facts and "2.5억원" in facts
    assert "식은 관계" in facts and "대조피에프브이" in facts
    # 순위 서술은 화면 칩과 같은 말이어야 한다 (그룹 모수, 2026-08-14 정합).
    assert "기업은행" in facts and "40명 중 3위" in facts
    # 원 단위 생숫자를 흘리지 않는다 — 모델이 재계산할 여지를 줄인다.
    assert "250000000" not in facts


def test_AI분석_엔드포인트도_같은_문지기를_쓴다():
    """조회 대상·범위는 _resolve_scope 가 정한다 — 클라이언트 숫자는 안 믿는다."""
    source = (ROOT / "app" / "routers" / "my_sales.py").read_text(encoding="utf-8")
    block = source[source.index('@router.get("/analyze"'):source.index('@router.get("/yearly"')]
    # 이 브랜치엔 메뉴 권한 체계가 없다(permission 브랜치에만 있다).
    # 관문은 _resolve_scope 하나다 — 클라이언트가 보낸 이름·지사를 안 믿는다.
    assert "_resolve_scope(db, user, emp_name, office_code, scope)" in block
    # 여섯 엔드포인트 전부 이 함수 하나만 거친다 — 본문에서 scope 를 직접
    # 해석하는 코드가 생기면 방어가 그 순간 0 이 된다.
    assert source.count("_resolve_scope(db, user,") == 6


def test_AI분석_출력은_textContent_로만_붓는다():
    """모델 출력도 신뢰하지 않는 데이터다 — innerHTML 이면 XSS 통로가 된다."""
    script = SCRIPT.read_text(encoding="utf-8")
    block = script[script.index("async function loadAnalysis"):script.index("function resetAnalysis")]
    assert "innerHTML" not in block
    assert "textContent" in block


def test_AI분석_출력의_마크다운을_걷는다():
    """'마크다운 금지'라고 해도 flash-lite 는 '*   ' 불릿과 굵게를 섞어 낸다(실측)."""
    got = my_sales._tidy_analysis("*   첫 **성과** 입니다.\n- 둘째\n다음 행동: 전화")
    assert got == "· 첫 성과 입니다.\n· 둘째\n다음 행동: 전화"


def test_AI분석_복사는_http_운영에서도_된다():
    """운영은 http 라 navigator.clipboard 가 없다(보안 컨텍스트 아님).

    구식 경로(textarea+execCommand) 폴백이 없으면 복사 버튼이 운영에서만
    조용히 죽는다 — 로컬(https/localhost)에서는 재현이 안 되는 유형이다.
    """
    script = SCRIPT.read_text(encoding="utf-8")
    assert "function legacyCopy(" in script
    assert "execCommand('copy')" in script
    assert "navigator.clipboard&&navigator.clipboard.writeText" in script


def test_AI분석_같은_조회는_다시_호출하지_않는다():
    """접었다 다시 열 때 5초를 또 기다리게 하지 않는다 — 캐시로 바로 편다.
    사람·기간이 바뀌면 resetAnalysis 가 캐시를 비운다."""
    script = SCRIPT.read_text(encoding="utf-8")
    assert "aiCache" in script
    block = script[script.index("function resetAnalysis")
                   :script.index("$('aiButton').addEventListener")]
    assert "aiCache=null" in block


# ── 2026-08-09 어르신 배려 묶음: 인쇄·프리셋·가독성 ─────────────────────


def test_인쇄는_버튼_없이_한_장_보고서다():
    """세 관점 발상이 독립적으로 낸 유일한 안 — Ctrl+P 만으로 보고서가 된다.

    메시·유리는 잉크 낭비라 걷고, 조작 요소는 숨기고, '더 보기' 뒤 행은
    beforeprint 에서 전건으로 펼친다(종이에서 잘린 표는 반출 자료가 못 된다).
    흑백 프린터에서 올해/전년 구분이 사라지므로 전년선만 점선으로 가른다
    (화면에서는 점선 금지 — 인쇄 전용 예외).
    """
    css = (ROOT / "desktop" / "ui" / "my-sales.css").read_text(encoding="utf-8")
    assert "@media print" in css
    block = css[css.index("@media print"):]
    assert "stroke-dasharray" in block, "흑백 인쇄에서 전년선 구분"
    assert ".ms-toolbar" in block and "display:none" in block

    script = SCRIPT.read_text(encoding="utf-8")
    assert "beforeprint" in script and "afterprint" in script
    page = PAGE.read_text(encoding="utf-8")
    assert 'id="printHeader"' in page


def test_기간은_연도_하나로_움직인다():
    """2026-08-10 요청 — 달력으로 월·일까지 고르게 하니 실제로는 늘 한 해를
    보는데 손이 두 번 갔다. 연도 고르개 하나로 바꾸고 프리셋은 걷었다.

    dateFrom·dateTo 는 숨은 채로 남는다 — 조회·AI 분석·상여·가변비가 모두
    그 두 값을 쓴다. 없애면 네 경로를 다 고쳐야 한다.
    """
    page = PAGE.read_text(encoding="utf-8")
    assert 'id="yearPick"' in page
    assert 'id="dateFrom" type="hidden"' in page
    assert 'id="dateTo" type="hidden"' in page
    assert "data-preset" not in page, "프리셋은 걷었다"
    script = SCRIPT.read_text(encoding="utf-8")
    assert "const PRESETS=" not in script
    # 연도를 바꾸면 바로 조회까지 간다.
    block = script[script.index("$('yearPick').addEventListener"):]
    assert "loadAll()" in block[:300]


def test_글자_바닥선은_12px_다():
    """노안 기준: 화면의 핵심 서사(전년 비교)가 10px 연회색이면 읽기 한계선
    아래다. 차트 글자·표 글자를 바닥선 위로 올렸다.

    2026-08-10 요청으로 표 글자를 한 단 더 키웠다(본문 13.5→14.5, 구성 탭 13.5,
    머리글은 색까지 진하게). 바닥선만 지키면 되므로 하한으로 검사한다."""
    import re

    css = (ROOT / "desktop" / "ui" / "my-sales.css").read_text(encoding="utf-8")
    screen = css[:css.index("@media print")]
    assert ".chart-svg text{font-size:12px" in screen

    def size(pattern: str, where: str) -> float:
        hit = re.search(pattern + r"[^}]*font-size:([0-9.]+)px", where)
        assert hit, pattern
        return float(hit.group(1))

    assert size(r"\.ms-table\{", screen) >= 13.5, "매출 인식 내역 본문"
    # 구성 탭 규칙은 인쇄 블록 뒤에 붙어 있다 — 전체에서 찾는다.
    assert size(r"table\.tab-table\{", css) >= 13, "구성 탭 본문"
    # 머리글은 옅은 회색이면 열 이름이 숫자에 묻힌다 (2026-08-10 제보).
    head = re.search(r"table\.tab-table th\{[^}]*\}", css)
    assert head and "font-weight:800" in head.group(0), "머리글은 굵게"
    assert "color:#2f3a46" in head.group(0), "머리글은 진하게"
    assert "nth-child(even)" in screen, "표 줄무늬 — 종이 장부의 괘선"


def test_메뉴명은_개인별_매출실적이다():
    """화면 제목과 메뉴명을 같게 (2026-08-09 사용자 확정) — 다르면 같은
    화면인지 헷갈린다."""
    context = (ROOT / "desktop" / "ui" / "context.js").read_text(encoding="utf-8")
    menu = context[context.index("const A10_MENU"):context.index("function a10MenuActive")]
    assert "'개인별 매출실적'" in menu
    assert "'내 매출실적'" not in menu


# 공개 범위 테스트(test_개인별_매출실적_공개_범위는_…)는 옮겨 오지 않았다.
# app.services.access_policy 를 부르는데 그 모듈은 feature/permission-management
# 에만 있다. 권한 브랜치가 main 에 들어올 때 그 브랜치가 자기 테스트로 지킨다.


def test_공동_후보만_원장에_묻는다():
    """정산은 지분표를 고치지 않는다(실측: 24~25년 1,872건 전부 공동계정 그대로).
    확정이 남는 유일한 경로가 배분 원장이라, 공동이 나올 수 있는 건에만 묻는다."""
    rows = [
        _row("고세욱", 100.0, "single1"),          # 순수 단독 — 후보 아님
        _row("공(고세욱)", 100.0, "joint1"),        # 칸 공동 표기
        _row("조근렬,강무진", 100.0, "multi1"),     # 칸 다중, 지분 없음
        _row("윤도,공(황인석)", 100.0, "ghost1"),   # 지분표가 공동계정 포함
    ]
    alloc = {"ghost1": {"윤도": 100.0, "공(황인석)": 100.0}}
    got = my_sales._joint_candidates(rows, alloc)
    assert got == ["ghost1", "joint1", "multi1"]


def test_원장_실명_확정이_있으면_원장이_정본이다():
    """실측 사례(01-2401-3-0217): 지분표는 '윤도 50/공(황인석) 50'인데 회사가
    원장에 확정한 배분은 '윤도 100'이다. 확정이 있으면 지분표를 덮는다 —
    '배분되면 개인에게 들어간다'가 이 폴백으로 실제 데이터에서 성립한다."""
    alloc = {"d1": {"윤도": 100.0, "공(황인석)": 100.0}}
    merged = {**alloc, "d1": {"윤도": 2496600.0}}   # _with_ledger_settlement 결과 모양
    got = my_sales._attribute(_row("윤도,공(황인석)", 1000.0), merged)
    assert got == [("윤도", 1000.0, "single")], "확정 후엔 공동 대기가 남지 않는다"

    # 확정이 없으면 종전대로: 윤도 확정 절반 + 황인석 공동 대기 절반
    before = my_sales._attribute(_row("윤도,공(황인석)", 1000.0), alloc)
    assert ("윤도", 500.0, "single") in before
    assert ("황인석", 500.0, "joint") in before


def test_식은_관계는_AI_분석에서만_나온다():
    """2026-08-10 사용자 확정: 발주처 카드의 상시 문구를 떼고 AI 분석으로 옮겼다.
    데이터(customers.gone)는 계속 내려오고 — AI 사실표가 먹는다 — 프롬프트가
    ⑤ 불릿을 필수로 강제한다(flash-lite 가 한 번 빼먹은 전적이 있다)."""
    script = SCRIPT.read_text(encoding="utf-8")
    assert "cl-gone" not in script, "카드 상시 표시는 제거됐다"
    service = SERVICE.read_text(encoding="utf-8")
    assert "'끊긴 거래' 는 사실표에 '식은 관계'가 있으면 **반드시**" in service
    assert '"gone":' in service or "gone" in service  # 페이로드는 유지


# ── 전년 동기 표시 — 틱 하나 → 뒤에 깐 회색 띠 (2026-08-10 확정) ────────────
STYLE = ROOT / "desktop" / "ui" / "my-sales.css"


def test_전년은_틱이_아니라_아랫줄_막대다():
    """3px 세로 틱은 세 경우에서 깨졌다 — 전년<올해면 파란 막대 안에 떨어져
    흠집으로 보이고, 전년이 없으면 틱도 없어 '신규'와 구분이 안 되며,
    올해 0·전년만인 행은 막대 없이 틱만 남았다."""
    css = STYLE.read_text(encoding="utf-8")
    rule = css.split(".cl-prev{")[1].split("}")[0]
    assert "width:3px" not in rule, "전년이 다시 틱으로 돌아갔다"
    assert "left:0" in rule, "두 줄은 같은 원점에서 서야 길이로 비교된다"
    assert "bottom:0" in rule, "전년은 아랫줄이다"


def test_두_줄의_두께가_같다():
    """9/5 로 나눴더니 잉크 면적이 길이와 어긋나, 안진회계법인이
    올해 1.60억 < 전년 1.72억 인데 올해가 1.86배 커 보였다(실측)."""
    css = STYLE.read_text(encoding="utf-8")
    cur = css.split(".cl-bar{")[1].split("}")[0]
    prev = css.split(".cl-prev{")[1].split("}")[0]
    assert "height:6px" in cur and "height:6px" in prev


def test_전년_회색은_트랙과_3대1을_넘긴다():
    """비텍스트 최소 대비(WCAG 1.4.11)가 3:1 이다. 실측 —
    #5f6b7c 4.99:1 · #93a2b7 2.39:1 · #c3cdd9 1.48:1 · 트랙 #f3f6f9 기준."""
    css = STYLE.read_text(encoding="utf-8")
    rule = css.split(".cl-prev{")[1].split("}")[0]
    assert "#5f6b7c" in rule
    for faint in ("#93a2b7", "#c3cdd9", "#aebbc9", "#d3dde8"):
        assert faint not in rule, f"{faint} 은 아랫줄이 안 보인다"


def test_값이_0이면_막대를_안_그린다():
    """최소 폭을 주면 '올해 0'이 실제 52만원짜리 행(물건종류 '기계기구')보다
    길어져 길이 채널에서 순위가 뒤집힌다."""
    script = SCRIPT.read_text(encoding="utf-8")
    body = script.split("function clTrack(")[1].split("\n}")[0]
    assert "prev>0?" in body and "cur>0?" in body
    assert "Math.max(" not in body, "0 에 최소 폭을 다시 먹였다"


def test_전년이_없는_두_경우를_배지가_가른다():
    """띠가 없으면 '신규'와 '올해 없음'이 같은 그림이 된다 — 틱이 깨지던 자리."""
    script = SCRIPT.read_text(encoding="utf-8")
    assert "function prevNote(" in script
    assert "badge-new" in script and "badge-gone" in script
    assert ".badge-gone{" in STYLE.read_text(encoding="utf-8")


def test_범례가_띠를_설명한다():
    """틱 범례(tick-key)는 '작대기가 전년 위치'라는 걸 못 읽혔다."""
    script = SCRIPT.read_text(encoding="utf-8")
    assert "tick-key" not in script
    assert script.count('<i class="prev-key"></i>') == 2   # 매출·거래처 탭
    assert ".prev-key{" in STYLE.read_text(encoding="utf-8")


# ── 소재지는 따로 묻는다 (2026-08-11) ─────────────────────────────────────
def test_소재지는_본문_질의에서_뺀다():
    """원장 apw_masterex 는 테이블이 아니라 **뷰**이고 Address 는 그 안에서
    스칼라 UDF(dbo.fnBun)로 조립하는 계산 열이다. 같이 물으면 질의가 무너진다.

    실측(본사 2026-01~08, 두 창 8,478건) — 조인만 2.55초 · +Manager 3.97초 ·
    +LCategory 2.78초 · +CustName 2.35초 · **+Address 38.62초**.
    """
    service = SERVICE.read_text(encoding="utf-8")
    body = service[service.index("_ROWS_SQL = "):]
    body = body[: body.index('"""', body.index('"""') + 3)]
    # 주석에는 나온다(왜 뺐는지 적어 두었다) — SQL 줄만 본다.
    sql = chr(10).join(
        line for line in body.splitlines() if not line.strip().startswith("--")
    )
    assert "m.Address" not in sql, "소재지를 본문 질의에 되돌리지 말 것"
    assert "def _addresses(" in service


def test_소재지는_있는_건만_덩어리로_묻는다():
    """원장에 **없는** 번호를 섞어 물으면 계획이 무너진다 — 실측 282개를 물어
    0건을 돌려주는 데 21초. 전사 조회에는 감정서가 아닌 관리번호(등본 발급
    수수료 등 400xxxxxx)가 섞이므로 in_ledger 로 먼저 거른다.

    덩어리 크기도 못 박는다 — 100건 0.16초 · 800건 0.90초 · 2,000건 33.78초 로
    2,000 근처에서 뷰 전체 훑기로 넘어간다. 그 안에서 200×4줄 동시가 가장
    빨랐다(800건 기준 400직렬 939ms · 800한번 752ms · 400×2 562ms ·
    **200×4 325ms** · 100×4 335ms, 결과는 다섯 방식 모두 동일).
    """
    service = SERVICE.read_text(encoding="utf-8")
    assert "_ADDR_CHUNK = 200" in service and "_ADDR_WORKERS = 4" in service
    # 스레드마다 제 세션을 열어야 한다 — 세션은 스레드 안전하지 않다.
    assert "def _in_session(" in service
    assert "in_ledger" in service
    block = service[service.index("    recent = _recent("):]
    block = block[: block.index("return {")]
    assert "in_ledger" in block, "원장에 없는 번호를 걸러야 한다"


def test_원장_조인은_LOOP_을_못박는다():
    """옵티마이저는 해시 조인을 골라 뷰 73만 행을 통째로 만든 뒤 8천 행에
    붙인다. 실측 — 본사 8개월 자동 5.10초 → LOOP 0.35초.

    뒤집히는 지점은 전사 5년(323,884행, 자동 7.14 → LOOP 12.52)인데 이 화면은
    기간을 연도 하나로만 고르므로(당해+전년=최대 2년) 거기 닿지 않는다.
    기간 선택을 여러 해로 넓히면 이 힌트를 다시 재야 한다.
    """
    service = SERVICE.read_text(encoding="utf-8")
    body = service[service.index("_ROWS_SQL = "):]
    body = body[: body.index('"""', body.index('"""') + 3)]
    assert "LEFT OUTER LOOP JOIN" in body


def test_전체_모드는_배분표를_아예_안_읽는다():
    """배분표는 커버리지 판정(_attribute 가 빈 목록인가)에만 쓰이는데,
    _multi_docs 가 **유치자 칸에 이름이 둘 이상인 건만** 묻는다 — 즉 배분표에
    든 건은 이미 이름이 있다. 그래서 배분표가 있든 없든 '이름이 하나도 없는 건'
    집합이 같다. 실측으로도 같다(본사 2026 미귀속 649,613,680원 · 3.56%, 원 단위 동일).
    """
    service = SERVICE.read_text(encoding="utf-8")
    block = service[service.index("    alloc: "):]
    block = block[: block.index("def mine(")]
    assert "{} if whole" in block


def test_화면은_세_요청을_나란히_던진다():
    """대시보드·연도별·목록은 서로의 결과를 안 쓴다. 직렬로 두면 개인 기준
    1.9초(연도별)가 그대로 쌓인다."""
    script = SCRIPT.read_text(encoding="utf-8")
    body = script[script.index("async function loadAll("):]
    body = body[: body.index(chr(10) + "}")]
    assert "Promise.all([loadAppraisers(), loadDashboard(force), loadYearly(force)])" in body
    assert "await loadAppraisers();" not in body, "직렬로 되돌리지 말 것"


def test_읽기는_교착으로_끊기면_다시_한다():
    """원장(apworksdw)에는 APWorks 가 지금도 쓰고 있다. 순수 읽기라도 잠금
    순서가 엇갈리면 SQL Server 가 우리를 **교착 희생자**로 골라 끊는다
    (SQLSTATE 40001 · 오류 1205). 실제로 났다 — 목록·대시보드·연도별을 나란히
    던지자 두 건이 500 으로 떨어졌다. 읽기 전용이라 그냥 다시 하면 된다.
    """
    service = SERVICE.read_text(encoding="utf-8")
    assert "def _exec(" in service and "_is_deadlock" in service
    assert "40001" in service and "(1205)" in service
    # 삼키고 넘어가면 안 된다 — 가변비 한 달이 조용히 0 원이 된다.
    vc = service[service.index("def _vc_one_month("):]
    vc = vc[: vc.index("# 달끼리는")]
    assert "_exec(" in vc


def test_상여_가변비를_두_번_던지지_않는다():
    """프리페치가 도는 중에 탭을 누르면 LATE[kind] 가 아직 null 이라
    renderMonths 가 loadLate 를 또 부른다 — 12초짜리 계산이 두 벌 돈다.
    키에 대상을 넣어야 한다: 사람을 바꾸면 새 요청은 막히면 안 된다."""
    script = SCRIPT.read_text(encoding="utf-8")
    body = script[script.index("async function loadLate("):]
    body = body[: body.index(chr(10) + "}")]
    assert "if(INFLIGHT[flight])return;" in body
    # 키에 대상뿐 아니라 **기간·지사까지** 넣어야 한다 — 이름만 넣으면 같은
    # 사람의 다른 기간 요청이 '이미 가는 중' 으로 오해받아 아예 안 나간다.
    assert "${kind}|${at}|" in body, "대상까지 키에 넣어야 한다"
    for part in ("officeCode", "dateFrom", "dateTo"):
        assert part in body.split("const flight=")[1].split(";")[0], part
    assert "delete INFLIGHT[flight]" in body, "끝나면 반드시 풀어야 한다"


def test_실적자_목록은_전용_질의를_쓴다():
    """대시보드의 _ROWS_SQL 을 빌려 쓰면 이 함수가 안 쓰는 것을 잔뜩 들고 온다 —
    거래처·물건·업무 이름, 미수 요약표 조인, 그리고 **전년 창까지**(prev 를 안
    넘기면 같은 창을 두 번 긁도록 만들어져 있어 5,301건이 10,602건이 된다).
    실측 — _ROWS_SQL 재사용 1,049ms · 전용 질의 296ms(이름까지 440ms).
    결과는 같다(본사 2026 82명, 명단·순서 완전 일치).
    """
    service = SERVICE.read_text(encoding="utf-8")
    assert "_NAMES_SQL = " in service
    body = service[service.index("def appraiser_names("):]
    body = body[: body.index(chr(10) + chr(10) + "def ")]
    assert "_NAMES_SQL" in body and "_fetch_rows(" not in body


def test_연결_풀은_화면_하나보다_커야_한다():
    """개인별 매출실적 한 화면이 최대 16개(대시보드1+소재지4 · 목록1 · 연도별1 ·
    가변비1+4 · 상여1+3)를 쓴다. 기본값 5+10=15 로는 한 사람이 화면 하나 여는
    데 바닥나고, **화면 16개가 이 풀 하나를 같이 쓰므로** 다른 메뉴까지 죽는다.
    """
    from app.database import _POOL_OVERFLOW, _POOL_SIZE

    worst = 1 + my_sales._ADDR_WORKERS + 1 + 1 + 1 + my_sales._VC_WORKERS         + 1 + my_sales._BONUS_WORKERS
    assert _POOL_SIZE + _POOL_OVERFLOW >= worst * 3, (
        f"화면 하나가 최대 {worst}개를 쓴다 — 동시 3명은 버텨야 한다")


def test_상여_한_달은_사람과_무관해서_한_번만_계산한다():
    """bonus_report(db, year, month) 는 그 달의 **전 직원**을 계산하고 우리는
    거기서 한 사람만 골라 낸다 — 두 사람이 같은 기간을 열면 똑같은 계산이 두 벌
    돈다. 부하 실측(동시 5명·같은 8개월): 상여 20초 → 52초.

    60초짜리 기억으로 겹침을 없앤다. **단일 비행**이 핵심이다 — 같은 달을 이미
    계산 중이면 기다렸다 그 결과를 쓴다. 안 그러면 다섯이 동시에 캐시를 놓치고
    다섯 벌이 그대로 돈다.

    이건 표가 아니라 프로세스 안 기억이다: 재기동하면 사라지고 산식이 바뀌면
    60초 뒤 저절로 따라간다(APW_IW_MONGABUNBI 사고와 성격이 다르다).
    """
    service = SERVICE.read_text(encoding="utf-8")
    assert "_BONUS_TTL = 60.0" in service
    block = service[service.index("def _bonus_report_memo("):]
    block = block[: block.index(chr(10) + chr(10) + "def ")]
    assert "with lock:" in block, "단일 비행이 없으면 동시 요청이 그대로 통과한다"
    assert block.count("time.monotonic() - hit[0] < _BONUS_TTL") == 2, (
        "자물쇠를 잡은 뒤 한 번 더 봐야 한다")
    # 상여 화면(bonus.py)은 이 기억을 안 쓴다 — 확정 숫자는 늘 새로 계산한다.
    bonus = (ROOT / "app" / "services" / "bonus.py").read_text(encoding="utf-8")
    assert "_bonus_report_memo" not in bonus


def test_상여_기억은_사람을_섞지_않는다():
    """기억은 '그 달의 전 직원 보고서' 이고, 사람은 그 뒤에 고른다.
    사람을 키에 넣지 않는 것이 이 최적화의 전제다."""
    service = SERVICE.read_text(encoding="utf-8")
    block = service[service.index("def _bonus_report_memo("):]
    block = block[: block.index(chr(10) + chr(10) + "def ")]
    assert "key = (year, month)" in block and "emp_name" not in block


# ── 전체 추이 스위치 (2026-08-11 요청) ─────────────────────────────────────
def test_추이_차트에서_가변비를_뺐다():
    """2026-08-13 요청 — "차트에는 가변비를 아예 제거". 가변비는 가변비 탭의
    월별 표에서만 본다. 축이 달라 매출 옆에 그리면 오독을 부르고, 부르는 데
    10초가 넘어 차트가 그 값을 물 이유도 없다.

    **상여도 여기 없다** — 한 번 얹어 봤다가 뺐다(2026-08-11 같은 날 요청).
    """
    script = SCRIPT.read_text(encoding="utf-8")
    for gone in ("SERIES", "box('variable'", "ln-vc", "gVc", "C_VC",
                 "vc-axis", "체크하면 불러옵니다"):
        assert gone not in script, f"가변비를 추이 차트에 되살리지 말 것: {gone}"
    # 그릴 것이 매출 하나뿐이라 켜고 끄는 스위치도 뺐다 (2026-08-18 요청) —
    # 끄면 빈 판만 남으므로 켤 것도 끌 것도 없다. 범례는 색 이름표로 남는다.
    assert 'data-series=' not in script, "체크박스를 되살리지 말 것"
    assert "function paintTrendLegend(" in script and "key key-line" in script
    for gone in ("C_BONUS", "bar-bonus", "showBn", "SERIES.bonus"):
        assert gone not in script, f"상여를 추이 차트에 되살리지 말 것: {gone}"
    # 가변비 **탭**은 남아 있다 — 탭을 열 때 부른다(renderMonths → loadLate).
    assert "renderMonths('variable',body)" in script


def test_상여_가변비를_미리_받아_탭이_즉시_뜬다():
    """2026-08-16 요청 — "바로 조회". 둘 다 사람·달마다 원장 프로시저를 도는
    일이라 실측 10~11초다. 탭을 누른 뒤에 부르면 그 시간을 사람이 통째로
    기다리므로, 화면이 다 그려진 뒤 백그라운드로 미리 받는다.

    서버도 같은 (사람·기간)을 캐시하니(_recent_vc·_recent_bonus) 되돌아올 때는
    아예 안 돈다. 전체 보기는 loadLate 가 스스로 거른다(isAll 조기 반환)."""
    script = SCRIPT.read_text(encoding="utf-8")
    body = script[script.index("function render(data){"):]
    body = body[: body.index(chr(10) + "}")]
    assert "loadLate('variable')" in body and "loadLate('bonus')" in body
    assert "setTimeout(()=>loadLate" not in script
    # 전체 보기 가드는 loadLate 안에 있어야 한다 — 부르는 쪽마다 적으면 샌다.
    late = script[script.index("async function loadLate("):]
    assert "if(isAll())return;" in late[: late.index(chr(10) + "}")]


def test_상여_가변비는_같은_기간이면_다시_안_돈다():
    """재조회 캐시 (2026-08-16). TTL 이 갈리는 건 원천의 성질 때문이다 —
    가변비는 사람이 당일에 고치는 값이 아니라 넉넉히, 상여는 조정 편집이
    있어 짧게. 결측을 정답인 양 굳히지 않도록 실패분은 적어 두지 않는다."""
    service = SERVICE.read_text(encoding="utf-8")
    assert "_VC_CACHE_TTL = 600.0" in service
    assert "_BONUS_CACHE_TTL = 180.0" in service
    vc = service[service.index("def variable_costs("):]
    vc = vc[: vc.index(chr(10) + "def ")]
    assert "_recall(_recent_vc, cache_key, _VC_CACHE_TTL)" in vc
    # 한 달이라도 프로시저가 실패했으면 캐시에 넣지 않는다.
    assert 'if all(m["found"] for m in out):' in vc
    bn = service[service.index("def bonus_months("):]   # 파일의 마지막 함수다
    assert "_recall(_recent_bonus, cache_key, _BONUS_CACHE_TTL)" in bn
    # 상여는 지급 0원인 달이 정상이라 found 로 판정하면 안 된다 — 전 달 실패만 거른다.
    assert "if paid:" in bn
    # 미리 받기가 실패했거나 아직 안 왔을 때, 탭을 누르면 그때 부르는 길도
    # 남아 있어야 한다 — 프리로드만 믿으면 실패 시 영영 빈 표가 된다.
    script = SCRIPT.read_text(encoding="utf-8")
    months = script[script.index("function renderMonths("):]
    months = months[: months.index(chr(10) + "}")]
    assert "loadLate(kind);" in months


def test_늦게_온_값은_제_탭에만_실린다():
    """가변비·상여가 도착하면 그 탭의 월별 표를 다시 그린다. 추이 차트는
    다시 안 그린다 — 둘 다 차트에서 뺐다(2026-08-13)."""
    script = SCRIPT.read_text(encoding="utf-8")
    block = script[script.index("async function loadLate("):]
    block = block[: block.index(chr(10) + "}")]
    assert "if(TAB===kind)renderMonths(kind,$('tabBody'));" in block
    assert "renderMonthly" not in block


# ── AI 분석 — 속도·내용·가독성 (2026-08-11 요청) ───────────────────────────
def test_AI분석은_방금_계산한_것을_다시_계산하지_않는다():
    """7.72초 중 5.32초가 대시보드(3.1)·연도별(2.3) 재계산이었다 — 모델은
    2.4초뿐이다(실측). 화면이 그 둘을 부를 때 적어 두고 여기서 읽는다.

    **조회 버튼은 영향이 없다**: /dashboard 는 언제나 새로 계산하고 적어 두기만
    한다. 읽기만 하는 쪽은 analyze 다 — '조회했는데 옛 숫자' 가 생길 수 없다.
    """
    service = SERVICE.read_text(encoding="utf-8")
    router = (ROOT / "app" / "routers" / "my_sales.py").read_text(encoding="utf-8")
    assert "def remember_dashboard(" in service and "def remember_years(" in service
    assert "_recall(_recent_dash" in service and "_recall(_recent_years" in service
    # 라우터는 적어 두기만 한다(읽지 않는다).
    assert "my_sales.remember_dashboard(" in router
    assert "my_sales.remember_years(" in router
    assert "_recall" not in router
    # 대시보드 엔드포인트는 언제나 새로 계산한다.
    block = router[router.index('@router.get("/dashboard"'):]
    block = block[: block.index('@router.get("/analyze"')]
    assert "my_sales.dashboard(" in block


def test_기억이_없으면_둘을_나란히_부른다():
    """줄 세우면 5.3초, 나란히면 3.1초다."""
    service = SERVICE.read_text(encoding="utf-8")
    block = service[service.index("def analyze_dashboard("):]
    block = block[: block.index("    facts = briefing_facts(")]
    assert "ThreadPoolExecutor(max_workers=2)" in block


def test_사실표에_미수가_들어간다():
    """화면에 탭이 있는데 사실표에는 통째로 빠져 있었다(2026-08-11 제보)."""
    service = SERVICE.read_text(encoding="utf-8")
    block = service[service.index("def briefing_facts("):]
    block = block[: block.index("def analyze_dashboard(")]
    # 2026-08-13 개편 — 미수 축은 물건·업무종류가 아니라 거래처다.
    assert "미수 잔액:" in block and "미수 거래처별:" in block
    # **전체 미수율은 주지 않는다** — 화면에 없는 숫자이고 축마다 분모가 다르다
    # (실측 안창덕 2026: 물건종류로 54% · 업무종류로 64%). 주석에는 그 이유가
    # 적혀 있으니 **코드 줄**에만 없어야 한다.
    code = chr(10).join(
        line for line in block.splitlines() if not line.lstrip().startswith("#")
    )
    assert "미수율" not in code


def test_AI_글은_구획으로_나눠_그린다():
    """'제목|내용' 으로 받아 왼쪽에 제목을 줄맞춰 세운다 — 훑기 쉽게.
    **여전히 textContent 로만 붓는다**: 모델 출력은 신뢰하지 않는 데이터다."""
    script = SCRIPT.read_text(encoding="utf-8")
    block = script[script.index("function paintAnalysis("):]
    block = block[: block.index(chr(10) + "}")]
    assert "createElement" in block and "textContent" in block
    assert "innerHTML" not in block, "모델 글을 HTML 로 넣지 말 것"
    # 형식을 어긴 줄(세로줄 없음)도 버리지 않고 그대로 한 줄로 둔다.
    assert "cut>0?line.slice(cut+1).trim():line" in block


def test_켜진_탭은_AI_버튼과_같은_색이다():
    """이 화면에서 '지금 눌린 것' 은 전부 같은 색이어야 눈이 덜 헤맨다
    (2026-08-11 요청)."""
    css = STYLE.read_text(encoding="utf-8")
    tab = css.split(".ms-tabs button.on{")[1].split("}")[0]
    ai = css.split("#aiButton{")[1].split("}")[0]
    assert "linear-gradient(120deg,#5b5bd6,#2563eb)" in tab
    assert "linear-gradient(120deg,#5b5bd6,#2563eb)" in ai


# ── 배포 전 리뷰에서 나온 것들 (2026-08-11) ────────────────────────────────
def test_상여_기억_정리는_순회_중_삽입을_막는다():
    """정리 루프가 _bonus_memo 를 순회하는 동안 다른 스레드가 새 달을 넣으면
    '순회 중 크기 변경' 으로 터진다. 목록을 먼저 뜨고, 쓰기도 같은 자물쇠 안에서."""
    service = SERVICE.read_text(encoding="utf-8")
    block = service[service.index("def _bonus_report_memo("):]
    block = block[: block.index(chr(10) + chr(10) + "def ")]
    assert "list(_bonus_memo.items())" in block, "순회 전에 목록을 떠야 한다"
    assert block.count("with _bonus_guard:") == 2, "쓰기도 같은 자물쇠 안에서"


def test_LATE_는_그리기_전에_비운다():
    """순서가 반대면 새 대상의 첫 그림에 직전 대상의 가변비가 그대로 실린다."""
    script = SCRIPT.read_text(encoding="utf-8")
    body = script[script.index("function render(data){"):]
    body = body[: body.index(chr(10) + "}")]
    assert body.index("LATE={bonus:null,variable:null}") < body.index("renderMonthly(data)")


def test_늦게_온_응답은_새_화면을_덮지_않는다():
    """A 를 고르고 곧바로 B 를 고르면 A 의 늦은 응답이 B 화면을 덮었다."""
    script = SCRIPT.read_text(encoding="utf-8")
    assert "let GEN=0;" in script
    for fn in ("async function loadDashboard(", "async function loadYearly("):
        body = script[script.index(fn):]
        body = body[: body.index(chr(10) + "}")]
        assert "gen!==GEN" in body, fn


def test_AI_글은_제목이_길어도_글자를_안_버린다():
    """종전에는 제목이 8자를 넘으면 그 줄의 앞부분이 통째로 사라졌다."""
    script = SCRIPT.read_text(encoding="utf-8")
    block = script[script.index("function paintAnalysis("):]
    block = block[: block.index(chr(10) + "}")]
    assert "if(head.length>8){ body=`${head} ${body}`; head=''; }" in block


def test_AI_복사는_원문을_쓴다():
    """화면은 줄마다 div 라 textContent 로 긁으면 줄바꿈 없이 다 붙는다."""
    script = SCRIPT.read_text(encoding="utf-8")
    assert "const text=(aiCache&&aiCache.text)||" in script


def test_실적이_없어도_스위치는_남는다():
    """범례를 통째로 지우면 가변비를 켤 수단이 사라진다(기본값이 꺼짐이라)."""
    script = SCRIPT.read_text(encoding="utf-8")
    assert "function paintTrendLegend(" in script
    assert "$('trendLegend').innerHTML='';" not in script


def test_미수_내역은_발송_기준이다():
    """2026-08-13 사용자 확정 — "감정서 발송되면 미수". 종전에는 당기 매출
    전표가 있는 건만 걸러서(recent 재활용) 발송했는데 전표도 입금도 없는 건이
    아예 안 보였다. 이제 서버가 발송일 기준으로 따로 준다(receivable_rows)."""
    script = SCRIPT.read_text(encoding="utf-8")
    block = script[script.index("function renderTable(data){"):]
    block = block[: block.index(chr(10) + "}")]
    assert "data.receivable_rows" in block
    # 옛 방식(같은 행에서 걸러내기)으로 되돌리지 말 것.
    assert "all.filter(r=>(r.outstanding||0)>0)" not in block
    # 잘림 안내는 미수 쪽도 제 총계로 말한다.
    assert "receivable_rows_truncated" in block
    assert "발송일" in block


# ── 거래처별현황·소속 순위 개편 (2026-08-13 요청) ───────────────────────────


def test_순위는_같은_소속끼리만_겨룬다():
    """주주 계열은 주주끼리, 소속은 소속끼리, 수습은 수습끼리 (2026-08-13).

    group_names 를 주면 그 사람들(과 본인)만 모수다. 그룹을 모르면 안 넘기면
    되고, 그때는 종전처럼 전체 기준 — 순위 카드가 사라지지 않는다.
    """
    rows = [
        _row("주주1", 300.0, "a"), _row("소속1", 500.0, "b"),
        _row("수습1", 100.0, "c"),
    ]
    r = my_sales._ranking(rows, {}, "주주1", None, {"주주1"}, "주주평가사")
    assert r["rank"] == 1 and r["total"] == 1
    assert r["group_label"] == "주주평가사"
    r2 = my_sales._ranking(rows, {}, "주주1")
    assert r2["total"] == 3 and r2["group_label"] is None
    # 본사 명부에 없는 사람은 등수를 아예 안 준다 — 실측(2026-08-13): 명부 밖
    # 재직 실적자 2명은 둘 다 대전세종지사 평가사(본사 건을 유치했을 뿐)였다.
    service = SERVICE.read_text(encoding="utf-8")
    assert "None if whole or no_rank else _ranking(" in service


def test_소속_코드는_실측_그대로다():
    """Seat_userinfo.Dept_Nm 코드 ↔ apw_dept 명칭 실명 대조(2026-08-13)로 확정.
    mp(부회장·이사급)·gam(감사)은 코드표에 없지만 직급 실측으로 주주 계열이다."""
    assert my_sales._RANK_GROUPS["주주평가사"] == frozenset(
        {"jip", "sim", "ju", "yj", "mp", "gam"})
    assert my_sales._RANK_GROUPS["소속평가사"] == frozenset({"so"})
    assert my_sales._RANK_GROUPS["수습평가사"] == frozenset({"su"})


def test_미수는_발송되면_잡힌다():
    """전표도 입금도 없어도 **발송됐으면 미수다** (2026-08-13 사용자 확정).
    종전에는 당기 전표 있는 건만 걸러 무전표 미수가 아예 안 보였다.
    기준액은 미수금현황과 같은 식: max(전표 청구액, 발송건 산정액) − 입금."""
    rows = [{
        "doc_id": "01-2608-3-0001", "send_date": date(2026, 8, 1),
        "customer_name": "테스트은행", "manager": "고세욱",
        "work_type": "담보", "category": "토지",
        "assessed": 1_100_000.0, "billed": 0.0, "received": 0.0,
    }]
    recv, details = my_sales._sent_receivable(rows, "고세욱", {}, False)
    assert details and details[0]["outstanding"] == 1_100_000.0
    assert details[0]["date"] == "2026-08-01"
    assert recv["customers"][0]["name"] == "테스트은행"
    # 완납되면 미수 목록에서 사라진다.
    rows[0]["received"] = 1_100_000.0
    recv2, details2 = my_sales._sent_receivable(rows, "고세욱", {}, False)
    assert not details2 and recv2["total"] == 0


def test_접수는_참여하면_1건이다():
    """건수 축은 지분으로 쪼개지 않는다 — 0.33건짜리 접수는 없다.
    전체 모드(emp_name=None)는 전 건을 센다."""
    rows = [
        {"doc_id": "d1", "customer_name": "A은행", "manager": "고세욱,김철수",
         "bucket": "cur"},
        {"doc_id": "d2", "customer_name": "A은행", "manager": "김철수",
         "bucket": "cur"},
    ]
    alloc = {"d1": {"고세욱": 50.0, "김철수": 50.0}}
    got = my_sales._intake_by_customer(rows, "고세욱", alloc)
    assert got["total"] == 1 and got["top"][0]["count"] == 1
    assert my_sales._intake_by_customer(rows, None, {})["total"] == 2


def test_미수율_분모에는_완납_건도_들어간다():
    """미수율 = 미수액 ÷ 그 거래처의 당기 발송 기준액 **전체**다. 미납 건만
    분모에 넣으면 부분 입금이 없는 한 미수율이 항상 100%로 떠서 결제 잘 하는
    거래처와 안 하는 거래처가 구분이 안 된다 (2026-08-14 검수에서 잡힌 회귀 —
    종전 미수 탭은 완납 건도 분모에 넣었다)."""
    base = {"send_date": date(2026, 8, 1), "customer_name": "테스트은행",
            "manager": "고세욱", "work_type": "담보", "category": "토지"}
    rows = [
        {**base, "doc_id": "01-2608-3-0001", "assessed": 10_000_000.0,
         "billed": 0.0, "received": 10_000_000.0},   # 완납
        {**base, "doc_id": "01-2608-3-0002", "assessed": 10_000_000.0,
         "billed": 0.0, "received": 0.0},            # 전액 미납
    ]
    recv, details = my_sales._sent_receivable(rows, "고세욱", {}, False)
    top = recv["customers"][0]
    assert top["amount"] == 10_000_000.0
    assert top["gross"] == 20_000_000.0   # 완납 건도 분모에 — 미수율 50%
    assert top["count"] == 1              # 미수 건수는 미납만
    assert len(details) == 1
    # 완납만 있는 거래처는 목록에 아예 안 뜬다.
    only_paid = [{**base, "doc_id": "01-2608-3-0003",
                  "assessed": 5_000_000.0, "billed": 0.0,
                  "received": 5_000_000.0}]
    recv2, _ = my_sales._sent_receivable(only_paid, "고세욱", {}, False)
    assert recv2["customers"] == []


def test_인쇄는_미수_내역_길이도_본다():
    """미수 내역은 별도 배열(receivable_rows)이라 recent 보다 길 수 있다 —
    recent 길이만 보면 인쇄가 중간에서 소리 없이 끊긴다 (2026-08-14 검수,
    실측 82명 중 4명이 미수 내역이 매출 내역보다 길었다)."""
    script = SCRIPT.read_text(encoding="utf-8")
    block = script[script.index("window.addEventListener('beforeprint'"):]
    block = block[: block.index("});") + 3]
    assert "latest.receivable_rows" in block


# ── 가변비 프로시저 교체 (2026-08-18) ──────────────────────────────────────


def test_가변비는_안분된_MonPung을_쓴다():
    """_Mon 은 유치자 칸을 정확일치로 걸어 공동(다인) 감정서를 한 건도 못 잡았다 —
    조근렬 2026-06 이 0원인데 상여는 같은 사람에게서 759,475원을 차감했다.
    _MonPung 은 부분일치로 쉼표 덩어리를 물고 지분표로 안분한 몫(AFPrice)을 준다.

    실측(2026-08-18, 본사 78명×2달): 2026-06 합계 +8.4%, 13명 증가·**0명 감소**,
    상여 대비 불일치 18명·2,127만 → 7명·240만.
    """
    service = SERVICE.read_text(encoding="utf-8")
    assert "SP_IW_S_TaskStats_MonPung :f_date, :manager" in service
    assert "SP_IW_S_TaskStats_Mon :f_date" not in service, "옛 프로시저로 되돌리지 말 것"
    # 안분 전 금액(Beprice)을 쓰면 공동 건이 참여자 수만큼 중복 계상된다.
    assert 'row.get("AFPrice")' in service
    assert 'row.get("Beprice")' not in service


def test_가변비_피벗은_금액을_잃지_않는다():
    """Gubun → 화면 항목 매핑. 인력 4항목의 Gubun 문자열은 원장
    APW_YJI_StandardPrice.Bigo 에서 오므로 거기서 이름을 고치면 매핑이 깨진다 —
    그때 금액이 조용히 사라지지 않도록 합계에는 살리고 경고를 남긴다."""
    service = SERVICE.read_text(encoding="utf-8")
    block = service[service.index("def _vc_pivot("):]
    block = block[: block.index(chr(10) + "def ")]
    # 합계는 매핑 성공 여부와 무관하게 먼저 더한다.
    assert "total += amount" in block
    assert block.index("total += amount") < block.index("label is None")
    assert "logger.warning(" in block and "매핑 안 되는 구분값" in block
    # 이름이 다른 여섯 개가 모두 매핑돼 있어야 한다.
    for gubun, label in (("수습남직원", "수습남"), ("비지오", "Visio"),
                         ("수습비지오", "수습 Visio"), ("KB탁상접수", "탁상접수 HF"),
                         ("KB탁상감정", "탁상감정 HF"), ("협회심사", "협회심사비")):
        assert f'"{gubun}": "{label}"' in service, gubun
    # 감정서경비는 한 덩어리로 와서 감정서번호 유무로 갈린다.
    assert '"감정서경비(문서있음)"' in block and '"감정서경비(문서없음)"' in block


def test_상세가_0건인_달은_상여와_대조한다():
    """_MonPung 의 '공(' 필터가 앵커되지 않아 '윤도,공(장재원)' 처럼 본인이 앞에
    있는 공동 표기를 통째로 버린다 — 윤도 2026-06 은 상세 0건인데 상여는
    2,280,025원을 잡는다. 값을 지어내지 않고 '상여에는 잡힌다'는 사실만 알린다."""
    service = SERVICE.read_text(encoding="utf-8")
    assert "def _vc_bonus_hint(" in service
    assert "APW_IW_MONGABUNBI" in service   # 상여 화면이 읽는 그 표
    body = service[service.index("def variable_costs("):]
    body = body[: body.index(chr(10) + "def ")]
    assert "empty_months" in body and 'month["bonus_only"] = hint' in body
    script = SCRIPT.read_text(encoding="utf-8")
    assert "m.bonus_only" in script, "화면이 그 사실을 보여줘야 한다"


def test_조회_실패와_0원인_달을_구분한다():
    """_vc_one_month 는 실패 None · 일 없음 [] · 상세 [...] 셋을 가른다.
    실패를 0원으로 뭉개면 화면이 '가변비가 없던 달' 과 구분하지 못하고,
    캐시가 그 결측을 10분 동안 정답인 양 굳힌다."""
    service = SERVICE.read_text(encoding="utf-8")
    one = service[service.index("def _vc_one_month("):]
    one = one[: one.index(chr(10) + "def ")]
    assert "return [dict(r) for r in rows]" in one and "return None" in one
    body = service[service.index("def variable_costs("):]
    body = body[: body.index(chr(10) + "def ")]
    assert 'if rows is None:' in body and '"found": False' in body
