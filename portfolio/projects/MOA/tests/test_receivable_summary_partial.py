"""요약 부분 재집계 — 대상 감정서 수집과 SQL 조립 검증."""

from datetime import date
from unittest.mock import MagicMock

import pytest

from app.services.receivable_summary import rebuild_receivable_summary_for
from app.services.voucher_cache_sync import VoucherCacheSynchronizer


class TestRebuildFor:
    def test_빈_목록이면_아무것도_안한다(self):
        db = MagicMock()
        assert rebuild_receivable_summary_for(db, []) == 0
        db.execute.assert_not_called()
        db.commit.assert_not_called()

    def test_공백만_있는_값은_무시한다(self):
        db = MagicMock()
        assert rebuild_receivable_summary_for(db, ["", "   ", None]) == 0
        db.execute.assert_not_called()

    @staticmethod
    def _statements(db):
        """실행된 (SQL, 파라미터) 목록. 파라미터 없이 부른 문장도 섞여 있다."""
        return [
            (str(call[0][0]), call[0][1] if len(call[0]) > 1 else {})
            for call in db.execute.call_args_list
        ]

    def test_대상_감정서마다_삭제후_재삽입(self):
        db = MagicMock()
        db.execute.return_value.rowcount = 2
        rebuild_receivable_summary_for(db, ["01-2607-3-0001", "01-2607-3-0002"])
        stmts = self._statements(db)
        delete_sql, delete_params = next(
            s for s in stmts if "DELETE FROM dbo.a10_receivable_summary" in s[0]
        )
        insert_sql, _ = next(
            s for s in stmts if "INSERT INTO dbo.a10_receivable_summary" in s[0]
        )
        # varchar 컬럼 비교는 CAST 없이 바인드하면 풀스캔이 난다
        assert "CAST(:d0 AS VARCHAR(50))" in delete_sql
        assert "CAST(:d0 AS VARCHAR(50))" in insert_sql
        assert delete_params == {"d0": "01-2607-3-0001", "d1": "01-2607-3-0002"}
        db.commit.assert_called_once()

    def test_중복은_한번만_그리고_정렬된다(self):
        db = MagicMock()
        db.execute.return_value.rowcount = 1
        rebuild_receivable_summary_for(db, ["01-2607-3-0002", "01-2607-3-0002 ", "01-2607-3-0001"])
        _, params = next(
            s for s in self._statements(db)
            if "DELETE FROM dbo.a10_receivable_summary" in s[0]
        )
        assert params == {"d0": "01-2607-3-0001", "d1": "01-2607-3-0002"}

    def test_500건씩_나눠_넣는다(self):
        db = MagicMock()
        db.execute.return_value.rowcount = 0
        rebuild_receivable_summary_for(db, [f"01-2607-3-{i:04d}" for i in range(1200)])
        deletes = [
            s for s in self._statements(db)
            if "DELETE FROM dbo.a10_receivable_summary" in s[0]
        ]
        assert len(deletes) == 3  # 500 + 500 + 200
        assert len(deletes[0][1]) == 500
        assert len(deletes[-1][1]) == 200


class TestAffectedDocs:
    def _synchronizer(self, existing):
        sync = VoucherCacheSynchronizer.__new__(VoucherCacheSynchronizer)
        sync.db = MagicMock()
        sync.db.execute.return_value.scalars.return_value = existing
        return sync

    def test_삭제될_전표의_감정서도_포함한다(self):
        """Amaranth에서 전표를 지우면 새 목록엔 없다 — 기존 캐시를 안 훑으면 놓친다."""
        sync = self._synchronizer(["01-2607-3-0001", "01-2607-3-0009"])
        rows = [{"management_no": "01-2607-3-0001"}, {"management_no": "01-2607-3-0002"}]
        found = sync._affected_docs(date(2026, 7, 1), date(2026, 7, 7), rows)
        assert found == {"01-2607-3-0001", "01-2607-3-0002", "01-2607-3-0009"}

    def test_관리번호_없는_행은_제외(self):
        sync = self._synchronizer([])
        rows = [{"management_no": None}, {"management_no": "  "}, {"management_no": "01-2607-3-0003"}]
        assert sync._affected_docs(date(2026, 7, 1), date(2026, 7, 7), rows) == {"01-2607-3-0003"}


class TestSyncWiring:
    @pytest.mark.parametrize("partial", [True, False])
    def test_partial_summary_플래그가_경로를_가른다(self, partial, monkeypatch):
        sync = VoucherCacheSynchronizer.__new__(VoucherCacheSynchronizer)
        sync.db = MagicMock()
        sync.progress = lambda _msg: None
        sync.db.execute.return_value.scalars.return_value = ["01-2607-3-0001"]

        calls = {"full": 0, "part": 0}
        monkeypatch.setattr(
            "app.services.receivable_summary.rebuild_receivable_summary",
            lambda db: calls.__setitem__("full", calls["full"] + 1) or 5,
        )
        monkeypatch.setattr(
            "app.services.receivable_summary.rebuild_receivable_summary_for",
            lambda db, docs: calls.__setitem__("part", calls["part"] + 1) or 1,
        )
        monkeypatch.setattr(
            "app.services.voucher_cache_sync._company_code", lambda *a, **k: "1000"
        )
        monkeypatch.setattr(
            "app.services.voucher_cache_sync._division_codes", lambda *a, **k: ["10"]
        )
        sync.client = MagicMock()
        sync.client.post.return_value = {"resultData": {"datas": [], "allCount": 0}}

        sync.sync(date(2026, 7, 1), date(2026, 7, 7), partial_summary=partial)
        assert calls["part"] == (1 if partial else 0)
        assert calls["full"] == (0 if partial else 1)
