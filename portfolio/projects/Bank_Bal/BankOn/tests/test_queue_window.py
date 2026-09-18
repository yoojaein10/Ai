"""큐 워커의 BANK24 조회기간 — 하루짜리 조회가 실패를 낳았다(2780, 2026-09-08).

BANK24 목록은 **의뢰일자(은행 발송 시각)** 기준으로 조회되고 APW RequestDate 는 우리 접수일이라
하루 어긋난다(2780: 의뢰일자 09-03 18:23 / APW 09-04). 기간에 앞뒤 여유가 있어야 한다.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import run_queue_worker as W  # noqa: E402


class TestQueryWindow:
    def test_2780_의뢰일자_전날저녁도_덮는다(self):
        start, end = W.query_window(dt.date(2026, 9, 4))
        assert start <= "2026-09-03" <= end          # BANK24 의뢰일자 09-03 18:23
        assert start <= "2026-09-04" <= end          # APW 의뢰일 당일

    def test_기본_여유는_앞3일_뒤1일(self):
        assert W.query_window(dt.date(2026, 9, 4)) == ("2026-09-01", "2026-09-05")

    def test_형식은_YYYY_MM_DD(self):
        start, end = W.query_window(dt.date(2026, 1, 2), before=5, after=0)
        assert (start, end) == ("2025-12-28", "2026-01-02")

    def test_넓은_기간은_2701_같은_9일_차이도_덮는다(self):
        # 2701: APW 의뢰일 08-25, Bank24 의뢰일자 09-03 (설치안내 2026-09-07 '조회기간 밖 실패' 사례)
        start, end = W.query_window(dt.date(2026, 8, 25), before=W.QUERY_WIDE_BEFORE, after=W.QUERY_WIDE_AFTER)
        assert start <= "2026-09-03" <= end

    def test_재시도_판별_문구는_navigate_와_같다(self):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
        from bankon.ui import navigate
        import inspect
        assert W.NOT_IN_LIST in inspect.getsource(navigate.ensure_row)
