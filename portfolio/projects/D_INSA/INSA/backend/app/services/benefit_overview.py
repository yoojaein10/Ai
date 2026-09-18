from datetime import date
from decimal import Decimal

from sqlalchemy import extract, func
from sqlalchemy.orm import Session

from app.db.models import BenefitEvent, BenefitHealth, BenefitItem
from app.schemas.benefit import (
    BenefitOverviewResponse,
    CategorySummary,
    HealthSummary,
    MonthlySummary,
)


_ABNORMAL_RESULTS = {"요관찰", "유소견", "질환의심"}
_NORMAL_RESULTS = {"정상", "정상A", "정상B"}


def get_overview(db: Session, year: int) -> BenefitOverviewResponse:
    start = date(year, 1, 1)
    end = date(year, 12, 31)

    # Total aggregates
    totals = (
        db.query(
            func.count(BenefitEvent.id),
            func.coalesce(func.sum(BenefitEvent.amount), 0),
            func.coalesce(func.sum(BenefitEvent.leave_days), 0),
        )
        .filter(BenefitEvent.event_date.between(start, end))
        .one()
    )
    total_count = int(totals[0] or 0)
    total_amount = Decimal(totals[1] or 0)
    total_leave = Decimal(totals[2] or 0)

    # By category (join item) — group by raw column, normalize NULL in Python
    # to avoid MSSQL ambiguity with coalesce() reused in SELECT and GROUP BY.
    cat_rows = (
        db.query(
            BenefitItem.category,
            func.count(BenefitEvent.id),
            func.coalesce(func.sum(BenefitEvent.amount), 0),
            func.coalesce(func.sum(BenefitEvent.leave_days), 0),
        )
        .outerjoin(BenefitItem, BenefitEvent.item_id == BenefitItem.id)
        .filter(BenefitEvent.event_date.between(start, end))
        .group_by(BenefitItem.category)
        .all()
    )
    by_category = [
        CategorySummary(
            category=row[0] or "미분류",
            count=int(row[1] or 0),
            total_amount=Decimal(row[2] or 0),
            total_leave_days=Decimal(row[3] or 0),
        )
        for row in cat_rows
    ]

    # By month
    month_rows = (
        db.query(
            extract("month", BenefitEvent.event_date),
            func.count(BenefitEvent.id),
            func.coalesce(func.sum(BenefitEvent.amount), 0),
        )
        .filter(BenefitEvent.event_date.between(start, end))
        .group_by(extract("month", BenefitEvent.event_date))
        .all()
    )
    month_map = {int(r[0]): (int(r[1] or 0), Decimal(r[2] or 0)) for r in month_rows}
    by_month = [
        MonthlySummary(
            month=m,
            count=month_map.get(m, (0, Decimal(0)))[0],
            total_amount=month_map.get(m, (0, Decimal(0)))[1],
        )
        for m in range(1, 13)
    ]

    # Health summary
    health_rows = db.query(BenefitHealth).filter(BenefitHealth.check_year == year).all()
    h_total = len(health_rows)
    h_normal = sum(1 for r in health_rows if (r.result or "") in _NORMAL_RESULTS)
    h_abnormal = sum(
        1 for r in health_rows if (r.result or "") in _ABNORMAL_RESULTS
    )
    h_caution = h_total - h_normal - h_abnormal
    h_recheck = sum(1 for r in health_rows if r.recheck_required)

    return BenefitOverviewResponse(
        year=year,
        event_total_count=total_count,
        event_total_amount=total_amount,
        event_total_leave_days=total_leave,
        by_category=by_category,
        by_month=by_month,
        health=HealthSummary(
            total=h_total,
            normal=h_normal,
            caution=h_caution,
            abnormal=h_abnormal,
            recheck_required=h_recheck,
        ),
    )
