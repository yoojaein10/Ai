from argparse import Namespace
from contextlib import contextmanager
from datetime import date

import pytest
from pydantic import ValidationError

from app.batch.voucher_cache_sync import _resolve_period
from app.routers.cache_admin import SyncRequest
from app.services import voucher_sync_runner
from app.services.voucher_sync_runner import month_ranges


def test_month_ranges_splits_on_calendar_month_boundaries():
    assert month_ranges(date(2026, 1, 15), date(2026, 3, 5)) == [
        (date(2026, 1, 15), date(2026, 1, 31)),
        (date(2026, 2, 1), date(2026, 2, 28)),
        (date(2026, 3, 1), date(2026, 3, 5)),
    ]


def test_month_ranges_handles_leap_year():
    assert month_ranges(date(2024, 2, 1), date(2024, 3, 1)) == [
        (date(2024, 2, 1), date(2024, 2, 29)),
        (date(2024, 3, 1), date(2024, 3, 1)),
    ]


def test_month_ranges_rejects_reverse_period():
    with pytest.raises(ValueError):
        month_ranges(date(2026, 2, 1), date(2026, 1, 31))


def test_batch_resolves_days_and_explicit_period():
    by_days = Namespace(days=7, date_from=None, date_to=None)
    assert _resolve_period(by_days, date(2026, 7, 23)) == (
        date(2026, 7, 17),
        date(2026, 7, 23),
    )

    explicit = Namespace(
        days=None,
        date_from=date(2026, 1, 1),
        date_to=date(2026, 1, 31),
    )
    assert _resolve_period(explicit, date(2026, 7, 23)) == (
        date(2026, 1, 1),
        date(2026, 1, 31),
    )


def test_sync_request_accepts_days_or_range_but_not_both():
    assert SyncRequest(days=60).days == 60
    request = SyncRequest(date_from=date(2026, 1, 1), date_to=date(2026, 1, 31))
    assert request.resolve_period() == (
        date(2026, 1, 1),
        date(2026, 1, 31),
        "range",
    )

    with pytest.raises(ValidationError):
        SyncRequest()
    with pytest.raises(ValidationError):
        SyncRequest(
            days=60,
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 31),
        )
    with pytest.raises(ValidationError):
        SyncRequest(date_from=date(2026, 1, 31), date_to=date(2026, 1, 1))


def test_monthly_execute_aggregates_chunks_and_rebuilds_summary_once(monkeypatch):
    @contextmanager
    def fake_lock():
        yield

    class FakeDb:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

    class FakeFactory:
        def __call__(self):
            return FakeDb()

    calls = []

    class FakeSynchronizer:
        def __init__(self, db, *, progress):
            self.progress = progress

        def sync(self, date_from, date_to, *, rebuild_summary, partial_summary=False):
            calls.append((date_from, date_to, rebuild_summary, partial_summary))
            return {
                "fetched": 10,
                "stored": 10,
                "pages": 1,
                "summary_rows": 0,
            }

    summary_calls = []
    payment_calls = []
    monkeypatch.setattr(voucher_sync_runner, "voucher_sync_lock", fake_lock)
    monkeypatch.setattr(voucher_sync_runner, "get_session_factory", lambda: FakeFactory())
    monkeypatch.setattr(voucher_sync_runner, "VoucherCacheSynchronizer", FakeSynchronizer)
    monkeypatch.setattr(
        voucher_sync_runner,
        "rebuild_receivable_summary",
        lambda db: summary_calls.append(db) or 123,
    )
    monkeypatch.setattr(
        voucher_sync_runner,
        "refresh_payment_status",
        lambda db: payment_calls.append(db) or 45,
    )

    result = voucher_sync_runner.execute_voucher_sync(
        date(2026, 1, 15),
        date(2026, 3, 5),
        monthly_chunks=True,
        progress=lambda message: None,
    )

    # 월별 분할(야간 심층)은 청크마다 재집계하지 않고 마지막에 전체로 한 번만 —
    # 부분 갱신도 쓰지 않는다(전체 재집계가 부분 갱신의 어긋남을 덮는 역할).
    assert calls == [
        (date(2026, 1, 15), date(2026, 1, 31), False, False),
        (date(2026, 2, 1), date(2026, 2, 28), False, False),
        (date(2026, 3, 1), date(2026, 3, 5), False, False),
    ]
    assert len(summary_calls) == 1
    # 입금 결과(a10_payment_status)도 동기화 마지막에 1회 갱신 — 입금문자내역 매시간 최신화
    assert len(payment_calls) == 1
    assert result["stored"] == 30
    assert result["pages"] == 3
    assert result["summary_rows"] == 123
    assert result["payment_rows"] == 45
    assert result["chunks_completed"] == 3
    assert result["chunks_total"] == 3
