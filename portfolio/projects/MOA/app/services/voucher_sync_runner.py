"""전표 캐시 동기화 실행 정책.

자동 배치와 관리자 수동 실행이 같은 DB 잠금을 사용해 서로 겹치지 않게 한다.
장기간 동기화는 월 단위로 나눠 처리하고, 입금·미수 요약은 마지막에 한 번만
재집계한다.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from typing import Any

from sqlalchemy import text

from app.database import get_engine, get_session_factory
from app.services.payment_sms import auto_send_pending, reconcile_sent_from_log
from app.services.payment_status import (
    reconcile_payment_status_with_master,
    refresh_payment_status,
    refresh_payment_status_for,
)
from app.services.receivable_summary import rebuild_receivable_summary
from app.services.voucher_cache_sync import VoucherCacheSynchronizer

LOCK_RESOURCE = "A10Bridge_VoucherCacheSync"


class VoucherSyncAlreadyRunning(RuntimeError):
    """다른 프로세스에서 전표 동기화를 이미 실행 중이다."""


def month_ranges(date_from: date, date_to: date) -> list[tuple[date, date]]:
    """지정 기간을 달력 월 경계로 나눈다."""
    if date_from > date_to:
        raise ValueError("시작일은 종료일보다 늦을 수 없습니다.")

    ranges: list[tuple[date, date]] = []
    current = date_from
    while current <= date_to:
        if current.month == 12:
            next_month = date(current.year + 1, 1, 1)
        else:
            next_month = date(current.year, current.month + 1, 1)
        chunk_to = min(date_to, next_month - timedelta(days=1))
        ranges.append((current, chunk_to))
        current = chunk_to + timedelta(days=1)
    return ranges


@contextmanager
def voucher_sync_lock() -> Iterator[None]:
    """SQL Server 세션 잠금으로 자동·수동 동기화의 프로세스 간 중복을 막는다."""
    connection = get_engine().connect()
    acquired = False
    try:
        result = connection.execute(
            text(
                """
                DECLARE @result int;
                EXEC @result = sys.sp_getapplock
                    @Resource = :resource,
                    @LockMode = 'Exclusive',
                    @LockOwner = 'Session',
                    @LockTimeout = 0;
                SELECT @result;
                """
            ),
            {"resource": LOCK_RESOURCE},
        ).scalar_one()
        acquired = int(result) >= 0
        if not acquired:
            raise VoucherSyncAlreadyRunning(
                "다른 전표 동기화가 실행 중입니다. 완료 후 다시 시도하세요."
            )
        yield
    finally:
        if acquired:
            try:
                connection.execute(
                    text(
                        """
                        EXEC sys.sp_releaseapplock
                            @Resource = :resource,
                            @LockOwner = 'Session';
                        """
                    ),
                    {"resource": LOCK_RESOURCE},
                )
            finally:
                connection.close()
        else:
            connection.close()


def execute_voucher_sync(
    date_from: date,
    date_to: date,
    *,
    monthly_chunks: bool = False,
    partial_summary: bool = False,
    progress: Callable[[str], None] = print,
) -> dict[str, Any]:
    """공통 잠금을 잡고 기간 전표를 동기화한다.

    partial_summary=True면 전표가 바뀐 감정서만 요약을 갈아끼운다(짧은 주기 배치용).
    전체 재집계가 주는 자동 복구를 포기하는 대신 훨씬 빠르다 —
    야간 심층 동기화는 계속 전체 재집계로 돌려 어긋남을 덮어야 한다.
    """
    if date_from > date_to:
        raise ValueError("시작일은 종료일보다 늦을 수 없습니다.")

    chunks = month_ranges(date_from, date_to) if monthly_chunks else [(date_from, date_to)]
    totals: dict[str, Any] = {
        "fetched": 0,
        "stored": 0,
        "pages": 0,
        "summary_rows": 0,
        "payment_rows": 0,
        "payment_reconciled": 0,
        "chunks_completed": 0,
        "chunks_total": len(chunks),
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
    }

    with voucher_sync_lock():
        with get_session_factory()() as db:
            synchronizer = VoucherCacheSynchronizer(db, progress=progress)
            cache_changed = False
            affected_docs: set[str] = set()
            try:
                for index, (chunk_from, chunk_to) in enumerate(chunks, start=1):
                    progress(
                        f"기간 {index}/{len(chunks)} "
                        f"({chunk_from.isoformat()}~{chunk_to.isoformat()})"
                    )
                    result = synchronizer.sync(
                        chunk_from,
                        chunk_to,
                        rebuild_summary=not monthly_chunks,
                        partial_summary=partial_summary,
                    )
                    cache_changed = True
                    totals["fetched"] += int(result["fetched"])
                    totals["stored"] += int(result["stored"])
                    totals["pages"] += int(result["pages"])
                    totals["chunks_completed"] = index
                    affected_docs.update(result.get("affected_docs") or ())
                    if not monthly_chunks:
                        totals["summary_rows"] = int(result["summary_rows"])
            finally:
                # 월별 처리 중 뒤쪽 월에서 실패해도 앞서 반영된 월과 요약 캐시가
                # 서로 어긋나지 않도록 완료된 변경분을 기준으로 재집계한다.
                if monthly_chunks and cache_changed:
                    progress("입금·미수 요약 재집계 중")
                    totals["summary_rows"] = rebuild_receivable_summary(db)
            # 입금 결과(a10_payment_status)도 요약과 같이 갱신 — 입금발송내역이
            # 배치 주기(10분)마다 최신화된다. 부분 동기화는 바뀐 감정서만 MERGE.
            # 야간 PaymentSync(22:30)도 그대로 둔다 — 배분 초안은 이제 여기서도 만든다(아래, 2026-09-14).
            if cache_changed:
                progress("입금 결과(payment_status) 갱신 중")
                totals["payment_rows"] = (
                    refresh_payment_status_for(db, affected_docs)
                    if partial_summary else refresh_payment_status(db)
                )
                # APWorks 청구금액만 수정된 건은 affected_docs에 들어오지 않는다.
                # 전표 부분 동기화 뒤에도 전체 저장 상태를 최신 APWorks와 대조해
                # 잘못 남은 완납/부분입금을 고친다. 야간 1년치 집계에서는 전체
                # MERGE 뒤의 명시적인 사후 검증 역할도 한다.
                progress("APWorks 청구액과 입금 판정 재대조 중")
                totals["payment_reconciled"] = reconcile_payment_status_with_master(db)
                if totals["payment_reconciled"]:
                    progress(
                        "입금 판정 보정 "
                        f"{totals['payment_reconciled']:,}건"
                    )
                # 입금 적용용 계산서 — 새 입금이 잡힌 감정서에 모계산서 잔액을 나눠 붙인다 (2026-09-10).
                # 실패해도 동기화 본체를 멈추지 않는다.
                try:
                    from app.services.invoice_pool import apply_all as apply_invoice_pools
                    pool_result = apply_invoice_pools(db)
                    if pool_result["applied"]:
                        totals["pool_applied"] = pool_result["applied"]
                        progress(f"입금 적용용 계산서 {pool_result['applied']}건 적용 ({pool_result['amount']:,}원)")
                except Exception as exc:      # noqa: BLE001
                    progress(f"입금 적용용 계산서 적용 실패: {exc}")

                # 유치실적(수수료 배분) 초안 — 완납이 잡히면 몇 분 안에 대기 목록에 뜨게 (2026-09-14 사용자).
                # 전에는 야간 PaymentSync(22:30)에서만 만들어 아침에 들어온 매출 전표로 완납된 건이 그날 밤까지
                # 안 보였다(01-2608-3-2607). 입금 판정을 맞춘 뒤라야 완납 게이트가 맞다. 이미 초안이 있으면
                # 건너뛰므로 여러 번 돌아도 같다. 실패해도 동기화 본체를 멈추지 않는다.
                try:
                    from app.services.gaprice_outbox import generate_gaprice_drafts
                    drafts = generate_gaprice_drafts(db)
                    if drafts:
                        totals["gaprice_drafts"] = drafts
                        progress(f"유치실적 배분 초안 {drafts}건 생성")
                except Exception as exc:      # noqa: BLE001
                    db.rollback()             # 실패한 문장이 세션을 막지 않게 — 뒤의 알림톡 보정이 이어서 돈다
                    progress(f"유치실적 배분 초안 생성 실패: {exc}")

                # 큐를 실제 발송 이력에 맞춘다 — 화면의 '미전송처리'가 sent_at 을
                # 지워서, 실제로 나간 건이 '미처리'로 남는 일이 있었다 (2026-08-21).
                # 이력(BIZ_LOG)은 지울 수 없으므로 그걸 기준으로 되채운다.
                # 실패해도 동기화 본체를 멈추지 않는다 — 표시가 늦을 뿐이다.
                try:
                    fixed = reconcile_sent_from_log(db)
                    if fixed:
                        totals["alert_reconciled"] = fixed
                        progress(f"알림톡 전송 기록 보정 {fixed}건")
                except Exception as exc:      # noqa: BLE001 - 보정 실패는 알리고 넘어간다
                    progress(f"알림톡 전송 기록 보정 실패: {exc}")

                # 입금내역 알림톡 자동 발송 — PAYMENT_ALERT_AUTO_SEND=true일 때만
                # (fail-closed). 대상: 최근 N일 입금완료·미전송·수신자 있는 건.
                alert_result = auto_send_pending(db)
                if alert_result is not None:
                    totals["alert_docs"] = alert_result["docs_sent"]
                    progress(
                        f"입금 알림톡 {alert_result['docs_sent']}건 큐잉"
                        f"{' (테스트 번호)' if alert_result['test_mode'] else ''}"
                    )

    progress(
        f"전표 동기화 완료: {totals['stored']:,}건, "
        f"{totals['chunks_completed']}/{totals['chunks_total']}개 기간"
    )
    return totals
