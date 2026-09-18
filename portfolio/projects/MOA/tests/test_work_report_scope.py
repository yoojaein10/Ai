"""업무실적 화면 판정 — 컨설팅 비대상(요구4)·선례대상(요구3).

축은 협회 목적코드(PCODE)가 아니라 사내 업무 대분류(apw_masterex.LWorkinfo)다.
기간별 매출실적(sales_stats.CATEGORIES)·상여·데이터품질이 모두 이 컬럼을 쓰므로
화면 간 집계가 갈리지 않게 맞춘 것이다. (2026-08-06 사용자 확정)
"""

import pytest

from app.services.sales_stats import CATEGORIES
from app.services.work_report import (
    CONSULTING_FEE_LIMIT,
    CONSULTING_WORK,
    REDEVELOPMENT_WORK,
    is_government_customer,
)


def test_axis_matches_sales_stats_categories():
    """대분류 값이 매출실적 보고서의 고정 분류와 같은 문자열이어야 한다."""
    assert CONSULTING_WORK in CATEGORIES
    assert REDEVELOPMENT_WORK in CATEGORIES


def test_boundary_includes_exactly_ten_million():
    """경계는 '이하' — 정확히 1천만원은 대상이고 초과부터 비대상이다.

    근거: 재무팀 원본 ★26.04월업무실적보고 상반의 컨설팅 6건 중 3건이 정확히
    10,000,000원인데 파일에 들어 있다. 1천만원 초과 컨설팅은 03·04·05월 세 파일
    통틀어 0건이다. (2026-08-06 실파일 대조)
    """
    assert CONSULTING_FEE_LIMIT == 10_000_000

    def out_of_scope(work, susu):
        return work == CONSULTING_WORK and susu > CONSULTING_FEE_LIMIT

    assert out_of_scope(CONSULTING_WORK, 9_999_999) is False
    assert out_of_scope(CONSULTING_WORK, 10_000_000) is False  # 경계: 대상
    assert out_of_scope(CONSULTING_WORK, 10_000_001) is True
    # 실파일에서 확인된 값들
    assert out_of_scope(CONSULTING_WORK, 6_000_000) is False    # 01-2604-5-0052 파일O
    assert out_of_scope(CONSULTING_WORK, 47_500_000) is True    # 01-2511-5-0186 파일X
    assert out_of_scope(CONSULTING_WORK, 27_855_000) is True    # 01-2512-5-0189 파일X
    # 컨설팅이 아니면 금액과 무관하게 대상이다.
    assert out_of_scope("담보", 99_000_000) is False
    assert out_of_scope(REDEVELOPMENT_WORK, 50_000_000) is False


@pytest.mark.parametrize("name", [
    "부산광역시 수영구청장", "평창군수", "태백시장", "부천시청", "예산군수",
    "영등포구청장", "대구광역시 서구청", "광명시장",
])
def test_government_customers(name):
    assert is_government_customer(name) is True


@pytest.mark.parametrize("name", [
    "한남4재정비촉진구역주택재개발정비사업조합장",   # 조합
    "인천광역시 동구청장(○○재개발정비사업조합장)",  # 구청장+조합 혼재 → 조합으로 본다
    "(주)GS건설", "하나은행 노원역금융센터장", "",
    "수원시 화성사업소장",       # 끝단어가 관공서가 아니다
    "○○전통시장상인회",         # 재래시장 오탐
    None,
])
def test_not_government_customers(name):
    assert is_government_customer(name) is False


def _judge(work, cust, is_public):
    """build_kapa_rows 가 붙이는 선례 관련 키와 같은 판정."""
    return {
        "PRECEDENT": bool(is_public),
        "PRECEDENT_CANDIDATE": bool(
            not is_public
            and work == REDEVELOPMENT_WORK
            and is_government_customer(cust)
        ),
    }


def test_precedent_comes_from_is_public_not_our_guess():
    """선례 대상은 우리가 다시 판정하지 않는다 — APWorks 의 IsPublic 이 정본이다.

    실측: IsPublic='Y' 의 49.4% 가 KAB 전송됨, 'N' 은 0.2%. 즉 대상 여부는 이미
    사람이 정해 기록해 두고 있다. 우리 규칙(정비사업+시군구)은 그중 69.8% 만 맞힌다.
    """
    # 보상 건은 우리 규칙에 안 걸리지만 IsPublic 이 Y 면 선례 대상이다.
    assert _judge("보상", "평창군수", True)["PRECEDENT"] is True
    # 담보처럼 규칙과 무관한 업무도 IsPublic 이 정본이다.
    assert _judge("담보", "하나은행 노원역금융센터장", True)["PRECEDENT"] is True
    assert _judge(REDEVELOPMENT_WORK, "부산광역시 수영구청장", False)["PRECEDENT"] is False


def test_candidate_flags_only_rule_match_without_is_public():
    """규칙엔 맞는데 IsPublic 이 안 잡힌 건만 '확인 필요'로 띄운다."""
    # 정비사업 + 시군구 인데 IsPublic 이 없다 → 판정 누락 후보
    c = _judge(REDEVELOPMENT_WORK, "부산광역시 수영구청장", False)
    assert c["PRECEDENT_CANDIDATE"] is True

    # 이미 IsPublic='Y' 면 후보가 아니다(중복 표시 방지)
    assert _judge(REDEVELOPMENT_WORK, "부산광역시 수영구청장", True)["PRECEDENT_CANDIDATE"] is False
    # 정비사업이어도 조합 의뢰면 후보가 아니다(실측: 조합 16.7% vs 시군구 69.8%)
    assert _judge(REDEVELOPMENT_WORK, "번동1구역 가로주택정비사업조합장", False)["PRECEDENT_CANDIDATE"] is False
    # 시군구 의뢰여도 정비사업이 아니면 후보가 아니다
    assert _judge("보상", "평창군수", False)["PRECEDENT_CANDIDATE"] is False


def test_shared_population_function_exists_for_both_screens():
    """업무실적과 보수기준이 같은 모집단 함수를 쓴다 (2026-08-06 사용자 원칙).

    한쪽만 정비사업 선례 건을 보면 같은 반월인데 행수가 갈려 어느 화면을 믿을지
    알 수 없게 된다.
    """
    import inspect

    from app.services import fee_basis
    from app.services.work_report import select_doc_ids_with_precedent

    # 보수기준이 그 함수를 실제로 import 하고 호출까지 하는지
    assert fee_basis.select_doc_ids_with_precedent is select_doc_ids_with_precedent
    source = inspect.getsource(fee_basis.build_fee_basis_report)
    assert "select_doc_ids_with_precedent" in source, "보수기준이 공유 함수를 안 쓴다"


def test_shared_common_sql_is_untouched():
    """_COMMON 은 실파일 recall 회귀와 보수기준이 함께 기대는 문자열이다.

    정비사업 갈래를 넣느라 여기를 고치면 두 화면과 회귀가 한꺼번에 흔들린다.
    """
    from app.services.work_report import _COMMON

    assert "m.[Status] = '72'" in _COMMON, "발송완료 조건이 사라졌다"
    assert "m.Result <= '10'" in _COMMON
    assert "m.Report = 'Y'" in _COMMON
    assert "NOT IN ('81', '44')" in _COMMON
    assert "APW_REPAPP" in _COMMON, "중복보고 가드가 사라졌다"
    assert _COMMON.count("?") == 3, "바인드 개수가 바뀌면 호출부가 전부 어긋난다"


def test_precedent_sql_is_a_separate_branch():
    """정비사업 갈래는 _COMMON 을 재사용하지 않고 Status 조건도 없다."""
    import inspect

    from app.services import work_report

    src = inspect.getsource(work_report._select_redevelopment_docs)
    body = src.split('"""')[-1]                       # 독스트링 제거
    code = "\n".join(line.split("#")[0] for line in body.splitlines())  # 주석 제거

    assert "_COMMON" not in code, "_COMMON 을 재사용하면 공유 모집단이 흔들린다"
    # 발송완료 건은 기존 갈래가 자기 발송 반월에 이미 올린다. 여기서 또 올리면
    # 같은 건이 접수 반월에 한 번 더 떠서 교차 반월 중복이 된다(실측 2건).
    assert "<> '72'" in code, "발송완료 건까지 끌어오면 교차 반월 중복이 난다"
    assert "LWorkinfo" in code, "축은 협회 목적코드가 아니라 사내 대분류다"
    assert "ReceiptDate" in code, "미발송 건은 전례일이 없어 접수일로 반월을 잡는다"
    # 중복보고 가드와 나머지 필터는 그대로 복제해야 한다
    assert "APW_REPAPP" in code, "중복보고 가드를 빠뜨리면 이미 보고한 건이 또 뜬다"
    assert "Result <= '10'" in code and "Report = 'Y'" in code


def test_not_sent_rows_are_included_by_default():
    """발송 전 정비사업 건은 기본 체크(보고 대상)여야 한다.

    협회가 발송 전 상태로도 받는다고 확인됐다(2026-08-07 사용자). 기본 제외로 두면
    '발송 여부와 무관하게 보고한다'는 요구 자체가 무의미해진다. 대신 발송일·수수료가
    비어 있다는 사실은 요약줄 건수로 알린다.
    """
    from pathlib import Path

    js = (Path(__file__).parents[1] / "desktop" / "ui" / "work-report.js").read_text(
        encoding="utf-8"
    )
    body = js.split("function autoExcluded(row){", 1)[1].split("}", 1)[0]
    assert "NOT_SENT" not in body, "발송 전 건을 기본 제외하면 보고에서 빠진다"
    assert "NO_FEE" in body and "OUT_OF_SCOPE" in body, "기존 제외 사유가 사라졌다"
    # 대신 요약줄에는 반드시 건수가 뜬다 — 배지가 없으니 이게 유일한 안내다.
    assert "정비사업 발송전" in js


def test_population_version_invalidates_fee_basis_cache():
    """모집단이 바뀌면 보수기준 스냅숏 캐시를 버려야 한다."""
    from app.services.fee_basis import _rule_versions
    from app.services.work_report import POPULATION_VERSION

    assert _rule_versions().get("population_version") == POPULATION_VERSION


def test_excluded_purpose_codes_cover_both_branches():
    """제외 목적코드는 상수 한 곳에서만 나온다 — 두 갈래가 따로 놀면 반월 행수가 갈린다.

    44 유동화자산은 협회비·공제료가 면제되는 업무라 실적보고 대상이 아니다
    (2026-09-01 사용자 확인). 하드코딩을 두 군데 두면 한쪽만 고쳐도 테스트가
    안 잡히므로, 두 SQL 모두 _excluded_purpose_sql() 이 만든 문자열을 쓰게 한다.
    """
    import inspect

    from app.services import work_report
    from app.services.work_report import (
        _COMMON,
        EXCLUDED_PURPOSE_CODES,
        _excluded_purpose_sql,
    )

    assert EXCLUDED_PURPOSE_CODES == ("81", "44")
    cond = _excluded_purpose_sql()
    assert cond.strip() == "AND ISNULL(p.CommonCode, '') NOT IN ('81', '44')"

    # ① 공유 모집단
    assert cond in _COMMON
    # ② 정비사업 선례 갈래도 같은 함수를 쓴다
    src = inspect.getsource(work_report._select_redevelopment_docs)
    assert "_excluded_purpose_sql()" in src, "선례 갈래가 상수를 안 쓰면 따로 논다"
    # 상수를 안 거치는 하드코딩이 어디에도 남으면 안 된다
    assert "NOT IN ('81')" not in inspect.getsource(work_report), "옛 하드코딩이 남아 있다"


def test_population_version_moved_when_population_changed():
    """모집단이 바뀌었으면 버전 문자열도 같이 움직여야 캐시가 비워진다."""
    from app.services.work_report import POPULATION_VERSION

    assert POPULATION_VERSION != "wr-population/precedent-1", (
        "44 를 뺐는데 버전이 그대로면 보수기준 스냅숏이 옛 행 목록을 계속 내준다"
    )
