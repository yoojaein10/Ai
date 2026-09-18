from decimal import Decimal

from bankon.mapping import survey


def test_build_matches_sent_2403():
    c = survey.SurveyCosts(travel=Decimal("107200"), land_survey=Decimal(0), object_survey=Decimal("40000"),
                           registry=Decimal("9000"), photo=Decimal("800"), special=Decimal(0),
                           vat=Decimal("15700"), subtotal=Decimal("157000"))
    v = survey.build(c, "2026-08-03")
    assert v["현장답사일"] == "2026-08-03"
    assert v["교통비"] == "107200" and v["물건조사비"] == "40000" and v["공부발급비"] == "9000"
    assert v["사진비"] == "800" and v["부가세"] == "15700" and v["실비합계"] == "172700"
    assert v["예외적용"] == "미적용"
    assert v["토지조사비"] == "0"            # form.is_blank 가드로 화면엔 안 들어감
    assert v["임대차조사비"] is None and v["기타실비"] is None


def test_vat_and_total_from_items_not_apw_sums():
    # 2676 실측: APW SILBISUM 52,000/SILBITAX 5,200 이지만 화면은 항목합 52,900 → 부가세 5,290 → 합계 58,190
    c = survey.SurveyCosts(travel=Decimal("40000"), object_survey=Decimal("10000"), registry=Decimal("2700"),
                           photo=Decimal("200"), vat=Decimal("5200"), subtotal=Decimal("52000"))
    v = survey.build(c, "2026-08-24")
    assert v["부가세"] == "5290" and v["실비합계"] == "58190"


def test_build_without_costs():
    v = survey.build(None, None)
    assert v["특별용역비"] == "0"           # 칸이 있는 폼은 0(전 은행 공통, 사용자 지시 2026-09-14)
    assert all(x is None for k, x in v.items() if k not in ("예외적용", "특별용역비"))
