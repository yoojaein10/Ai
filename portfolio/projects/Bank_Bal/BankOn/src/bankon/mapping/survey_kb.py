"""국민 담보 **현장조사서**(TBNKKBB24Hyun) 매핑 — 우클릭 '현장조사서 작성(E)'. 정찰 2026-08-26(recon/fields_kb_damb.md).

신한(TBNKSHG24Hyun)과 칸이 다르다: 담당자 콤보(대표·평가사1~3·심사자) + 현장조사일 + 계좌 2칸 + 사업등록번호 +
교통비·물건조사비·공부발급비·기타실비(모두 '절사전 금액입력') + 부가세(자동계산 버튼) + 기타실비내용.
대응(초안 — 발송 실물 대조로 확정할 것):
    교통비      ← APW_Bill.YEBI
    물건조사비  ← APW_Bill.MULJOSABI
    공부발급비  ← APW_Bill.GONGBU
    기타실비    ← TOJOSABI + SILBI + YONGYEUK (국민 폼엔 토지조사비·사진비·특별용역비 칸이 없다)
    부가세      ← 항목합을 1,000원 절사 후 10% (작성폼 '실비-총액' 절사 규칙과 동일)
평가사명1 은 텍스트(9/11 이전 의뢰건용)와 **라벨 없는 콤보**(바로 아래 +24px)가 있어 콤보는 상대좌표로 잡는다.
"""
from __future__ import annotations

from decimal import Decimal

from .survey import SurveyCosts, _money

POSITIONAL = {
    "평가사콤보1": ("평가사명1", 0, 24, "TcxDBLookupComboBox"),   # 평가사명1 텍스트칸(@106,159) 아래 콤보(@130,159)
}


def _cut1000(value: Decimal) -> Decimal:
    return (value / 1000).to_integral_value(rounding="ROUND_DOWN") * 1000


def build(costs: SurveyCosts | None, context) -> dict[str, str | None]:
    c = costs or SurveyCosts()
    etc = [v for v in (c.land_survey, c.photo, c.special) if v]
    etc_sum = sum(etc, Decimal(0)) if etc else None
    items = [c.travel, c.object_survey, c.registry, etc_sum]
    vat = None
    if any(v is not None for v in items):
        vat = (_cut1000(sum((v or Decimal(0)) for v in items)) * Decimal("0.1")).quantize(Decimal(1))
    parties = context.parties
    return {
        "대표,지사장": parties.boss,
        "평가사콤보1": parties.appraiser(0),
        "평가사명2": parties.appraiser(1),
        "평가사명3": parties.appraiser(2),
        "심사자": parties.reviewer,
        "현장조사일": context.survey_date,
        # 계좌 2칸: 발송 실물(2418·2647) 비어 있음 + 화면 안내 "계좌정보는 법인별 고정값으로 변경" → 넣지 않는다.
        "사업등록번호": context.business_number,
        "교통비": _money(c.travel),
        "물건조사비": _money(c.object_survey),
        "공부발급비": _money(c.registry),
        "기타실비": _money(etc_sum),
        "부가세": _money(vat),
    }
