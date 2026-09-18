"""기업 담보 **현장조사서**(TBNKKIB24Hyun) 매핑 — 우클릭 '현장조사서 작성(E)'. 정찰 2026-08-28(recon/fields_ibk_damb.md).

신한·국민과 달리 실비를 **세분 항목**으로 받고 소계 4개(여 비·물건조사비·공부발급비·기타실비)는 '자동계산' 이다.
발송 실물 2704·2683 과 APW_Bill 대조로 확정한 관계:

    교통비          ← YEBI (40,000)          출장회수·출장인원 ← 1 (두 건 모두)         여 비 = 교통비+일비+숙박비+식비
    건물조사비용    ← MULJOSABI (10,000)     건물수 ← 건물 동 수(2683: 1)               물건조사비 = 건물조사비용
    등기사항전부증명서 건수 ← 공부스캔 고유번호 수(2704: 1, 2683: 2) · 비용 = 건수 × 1,000
    토지이용계획확인원 건수 ← 필지 수(공부스캔 토지 행 지번; 2719 구분건물 2필지 = 2건 실측) · 비용 = 건수 × 1,000
    일반건축물대장 비용 ← GONGBU − 등기비용 − 토지이용비용 (2683: 8,400−2,000−1,000 = 5,400 ✓; 건수 4 는 출처 불명 → 비움)
    공부발급비 = 등기+토지대장+건축물대장+지적도+토지이용 비용 = GONGBU
    사진 매수·비용  ← SILBI 가 1,000 단위면 매수 = SILBI/1,000 · 비용 = SILBI (2704: 4매 4,000)
                      아니면 bill30 area6 메모(담당자 실비 내역, context.expense_note)에서 '사진 N' 을 찾아
                      사진 비용으로, 나머지(SILBI−사진)는 임대차확인 비용으로 분해(2743: 11,400 = 사진 6,000
                      + 전입+교통비 5,400, 2026-09-02). 메모도 없으면 비움 → 사람이 넣음(fail-closed 거부)
    기타실비 = 사진 비용 + 임대차확인 비용 = SILBI
소계 4칸은 자동계산이라도 기대값을 함께 내서 드라이런 대조(일치/채움)에 쓴다. 0 은 form.is_blank 가드로 비워진다.
"""
from __future__ import annotations

import re
from decimal import Decimal

from .ibk import OBJECT_BUILDING, OBJECT_LAND, split_objects
from .survey import SurveyCosts, _money

# '자동계산' 소계 — 읽기전용. LIVE 는 칸 옆 '자동계산' 버튼 4개를 눌러 채운 뒤 이 기대값과 대조한다(autofill_survey, 2026-09-01).
AUTO_FIELDS = frozenset({"여 비", "물건조사비", "공부발급비", "기타실비"})

UNIT_REGISTRY = Decimal(1000)       # 등기사항전부증명서 1건 비용
UNIT_LAND_USE = Decimal(1000)       # 토지이용계획확인원 1건 비용
UNIT_PHOTO = Decimal(1000)          # 사진 1매 비용


def _count(value: int) -> str | None:
    return str(value) if value else None


def _photo_from_note(note: str | None) -> Decimal | None:
    """bill30 area6 실비 메모에서 사진 비용을 찾는다('사진 6,000')."""
    if not note:
        return None
    m = re.search(r"사진\s*([\d,]+)", note)
    if not m:
        return None
    amount = Decimal(m.group(1).replace(",", ""))
    return amount if amount > 0 else None


def build(costs: SurveyCosts | None, context) -> dict[str, str | None]:
    c = costs or SurveyCosts()
    specs = split_objects(context.details)
    registry_n = len({g.unique_no for g in context.gongbu if g.unique_no})
    # 토지이용계획확인원 건수 = 필지 수. 공부스캔 토지 행의 지번(구분건물도 대지권 필지가 다 있음: 2719 555-42·555-43 = 2건)이 우선,
    # 없으면 명세표 토지 물건, 그래도 없으면 1.
    scan_parcels = {re.sub(r"\s+", "", g.address.rsplit(" ", 1)[-1]) for g in context.gongbu if g.is_land and g.address}
    parcel_n = len(scan_parcels) or len({(s.head.jibun or "").strip() for s in specs if s.kind == OBJECT_LAND}) or (1 if specs else 0)
    building_n = len({id(s.head) for s in specs if s.kind == OBJECT_BUILDING})
    if c.registry is not None and c.registry <= 0:
        # APW 공부발급비(GONGBU)가 0 이면 공부 항목을 하나도 청구하지 않은 건 — 공부스캔에 등기·필지가 있어도 건수·비용을 비운다
        # (2387: 등기 2·필지 2 를 세어 4,000 을 넣으면 실비 합 93,000 과 어긋남, 2026-09-01).
        registry_n = parcel_n = 0

    registry_cost = UNIT_REGISTRY * registry_n if registry_n else None
    land_use_cost = UNIT_LAND_USE * parcel_n if parcel_n else None
    building_ledger = None
    if c.registry is not None:
        rest = c.registry - (registry_cost or 0) - (land_use_cost or 0)
        building_ledger = rest if rest > 0 else None

    photo_n = photo_cost = rental_cost = None
    if c.photo is not None and c.photo > 0:
        if c.photo % UNIT_PHOTO == 0:
            photo_n, photo_cost = int(c.photo / UNIT_PHOTO), c.photo
        else:
            # 1,000 단위가 아니면 혼합(사진+임대차 등) — area6 메모의 사진 금액으로 분해한다.
            memo_photo = _photo_from_note(getattr(context, "expense_note", None))
            if memo_photo is not None and memo_photo < c.photo:
                photo_cost, rental_cost = memo_photo, c.photo - memo_photo
                if memo_photo % UNIT_PHOTO == 0:
                    photo_n = int(memo_photo / UNIT_PHOTO)

    travel = c.travel
    return {
        "평가사명": context.parties.appraiser(0),
        "교통비": _money(travel),
        "일 비": None, "숙박비": None, "식 비": None,
        "출장회수": "1" if travel else None,
        "출장인원": "1" if travel else None,
        "여 비": _money(travel),
        "건물수": _count(building_n),
        "건물조사비용": _money(c.object_survey),
        "물건조사비": _money(c.object_survey),
        "등기사항전부증명서 건수": _count(registry_n),
        "등기사항전부증명서 비용": _money(registry_cost),
        "토지(임야)대장 건수": None, "토지(임야)대장 비용": None,
        "일반건축물대장 건수": None,
        "일반건축물대장 비용": _money(building_ledger),
        "지적도(임야도) 건수": None, "지적도(임야도) 비용": None,
        "토지이용계획확인원 건수": _count(parcel_n),
        "토지이용계획확인원 비용": _money(land_use_cost),
        "공부발급비": _money(c.registry),
        "사진 매수": _count(photo_n or 0),
        "사진 비용": _money(photo_cost),
        "임대차확인 비용": _money(rental_cost),
        "기타실비": _money(c.photo),
    }
