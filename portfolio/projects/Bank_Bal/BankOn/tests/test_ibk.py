"""기업은행 매핑 — 발송 실물 2704(토지 1물건)·2683(대지+건물 1층/지하층 = 3물건) 정찰값(2026-08-28)으로 검증."""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from bankon.mapping import ibk, survey_ibk
from bankon.mapping.survey import SurveyCosts
from bankon.model import DocumentContext, Fee, Parties
from bankon.parse.buildings import BuildingRow
from bankon.parse.cost import CostLayer
from bankon.parse.detail import DetailRow
from bankon.parse.outline import Outline
from bankon.sources.apw import Jibun
from bankon.sources.scan import GongbuRow


def _row(**kw) -> DetailRow:
    base = dict(table="land_list0")
    base.update(kw)
    return DetailRow(**base)


def ctx_2704() -> DocumentContext:
    """인천 십정동 565-10 공장용지 1필지(발송완료). 화면: 대지 콤보·일반공업지역·1,653.00·3,250,000·5,372,250,000."""
    return DocumentContext(
        doc_id="01-2608-3-2704", business_number="2148746436",
        parties=Parties(boss="정우종", appraisers=("유승민",), reviewer="오병오"),
        fee=Fee(net=Decimal("3774460"), vat=Decimal("382000"), subtotal=Decimal("3820000"), total=Decimal("4202000"),
                expense_base=Decimal("46000"), expense_extra=Decimal("4000"),
                expense_parts=(Decimal("2000"), Decimal("40000"))),
        jibun=Jibun(reg="28237", eub="10200", san="1", bun1="565", bun2="10"),
        outline=Outline(address="십정동 565-10", zone="일반공업지역", usage="공업나지", category="장"),
        price_point_date="2026-08-26", survey_date="2026-08-26", total_amount=Decimal("5372250000"),
        gongbu=(GongbuRow("1", "토지", "1201-2019-000075", "인천광역시 부평구 십정동 565-10", Decimal("1653"), "공장용지"),),
        details=(_row(seq_no="1", location="인천광역시 부평구 십정동", jibun="565-10", category="공장용지",
                      zone="일반공업지역", area_public=Decimal("1653"), area_assessed=Decimal("1653"),
                      unit_price=Decimal("3250000"), amount=Decimal("5372250000")),),
    )


def ctx_2683() -> DocumentContext:
    """서울 수서동 461-17 단독주택(발송완료). 화면: 물건 3행(대지 / 건물 1층 / 건물 지하층), 건물구조 '벽돌조', 45/14."""
    return DocumentContext(
        doc_id="01-2608-3-2683", business_number="2148746436",
        parties=Parties(boss="정우종", appraisers=("전영배",), reviewer="김태우"),
        fee=Fee(net=Decimal("3622267"), vat=Decimal("369200"), subtotal=Decimal("3692000"), total=Decimal("4061200"),
                expense_base=Decimal("69000"), expense_extra=Decimal("11500"),
                expense_parts=(Decimal("8400"), Decimal("40000"), Decimal("10000"))),
        jibun=Jibun(reg="11680", eub="11500", san="1", bun1="461", bun2="17"),
        outline=Outline(address="수서동 461-17", zone="개발제한 자연녹지", usage="단독주택", category="대", building_use="주택",
                        struct="벽돌조 /슬래브위 기와지붕", floors_text="지하 1층/ 지상 1층", approval_date="1989-12-19"),
        price_point_date="2026-08-25", survey_date="2026-08-25", total_amount=Decimal("5100478080"),
        cost_layers=(CostLayer(mark="가", floor="지하1층", use="주택", replacement_cost=Decimal("1100000"),
                               remaining_years=14, useful_years=45, unit_price=Decimal("342000")),),
        buildings=(BuildingRow(mark="가", location="수서동 461-17", use="주택", struct="벽돌조",
                               area_total=Decimal("199.68"), floors="지하 1층/ 지상 1층", approval_date="1989-12-19"),),
        gongbu=(
            GongbuRow("1", "토지", "1146-1996-059070", "서울특별시 강남구 수서동 461-17", Decimal("318"), "대"),
            GongbuRow("1", "건물", "1146-1996-065379", "서울특별시 강남구 수서동 461-17외 1필지", Decimal("99.84"), "벽돌조 … 1층"),
            GongbuRow("2", "건물", "1146-1996-065379", "서울특별시 강남구 수서동 461-17외 1필지", Decimal("99.84"), "벽돌조 … 지하층"),
        ),
        details=(
            _row(seq_no="1", location="서울특별시 수서동", jibun="461-17", category="대", zone="개발제한구역",
                 area_public=Decimal("318"), area_assessed=Decimal("318"), unit_price=Decimal("15800000"),
                 amount=Decimal("5024400000")),
            _row(seq_no="가", location="동소", jibun="461-17,", category="주택", zone="벽돌조", note="현황"),
            _row(jibun="450-15", zone="슬래브위", note="461-17번지"),
            _row(location="광평로", zone="1층", note="1,350,000", area_public=Decimal("99.84"),
                 area_assessed=Decimal("99.84"), unit_price=Decimal("420000"), amount=Decimal("41932800")),
            _row(zone="지하층", note="1,100,000", area_public=Decimal("99.84"), area_assessed=Decimal("99.84"),
                 unit_price=Decimal("342000"), amount=Decimal("34145280")),
        ),
    )


class Test2704:
    def test_헤더는_gam_info_수수료_그대로(self):
        header, _ = ibk.build_ibk(ctx_2704())
        assert header == {
            "평가사명": "유승민", "헤더:물건종류": "공장용지", "기준시점": "2026-08-26",
            "감정수수료": "4202000", "순수수료": "3774460", "실 비": "46000", "특별용역비": "0", "부가세": "382000",
        }

    def test_토지_1필지_1물건(self):
        _, objects = ibk.build_ibk(ctx_2704())
        assert len(objects) == 1
        o = objects[0]
        assert o["_kind"] == "토지"
        assert (o["물건:법정동코드"], o["물건:번지구분"], o["물건:본번지"], o["물건:부번지"]) == ("2823710200", "일반", "565", "10")
        assert o["물건:소재지"] == "인천광역시 부평구 십정동"
        assert o["물건:물건종류"] == "대지"                  # 실물: 공장용지도 '대지'
        assert o["물건:총감정평가액"] == "5372250000" and o["물건:토지평가금액"] == "5372250000"
        assert o["물건:건물평가금액"] is None and o["물건:부동산구분"] == "토지"
        assert (o["탭:공부지목"], o["탭:용도지역"]) == ("공장용지", "일반공업지역")
        assert (o["탭:공부면적"], o["탭:사정면적"], o["탭:평가단가"], o["탭:감정평가액"]) == (
            "1653.00", "1653.00", "3250000", "5372250000")
        assert o["탭:비 고"] is None and "탭:건물구조" not in o

    def test_특별용역비는_APW_Bill(self):
        header, _ = ibk.build_ibk(ctx_2704(), SurveyCosts(special=Decimal("50000")))
        assert header["특별용역비"] == "50000"


class Test2683:
    def test_금액행_1개가_물건_1개(self):
        header, objects = ibk.build_ibk(ctx_2683())
        assert header["헤더:물건종류"] == "단독주택" and header["평가사명"] == "전영배"
        assert header["실 비"] == "69900" and header["부가세"] == "369200" and header["감정수수료"] == "4061200"
        assert [o["_kind"] for o in objects] == ["토지", "건물", "건물"]
        assert [o["물건:일련번호"] for o in objects] == ["1", "2", "3"]

    def test_토지_물건(self):
        _, objects = ibk.build_ibk(ctx_2683())
        land = objects[0]
        assert land["물건:소재지"] == "서울특별시 강남구 수서동"    # 명세 '서울특별시 수서동'이 아니라 공부스캔 주소
        assert (land["물건:본번지"], land["물건:부번지"], land["물건:물건종류"], land["물건:부동산구분"]) == ("461", "17", "대지", "토지")
        assert land["탭:공부지목"] == "대지"
        assert land["탭:용도지역"] == "자연녹지지역"               # 문서 '개발제한구역' → 개요의 자연녹지 + '지역'
        assert (land["탭:공부면적"], land["탭:평가단가"], land["탭:감정평가액"]) == ("318.00", "15800000", "5024400000")

    def test_건물_층별_물건(self):
        _, objects = ibk.build_ibk(ctx_2683())
        f1, b1 = objects[1], objects[2]
        for o in (f1, b1):
            assert (o["물건:본번지"], o["물건:부번지"]) == ("461", "17")       # 머리행 '461-17,' 에서
            assert o["물건:물건종류"] == "건물" and o["물건:부동산구분"] == "건물"
            assert o["물건:법정동코드"] == "1168011500"
            assert (o["탭:건물구조"], o["탭:준공일자"], o["탭:내용년수"], o["탭:잔존년수"]) == ("벽돌조", "1989-12-19", "45", "14")
            assert o["탭:공부면적(전용면적)"] == "99.84" and o["탭:사정면적"] == "99.84"
            assert "탭:공부지목" not in o
        assert (f1["탭:평가단가"], f1["탭:감정평가액"], f1["탭:비 고"]) == ("420000", "41932800", "1층")
        assert (b1["탭:평가단가"], b1["탭:감정평가액"], b1["탭:비 고"]) == ("342000", "34145280", "지하층")

    def test_평가금액_합계는_물건_공통(self):
        _, objects = ibk.build_ibk(ctx_2683())
        for o in objects:
            assert o["물건:총감정평가액"] == "5100478080"
            assert o["물건:토지평가금액"] == "5024400000"
            assert o["물건:건물평가금액"] == "76078080"
            assert o["물건:기계기구평가금액"] is None


class TestRules:
    def test_zone(self):
        assert ibk._ibk_zone("일반공업지역", None) == "일반공업지역"
        assert ibk._ibk_zone("자연녹지", None) == "자연녹지지역"
        assert ibk._ibk_zone("개발제한구역", "개발제한 자연녹지") == "자연녹지지역"
        assert ibk._ibk_zone("개발제한구역", None) is None
        assert ibk._ibk_zone(None, "계획관리지역") == "계획관리지역"

    def test_object_combo(self):
        assert ibk.object_combo("토지", "대") == "대지"
        assert ibk.object_combo("토지", "공장용지") == "대지"
        assert ibk.object_combo("토지", "전") == "대지"       # 콤보에 지목 항목 없음(2026-09-01 수집) — 지목은 탭 공부지목
        assert ibk.object_combo("토지", None) == "대지"
        assert ibk.object_combo("건물", None) == "건물"

    def test_금액없는_행은_물건이_아니다(self):
        rows = (_row(seq_no="1", jibun="1", category="대", amount=Decimal("10")),
                _row(seq_no="2", jibun="2", category="도로"),                      # 금액 없음
                _row(zone="현황 도로", area_assessed=Decimal("5"), amount=Decimal("3")),   # 2번 필지 소분행
                _row(table="rent0", seq_no="1", amount=Decimal("999")))            # 임대료 표는 제외
        specs = ibk.split_objects(rows)
        assert [(s.kind, s.row.amount, s.head.jibun) for s in specs] == [("토지", Decimal("10"), "1"), ("토지", Decimal("3"), "2")]

    def test_구분건물과_기계기구(self):
        rows = (_row(table="section_build0", seq_no="가", jibun="12", struct="철근콘크리트구조", amount=Decimal("1")),
                _row(table="section_build0", seq_no="나", jibun="12", amount=Decimal("2")),
                _row(table="detail_machin0", seq_no="1", category="선반", amount=Decimal("3")))
        specs = ibk.split_objects(rows)
        assert [s.kind for s in specs] == ["건물", "건물", "기계기구"]
        _, objects = ibk.build_ibk(DocumentContext(doc_id="x", business_number="1", details=rows))
        # 구분건물 호 1개 = 건물 + 대지 2물건(실물 2719·2682) → 4개 + 기계기구 1개
        assert [o["_kind"] for o in objects] == ["건물", "토지", "건물", "토지", "기계기구"]
        assert [o["물건:일련번호"] for o in objects] == ["1", "2", "3", "4", "5"]
        assert objects[4]["물건:물건종류"] == "국산기계" and objects[4]["탭:감정평가액"] == "3"   # 업무팀 확정 2026-09-07, 기계 탭 채움
        assert objects[4]["물건:부동산구분"] is None                                             # 콤보에 기계 항목 없음 → 비움
        assert objects[4]["물건:기계기구평가금액"] == "3"

    def test_기계기구는_명세표_순서와_무관하게_맨_마지막(self):
        # 기계 표가 토지 표보다 앞에 와도(테이블 순서) 화면 물건 순서는 토지·건물 → 기계기구(업무팀 확정 2026-09-07)
        rows = (_row(table="detail_machin0", seq_no="1", category="선반", amount=Decimal("3")),
                _row(table="detail_machin0", seq_no="2", category="밀링", amount=Decimal("4")),
                _row(seq_no="1", jibun="7", category="공장용지", amount=Decimal("10")))
        _, objects = ibk.build_ibk(DocumentContext(doc_id="x", business_number="1", details=rows))
        assert [o["_kind"] for o in objects] == ["토지", "기계기구", "기계기구"]
        assert [o["물건:일련번호"] for o in objects] == ["1", "2", "3"]
        assert [o["물건:물건종류"] for o in objects] == ["대지", "국산기계", "국산기계"]

    def test_zone_전각숫자와_공법관계_폴백(self):
        assert ibk._ibk_zone("제2종일반주거지역", None) == "제２종일반주거지역"
        assert ibk._ibk_zone(None, None, "기호(1, 2) 공히 도시지역, 준공업지역, 지구단위계획구역") == "준공업지역"
        assert ibk._ibk_zone(None, None, "제2종일반주거지역(제2종일반주거지역(남동구)), 가축사육제한구역") == "제２종일반주거지역"


def ctx_2719() -> DocumentContext:
    """안양 호계동 555-42 지식산업센터 2호(발송완료 덤프 2026-08-31): 호마다 건물+대지 물건, 부동산구분 집합건물."""
    from bankon.parse.units import UnitRow
    return DocumentContext(
        doc_id="01-2608-3-2719", business_number="2148746436",
        parties=Parties(boss="정우종", appraisers=("유승민",), reviewer="김태우"),
        fee=Fee(net=Decimal("1203760"), vat=Decimal("132800"), total=Decimal("1460800"),
                expense_parts=(Decimal("4000"), Decimal("93000"), Decimal("20000")), expense_extra=Decimal("8000")),
        jibun=Jibun(reg="41173", eub="10400", san="1", bun1="555", bun2="42"),
        outline=Outline(address='경기도 안양시 동안구 호계동 555-42외 1필지 "안양에스케이브이1센터"',
                        building_use="공장(지식산업센터), 지원시설(근린생활시설)", struct="철근콘크리트구조 (철근)콘크리트지붕",
                        approval_date="2018-10-26", area_exclusive=Decimal("135.34"), area_land_right=Decimal("36.99")),
        price_point_date="2026-08-27", total_amount=Decimal("1309000000"),
        units=(UnitRow("가", "제4층 제420호", Decimal("135.34"), Decimal("135.25"), Decimal("270.59"), Decimal("36.99"), "공장 (지식산업센터)"),
               UnitRow("나", "제4층 제421호", Decimal("137.51"), Decimal("137.42"), Decimal("274.93"), Decimal("37.59"), "공장 (지식산업센터)")),
        gongbu=(
            GongbuRow("1", "토지", "1341-2018-009021", "경기도 안양시 동안구 호계동 555-42", Decimal("4358.5"), "공장용지"),
            GongbuRow("2", "토지", "1341-2018-009021", "경기도 안양시 동안구 호계동 555-43", Decimal("4358.9"), "공장용지"),
            GongbuRow("3", "건물", "1341-2018-009021", "경기도 안양시 동안구 호계동 555-42외 1필지 안양에스케이브이1센터 제4층 제420호", Decimal("135.34"), "전유부분 철근콘크리트구조"),
            GongbuRow("1", "토지", "1341-2018-009022", "경기도 안양시 동안구 호계동 555-42", Decimal("4358.5"), "공장용지"),
            GongbuRow("3", "건물", "1341-2018-009022", "경기도 안양시 동안구 호계동 555-42외 1필지 안양에스케이브이1센터 제4층 제421호", Decimal("137.51"), "전유부분 철근콘크리트구조"),
        ),
        details=(_row(table="section_build0", seq_no="가", jibun="555-42,", area_public=Decimal("135.34"), area_assessed=Decimal("135.34"), amount=Decimal("649000000"), note="비준가액"),
                 _row(table="section_build0", seq_no="나", jibun="555-42,", area_public=Decimal("137.51"), area_assessed=Decimal("137.51"), amount=Decimal("660000000"), note="비준가액")),
        legal_text="기호(1, 2) 공히 도시지역, 준공업지역, 지구단위계획구역, 중로2류(폭 15m~20m)(접합)",
    )


class TestCondo2719:
    def test_호마다_건물과_대지(self):
        header, objects = ibk.build_ibk(ctx_2719())
        assert header["헤더:물건종류"] == "아파트형공장"
        assert [(o["_kind"], o["물건:물건종류"], o["물건:부동산구분"], o["물건:등기소기준 고유번호"]) for o in objects] == [
            ("건물", "건물", "집합건물", "13412018009021"), ("토지", "대지", "집합건물", "13412018009021"),
            ("건물", "건물", "집합건물", "13412018009022"), ("토지", "대지", "집합건물", "13412018009022")]
        b, l = objects[0], objects[1]
        assert (b["탭:건물구조"], b["탭:준공일자"], b["탭:공부면적(전용면적)"], b["탭:사정면적"], b["탭:감정평가액"]) == (
            "철근콘크리트구조", "2018-10-26", "135.34", "135.34", "649000000")
        assert b["탭:내용년수"] == "0" and b["탭:잔존년수"] == "0" and b["탭:평가단가"] == "0"   # 구분건물은 0 을 넣는다(업무팀 확정 2026-09-07)
        assert (l["탭:공부지목"], l["탭:용도지역"], l["탭:공부면적"], l["탭:사정면적"]) == ("공장용지", "준공업지역", "36.99", "36.99")
        assert l["탭:감정평가액"] == "0" and l["탭:평가단가"] == "0"        # 구분건물 대지는 0 원을 실제로 넣는다(업무팀 확정 2026-09-07)
        assert objects[3]["탭:공부면적"] == "37.59"
        for o in objects:
            assert o["물건:토지평가금액"] is None and o["물건:건물평가금액"] == "1309000000"


class TestSurvey:
    def test_2704(self):
        v = survey_ibk.build(SurveyCosts(travel=Decimal("40000"), registry=Decimal("2000"), photo=Decimal("4000"),
                                         object_survey=Decimal("0")), ctx_2704())
        assert v["교통비"] == "40000" and v["여 비"] == "40000" and (v["출장회수"], v["출장인원"]) == ("1", "1")
        assert (v["등기사항전부증명서 건수"], v["등기사항전부증명서 비용"]) == ("1", "1000")
        assert (v["토지이용계획확인원 건수"], v["토지이용계획확인원 비용"]) == ("1", "1000")
        assert v["일반건축물대장 비용"] is None and v["공부발급비"] == "2000"
        assert (v["사진 매수"], v["사진 비용"], v["기타실비"]) == ("4", "4000", "4000")
        assert v["건물수"] is None and v["물건조사비"] == "0"     # 0 은 form 가드가 비운다

    def test_2683(self):
        v = survey_ibk.build(SurveyCosts(travel=Decimal("40000"), registry=Decimal("8400"), photo=Decimal("11500"),
                                         object_survey=Decimal("10000")), ctx_2683())
        assert (v["등기사항전부증명서 건수"], v["등기사항전부증명서 비용"]) == ("2", "2000")
        assert v["일반건축물대장 비용"] == "5400" and v["공부발급비"] == "8400"
        assert (v["건물수"], v["건물조사비용"], v["물건조사비"]) == ("1", "10000", "10000")
        assert v["사진 매수"] is None and v["사진 비용"] is None and v["기타실비"] == "11500"   # 사진 6,000+임대차 5,500, 메모 없어 분해 불가

    def test_2743_area6_메모로_기타실비_분해(self):
        """SILBI 11,400 이 1,000 단위가 아니면 bill30 area6 메모의 '사진 N' 으로 사진/임대차를 분해한다(2026-09-02 실증)."""
        ctx = replace(ctx_2683(), doc_id="01-2608-3-2743",
                      expense_note="토이계 3,000  등기 1,000\r\n전입+교통비 5,400\r\n도면+교통비 5,200\r\n사진 6,000")
        v = survey_ibk.build(SurveyCosts(travel=Decimal("40000"), registry=Decimal("9200"), photo=Decimal("11400"),
                                         object_survey=Decimal("10000")), ctx)
        assert (v["사진 매수"], v["사진 비용"]) == ("6", "6000")
        assert v["임대차확인 비용"] == "5400" and v["기타실비"] == "11400"   # 소계 = 사진+임대차 = SILBI → 자동계산 일치

    def test_area6_메모_사진이_SILBI_이상이면_분해하지_않는다(self):
        ctx = replace(ctx_2683(), expense_note="사진 12,000")
        v = survey_ibk.build(SurveyCosts(photo=Decimal("11400")), ctx)
        assert v["사진 비용"] is None and v["임대차확인 비용"] is None and v["기타실비"] == "11400"


def test_struct_raw():
    assert ibk._struct_raw("벽돌조 /슬래브위 기와지붕") == "벽돌조"
    assert ibk._struct_raw("철골조 경량판넬지붕") == "철골조"          # 2714 의견서 표(지붕 붙음)
    assert ibk._struct_raw("철근콘크리트구조") == "철근콘크리트구조"
    assert ibk._struct_raw("76.82") is None                          # 2684 명세 word-wrap 조각
    assert ibk._struct_raw("1층") is None
    assert ibk._pick_struct("76.82", None, "세멘벽돌조", "철근콘크리트조") == "세멘벽돌조"

    def test_2719_구분건물_필지2개(self):
        v = survey_ibk.build(SurveyCosts(travel=Decimal("93000"), registry=Decimal("4000"), photo=Decimal("8000"),
                                         object_survey=Decimal("20000")), ctx_2719())
        # 실화면(2026-08-31): 등기 2건 2,000 · 토지이용 2건 2,000(555-42·555-43) · 건축물대장 빈칸 · 건물수 2 · 사진 8매
        assert (v["등기사항전부증명서 건수"], v["토지이용계획확인원 건수"], v["토지이용계획확인원 비용"]) == ("2", "2", "2000")
        assert v["일반건축물대장 비용"] is None and v["건물수"] == "2" and v["사진 매수"] == "8"


def test_object_combo_land_always_daeji():
    """기업 물건종류 콤보엔 지목 항목이 없다(recon/combo_ibk.md) → 토지는 전·목장용지·임야도 '대지'(2706 LIVE 거부로 확인, 2026-09-01)."""
    for cat in ("전", "목장용지", "임야", "대", "공장용지", "잡종지", None):
        assert ibk.object_combo(ibk.OBJECT_LAND, cat) == "대지"
    assert ibk.object_combo(ibk.OBJECT_BUILDING, None) == "건물"


def test_동소_건물은_토지_소재지를_승계한다():
    """2636 통합 명세표: 건물 머리행 소재지 '동 소'(同所), 공부스캔 없음 → 같은 표 토지의 병합 소재지."""
    rows = (
        _row(seq_no="1", location="경기도 화성시 만세구 남양읍 북양리", jibun="708-3", category="공장용지", zone="계획관리지역",
             area_public=Decimal("4011.2"), area_assessed=Decimal("3861.2"), unit_price=Decimal("946000"), amount=Decimal("3652695200")),
        _row(seq_no="가", location="동 소", jibun="708-3", category="공장", zone="일반철골구조", note="일반건축물"),
        _row(location="화성시", zone="1층", area_public=Decimal("703.3"), area_assessed=Decimal("908.85"),
             unit_price=Decimal("1300000"), amount=Decimal("1181505000"), group_head=True),
    )
    _, objects = ibk.build_ibk(DocumentContext(doc_id="01-2608-3-2636", business_number="1", details=rows,
                                               jibun=Jibun(reg="41591", eub="25628", san="1", bun1="708", bun2="2")))
    assert [o["_kind"] for o in objects] == ["토지", "건물"]
    assert objects[0]["물건:소재지"] == "경기도 화성시 만세구 남양읍 북양리"
    assert objects[1]["물건:소재지"] == "경기도 화성시 만세구 남양읍 북양리"
    assert objects[1]["탭:건물구조"] == "일반철골구조"


def _land(seq, jibun, cat, pub, assessed, price, amount, table="land_list0", **kw):
    return _row(table=table, seq_no=seq, jibun=jibun, category=cat, zone="계획관리지역", area_public=pub, area_assessed=assessed,
                unit_price=price, amount=amount, **kw)


def test_감정평가외_도로필지는_대지_단가1_금액0():
    """2636 발송본: 708-4 도로(PRICE '감정평가외', 사정 258) → 대지 행, 공부=사정=258, 단가 1, 감정평가액 0."""
    rows = (
        _land("1", "708-2", "공장용지", Decimal("3222.4"), Decimal("3172.4"), Decimal("946000"), Decimal("3001090400"),
              location="경기도 화성시 만세구 남양읍 북양리", group_head=True),
        _land("2", "708-4", "도로", Decimal("1567.4"), Decimal("258.00"), None, None, excluded=True, location="동 소"),
    )
    _, objects = ibk.build_ibk(DocumentContext(doc_id="x", business_number="1", details=rows))
    assert [o["_kind"] for o in objects] == ["토지", "토지"]
    road = objects[1]
    assert (road["물건:본번지"], road["물건:부번지"], road["물건:물건종류"], road["탭:공부지목"]) == ("708", "4", "대지", "도로")
    assert (road["탭:공부면적"], road["탭:사정면적"], road["탭:평가단가"], road["탭:감정평가액"]) == ("258.00", "258.00", "1", "0")
    assert objects[0]["물건:토지평가금액"] == "3001090400"           # 감정평가외는 합계에 안 들어감


def test_일단지_머리행_공부면적은_구성필지_합():
    """2706 발송본: 1124(240, '<') + 1124-1(2,292, '>') 일단지 → 공부면적 2,532 = 사정면적."""
    rows = (
        _land("1", "1124", "전", Decimal("240"), Decimal("2532"), Decimal("314000"), Decimal("795048000"), group_head=True,
              location="경기도 화성시 만세구 양감면 용소리"),
        _land("2", "1124-1", "전", Decimal("2292"), None, None, None, group_member=True, location="동 소"),
        _land("3", "1124-9", "목장용지", Decimal("3114"), Decimal("4014"), Decimal("1"), Decimal("1336662000")),
    )
    _, objects = ibk.build_ibk(DocumentContext(doc_id="x", business_number="1", details=rows))
    assert [o["물건:부번지"] for o in objects] == [None, "9"]        # 1124-1 은 별도 물건이 아니다
    assert (objects[0]["탭:공부면적"], objects[0]["탭:사정면적"]) == ("2532.00", "2532.00")
    assert objects[1]["탭:공부면적"] == "3114.00"


def test_대표지번_명세표를_앞에_둔다():
    """2636 발송본: land_list0=708-3, land_list1=708-2, APW 대표지번 708-2 → 708-2 묶음이 먼저."""
    rows = (
        _land("1", "708-3", "공장용지", Decimal("4011.2"), Decimal("3861.2"), Decimal("946000"), Decimal("3652695200"), table="land_list0"),
        _land("1", "708-2", "공장용지", Decimal("3222.4"), Decimal("3172.4"), Decimal("946000"), Decimal("3001090400"), table="land_list1"),
    )
    ctx = DocumentContext(doc_id="x", business_number="1", details=rows, jibun=Jibun(reg="41591", eub="25628", san="1", bun1="708", bun2="2"))
    _, objects = ibk.build_ibk(ctx)
    assert [o["물건:부번지"] for o in objects] == ["2", "3"]
    _, objects = ibk.build_ibk(DocumentContext(doc_id="x", business_number="1", details=rows))   # 대표지번 없으면 명세표 순서
    assert [o["물건:부번지"] for o in objects] == ["3", "2"]


def test_동호는_명세_제N동일_때만():
    rows = (
        _land("1", "708-3", "공장용지", Decimal("4011.2"), Decimal("3861.2"), Decimal("946000"), Decimal("3652695200")),
        _row(seq_no="가", location="동 소", jibun="708-3", category="공장", zone="일반철골구조"),
        _row(jibun="제2동", zone="일반철골지붕"),
        _row(location="화성시", zone="1층", area_public=Decimal("848.5"), area_assessed=Decimal("848.5"),
             unit_price=Decimal("1200000"), amount=Decimal("1018200000")),
    )
    _, objects = ibk.build_ibk(DocumentContext(doc_id="x", business_number="1", details=rows))
    assert objects[1]["_kind"] == "건물" and objects[1]["탭:동/호"] == "2"
    # 명세표에 '제N동' 이 없으면 비운다(2706 발송본: 의견서 건물표 '1동' 꼬리가 있어도 담당자는 비웠음)
    rows2 = rows[:2] + (rows[3],)
    _, objects = ibk.build_ibk(DocumentContext(doc_id="x", business_number="1", details=rows2))
    assert objects[1]["탭:동/호"] is None


def test_원가표_같은기호_여러층은_명세단가로_고른다():
    """2706 '다': 1층 철파이프조(25/10, 72,000) + 부속 시멘트블럭조(40/11, 123,000) → 93㎡(단가 123,000) 물건은 40/11."""
    from bankon.parse.cost import CostLayer
    layers = (CostLayer(mark="다", floor="1층 (철파이프조)", use="동.식물관련시설", replacement_cost=Decimal("180000"),
                        remaining_years=10, useful_years=25, unit_price=Decimal("72000")),
              CostLayer(mark="다", floor="", use="시멘트블럭조", replacement_cost=Decimal("450000"),
                        remaining_years=11, useful_years=40, unit_price=Decimal("123000")))
    rows = (
        _row(seq_no="다", location="동 소", jibun="1124-9,", category="동.식물", zone="철파이프조"),
        _row(zone="1층", area_public=Decimal("1183.2"), area_assessed=Decimal("1183.2"), unit_price=Decimal("72000"), amount=Decimal("85190400")),
        _row(zone="1층", area_public=Decimal("93"), area_assessed=Decimal("93"), unit_price=Decimal("123000"), amount=Decimal("11439000")),
    )
    _, objects = ibk.build_ibk(DocumentContext(doc_id="x", business_number="1", details=rows, cost_layers=layers))
    assert [(o["탭:내용년수"], o["탭:잔존년수"]) for o in objects] == [("25", "10"), ("40", "11")]


def test_원가표_이어짐행_우측정렬():
    from bankon.parse import cost
    assert cost._aligned(("시멘트블럭조", "450,000", "11", "40", "123,750", "123,000"), 8) == \
        ("", "", "시멘트블럭조", "450,000", "11", "40", "123,750", "123,000")
    assert cost._aligned(("가", "1층", "용도", "1", "2", "3", "4", "5"), 8) == ("가", "1층", "용도", "1", "2", "3", "4", "5")


def test_현장조사서_공부발급비_0이면_공부항목_비움():
    """2387: APW GONGBU=0 인데 공부스캔에 등기 2·필지 2 → 종전엔 2,000+2,000 을 넣어 실비 합이 어긋남."""
    ctx = DocumentContext(doc_id="01-2607-3-2387", business_number="1", parties=Parties(boss="x", appraisers=("유승민",), reviewer=None),
                          gongbu=(GongbuRow(seq_no="1", kind="토지", unique_no="1234-2020-000001", address="인천광역시 서구 경서동 363-172",
                                            area=Decimal("100"), note="공장용지"),
                                  GongbuRow(seq_no="2", kind="토지", unique_no="1234-2020-000002", address="인천광역시 서구 경서동 363-173",
                                            area=Decimal("100"), note="공장용지")))
    zero = SurveyCosts(travel=Decimal("40000"), object_survey=Decimal("40000"), registry=Decimal("0"), photo=Decimal("13000"),
                       subtotal=Decimal("93000"))
    out = survey_ibk.build(zero, ctx)
    assert out["등기사항전부증명서 건수"] is None and out["토지이용계획확인원 비용"] is None and out["공부발급비"] in (None, "0")
    some = SurveyCosts(travel=Decimal("40000"), object_survey=Decimal("40000"), registry=Decimal("4000"), photo=Decimal("13000"))
    out = survey_ibk.build(some, ctx)
    assert (out["등기사항전부증명서 건수"], out["토지이용계획확인원 건수"], out["공부발급비"]) == ("2", "2", "4000")


def test_특별용역비_없으면_0():
    header, _ = ibk.build_ibk(ctx_2704())
    assert header["특별용역비"] == "0"
    from bankon.ui import form
    assert "특별용역비" in form.ZERO_ALLOWED_FULL        # 0 입력 가드 예외 — 실제로 '0' 이 써져야 한다


class TestCondoAndMachineTabs2776:
    """2776 실물(2026-09-07): 구분건물 호 2개 + 기계 1대. 동/호·대지 0원·기계기구 탭이 비어 있던 문제."""

    def _rows(self):
        return (
            _row(table="section_build0", seq_no="가", jibun="662-3", struct="철골철근콘크리트합성구조",
                 location="제3층 제301호", area_public=Decimal("243.671"), area_assessed=Decimal("243.671"), amount=Decimal("914000000")),
            _row(table="detail_machin0", seq_no="1", category="PUMA GT 2600", qty="1(식)", made="2022.08",
                 note="85,000,000", note_more="0.733(11/15)", unit_price=Decimal("62305000"), amount=Decimal("62305000")),
        )

    def test_구분건물_호와_대지_0원(self):
        _, objects = ibk.build_ibk(DocumentContext(doc_id="x", business_number="1", details=self._rows()))
        building, land = objects[0], objects[1]
        assert building["_kind"] == "건물" and building["탭:동/호@2"] == "301" and building["탭:동/호"] is None
        assert land["_kind"] == "토지" and land["탭:평가단가"] == "0" and land["탭:감정평가액"] == "0"   # 업무팀 확정 2026-09-07

    def test_기계기구_탭(self):
        _, objects = ibk.build_ibk(DocumentContext(doc_id="x", business_number="1", details=self._rows()))
        m = objects[-1]
        assert m["_kind"] == "기계기구" and m["물건:물건종류"] == "국산기계"
        assert (m["탭:기계기구명"], m["탭:내용년수"], m["탭:잔존년수"], m["탭:수 량"], m["탭:취득단가"], m["탭:감정평가액"])             == ("PUMA GT 2600", "15", "11", "1", "62305000", "62305000")      # 취득단가 = 감정평가액(업무팀 확정 2026-09-07)
        assert m["탭:제작일자"] == "2022-08-01"             # '2022.08' → 그 달 1일(업무팀 확정 2026-09-07, 2776 실물)


def test_detail_machine_columns_and_note_more():
    """detail_machin: 머리행 count/make_date 와 뒤따르는 부기 행 BIGO('0.733(11/15)')를 머리행에 모은다(2776)."""
    from bankon.parse import detail
    rows = detail.parse({"detail_machin0": [
        {"NO": "1", "machine_detail": "PUMA GT 2600", "make_date": "2022.08", "count": "1(식)", "DANGA": "62,305,000",
         "PRICE": "62,305,000", "BIGO": "85,000,000"},
        {"make_date": "디엠공작기계", "BIGO": "0.733(11/15)"},
        {"machine_detail": "제조번호 : ML0258-002441"},
    ]})
    assert len(rows) == 1
    r = rows[0]
    assert (r.category, r.qty, r.made, r.note, r.note_more) == ("PUMA GT 2600", "1(식)", "2022.08", "85,000,000", "0.733(11/15)")

