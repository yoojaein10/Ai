"""KB_* 테이블 파싱 — 실제 `.gam` 값(01-2607-3-2418)으로 검증."""
from __future__ import annotations

from decimal import Decimal

from bankon.codes import common
from bankon.mapping import kookmin
from bankon.model import DocumentContext
from bankon.parse import detail, kb

SUMMARY_ROW = {
    "CustName": "국민은행 강남파이낸스지점장",
    "debtor": "(주)티펙스",
    "category": "토지건물",
    "addr": "경기도 이천시 마장면 양촌리 299-8외 19필지 ",
    "GuBun": "A",
    "Write_Date": "2026-08-05",
    "Writer": "박수현",
}
ALL_NO = {**{f"a{i}": "N" for i in range(1, 13)},
          **{f"b{i}": "N" for i in range(1, 6)},
          **{f"c{i}": "N" for i in range(1, 4)}}


class TestSummary:
    def test_요약을_읽는다(self):
        result = kb.parse_summary({"KB_Summary0": [SUMMARY_ROW]})
        assert result.client == "국민은행 강남파이낸스지점장"
        assert result.category == "토지건물"
        assert result.address == "경기도 이천시 마장면 양촌리 299-8외 19필지"
        assert result.writer == "박수현"

    def test_바인더번호가_붙어도_찾는다(self):
        assert kb.parse_summary({"KB_Summary1008": [SUMMARY_ROW]}).debtor == "(주)티펙스"

    def test_없으면_빈값(self):
        assert kb.parse_summary({"land_list0": [{}]}).address is None


class TestChecks:
    def test_20개를_화면_순서로_돌려준다(self):
        answers = kb.parse_checks({"KB_Summary_Chk0": [ALL_NO]})
        assert len(answers) == 20          # a1~a12(12) + b1~b5(5) + c1~c3(3)
        assert set(answers) == {"아니오"}

    def test_컬럼_순서가_a_b_c다(self):
        assert kb.CHECK_COLUMNS[:3] == ("a1", "a2", "a3")
        assert kb.CHECK_COLUMNS[11:14] == ("a12", "b1", "b2")
        assert kb.CHECK_COLUMNS[-3:] == ("c1", "c2", "c3")

    def test_Y는_예로_바뀐다(self):
        row = {**ALL_NO, "a4": "Y", "b1": "Y", "c3": "Y"}
        answers = kb.parse_checks({"KB_Summary_Chk0": [row]})
        assert answers[3] == "예"      # a4 = 미등기·무허가·위반건축물
        assert answers[12] == "예"     # b1 = 조건부감정
        assert answers[19] == "예"     # c3 = 취약 담보물건

    def test_True_False_표기도_받는다(self):
        answers = kb.parse_checks({"KB_Summary_Chk0": [{**ALL_NO, "a1": "True"}]})
        assert answers[0] == "예"

    def test_표가_없으면_전부_None(self):
        answers = kb.parse_checks({"land_list0": [{}]})
        assert len(answers) == 20 and set(answers) == {None}


class TestCon:
    def test_물건별_집계값을_읽는다(self):
        rows = kb.parse_con({"KB_Con0": [{
            "Con_Area1": "798.5", "Con_Price1": "68600000", "Con_TotPrice1": "54777100000",
            "Con_Area2": "3264.11", "Con_Price2": "1443000", "Con_TotPrice2": "3925233780"}]})
        assert len(rows) == 2
        assert rows[0].amount == Decimal("54777100000") and rows[0].area == Decimal("798.5")
        assert not rows[0].aggregated

    def test_N개호는_합산으로_표시한다(self):
        rows = kb.parse_con({"KB_Con0": [{"Con_Ho2": "8개호", "Con_TotPrice2": "25607000000"}]})
        assert rows[0].aggregated is True                 # 8개호 = 개별물건 아님
        one = kb.parse_con({"KB_Con0": [{"Con_Ho2": "1개호", "Con_TotPrice2": "398000000"}]})
        assert one[0].aggregated is False                 # 1개호 = 단일물건

    def test_없으면_빈튜플(self):
        assert kb.parse_con({"land_list0": [{}]}) == ()


class TestReviewerFromRound:
    def test_round0의_inspection을_읽는다(self):
        tables = {"round0": [{"inspection": "김형식", "par_player": "정원정"}]}
        assert kb.reviewer_from_round(tables) == "김형식"

    def test_서식행_테이블은_무시한다(self):
        assert kb.reviewer_from_round({"round_20": [{"inspection": "엉뚱"}]}) is None

    def test_없거나_비면_None(self):
        assert kb.reviewer_from_round({"land_list0": [{}]}) is None
        assert kb.reviewer_from_round({"round0": [{"inspection": ""}]}) is None


class TestMapping:
    def _context(self, **kwargs) -> DocumentContext:
        return DocumentContext(doc_id="01-2607-3-2418", business_number="2148746436", **kwargs)

    def test_건물명을_소재지에서_뗀다(self):
        summary = kb.parse_summary({"KB_Summary0": [
            {**SUMMARY_ROW, "category": "구분건물",
             "addr": "경기도 군포시  당정동 1128 신라테크노빌   704-1호  "}]})
        built = kookmin.build(self._context(kb_summary=summary))
        assert built["건물명"] == "신라테크노빌"
        assert built["호"] == "704-1"

    def test_건물명_끝의_동번호를_뗀다(self):
        # 실측 1642: addr '…202-5 청라에이스하이테크시티  3동 2층 207호외208호'.
        # '3동'은 건물명이 아니라 동(호=3-207에 있음) → 건물명에서 제거.
        summary = kb.parse_summary({"KB_Summary0": [
            {**SUMMARY_ROW, "category": "구분건물",
             "addr": "인천광역시 서구 청라동 202-5 청라에이스하이테크시티  3동 2층 207호외208호"}]})
        assert kookmin.build(self._context(kb_summary=summary))["건물명"] == "청라에이스하이테크시티"

    def test_건물명_끝의_한글동도_뗀다(self):
        # 실측 1638: '…653 인덕원아이티밸리  씨동 8층 808호' → '씨동'(C동) 제거.
        summary = kb.parse_summary({"KB_Summary0": [
            {**SUMMARY_ROW, "category": "구분건물",
             "addr": "경기도 의왕시 포일동 653 인덕원아이티밸리  씨동 8층 808호"}]})
        assert kookmin.build(self._context(kb_summary=summary))["건물명"] == "인덕원아이티밸리"

    def test_건물명_다물건_외구조에서도_뽑는다(self):
        # 실측 1623: '…75 외 디엠씨 자이1단지 제1층 제118호 외 제1층 제119호'.
        # 지번 뒤 '외' 건너뛰고 첫 층/호 앞까지 = 건물명. 뒤 물건들은 무시.
        summary = kb.parse_summary({"KB_Summary0": [
            {**SUMMARY_ROW, "category": "구분건물",
             "addr": "서울특별시 은평구 수색동 75 외 디엠씨 자이1단지 제1층 제118호 외 제1층 제119호"}]})
        assert kookmin.build(self._context(kb_summary=summary))["건물명"] == "디엠씨 자이1단지"

    def test_건물명_영문호도_뽑는다(self):
        # 실측 1614: '…274 영등포자이타워 제F0306호' — 호가 F로 시작(영문).
        summary = kb.parse_summary({"KB_Summary0": [
            {**SUMMARY_ROW, "category": "구분건물",
             "addr": "서울특별시 영등포구 양평동1가 274 영등포자이타워 제F0306호"}]})
        assert kookmin.build(self._context(kb_summary=summary))["건물명"] == "영등포자이타워"

    def test_토지는_건물명이_없다(self):
        # addr 끝에 '호' 가 없으면(토지·토지건물) 건물명 None → 오값 대신 빈값.
        ctx = self._context(kb_summary=kb.parse_summary({"KB_Summary0": [SUMMARY_ROW]}))
        assert kookmin.build(ctx)["건물명"] is None

    def test_공부스캔_구조의_끊긴_조를_잇는다(self):
        # 2829 T_SCAN_GONGBU 비고 `전유부분 철골철근콘크리트구 조` → 예전엔 `철골철근콘크리트구 구조` 가 나갔다(2026-09-11).
        assert kookmin._struct_only("철골철근콘크리트구 조") == "철골철근콘크리트구조"
        assert common.struct_only("철골철근콘크리트구 조", to_gujo=False) == "철골철근콘크리트구조"
        # 지붕·층·용도가 이어진 긴 비고는 뭉개지 않는다.
        long_note = "경량철골구조 기타지붕 1층 위험물저장및처리시설 1층"
        assert " " in (common.struct_only(long_note) or "")

    def test_건물구조_접미사를_구조로_정규화한다(self):
        # 유닛머리 gujo(구조) → 정규화. 가격행은 제N층 제N호.
        rows = detail.parse({"section_build0": [
            {"NO": "가", "gujo": "철근콘크리트조"},
            {"gujo": "제3층 제301호", "AREA1": "50", "PRICE": "100000000"}]})
        assert kookmin.build(self._context(details=rows))["건물구조"] == "철근콘크리트구조"

    def test_층과_호를_명세표에서_뽑는다(self):
        rows = detail.parse({"section_build0": [
            {"NO": "가", "gujo": "철근콘크리트조"},
            {"gujo": "제7층 제704-1호", "AREA1": "383.5", "AREA2": "383.5",
             "PRICE": "656,000,000"}]})
        built = kookmin.build(self._context(details=rows))
        assert built["건물 층수"] == "7"
        assert built["호"] == "704-1"

    def test_일단지_묶음머리는_head_raw_사정을_쓴다(self):
        # 일단지(AREA1 묶음=group_head)면 head 필지 raw AREA2/PRICE 가 그 물건 값
        # (실측 1344 245·612,500,000 · 0033 5997). 소분 합산도, 공부 축소도 안 한다.
        rows = detail.parse({"land_list0": [
            {"NO": "1", "JIBUN": "289-3", "AREA1": "132", "AREA1RB": "<",
             "AREA2": "245", "DANGA": "2,500,000", "PRICE": "612,500,000"},
            {"NO": "2", "JIBUN": "289-4", "AREA1": "16", "AREA1RB": ">"}]})
        built = kookmin.build(self._context(details=rows))
        assert built["사정면적"] == "245.00"
        assert built["감정평가액"] == "612500000"

    def test_토지_소분블록을_합산한다(self):
        # 비-일단지 필지의 도로저촉 소분(seq_no=None valued 행)을 head 와 합산
        # (실측 1258 사정 396+44=440, 감정 1,152,360,000+89,760,000).
        rows = detail.parse({"land_list0": [
            {"NO": "1", "JIBUN": "45-8", "AREA1": "440", "AREA2": "396", "AREA2LB": "<",
             "DANGA": "2,910,000", "PRICE": "1,152,360,000"},
            {"AREA2": "44", "AREA2RB": ">", "DANGA": "2,040,000", "PRICE": "89,760,000"}]})
        built = kookmin.build(self._context(details=rows))
        assert built["사정면적"] == "440.00"
        assert built["감정평가액"] == "1242120000"

    def test_소재지는_KB_Summary를_우선한다(self):
        ctx = self._context(kb_summary=kb.parse_summary({"KB_Summary0": [SUMMARY_ROW]}))
        # land_list 처럼 계층으로 쪼개진 주소 대신 완성된 문자열을 쓴다.
        # 화면 소재지는 동까지만 — 지번은 본번지/부번지 칸에 따로 들어간다.
        assert kookmin.build(ctx)["소재지"] == "경기도 이천시 마장면 양촌리"

    def test_점검항목은_gam_값을_쓴다(self):
        row = {**ALL_NO, "a4": "Y"}
        ctx = self._context(kb_checks=kb.parse_checks({"KB_Summary_Chk0": [row]}))
        answers = kookmin.checklist_answers(ctx)
        assert len(answers) == 20
        assert answers[3] == "예"
        assert answers[0] == "아니오"

    def test_값이_없으면_기본값으로_채운다(self):
        answers = kookmin.checklist_answers(self._context())
        assert answers == ("아니오",) * 20


def test_object_type_from_category_rule_a():
    from bankon.mapping import kookmin
    assert kookmin.object_type_from_category("대") == "대/ 공장용지"
    assert kookmin.object_type_from_category("대지") == "대/ 공장용지"
    assert kookmin.object_type_from_category("도로") == "도로"
    assert kookmin.object_type_from_category("답") == "답"
    assert kookmin.object_type_from_category("이상한지목") is None


def test_parcel_key():
    from bankon.mapping import kookmin
    assert kookmin._parcel_key("306,") == "306"
    assert kookmin._parcel_key(" 299-5 ") == "299-5"
    assert kookmin._parcel_key("0299-0005") == "299-5"
    assert kookmin._parcel_key(None) is None


def test_gongbu_address_patterns():
    from bankon.mapping import kookmin
    assert kookmin._ADDR_LAND.search("경기도 이천시 마장면 양촌리 299-8").group(1) == "299-8"
    m = kookmin._ADDR_BUILDING.search("경기도 이천시 마장면 양촌리 306외 1필지 2동")
    assert (m.group(1), m.group(2)) == ("306", "2")
    m = kookmin._ADDR_BUILDING.search("경기도 이천시 마장면 양촌리 299-8 제1동")
    assert (m.group(1), m.group(2)) == ("299-8", "1")
    m = kookmin._ADDR_BUILDING.search("경기도 김포시 대곶면 송마리 211-1 제2동호")
    assert (m.group(1), m.group(2)) == ("211-1", "2")
    m = kookmin._ADDR_BUILDING.search("경기도 김포시 감정동 108-3외 1필지")
    assert (m.group(1), m.group(2)) == ("108-3", None)
    assert kookmin._struct_from_note("1동 철골조 및 경량철골조 판넬지붕 단층공장") == "철골조 및 경량철골조"
    assert kookmin._struct_from_note("일반철골구조 경량판넬지붕 1층 동.식물관련시설 1층") == "일반철골구조"
    assert kookmin._struct_from_note("브럭조 스레트지붕 단층 근린 생활시설") == "브럭조"


def test_buildings_table_parse():
    from bankon.parse import buildings
    body = ('<table><tr><td>기호</td><td>소재지</td><td>용 도</td><td>구조/지붕</td><td>연면적(㎡)</td><td>층 수</td>'
            '<td>사용승인일자</td></tr><tr><td>가</td><td>양촌리 299-3</td><td>축사</td><td>일반철골구조\n/일반철골구조</td>'
            '<td>281.75</td><td>지상 1층</td><td>2018.06.26</td></tr><tr><td>라</td><td>양촌리 299-8</td><td>축사</td>'
            '<td>경량철골구조\n/판넬</td><td>29.40</td><td>지상 1층</td><td>2019.05.10</td></tr></table>')
    rows = buildings.parse(body)
    assert [r.mark for r in rows] == ["가", "라"]
    assert buildings.by_mark(rows, "라").approval_date == "2019-05-10"
    assert buildings.by_mark(rows, "가").struct == "일반철골구조"
    assert buildings.by_mark(rows, "나") is None


def test_worker_bank_and_runners():
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
    import run_queue_worker as W
    assert W.bank_of("국민은행 미아동지점 외") == "국민"
    assert W.bank_of("신한은행 강남중앙금융센터") == "신한"
    assert W.bank_of("기업은행 남시화지점장") == "기업"
    assert W.bank_of("농협은행 김포지점장") == "농협"                 # 농협은행(중앙회)만(2026-09-07 이식)
    assert W.bank_of("군자농협 시화지점장") is None                  # 지역·품목농협은 폼 변형(할인 블록·현장조사서 비용) → 보류
    # 2026-09-10 인계본 이식 4개 — APW CustName 실측 표기
    assert W.bank_of("KEB하나은행 원주지점") == "하나"
    assert W.bank_of("㈜하나은행 당진지점장") == "하나"
    assert W.bank_of("하나새마을금고 이사장") == "새마을"              # '하나' 만으로 하나은행이 아니다
    assert W.bank_of("우리은행 여신업무센터장") == "우리"
    assert W.bank_of("(주)우리은행여신업무센터") == "우리"
    assert W.bank_of("원주우리새마을금고 이사장") == "새마을"          # 우리새마을금고 ≠ 우리은행
    assert W.bank_of("목포우리신용협동조합이사장") is None
    assert W.bank_of("삼천포수협 북부지점장") == "수협"
    assert W.bank_of("경남정치망수협 통영지점") == "수협"
    assert W.bank_of("북부천새마을금고이사장") == "새마을"
    assert W.bank_of("우리자산신탁(주)") is None
    from bankon import paths
    assert set(W.RUNNERS) == {"신한", "국민", "기업", "농협", "수협", "하나", "우리", "새마을"} == set(W.SUPPORTED)
    assert all((paths._REPO / "tools" / f"{m}.py").exists() for m in W.RUNNERS.values())   # exe 는 --runner <모듈> 로 자기 재호출
    assert W.DAMBO_DOC.match("01-2608-3-2676") and not W.DAMBO_DOC.match("01-2608-6-0482")
    # exe 는 hiddenimports 에 적힌 모듈만 번들한다 — 러너가 빠지면 `--runner` 재호출이 exe 에서만 실패(2026-09-01 기업 누락 발견)
    spec = (paths._REPO / "bankon_gui.spec").read_text(encoding="utf-8")
    for mod in [*W.RUNNERS.values(), "autofill_shinhan", "autofill_kb", "autofill_ibk", "autofill_survey", "autofill_nh", "verify_fill_nh",
                "bank_runner", "autofill_slot", "autofill_ssb", "autofill_hnb", "autofill_wrb", "autofill_mgb",
                "verify_fill_ssb", "verify_fill_hnb", "verify_fill_wrb", "verify_fill_mgb"]:
        assert f"'{mod}'" in spec, f"bankon_gui.spec hiddenimports 에 {mod} 없음"
    import human_guard
    assert set(W.RUNNERS) <= set(human_guard.INDICATORS)            # 러너가 사람 작성 보호를 못 거르는 은행이 없어야 한다


def test_unit_object_type_and_addr():
    from bankon.mapping import kookmin
    assert kookmin.unit_object_type("근린생활시설") == "집합상가-근린(점포)상가"
    assert kookmin.unit_object_type("아파트") == "아파트(주상복합아파트포함)"
    assert kookmin.unit_object_type("판매시설, 창고시설, 업무시설") is None      # 복합용도 첫 항목만 → 사람이 고름
    m = kookmin._UNIT_ADDR.search("서울특별시 송파구 문정동 628 가든파이브툴 제4층 제4-에이17호")
    assert (m.group(1), m.group(2)) == ("4", "4-에이17")
    m = kookmin._UNIT_ADDR.search("경기도 수원시 영통구 영통동 974-6 세일빌딩 제4층 제403호")
    assert (m.group(1), m.group(2)) == ("4", "403")


def test_building_object_type_2703():
    # 2703: 지목 공장용지 + 용도 제2종근린생활시설 → 담당자 '일반공장'(지목 우선). 사용자 정정 2026-08-28.
    assert kookmin.building_object_type("공장용지", "제2종근린생활시설") == "일반공장"
    assert kookmin.building_object_type("대", "제2종근린생활시설") == "일반상가-근린(점포)상가"
    assert kookmin.building_object_type("대", "동·식물관련시설(축사)") == "축사"
    assert kookmin.building_object_type("대", None) is None


def test_worker_default_status_and_pdf_skipped_note():
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
    import run_queue_worker as W
    assert W.DEFAULT_STATUSES == ("대기",)                       # 사용자 확정 2026-09-03: 대기 건만(종전 진행)
    assert W.humanize("[요약] pdf=x | write_save=['예']") == "정상 처리"
    assert W.humanize("[요약] write_save=['예'] | pdf_skipped=감정서,현장조사 | survey_save=['예']") \
        == "PDF 건너뜀(감정서,현장조사) — 수동 등록 필요"
    assert W.humanize("[요약] pdf_skipped=수수료 | error=RuntimeError('x')") == "RuntimeError: 'x'"   # 실패는 오류 사유 우선
    # 거부 칸은 비운 채 저장하고 완료(2026-09-03) — 비고에 거부 칸·PDF 건너뜀을 함께
    done = ("[거부(콤보 항목 없음: '개발제한구역' (되돌림 '', 원래 ''))] 세부:용도지역 넣을값=개발제한구역 / "
            "[요약] write_rejected=있음(빈칸 저장) | pdf_skipped=현장조사")
    assert W.humanize(done) == "입력 거부(빈칸 저장, 담당자 확인): 세부:용도지역=개발제한구역; PDF 건너뜀(현장조사) — 수동 등록 필요"
    assert W.humanize("[거부(x)] 라벨 넣을값=값 / [요약] write_rejected=있음(빈칸 저장)") == "입력 거부(빈칸 저장, 담당자 확인): 라벨=값"
    # 농협 다물건: 화면 슬롯 하나만 채운 건은 비고에 남겨 담당자가 나머지 물건을 넣는다(2026-09-07)
    assert (W.humanize("[요약] write_fill=exit=0 | multi_object=물건 2개 중 슬롯 1(우리 1)만 입력 — 나머지 수동 | write_save=['예']")
            == "다물건 일부만 입력(물건 2개 중 슬롯 1(우리 1)만 입력 — 나머지 수동)")
    # varchar(500) 은 바이트 기준 — 한글 300자(600B)는 [:500] 로도 넘쳐 8152 오류(2754, 2026-09-03)
    long = "가" * 300
    assert len(W.fit_bytes(long, 500).encode("cp949")) <= 500 and W.fit_bytes(long, 500) == "가" * 250
    assert W.fit_bytes("abc", 500) == "abc" and W.fit_bytes(None, 10) == ""
    assert W.fit_bytes("a가b", 2) == "a"                                  # 글자 중간에서 안 끊음


def test_kb_zone_alias_2754():
    # 2754 발송본 대조(2026-09-07): 콤보 항목명은 '개발제한' — '개발제한구역' 그대로 넣으면 항목 없음으로 거부됐다.
    assert kookmin._kb_zone("개발제한구역") == "개발제한"
    assert kookmin._kb_zone("개발제한 구역") == "개발제한"
    assert kookmin._kb_zone("자연녹지지역") == "자연녹지"
    assert kookmin._kb_zone("계획관리지역") == "계획관리"
    assert kookmin._kb_zone(None) is None
