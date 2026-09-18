"""`.gam` 요약표 비고의 임대 단서 → 신한 `임대` 힌트(parse/rental)."""
from __future__ import annotations

from bankon.parse.characteristics import LEASE_PRESENT
from bankon.parse.rental import lease_hint


def test_월임대료_비고면_임대있음():
    # 실측 2831: bigo2 = '월 임대료 : 3,800,000원' 인데 자가사용으로 나갔다(2026-09-11).
    assert lease_hint({"outline6_na0": [{"bigo2": "월 임대료 : 3,800,000원", "bigo5": "근저당권"}]}) == LEASE_PRESENT
    assert lease_hint({"outline6_na1": [{"bigo1": "월임대료 33,000,000원"}]}) == LEASE_PRESENT
    assert lease_hint({"outline6_na0": [{"bigo3": "임차보증금 5,000만원"}]}) == LEASE_PRESENT


def test_단서가_없으면_None():
    assert lease_hint({"outline6_na0": [{"bigo5": "근저당권", "rental_lack": "360000000"}]}) is None
    assert lease_hint({"outline6_na0": [{"bigo1": "임대이상무."}]}) is None     # 임대료 언급이 아니다
    assert lease_hint({"land_list0": [{"BIGO": "월 임대료 100원"}]}) is None    # 요약표가 아니다
    assert lease_hint({}) is None and lease_hint(None) is None
