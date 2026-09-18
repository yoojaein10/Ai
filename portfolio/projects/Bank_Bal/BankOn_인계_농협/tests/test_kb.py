"""KB_* 테이블 파싱 — 실제 `.gam` 값(01-2607-3-2418)으로 검증."""
from __future__ import annotations

from decimal import Decimal

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

    def test_일단지_묶음머리는_head_단독값을_쓴다(self):
        """묶음머리(AREA1 묶음=group_head)는 **머리 필지 단독값**(AREA1, AREA1×단가).

        AREA2/PRICE 는 묶음 합계라 화면(물건 하나)과 다르다. 화면값 163건으로 묶음머리
        20건을 재 봤다 — **화면=AREA1 15건 / AREA2 4건**. 다수 쪽을 쓴다.
        (남는 4건 0033·0663·0916·1344 는 사람이 고친다 — 가르는 소스 신호를 못 찾았다.)
        """
        rows = detail.parse({"land_list0": [
            {"NO": "1", "JIBUN": "289-3", "AREA1": "132", "AREA1RB": "<",
             "AREA2": "245", "DANGA": "2,500,000", "PRICE": "612,500,000"},
            {"NO": "2", "JIBUN": "289-4", "AREA1": "16", "AREA1RB": ">"}]})
        built = kookmin.build(self._context(details=rows))
        assert built["사정면적"] == "132.00"
        assert built["감정평가액"] == "330000000"       # 132 × 2,500,000

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
        assert kookmin.build(ctx)[kookmin.BOX_SITE] == "경기도 이천시 마장면 양촌리"

    def test_소재지에_건물명이_딸려오지_않는다(self):
        # 예전엔 마지막 `…동` 을 탐욕 매칭해 건물명의 `씨동`·`상가동`까지 먹었다(실측 28건).
        summary = kb.parse_summary({"KB_Summary0": [
            {**SUMMARY_ROW, "addr": "경기도 의왕시 포일동 653 인덕원아이티밸리 씨동"}]})
        built = kookmin.build(self._context(kb_summary=summary))
        assert built[kookmin.BOX_SITE] == "경기도 의왕시 포일동"

    def test_용도지역은_화면_약칭으로(self):
        # 국민 화면은 `제1종일반주거지역` 을 `1종일반주거` 로 쓴다(기업은 정식 명칭 그대로).
        assert kookmin.zone_short("제1종일반주거지역") == "1종일반주거"
        assert kookmin.zone_short("계획관리지역") == "계획관리"
        assert kookmin.zone_short("개발제한구역") == "개발제한"
        assert kookmin.zone_short("제２종일반주거지역") == "2종일반주거"   # 전각도
        # 등급도 수식도 없는 단독 명칭은 통째로 쓴다(실측).
        assert kookmin.zone_short("농림지역") == "농림지역"
        assert kookmin.zone_short(None) is None

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
