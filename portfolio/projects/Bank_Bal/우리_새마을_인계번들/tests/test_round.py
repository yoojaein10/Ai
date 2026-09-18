"""감정평가표 머리말(`round*`) 파싱."""
from __future__ import annotations

from decimal import Decimal

from bankon.parse import round as round_parse

# 실측 01-2608-3-2625 round0.
ROUND0 = {
    "par_player": "김기석", "inspection": "최병산",
    "custpart": "농협은행 성동금융센터장", "debtor": "주식회사안현",
    "ownername": "주식회사안현", "category": "구분건물",
    "round_price": "1103000000", "atitle": "(구분건물)감정평가표",
    "round_memo": "집계명세표 : 구분건물명세표",
}


class TestParse:
    def test_머리말을_읽는다(self):
        (info,) = round_parse.parse({"round0": [ROUND0]})
        assert info.appraiser == "김기석" and info.reviewer == "최병산"
        assert info.client == "농협은행 성동금융센터장"
        assert info.owner == "주식회사안현" and info.category == "구분건물"
        assert info.amount == Decimal("1103000000")

    def test_줄바꿈을_한_칸으로(self):
        # catalogue 처럼 줄바꿈이 든 칸이 있다 — 이름·의뢰처도 마찬가지라 정리한다.
        (info,) = round_parse.parse({"round0": [{"custpart": "농협은행\n\n보문동지점장"}]})
        assert info.client == "농협은행 보문동지점장"

    def test_표가_여러장이면_번호순으로(self):
        # 실측 2645: 물건마다 감정평가표가 따로라 표별 총액이 다르다.
        rounds = round_parse.parse({
            "round1": [{"round_price": "338000000", "ownername": "이종림"}],
            "round0": [{"round_price": "338000000", "ownername": "이종림"}],
        })
        assert [r.index for r in rounds] == [0, 1]

    def test_서식행_테이블은_무시한다(self):
        assert round_parse.parse({"round_20": [{"ownername": "무시"}]}) == ()

    def test_빈_입력(self):
        assert round_parse.parse({}) == ()
        assert round_parse.first(()).owner is None
        assert round_parse.first(round_parse.parse({"round0": [ROUND0]})).owner == "주식회사안현"
