"""입금 알림 큐 적재 — 범위 한정과 부트스트랩 가드 검증.

여기서 지키려는 것 두 가지:
  1) 부분 갱신의 큐 적재 범위가 스냅샷과 같아야 한다.
     안 그러면 스냅샷에 없는 51만 행이 전부 '신규 입금'으로 딸려 들어간다.
  2) 요약을 처음 채울 때(전체 재집계, 스냅샷 0행)는 큐에 넣지 않아야 한다.
"""

from unittest.mock import MagicMock

from app.services.receivable_summary import (
    rebuild_receivable_summary,
    rebuild_receivable_summary_for,
)


def _sql_texts(db):
    return [str(call[0][0]) for call in db.execute.call_args_list]


class TestPartialEnqueue:
    def _db(self, snapshot_rows=3):
        db = MagicMock()
        db.execute.return_value.rowcount = snapshot_rows
        return db

    def test_큐_적재가_대상_감정서로_한정된다(self):
        db = self._db()
        rebuild_receivable_summary_for(db, ["01-2607-3-0001", "01-2607-3-0002"])
        enqueue = next(s for s in _sql_texts(db) if "a10_payment_notify" in s)
        assert "AND s.doc_id IN (" in enqueue
        assert "CAST(:d0 AS VARCHAR(50))" in enqueue

    def test_늘어난_경우만_넣는다(self):
        db = self._db()
        rebuild_receivable_summary_for(db, ["01-2607-3-0001"])
        enqueue = next(s for s in _sql_texts(db) if "a10_payment_notify" in s)
        assert "s.received_amount > ISNULL(p.amount, 0)" in enqueue

    def test_스냅샷이_비어도_부분갱신은_큐에_넣는다(self):
        """새 감정서의 첫 입금도 알려야 한다 — 스냅샷에는 당연히 없다."""
        db = self._db(snapshot_rows=0)
        rebuild_receivable_summary_for(db, ["01-2607-3-9999"])
        assert any("a10_payment_notify" in s for s in _sql_texts(db))

    def test_스냅샷과_삭제와_적재가_같은_범위를_쓴다(self):
        db = self._db()
        rebuild_receivable_summary_for(db, ["01-2607-3-0001"])
        texts = _sql_texts(db)
        snapshot = next(s for s in texts if "#prev_received (doc_id, amount)" in s)
        delete = next(s for s in texts if "DELETE FROM dbo.a10_receivable_summary" in s)
        enqueue = next(s for s in texts if "a10_payment_notify" in s)
        for sql in (snapshot, delete, enqueue):
            assert "doc_id IN (CAST(:d0 AS VARCHAR(50)))" in sql

    def test_대상이_없으면_아무것도_안한다(self):
        db = self._db()
        assert rebuild_receivable_summary_for(db, []) == 0
        db.execute.assert_not_called()


class TestFullRebuildEnqueue:
    def test_첫_구축시에는_큐에_넣지_않는다(self):
        """스냅샷 0행 = 요약을 처음 채우는 것. 과거 입금 전부가 쏟아지면 안 된다."""
        db = MagicMock()
        db.execute.return_value.rowcount = 0
        rebuild_receivable_summary(db)
        assert not any("a10_payment_notify" in s for s in _sql_texts(db))

    def test_이미_채워져_있으면_큐에_넣는다(self):
        db = MagicMock()
        db.execute.return_value.rowcount = 500_000
        rebuild_receivable_summary(db)
        enqueue = [s for s in _sql_texts(db) if "a10_payment_notify" in s]
        assert len(enqueue) == 1
        # 전체 재집계는 스냅샷도 전체이므로 범위 조건이 붙지 않는다
        assert "AND s.doc_id IN" not in enqueue[0]

    def test_임시표를_매번_새로_만든다(self):
        db = MagicMock()
        db.execute.return_value.rowcount = 1
        rebuild_receivable_summary(db)
        texts = _sql_texts(db)
        assert any("DROP TABLE #prev_received" in s for s in texts)
        assert any("CREATE TABLE #prev_received" in s for s in texts)
