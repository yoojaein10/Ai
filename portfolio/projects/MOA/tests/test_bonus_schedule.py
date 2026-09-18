"""주주 상여율 스케줄 — 엑셀 합계행 라벨을 (사람, 접수일 구간) 표로 바꾼다.

라벨 31종은 ★★2026년 성과상여.xlsx 9개월 주주 시트 전체에서 나온 것 그대로다
(2026-08-25 seed_report). 구간은 양끝 포함 — 이영준 '~2026년 7월7일' 블록에
접수 07-07 건이 실제로 들어 있었다.
"""

from datetime import date

import pytest

from app.services.bonus.schedule import (
    BonusMasterError,
    RateBlock,
    normalize_blocks,
    parse_rate_label,
    rate_for,
)

Y2019 = (date(2019, 1, 1), date(2019, 12, 31))
LABELS = [
    ("2020년~2021년 2월", [(date(2020, 1, 1), date(2021, 2, 28))]),
    ("2019년분/2021년 3월~", [Y2019, (date(2021, 3, 1), None)]),
    ("2022년 7월~", [(date(2022, 7, 1), None)]),
    ("2022년 03월 ~", [(date(2022, 3, 1), None)]),
    ("2024년 7월~", [(date(2024, 7, 1), None)]),
    ("2021년 3월~2022년 06월", [(date(2021, 3, 1), date(2022, 6, 30))]),
    ("2019년분/2021년 3월~2022년 02월", [Y2019, (date(2021, 3, 1), date(2022, 2, 28))]),
    ("2019년분", [Y2019]),
    ("2019년분/2021년 3월~ 2025년 12월 10일까지", [Y2019, (date(2021, 3, 1), date(2025, 12, 10))]),
    ("2024년 7월 1일~", [(date(2024, 7, 1), None)]),
    ("2022년 7월~24년 6월까지", [(date(2022, 7, 1), date(2024, 6, 30))]),
    ("2019년분/2021년 3월~24년 12월까지", [Y2019, (date(2021, 3, 1), date(2024, 12, 31))]),
    ("2025년 7월 7일 접수분~", [(date(2025, 7, 7), None)]),
    ("2022년 7월~ 2025년 7월 6일 접수분까지", [(date(2022, 7, 1), date(2025, 7, 6))]),
    ("2023.6.12일부터", [(date(2023, 6, 12), None)]),
    ("2019년분/2021년 3월~ 2023년 12월 접수분까지", [Y2019, (date(2021, 3, 1), date(2023, 12, 31))]),
    ("2025년 02월 18일 ~", [(date(2025, 2, 18), None)]),
    ("2023.01~", [(date(2023, 1, 1), None)]),
    ("2019년분/2021년 3월~2023.12", [Y2019, (date(2021, 3, 1), date(2023, 12, 31))]),
    ("2022년 07월~", [(date(2022, 7, 1), None)]),
    ("2021년 3월~2022년 6월", [(date(2021, 3, 1), date(2022, 6, 30))]),
    ("2025.10월~", [(date(2025, 10, 1), None)]),
    ("2019년분/2021년 3월~2022/12", [Y2019, (date(2021, 3, 1), date(2022, 12, 31))]),
    ("2019년분/2021년 3월~2025년 3월 3일", [Y2019, (date(2021, 3, 1), date(2025, 3, 3))]),
    ("2026년 7월~", [(date(2026, 7, 1), None)]),
    ("2019년분/2021년 3월~ 2024년 12월 접수분까지", [Y2019, (date(2021, 3, 1), date(2024, 12, 31))]),
    ("2019년분/2021년 3월~ 25년 12월까지", [Y2019, (date(2021, 3, 1), date(2025, 12, 31))]),
    ("2019년분/2021년 3월~21년 12월까지", [Y2019, (date(2021, 3, 1), date(2021, 12, 31))]),
    ("2019년분/2021년 3월~ 24년 12월까지", [Y2019, (date(2021, 3, 1), date(2024, 12, 31))]),
    ("2026년 7월 8일~", [(date(2026, 7, 8), None)]),
    ("2024년 7월~2026년 7월7일", [(date(2024, 7, 1), date(2026, 7, 7))]),
]


@pytest.mark.parametrize("label,expected", LABELS, ids=[label for label, _ in LABELS])
def test_엑셀_라벨_31종을_전부_구간으로_읽는다(label, expected):
    assert parse_rate_label(label) == expected


def test_라벨이_비거나_날짜가_없으면_구간이_없다():
    assert parse_rate_label("") == []
    assert parse_rate_label(None) == []
    assert parse_rate_label("정산 예정") == []


def _blocks(*items):
    return normalize_blocks([RateBlock("노승환", f, t, r, "") for f, t, r in items])


def test_접수일이_구간_안이면_그_요율이고_양끝을_포함한다():
    blocks = _blocks((date(2022, 7, 1), date(2025, 7, 6), 30), (date(2025, 7, 7), None, 40))
    assert rate_for(blocks, date(2025, 7, 6)) == (30, date(2022, 7, 1), "SCHEDULE")
    assert rate_for(blocks, date(2025, 7, 7)) == (40, date(2025, 7, 7), "SCHEDULE")
    assert rate_for(blocks, date(2026, 8, 25)) == (40, date(2025, 7, 7), "SCHEDULE")


def test_구간_밖이면_가장_최근_블록으로_폴백하고_표시한다():
    blocks = _blocks((date(2022, 7, 1), date(2025, 7, 6), 30), (date(2025, 7, 7), None, 40))
    assert rate_for(blocks, date(2020, 1, 1)) == (40, date(2025, 7, 7), "FALLBACK_LATEST")
    assert rate_for(blocks, None) == (40, date(2025, 7, 7), "FALLBACK_LATEST")
    gap = _blocks((date(2019, 1, 1), date(2019, 12, 31), 40), (date(2021, 3, 1), None, 40))
    assert rate_for(gap, date(2020, 6, 1)) == (40, date(2021, 3, 1), "FALLBACK_LATEST")


def test_블록이_없으면_요율도_없다():
    assert rate_for([], date(2026, 1, 1)) == (None, None, "NONE")


def test_처음부터_계속인_블록은_모든_날짜에_맞는다():
    blocks = _blocks((None, None, 40))
    assert rate_for(blocks, date(1999, 1, 1)) == (40, None, "SCHEDULE")


def test_겹치는_구간은_저장_전에_거부한다():
    with pytest.raises(BonusMasterError):
        _blocks((date(2022, 7, 1), None, 30), (date(2024, 7, 1), None, 40))
    with pytest.raises(BonusMasterError):
        _blocks((date(2024, 7, 1), date(2023, 1, 1), 30))
    # 맞닿은 구간(6일까지 / 7일부터)은 겹침이 아니다
    _blocks((date(2022, 7, 1), date(2025, 7, 6), 30), (date(2025, 7, 7), None, 40))


def test_정규화는_시작일_순으로_정렬한다():
    blocks = _blocks((date(2025, 7, 7), None, 40), (None, date(2019, 12, 31), 45), (date(2021, 3, 1), date(2025, 7, 6), 30))
    assert [b.rate for b in blocks] == [45, 30, 40]
