"""엑셀 미수금 탭 시딩 (2026-08-27) — 정산월(K)·차감일(J)이 모두 빈 행만 미수금 회수(OTHER_DEDUCT) 대기로.

정산월이 적힌 행은 이미 그 달 AB 에서 회수된 것이고, 옛 행은 차감일(J) 열로 정산을 표시했다.
사람은 최근 행은 F열, 그 전엔 적요 끝 '-이름(직함)', 더 옛날엔 담당자(I) 열이다.
"""

from datetime import datetime

from scripts.seed_bonus_misugum import parse_open_items


def _row(day, remark, amount, *, name_col=None, manager=None, deduct="", settle=""):
    # 열 순서: A 전표일자 | B 전표번호 | C 감정서번호 | D 적요 | E 차변 | F (최근: 사람) | G | H 거래처 | I 담당자 | J 차감일 | K 정산월 | L 비고
    return (day, None, None, remark, amount, name_col, None, None, manager, deduct, settle, None)


ROWS = [
    _row(datetime(2026, 5, 6), "9708.05.05. 크라운호프 월곶점", 27_600, name_col="곽범석", settle="26.08월"),   # 이미 회수
    _row(datetime(2016, 7, 28), "0861.07.28. (주)대명레저-김정원", 80_000, manager="김정원", deduct="2016.08.19"),  # 옛 방식 정산
    _row(datetime(2026, 7, 27), "3083.07.25. 선물하기_카카오페이", 23_400, name_col="한경선"),                    # 미회수 (F열 이름)
    _row(datetime(2026, 3, 16), "1815.03.16. 주식회사캐슬렉스서울-정인수", 269_500),                              # 미회수 (적요 끝 이름)
    _row(datetime(2024, 5, 7), "인천수협 대위변제 - 서완석부회장", 243_003_208),                                  # 미회수 (직함 붙은 이름)
    _row(datetime(2024, 5, 7), "인천수협 경매취하비용 - 서완석부회장", 100_000),
    _row(datetime(2020, 3, 6), "회식", 100_000),                                                                  # 사람을 못 읽음
    _row(None, "머리글·메모 줄", None),                                                                            # 금액 없음 → 무시
]


def test_정산_안_된_행만_사람을_찾아_대기_항목으로_만든다():
    items, unknown = parse_open_items(ROWS)
    assert [(i["person"], i["amount"]) for i in items] == [
        ("한경선", 23_400), ("정인수", 269_500), ("서완석", 243_003_208), ("서완석", 100_000),
    ]
    first = items[0]
    assert first["kind"] == "OTHER_DEDUCT" and first["status"] == "PENDING" and first["source"] == "EXCEL"
    assert first["occurred_on"] == datetime(2026, 7, 27).date()
    assert first["source_key"] == "misu:20260727:한경선:23400"
    assert "선물하기" in first["memo"]
    assert unknown == [(9, "회식", 100_000)]                             # 3행부터 세므로 ROWS[6] = 9행


def test_같은_날_같은_사람_같은_금액이_두_건이면_키에_번호를_붙인다():
    items, _ = parse_open_items([
        _row(datetime(2026, 7, 8), "스타벅스(자동충전)", 50_000, name_col="조경미"),
        _row(datetime(2026, 7, 8), "스타벅스(자동충전)", 50_000, name_col="조경미"),
    ])
    assert [i["source_key"] for i in items] == ["misu:20260708:조경미:50000", "misu:20260708:조경미:50000:2"]
