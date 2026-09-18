"""성과상여 재작성 패키지 (2026-08-25 계획).

구 구현은 app/services/bonus_legacy.py 에 동결돼 있고, 이 패키지는 legacy 를
import 하지 않는다 (legacy 가 여기 rules 를 가져다 쓰므로 거꾸로 물면 순환이 된다).
"""

from app.services.bonus.rules import (
    ALLOWED_RATES,
    ASSOCIATE_DEPTS,
    ASSOCIATION_FEE_EXEMPT,
    EXPENSE_ACCOUNTS,
    FIELD_LABELS,
    INDEMNITY_HIGH,
    SHAREHOLDER_RATES,
    TAX_RATE,
    associate_doc_calc,
    classify_manager,
    extract_doc_ids,
    manager_names,
    person_share,
    shareholder_doc_calc,
    survey_payout,
    travel_shortfall,
)

__all__ = [
    "ALLOWED_RATES",
    "ASSOCIATE_DEPTS",
    "ASSOCIATION_FEE_EXEMPT",
    "EXPENSE_ACCOUNTS",
    "FIELD_LABELS",
    "INDEMNITY_HIGH",
    "SHAREHOLDER_RATES",
    "TAX_RATE",
    "associate_doc_calc",
    "classify_manager",
    "extract_doc_ids",
    "manager_names",
    "person_share",
    "shareholder_doc_calc",
    "survey_payout",
    "travel_shortfall",
]
