"""APScheduler integration for recurring leave jobs (PHASE 14).

Jobs:
- `leave_monthly_accrual` — 매월 1일 00:05 KST: grant +1 day to every <1yr emp
- `leave_yearly_reset` — 매년 1/1 00:10 KST: expire or carry-over + new-year grant

Idempotency: service functions check `insa_scheduler_lock` before writing. Even
if APScheduler misfires or the process restarts mid-month, a duplicate job
invocation is a no-op.

Toggle with `SCHEDULER_ENABLED=false` for local/dev environments.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.db.session import SessionLocal

logger = logging.getLogger("insa.scheduler")

_scheduler: Optional[BackgroundScheduler] = None


def _run_monthly_accrual() -> None:
    today = date.today()
    db = SessionLocal()
    try:
        from app.services.leave_service import monthly_accrual

        granted = monthly_accrual(db, today.year, today.month)
        logger.info(
            "leave_monthly_accrual year=%s month=%s granted=%s",
            today.year,
            today.month,
            granted,
        )
    except Exception as exc:
        logger.exception("leave_monthly_accrual failed: %s", exc)
        db.rollback()
    finally:
        db.close()


def _run_yearly_reset() -> None:
    today = date.today()
    db = SessionLocal()
    try:
        from app.services.leave_service import yearly_reset

        result = yearly_reset(db, today.year)
        logger.info("leave_yearly_reset year=%s result=%s", today.year, result)
    except Exception as exc:
        logger.exception("leave_yearly_reset failed: %s", exc)
        db.rollback()
    finally:
        db.close()


def start_scheduler() -> Optional[BackgroundScheduler]:
    """Start the background scheduler. No-op when disabled."""
    global _scheduler
    if not settings.SCHEDULER_ENABLED:
        logger.info("scheduler disabled (SCHEDULER_ENABLED=false)")
        return None
    if _scheduler is not None:
        return _scheduler

    sched = BackgroundScheduler(timezone=settings.SCHEDULER_TIMEZONE)
    sched.add_job(
        _run_monthly_accrual,
        CronTrigger(day=1, hour=0, minute=5, timezone=settings.SCHEDULER_TIMEZONE),
        id="leave_monthly_accrual",
        replace_existing=True,
    )
    sched.add_job(
        _run_yearly_reset,
        CronTrigger(month=1, day=1, hour=0, minute=10, timezone=settings.SCHEDULER_TIMEZONE),
        id="leave_yearly_reset",
        replace_existing=True,
    )
    sched.start()
    _scheduler = sched
    logger.info("scheduler started timezone=%s", settings.SCHEDULER_TIMEZONE)
    return sched


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("scheduler stopped")
