"""보수기준 점검 화면의 금액 판정 — 코드 일치와 독립된 축.

금액 로직은 fee_rules(순수 함수)를 그대로 쓰고, 평가액·순수수료는 협회양식과 같은
build_kapa_rows에서 받는다. 여기서 고정하는 것은 "계산할 수 없는 경우를 0원으로
뭉개지 않는다"는 규칙이다 — 미입력·평가액 없음·청구행 금액 충돌은 서로 다른 상태다.
"""

from pathlib import Path

from app.services import fee_basis

fee_rules = fee_basis

UI = Path(__file__).resolve().parent.parent / "desktop" / "ui"


def judged(appraisal, actual, *, conflict=False, missing=False, no_fee=False):
    amount = None if missing else {
        "conflict": conflict,
        "row_count": 2 if conflict else 1,
        "appraisal_amount": appraisal,
        "actual_fee": actual,
        "no_fee": no_fee,
    }
    return fee_basis._fee_judgement(amount, "2026-06-10")


def test_amount_inside_band_is_within_and_has_no_state():
    _standard, lower, upper = fee_rules.fee_bands(3_000_000_000)
    result = judged(3_000_000_000, round((lower + upper) / 2))

    assert result["deviation_direction"] == fee_rules.DEVIATION_WITHIN
    assert result["fee_state"] == ""
    assert result["lower_fee"] == lower
    assert result["upper_fee"] == upper


def test_below_floor_of_lower_is_flagged():
    from math import floor

    _standard, lower, _upper = fee_rules.fee_bands(3_000_000_000)
    # 1원은 원 단위 절사 오차로 허용하므로 2원부터 이탈이다.
    result = judged(3_000_000_000, floor(lower) - 2)

    assert result["deviation_direction"] == fee_rules.DEVIATION_BELOW


def test_above_ceil_of_upper_is_flagged():
    from math import ceil

    _standard, _lower, upper = fee_rules.fee_bands(3_000_000_000)
    result = judged(3_000_000_000, ceil(upper) + 2)

    assert result["deviation_direction"] == fee_rules.DEVIATION_ABOVE


def test_one_won_off_the_band_stays_within():
    """화면에서 요율적용금액과 순수수료가 같은 숫자로 보이는데 이탈색이 되면 안 된다."""
    from math import ceil, floor

    _standard, lower, upper = fee_rules.fee_bands(3_000_000_000)

    assert judged(3_000_000_000, floor(lower) - 1)["deviation_direction"] == (
        fee_rules.DEVIATION_WITHIN
    )
    assert judged(3_000_000_000, ceil(upper) + 1)["deviation_direction"] == (
        fee_rules.DEVIATION_WITHIN
    )


def test_gap_rate_is_measured_against_the_lower_bound():
    """격차율은 하한 대비다. 기준(100%) 대비로 착각하면 이탈 판정을 오해한다."""
    _standard, lower, _upper = fee_rules.fee_bands(3_000_000_000)
    actual = round(lower * 1.1)

    result = judged(3_000_000_000, actual)

    assert abs(result["reference_gap_rate"] - (actual / lower - 1)) < 1e-9


def test_missing_fee_is_not_treated_as_zero():
    """수수료 미입력과 0원 청구는 재무 대사에서 뜻이 전혀 다르다."""
    result = judged(3_000_000_000, None)

    assert result["actual_fee"] is None
    assert result["deviation_direction"] == fee_rules.DEVIATION_MISSING


def test_conflicting_bill_rows_hold_the_judgement():
    """같은 감정서에 청구행이 여럿이고 금액이 다르면 대표값을 고르지 않는다."""
    result = judged(3_000_000_000, 5_000_000, conflict=True)

    assert result["fee_state"] == fee_basis.FEE_CONFLICT
    assert result["deviation_direction"] is None
    assert result["lower_fee"] is None


def test_no_appraisal_amount_cannot_use_the_fee_table():
    """평가액이 없으면 보수표를 적용할 수 없다(컨설팅·자문 등)."""
    result = judged(0, 5_000_000)

    assert result["fee_state"] == fee_basis.NOT_COMPARABLE_APPRAISAL
    assert result["deviation_direction"] is None
    assert result["actual_fee"] == 5_000_000


def test_row_without_kapa_amounts_says_so():
    """모집단에는 있는데 협회양식 행이 없는 건. 조용히 넘기지 않는다."""
    result = judged(None, None, missing=True)

    assert result["fee_state"] == fee_basis.NO_AMOUNT_SOURCE
    assert result["deviation_direction"] is None


def test_expense_only_row_is_not_judged_against_the_fee_table():
    """감정수수료 계상이 없는 건은 금액이 있어도 그건 실비다.

    실측 2026-06에서 3건(01-2505-4-0159 등)이 여기 걸린다. NO_FEE를 안 보면
    실비 금액을 수수료로 오인해 '기준 내'로 잘못 판정한다.
    """
    result = judged(3_000_000_000, 30_204_024, no_fee=True)

    assert result["fee_state"] == fee_basis.EXPENSE_ONLY
    assert result["deviation_direction"] is None
    assert result["lower_fee"] is None
    assert result["actual_fee"] == 30_204_024


def test_fee_states_keep_the_finance_wording_without_fee_review_dependency():
    """점검 단독 배포에서도 재무팀에 노출할 상태 문구는 고정한다."""
    assert fee_basis.EXPENSE_ONLY == "실비만"
    assert fee_basis.FEE_CONFLICT and fee_basis.NOT_COMPARABLE_APPRAISAL


def test_screen_shows_both_axes():
    """두 축은 집계와 필터로 본다. 표에서는 판정 열을 뺐다(사용자 요청).

    다만 격차율이 비는 행은 이유를 알아야 하므로 비교 불가 사유는 그 칸에 남긴다.
    """
    script = (UI / "fee-basis.html").read_text(encoding="utf-8")
    html = (UI / "fee-basis.html").read_text(encoding="utf-8")

    # 판정 열과 그 배지 함수는 없앴다.
    assert "feeBadge" not in script and "verdictBadge" not in script
    assert "<th>금액 판정</th>" not in script and "<th>코드 판정</th>" not in script
    # 집계는 총 건수 + 이탈 둘만 본다(사용자 요청). 코드 판정은 표·엑셀에서 확인한다.
    # 주석에 '코드 일치'가 들어 있어 문자열 검사 대신 집계 생성부만 본다.
    summary_block = script[script.index("$('summary').innerHTML"):]
    summary_block = summary_block[:summary_block.index(";", summary_block.index("fee_above"))]
    assert "item_('총'" in summary_block
    assert "s.fee_below" in summary_block and "s.fee_above" in summary_block
    for dropped in ("s.match", "s.mismatch", "s.missing", "s.parsed",
                    "s.fee_within", "s.fee_uncomparable"):
        assert dropped not in summary_block, f"{dropped} 가 집계에 남아 있다"
    # 표는 요율적용금액과 청구 순수수료를 나란히 두고 그 옆에 격차율을 붙인다.
    # 격차율은 2026-08-06 사용자 요청으로 되살렸다(그전에는 뺐던 열이다).
    # 적용 요율 열은 계속 뺀 상태다.
    assert "요율적용금액" in script and "순수수료" in script
    assert "격차율" in script and "gapCell" in script
    assert "<th>적용 요율</th>" not in script
    # 금액을 못 구하는 행은 그 이유를 그 칸에 남긴다.
    assert "appliedFeeCell" in script and "fee_state" in script
    # 이탈은 행 색으로 먼저 보인다. 색은 둘만 쓴다 — 넷이면 무엇이 급한지 모른다.
    assert "rowClass" in script
    for css in ("is-below", "is-above"):
        assert css in script and css in html
    for dropped in ("is-special", "is-unexplained"):
        assert dropped not in script
    # 상한·하한, 입력된 보수기준 열은 화면에서 뺐다. 엑셀에는 남긴다.
    assert "하한(80%)" not in script and "상한(120%)" not in script
    assert "<th>입력된 보수기준</th>" not in script
    # 입력값은 코드 일치/불일치 판정의 근거이므로 셀 설명에 남긴다.
    assert "입력값:" in script
    # 기준은 매출(입금)으로 고정이다 — 배치가 그것만 만들어서 다른 기준을 고르면
    # 사용자가 80초를 기다린다. 판정 필터도 뺐다(행 색상·집계로 본다).
    assert 'id="basis"' not in html and "매출(입금)기준" in html
    assert 'id="flt"' not in html


def test_excel_columns_match_the_screen_plus_the_opinion():
    """열이 다르면 화면을 보고 엑셀에 옮겨 적는 일이 생긴다.

    화면 9열과 같은 순서로 두고 끝에 의견 하나만 더 붙인다.
    """
    import re

    router = (
        Path(__file__).resolve().parent.parent
        / "app" / "routers" / "fee_basis.py"
    ).read_text(encoding="utf-8")

    block = router[router.index("    columns = ["):]
    block = block[:block.index("]")]
    headers = re.findall(r'\("([a-z_]+)", "([^"]+)"\)', block)

    assert [name for _key, name in headers] == [
        "감정서번호", "접수일", "거래처", "업무 / 세부목적", "유치자",
        "감정평가액", "요율적용금액", "순수수료", "격차율(%)",
        # 할인 점검 두 열은 화면에선 요율적용금액 칸 배지로 접혀 있다 — 엑셀은 펼친다.
        "할인 점검", "할인 점검 비고", "자동판별", "의견",
    ]
    # 화면이 업무·목적을 한 칸에 보여주므로 엑셀도 합쳐 넣는다.
    assert "work_purpose" in router


def test_screen_has_the_save_controls():
    """미저장 표시·저장 버튼·엑셀 잠금이 없으면 담당자가 저장한 줄 알고 창을 닫는다."""
    script = (UI / "fee-basis.html").read_text(encoding="utf-8")
    html = (UI / "fee-basis.html").read_text(encoding="utf-8")

    for control_id in ("saveButton", "saveStatus", "runMeta"):
        assert f'id="{control_id}"' in html
    # 신규 조회 버튼은 뺐다 — 배치가 사전생성하고 캐시로 나오므로 쓸 일이 없다.
    assert 'id="refreshButton"' not in html

    # 지금 적혀 있는 의견을 그 자리에서 고친다(빈 입력칸을 따로 두지 않는다).
    assert "opinionInput" in script
    # 의견 칸에는 placeholder 를 두지 않는다. 화면 전체를 막으면 검색 칸 같은
    # 무관한 입력에도 걸리므로(2026-08-06 실제로 걸림) 의견 칸 조각만 본다.
    opinion_markup = script.split("opinionInput", 1)[1].split(">", 1)[0]
    assert "placeholder" not in opinion_markup
    assert "dirty" in script and ".fb-op.dirty" in html
    # 정상 조회에서는 안내 문구를 띄우지 않는다. 실패만 알린다.
    assert "사전생성본 사용" not in script
    assert "JUN 근거 조회 실패" in script
    # 미저장 상태로 엑셀을 내려받으면 화면과 다른 파일이 나온다.
    assert "의견을 저장한 뒤 내려받아 주세요." in script
    # 창 닫기 경고
    assert "beforeunload" in script
    # 원천 변경은 저장을 거부하고 다시 조회하게 안내한다.
    # 의견은 감정서번호로 저장하므로 원천이 바뀌어도 엉뚱한 행에 붙지 않는다.
    # 대신 금액이 달라졌을 수 있어 재확인을 안내한다.
    assert "opinions_stale" in script and "저장 의견 재확인 필요" in script
    # 저장소에 동결되지 않은 조회 결과에는 의견을 저장할 수 없다.
    assert "!state.runId" in script and "!state.sourceSha" in script


def test_screen_saves_by_row_number():
    script = (UI / "fee-basis.html").read_text(encoding="utf-8")

    # 의견은 감정서번호로 저장한다 — 행 번호는 순번이라 옛 의견이 엉뚱한 행에 붙는다.
    assert "data-doc=" in script and "source_row_number" not in script
    assert "/api/fee-basis/opinions" in script and "'PATCH'" in script


def test_screen_scripts_are_cache_busted():
    """?v= 없이 두면 브라우저가 옛 JS를 계속 써서 서버가 맞게 보내도 화면이 안 바뀐다.

    공용 스크립트도 캐시가 남으면 서버와 화면 계약이 달라질 수 있다.
    """
    import re

    html = (UI / "fee-basis.html").read_text(encoding="utf-8")
    scripts = re.findall(r'<script src="((?:/|\.\./)ui/[^"]+)"', html)

    assert scripts, "화면 스크립트를 찾지 못했다"
    for src in scripts:
        assert "?v=" in src, f"캐시 무효화가 없다: {src}"


def test_screen_css_resolves_from_server_and_local_file():
    """공용 CSS는 새 파일을 복제하지 않고 서버·file:// 양쪽에서 같은 파일을 쓴다."""
    html = (UI / "fee-basis.html").read_text(encoding="utf-8")

    for asset in ("dashboard.css", "desktop.css"):
        assert f'href="../ui/{asset}"' in html
        assert (UI / asset).is_file()


def test_auto_detection_renders_exactly_one_line():
    """후보가 여러 개여도 화면에는 하나만 나와야 한다."""
    script = (UI / "fee-basis.html").read_text(encoding="utf-8")

    assert "primary_candidate" in script
    # +n 배지는 뺐다 — 정확히 한 줄만 보인다. 나머지는 셀 설명(title)에만 둔다.
    assert 'class="more"' not in script
    assert "(대안)" in script


def test_row_colours_are_visible_and_hover_does_not_erase_them():
    """흰색과 1~2% 차이면 화면에서 구분되지 않는다(실측: 색이 안 보인다는 지적).

    hover 를 배경색으로 주면 행 색을 덮어써 상태가 사라지므로 밝기만 낮춘다.
    """
    html = (UI / "fee-basis.html").read_text(encoding="utf-8")

    # 실제 규칙에 거의 흰색 값이 남아 있으면 안 된다(주석의 예시는 제외한다).
    import re

    rules = re.findall(r"tr\.is-\w+ td\{background:(#[0-9a-f]{6})\}", html)
    assert len(rules) == 2, f"행 색상 규칙 2개가 아니다: {rules}"
    for colour in rules:
        red, green, blue = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
        # 흰색과의 거리. 채널 하나라도 20 이상 차이 나야 화면에서 구분된다.
        assert max(255 - red, 255 - green, 255 - blue) >= 20, (
            f"{colour} 는 흰색과 너무 가깝다"
        )
    # 배경만으로 부족해 왼쪽 색 띠도 둔다.
    assert html.count("box-shadow:inset 4px 0 0") == 2


def test_summary_sits_in_the_panel_heading_like_other_screens():
    """집계는 패널 제목 아래 한 줄이다 — 매출 입력 대기의 resultSummary 와 같은 자리.

    <p> 안이라 블록 요소를 쓰면 브라우저가 <p> 를 끊는다.
    """
    script = (UI / "fee-basis.html").read_text(encoding="utf-8")
    html = (UI / "fee-basis.html").read_text(encoding="utf-8")

    assert '<p id="summary" class="fb-summary">' in html
    assert '<div class="row">' not in script
    assert "<br>금액" not in script
    # 항목 하나가 숫자와 갈라지면 읽을 수 없다.
    assert ".fb-summary .it{white-space:nowrap" in html


def test_row_colour_legend_is_removed():
    """색 자체로 충분하다는 판단(사용자 요청). 흔적이 남으면 빈 자리가 생긴다."""
    html = (UI / "fee-basis.html").read_text(encoding="utf-8")

    assert "fb-legend" not in html
    # 행 색상 규칙은 남아 있어야 한다.
    assert "tr.is-below td{background:" in html


def test_table_uses_the_shared_layout_of_other_screens():
    """표는 다른 화면과 같은 구조·스타일을 쓴다.

    dashboard.css 의 .list-panel > .table-wrap > table 이 sticky 제목·좌측 고정
    감정서번호·hover 를 모두 담당한다. 여기서 다시 정의하면 화면마다 표가 달라진다.
    """
    html = (UI / "fee-basis.html").read_text(encoding="utf-8")
    shared = (UI / "dashboard.css").read_text(encoding="utf-8")

    # 매출 입력 대기와 같은 감싸기
    assert '<section class="workspace">' in html
    assert '<article class="list-panel">' in html
    assert '<div class="panel-heading">' in html
    assert '<div class="table-wrap" id="tableWrap">' in html
    # sticky 제목은 공용 스타일이 준다.
    assert "th { position: sticky; top: 0;" in shared
    # 표는 내용 폭만큼 커지고 랩이 가로 스크롤을 만든다. 공용 width:100% 그대로면
    # 표가 컨테이너보다 커질 수 없어 스크롤 없이 마지막 열이 잘린다(실측).
    assert "table.fb-table{width:max-content;min-width:100%}" in html
    # 랩의 가로 스크롤은 공용 overflow:auto 가 담당한다.
    assert "overflow: auto" in shared


def test_empty_state_sits_where_the_table_would_be():
    """공용 .table-wrap 은 최소 430px 을 잡는다. 그대로 두면 표가 비어도 그만큼
    빈 자리가 생기고 안내문이 아래로 밀린다. 이 화면만 높이를 풀어 준다.
    """
    import re

    html = (UI / "fee-basis.html").read_text(encoding="utf-8")

    rule = re.search(r"\.table-wrap\{([^}]*)\}", html).group(1)
    assert "min-height:0" in rule, f"최소 높이를 풀지 않았다: {rule}"
    assert 'id="empty" class="fb-empty"' in html
    # 공용 .workspace 는 2열 그리드다. 패널이 하나뿐이라 1열로 펴지 않으면
    # 표가 첫 열(~65%)만 차지해 툴바와 폭이 어긋난다.
    assert ".workspace{grid-template-columns:1fr;min-height:0}" in html
    # 빈 상태는 패널 안이라 자체 테두리를 주면 상자 속 상자(빈 표)처럼 보인다.
    empty_rule = re.search(r"\.fb-empty\{([^}]*)\}", html).group(1)
    assert "border" not in empty_rule, f"빈 상태에 테두리가 남아 있다: {empty_rule}"


def test_cells_do_not_wrap_and_long_text_is_ellipsised():
    """글자가 길어도 셀 안에서 줄바꿈되면 행 높이가 제멋대로 늘어난다.

    공용 td 가 nowrap+말줄임을 주므로 화면 쪽 white-space:normal 예외를 두지 않는다.
    자동판별의 조문·근거도 각 한 줄로 자른다 — 전체 문장은 셀 설명(title)에 있다.
    """
    import re

    html = (UI / "fee-basis.html").read_text(encoding="utf-8")
    shared = (UI / "dashboard.css").read_text(encoding="utf-8")

    # 공용 기본이 nowrap+말줄임이다.
    assert "white-space: nowrap" in shared and "text-overflow: ellipsis" in shared
    # 화면 쪽에서 그것을 풀지 않는다.
    td_rule = re.search(r"\.fb-table td\{([^}]*)\}", html).group(1)
    assert "white-space" not in td_rule, f"td 에 줄바꿈 예외가 남아 있다: {td_rule}"
    # 조문·근거는 한 줄 + 말줄임.
    for cls in (".fb-cand .lbl", ".fb-cand .ev"):
        rule = re.search(re.escape(cls) + r"\{([^}]*)\}", html, re.S).group(1)
        assert "nowrap" in rule and "ellipsis" in rule, f"{cls} 가 줄바꿈된다: {rule}"


def test_money_columns_fit_the_largest_observed_amount():
    """감정평가액 최대 실측 331,456,000,000(15자)이 좁은 열에서는 잘린다."""
    import re

    script = (UI / "fee-basis.html").read_text(encoding="utf-8")
    block = script[script.index("<colgroup>"):script.index("</colgroup>")]
    widths = [int(w) for w in re.findall(r"width:(\d+)px", block)]

    # 10열 전부 고정폭 — width:max-content 에서 유동 열은 말줄임 대신 전체 문장
    # 폭만큼 늘어나 버린다. 고정폭이라야 말줄임이 동작한다.
    # (격차율 열이 2026-08-06 에 돌아와 9 → 10 이 됐다)
    assert len(widths) == 10
    # 감정평가액(6번째 열)은 15자 숫자가 들어간다.
    assert widths[5] >= 130, f"감정평가액 열이 좁다: {widths[5]}px"
    # 격차율은 '+123.4%' 정도만 들어가면 된다.
    assert widths[8] >= 70, f"격차율 열이 좁다: {widths[8]}px"
    # 자동판별·의견 열은 조문 이름과 입력칸이 들어갈 만큼 넓어야 한다.
    assert widths[9] >= 380, f"자동판별 열이 좁다: {widths[9]}px"


def test_stale_column_widths_from_the_old_layout_are_not_applied():
    """열 구성이 바뀌면 저장 키도 바꿔야 한다.

    옛 12~14열 시절 localStorage 폭이 지금 9열에 인덱스대로 적용되어
    표 폭이 어긋났다(실측). 키 세대를 올려 낡은 저장값을 무시한다.
    """
    script = (UI / "fee-basis.html").read_text(encoding="utf-8")

    assert "'a10.feeBasis.columnWidths.v2'" in script
    assert "'a10.feeBasis.columnWidths'" not in script


def test_zero_fee_is_not_a_below_band_deviation():
    """0원 청구는 합산청구 등으로 이 건에 계상이 없는 상태다.

    하한 미만으로 확정하면 이탈 목록이 허수로 부푼다(배포 전 검토 발견).
    fee_review 의 ZERO_FEE_REVIEW 게이트와 같은 판단이다.
    """
    result = judged(3_000_000_000, 0)

    assert result["fee_state"] == fee_basis.ZERO_FEE
    assert result["deviation_direction"] is None


def test_screen_freezes_the_query_used_for_save_and_export():
    """저장·엑셀은 '조회 시점' 조건을 써야 한다. 현재 툴바 값을 쓰면 조회 후
    반월·월·지사를 바꾸고 저장했을 때 다른 기간에 의견이 붙는다(배포 전 검토 발견).
    """
    script = (UI / "fee-basis.html").read_text(encoding="utf-8")

    assert "state.query = query.toString()" in script
    assert "/api/fee-basis/opinions?${state.query}" in script
    assert "query.set('run_id', state.runId)" in script
    assert "query.set('source_sha256', state.sourceSha)" in script
    assert "run_id: state.runId" in script
    assert "source_sha256: state.sourceSha" in script
    # 조회 전에는 저장·엑셀이 눌리지 않는다.
    assert "!state.query" in script


def test_save_success_only_clears_drafts_matching_what_was_sent():
    """저장이 나는 동안 입력한 편집분을 저장된 것으로 위장하면 조용히 사라진다."""
    script = (UI / "fee-basis.html").read_text(encoding="utf-8")

    assert "state.draft.get(doc) === sent[doc]" in script
    # 저장 뒤 편집분이 없으면 재조회로 서버 확정 상태(빈 값 삭제→자동 제안 부활)를 반영.
    assert "screenQuery().toString() === state.query) await run()" in script


def test_get_api_has_no_public_refresh_switch():
    """refresh=true 를 외부에서 반복 호출하면 80초 원천 재생성을 무한히 시킬 수 있다."""
    router = (
        Path(__file__).resolve().parent.parent
        / "app" / "routers" / "fee_basis.py"
    ).read_text(encoding="utf-8")

    get_block = router[router.index('@router.get("", response_model'):]
    get_block = get_block[:get_block.index("@router.", 10)]
    assert "refresh" not in get_block.split("# refresh")[0].split("->")[0]
