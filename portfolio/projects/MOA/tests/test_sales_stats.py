from app.services.sales_stats import CATEGORIES, build_stat_rows, category_of


def test_category_of_maps_known_and_unknown_values():
    assert category_of("담보") == "담보"
    assert category_of("법원 및 공매") == "법원 및 공매"
    assert category_of("PF") == "PF"
    assert category_of("기타 공공") == "기타"      # 분류 밖 값은 기타로
    assert category_of(" 담보 ") == "담보"          # 공백 정리
    assert category_of(None) == "기타"
    assert category_of("") == "기타"


def test_build_stat_rows_covers_all_categories_and_total():
    rows = build_stat_rows(
        current={"담보": {"docs": 10, "amount": 1000}},
        previous={"담보": {"docs": 8, "amount": 800}, "보상": {"docs": 2, "amount": 200}},
    )
    assert [row["purpose"] for row in rows] == CATEGORIES + ["합계"]

    dambo = next(row for row in rows if row["purpose"] == "담보")
    assert dambo["docs"] == 10 and dambo["amount"] == 1000
    assert dambo["prev_docs"] == 8 and dambo["prev_amount"] == 800
    assert dambo["diff"] == 200
    assert dambo["rate"] == 25.0
    # 달성률 = 당기 ÷ 전기 (증감률 + 100)
    assert dambo["achievement"] == 125.0

    bosang = next(row for row in rows if row["purpose"] == "보상")
    assert bosang["docs"] == 0 and bosang["amount"] == 0
    assert bosang["diff"] == -200
    assert bosang["rate"] == -100.0

    total = rows[-1]
    assert total["purpose"] == "합계"
    assert total["docs"] == 10 and total["amount"] == 1000
    assert total["prev_docs"] == 10 and total["prev_amount"] == 1000
    assert total["diff"] == 0
    assert total["rate"] == 0.0


def test_build_stat_rows_rate_is_none_when_previous_is_zero():
    rows = build_stat_rows(current={"PF": {"docs": 1, "amount": 500}}, previous={})
    pf = next(row for row in rows if row["purpose"] == "PF")
    assert pf["diff"] == 500
    assert pf["rate"] is None  # 전년 실적 0이면 증감률·달성률 표시 불가
    assert pf["achievement"] is None


def test_build_stat_rows_achievement_below_100_when_declined():
    rows = build_stat_rows(
        current={"보상": {"docs": 1, "amount": 671}},
        previous={"보상": {"docs": 2, "amount": 1000}},
    )
    bosang = next(row for row in rows if row["purpose"] == "보상")
    assert bosang["rate"] == -32.9
    assert bosang["achievement"] == 67.1


def test_build_stat_rows_rate_is_none_when_previous_is_negative():
    # 취소 전표가 매출보다 커서 전년이 음수인 분류 — 증감률은 의미가 없으므로 표시하지 않는다
    rows = build_stat_rows(
        current={"기타": {"docs": 2, "amount": 100}},
        previous={"기타": {"docs": 3, "amount": -200}},
    )
    etc = next(row for row in rows if row["purpose"] == "기타")
    assert etc["diff"] == 300
    assert etc["rate"] is None


def test_기본_기간은_오늘_하루다():
    """시작일을 종료일과 같은 날로 둔다 (2026-08-03 사용자 요청).

    예전에는 당기 시작일이 올해 1월 1일로 고정돼 있어, 하루·한 달치를 보려면
    매번 시작일을 고쳐야 했다. 전기는 suggestPrevPeriod 가 전년 같은 날로 맞춘다.
    """
    from pathlib import Path

    script = (
        Path(__file__).resolve().parent.parent / "desktop" / "ui" / "sales-stats.js"
    ).read_text(encoding="utf-8")
    start = script.index("// 기본 기간")
    block = script[start : script.index("suggestPrevPeriod();", start)]
    assert "$('dateFrom').value=inputDate(today);" in block
    assert "$('dateTo').value=inputDate(today);" in block
    assert "-01-01" not in block, "연초 고정이 남아 있다"


def test_화면이_캐시되지_않는다():
    """HTML이 캐시되면 안에 적힌 ?v= 도 옛 값이라 새 JS를 영영 안 받는다."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    main = (root / "app" / "main.py").read_text(encoding="utf-8")
    index = main.index("def desktop_sales_stats(")
    assert "no-cache" in main[index : index + 400]
    html = (root / "desktop" / "ui" / "sales-stats.html").read_text(encoding="utf-8")
    assert "sales-stats.js?v=" in html, "캐시버스터가 없으면 새 JS가 안 나간다"


def test_원장에_없으면_전표_업무구분으로_분류한다():
    """관리번호에 감정서번호가 아닌 값이 오는 매출이 있다 (2026-08-03 재무팀 확인).

    사업명('26년 2분기 든든'), 거래처명('주택도시보증공사'), 은행 의뢰번호(400xxxxxx)
    등이 그대로 들어와 원장 매칭에 실패하면 전부 '기타'로 뭉쳤다. 아마란스 전표에는
    업무구분(l2Nm)이 이미 있으므로 그걸로 채운다.
    실측: 2026년 기타 4.66억 → 3.25억, 보상 +2.21억 / 컨설팅 +5,530만.
    """
    from app.services.sales_stats import (
        AMARANTH_CATEGORY,
        CATEGORIES,
        _amaranth_case,
        _category_list,
    )

    # 매핑 결과는 반드시 화면 분류 안에 있어야 한다 (오타 방지).
    for src, dst in AMARANTH_CATEGORY.items():
        assert dst in CATEGORIES, f"{src} → {dst} 는 화면 분류에 없다"
    assert AMARANTH_CATEGORY["담보부문"] == "담보"
    assert AMARANTH_CATEGORY["경매부문"] == "법원 및 공매"
    # 우리 쪽에 대응 항목이 없는 것은 기타로 (재무팀: 약식은 기타에 남긴다).
    assert AMARANTH_CATEGORY["약식부분"] == "기타"
    # 쟁송(소송 감정)은 원장에 있는 40줄이 전부 '법원 및 공매'였다.
    assert AMARANTH_CATEGORY["쟁송"] == "법원 및 공매"
    # 아마란스 입력 오타도 받아준다 ('담보부문'을 '담보'로 친 것 등).
    assert AMARANTH_CATEGORY["담보"] == "담보"

    case = _amaranth_case()
    assert "JSON_VALUE" in case and "$.l2Nm" in case
    assert case.rstrip().endswith("ELSE N'기타' END"), "모르는 값은 기타로 떨어져야 한다"
    # fallback 이므로 '기타'는 IN 절에 없어야 한다 (있으면 원장 기타가 우선돼 보완이 죽는다).
    assert "N'기타'" not in _category_list()
    assert "N'담보'" in _category_list()


def test_집계_SQL이_원장_우선_전표_보완_순서다():
    from app.services.sales_stats import _STATS_SQL

    assert "CASE WHEN RTRIM(m.LWorkinfo) IN ({category_list})" in _STATS_SQL
    assert "ELSE s.voucher_purpose END AS purpose" in _STATS_SQL
    # GROUP BY 도 같은 식이어야 행이 쪼개지지 않는다.
    assert _STATS_SQL.count("ELSE s.voucher_purpose END") == 2


def test_상세도_집계와_같은_분류를_쓴다():
    """집계표에서 분류를 클릭하면 오른쪽 상세가 그 분류만 보여준다.

    예전에는 상세가 하이픈 없는 관리번호를 '(번호없음)' 하나로 묶고 업무구분도
    원장 값만 썼다. 그래서 7/31 상세에 9,659,632 짜리 한 줄이 떴는데, 집계는
    담보 8,553,632 + 기타 1,106,000 으로 나뉘어 숫자가 안 맞았다.
    """
    from app.services.sales_stats import _DETAIL_SQL

    assert "{amaranth_case} AS voucher_purpose" in _DETAIL_SQL
    assert "ELSE s.voucher_purpose END AS work_type" in _DETAIL_SQL
    # 감정서번호가 아닌 관리번호는 집계표와 같이 '(번호없음)'으로 묶는다.
    assert "N'(번호없음)' END AS doc_key" in _DETAIL_SQL
    # 다만 분류까지 묶어야 한다 — 안 그러면 성격이 다른 전표가 한 줄에 뭉쳐
    # 집계표에서 분류를 클릭했을 때 금액이 안 맞는다.
    assert "GROUP BY doc_key, work_type" in _DETAIL_SQL
