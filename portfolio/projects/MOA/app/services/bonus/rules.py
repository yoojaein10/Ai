"""성과상여 순수 계산 규칙 — DB 없이 숫자만 다룬다.

재무팀 성과상여 엑셀의 수식을 그대로 옮긴 것이라 여기 있는 상수·절사 규칙은
시트와 1원 단위로 맞아야 한다 (2026-08-25 ★★2026년 성과상여.xlsx 전면 분석).
구 bonus.py(bonus_legacy.py)에서 쓰던 함수는 이름 그대로 두어 두 쪽이 같은 규칙을 쓴다.
"""

import re
from decimal import ROUND_DOWN, Decimal
from typing import Any

# ── 새 엔진의 원천 상수 (2026-08-25 실측) ────────────────────────────────────────
# 상여 원천은 감정수수료 하나. 4010002 기타수수료(사본발급 등 소액)·4010003 공시지가등수익은 제외.
FEE_ACCOUNTS = ("4010001",)
# 유형 6(가격자문)은 재무팀 지침(2026-08-06)으로 매출을 4010002 에 낸다 — 그 건만 기타수수료가 수수료다.
PRICE_ADVICE_TYPE = "6"
PRICE_ADVICE_ACCOUNT = "4010002"
HQ_DIVISION = "1000"  # 본사 회계단위 — 상여는 본사 감정서(01-%)만
LITIGATION_WORK = ("일반쟁송",)  # B.C(법인카드 한도) 제외 업무분류 — 엑셀 IF(B="일반쟁송","",H*5%)
INCOME_TAX_RATE = Decimal("0.30")   # 소득세 = ROUNDDOWN(산정금액 × 30%, -3)
RESIDENT_TAX_RATE = Decimal("0.10")  # 주민세 = ROUNDDOWN(소득세 × 10%, -1)
CARD_LIMIT_RATE = Decimal("0.05")
# 소속평가사 건별 한계누진 (상한, 요율) — 26.08 시트 P/S/U/W 열, 김혜수 대형건 수식으로 확인
ASSOCIATE_BRACKETS = (
    (Decimal(5_000_000), Decimal("0.20")),
    (Decimal(20_000_000), Decimal("0.25")),
    (Decimal(100_000_000), Decimal("0.30")),
    (None, Decimal("0.35")),
)

SHAREHOLDER_RATES = (0.4, 0.45, 0.35, 0.3)
# 행별 적용률 허용값 — 주주 40/45/35/30, 평·동 20 기본(구간 10~40)·공통건 3
ALLOWED_RATES = (3, 10, 15, 20, 25, 30, 35, 40, 45)
ASSOCIATE_DEPTS = ("so",)
INDEMNITY_HIGH = ("담보", "가격자문")
ASSOCIATION_FEE_EXEMPT = ("컨설팅", "가격자문", "유동화자산")
# 주주 정산표의 인별 수기 입력 항목 (FIELD 보정 label)
FIELD_LABELS = ("가변비", "미납비이월", "감정서경비", "화환공제", "기타공제")
TAX_RATE = 0.33  # 구 화면의 제세공과율 — 새 엔진은 income_tax()/resident_tax() 를 쓴다
# 당월감정서경비 대상 계정 (재무팀 issue 5번: 40% 적용 전 차감 내역)
EXPENSE_ACCOUNTS = ("8070000", "8170000", "8260000", "8540000")  # 잡급·세금과공과금·도서인쇄비·용역비
# 적요에서 감정서번호 추출 — 표준형(01-2604-3-1234), 대시 누락(012604-3-1234-1),
# 유형 자리 중복 오타(01-2606-5-5-0090)까지 흡수한다.
_DOC_ID_PATTERN = re.compile(r"01-?(\d{4})-([0-9A-Za-z])(?:-\2(?=-))?-?(\d{3,5})")


def _floor_thousand(value: float) -> float:
    """천원 미만 절사 (0 방향 — 음수는 -7,731,900 → -7,731,000)."""
    return float(int(value / 1000) * 1000)


def travel_shortfall(travel_billed: float, travel_claimed: float) -> float:
    """부족출장비 — 조사자 청구가 고객 청구 여비를 초과한 부족분만, 남으면 0."""
    return max(travel_claimed - travel_billed, 0.0)


def extract_doc_ids(remark: str) -> "list[str]":
    """적요에서 감정서번호를 전부 뽑아 표준형으로 돌려준다 (중복 제거, 순서 유지)."""
    found = [
        f"01-{m.group(1)}-{m.group(2)}-{m.group(3)}"
        for m in _DOC_ID_PATTERN.finditer(remark or "")
    ]
    return list(dict.fromkeys(found))


def manager_names(doc_manager: str) -> "list[str]":
    """감정서 담당자 문자열 → 이름 목록. '공(이름)'은 괄호 안 이름으로 푼다.
    첫 이름이 평가자(물건조사비 지급 대상)다."""
    names = []
    for part in str(doc_manager or "").split(","):
        name = part.strip()
        if name.startswith("공(") and name.endswith(")"):
            name = name[2:-1].strip()
        if name:
            names.append(name)
    return names


def survey_payout(
    uploaded: float, claims: "dict[str, float]", names: "list[str]"
) -> float:
    """물건조사비 지급액 = 통합 업로드값 - 담당자 아닌 조사자의 청구 합.

    단독 조사(타 조사자 청구 없음)면 업로드값 그대로다 (재무팀 issue 4번:
    '평가자 정우종·조사자 정우종+최병천이면 청구 물건조사비-최병천 청구비').
    """
    others = sum(
        amount for who, amount in (claims or {}).items() if who not in names
    )
    return uploaded - others


def classify_manager(manager: str, dept: "str | None") -> "tuple[str, str]":
    """담당자 문자열·부서코드 → (구분, 귀속 이름). 구분: 주주 | 평동 | 공통."""
    name = (manager or "").strip()
    if name.startswith("공(") and name.endswith(")"):
        return ("공통", name[2:-1].strip())
    if dept in ASSOCIATE_DEPTS:
        return ("평동", name)
    return ("주주", name)


def shareholder_doc_calc(
    work: str, fee: float, land_fee: float, travel_fee: float = 0.0
) -> "dict[str, float]":
    indemnity_rate = 0.015 if work in INDEMNITY_HIGH else 0.01
    association = 0.0 if work in ASSOCIATION_FEE_EXEMPT else fee * 0.0148
    return {
        "assessed": fee - travel_fee + land_fee,  # 산정수수료 = 순수수료 - 부족출장비 + 토지조사비
        "indemnity": fee * indemnity_rate,
        "association_fee": association,
    }


def associate_doc_calc(
    work: str, fee: float, land_fee: float, travel_fee: float = 0.0
) -> "dict[str, float]":
    """평·동 행 계산 — 주주와 같은 19컬럼 구조. 손배만 ROUND, 협회비 면제.
    기존 '산정금액(합계-손배)'은 상여기준액(10) = 산정수수료 - 손배와 같다."""
    return {
        "assessed": fee - travel_fee + land_fee,
        "indemnity": float(round(fee * (0.015 if work == "담보" else 0.01))),
        "association_fee": 0.0,
    }


def person_share(
    person: str,
    in_price: float,
    base_fee: float,
    land_fee: float,
    ratio_names: "str | None",
    ratio_values: "str | None",
    doc_person_count: int,
    travel_fee: float = 0.0,
    expense_fee: float = 0.0,
) -> "dict[str, Any]":
    """GaPrice 행 하나의 인별 몫. 승인 배분액 → 담당자 비율 → 균등 순으로 결정.

    감정서 단위 경비(토지조사비·여비·감정서경비)는 같은 비율로 안분한다.
    물건조사비는 안분하지 않는다 — 평가자 행에만 지급 (survey_payout).
    """
    if in_price and in_price > 0:
        ratio = (in_price / base_fee) if base_fee > 0 else 0.0
        fee, estimated = in_price, False
    else:
        ratio = _charge_ratio(person, ratio_names, ratio_values)
        if ratio is None:
            ratio = 1 / doc_person_count if doc_person_count > 0 else 1.0
        fee, estimated = base_fee * ratio, True
    return {
        "fee": fee,
        "land_fee": land_fee * ratio,
        "travel_fee": travel_fee * ratio,
        "expense_fee": expense_fee * ratio,
        "estimated": estimated,
    }


def _charge_ratio(
    person: str, ratio_names: "str | None", ratio_values: "str | None"
) -> "float | None":
    names = [name.strip() for name in str(ratio_names or "").split(",")]
    ratios = [value.strip() for value in str(ratio_values or "").split(",")]
    if person in names:
        index = names.index(person)
        if index < len(ratios):
            try:
                return float(ratios[index]) / 100
            except ValueError:
                return None
    return None


# ── 엑셀 절사·세금·누진 (새 엔진) ──────────────────────────────────────────────

def _decimal(value: "float | int | Decimal") -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _rounddown_decimal(value: Decimal, digits: int) -> Decimal:
    """엑셀 ROUNDDOWN — 0 방향 절사. digits=-3 이면 천원, -1 이면 십원."""
    unit = Decimal(1).scaleb(-digits)
    return (value / unit).to_integral_value(rounding=ROUND_DOWN) * unit


def rounddown(value: "float | int | Decimal", digits: int = 0) -> float:
    """엑셀 ROUNDDOWN(value, digits). 부동소수 오차를 피하려고 Decimal 로 계산한다."""
    return float(_rounddown_decimal(_decimal(value), digits))


def income_tax(pretax: "float | int | Decimal", rate: "float | Decimal" = INCOME_TAX_RATE) -> float:
    """소득세 = ROUNDDOWN(산정금액 × 율, -3). 주주 30%, 소속 15%(사람별 파라미터)."""
    return float(_rounddown_decimal(_decimal(pretax) * _decimal(rate), -3))


def resident_tax(tax: "float | int | Decimal") -> float:
    """주민세(지방소득세) = ROUNDDOWN(소득세 × 10%, -1)."""
    return float(_rounddown_decimal(_decimal(tax) * RESIDENT_TAX_RATE, -1))


def is_litigation(work_type: "str | None") -> bool:
    return (work_type or "").strip() in LITIGATION_WORK


def card_limit(rows: "list[dict[str, Any]]") -> float:
    """B.C(법인카드 한도) = Σ 산정금액 × 5% (일반쟁송 제외), 사람 단위 천원 절사."""
    total = sum(
        (_decimal(row.get("assessed") or 0) * CARD_LIMIT_RATE
         for row in rows if not is_litigation(row.get("work_type"))),
        Decimal(0),
    )
    return float(_rounddown_decimal(total, -3))


def progressive_bonus(assessed: "float | int | Decimal") -> float:
    """소속평가사 상여 — 산정금액을 구간별로 잘라 한계요율을 곱해 더한다."""
    remaining = _decimal(assessed)
    if remaining <= 0:
        return 0.0
    total, lower = Decimal(0), Decimal(0)
    for upper, rate in ASSOCIATE_BRACKETS:
        band = (min(remaining, upper) - lower) if upper is not None else (remaining - lower)
        if band <= 0:
            break
        total += band * rate
        lower = upper if upper is not None else remaining
        if upper is not None and remaining <= upper:
            break
    return float(total)


def manager_entries(doc_manager: str) -> "list[tuple[str, bool]]":
    """담당자 문자열 → [(이름, 공통건 여부)]. '윤도,공(장재원)' → [('윤도', False), ('장재원', True)].
    공통건 담당자는 지분을 나누지 않고 전액 × 공통건 요율(기본 3%)을 따로 받는다."""
    entries = []
    for part in str(doc_manager or "").split(","):
        name = part.strip()
        common = name.startswith("공(") and name.endswith(")")
        if common:
            name = name[2:-1].strip()
        if name:
            entries.append((name, common))
    return entries


def unwrap_common(name: str) -> "tuple[str, bool]":
    """'공(정인수)' → ('정인수', True), '정인수' → ('정인수', False)."""
    text = str(name or "").strip()
    if text.startswith("공(") and text.endswith(")"):
        return text[2:-1].strip(), True
    return text, False


# ── 공통건·특수 지분 규칙 (2026-08-27 재무팀 확인) ───────────────────────────
WOORI_JOINT_PCT = 50.0        # 유치자가 공(주주이사)인 우리은행 건 → 그 이사에게 순수수료 50% (주주 행)
SIGNING_MAX_PCT = 10.0        # 지분표 합이 100 을 넘으면 이 이하 지분은 서명료(캡스톤 안창덕 2.5%) — 손배·협회비 없음
COMMON_DEFAULT_RATE = 3.0     # 공통건 기본 요율 (은행 가격자문·담보)
COMMON_FLOOR = 300_000.0      # 국공유재산·법원 및 공매 공통건 하한 (엑셀 정액 300,000)
COMMON_CUSTOMER_RATES = (("산업은행", 4.0),)                 # 거래처 키워드 → 담당 공(X) 요율
CHANNEL_OWNERS = (("산업은행", "윤도", 23.0),)               # 거래처 키워드 → (채널 주인, 요율): 같은 건에 따로 한 줄
COMMON_WORK_RATES = {"국공유재산": (15.0, COMMON_FLOOR), "법원 및 공매": (15.0, COMMON_FLOOR), "보상": (15.0, 0.0)}


def is_woori(customer: str) -> bool:
    return "우리은행" in str(customer or "")


def channel_owner(customer: str) -> "tuple[str, float] | None":
    """KDB산업은행 건은 담당 공(X) 4% 와 별도로 윤도 평가사가 23% 를 받는다 (26.06·26.08 평·동 '주주 합계' 윤도 블록)."""
    text = str(customer or "")
    for key, person, rate in CHANNEL_OWNERS:
        if key in text:
            return person, rate
    return None


def common_rate_rule(work_type: str, customer: str, person_rate: "float | None" = None) -> "tuple[float, float, str]":
    """공통건(공(X)) 요율 → (요율 %, 하한 금액, 출처).

    우선순위: 거래처 규칙(산업은행 4%) > 업무구분 규칙(국공유재산·법원 15% 하한 30만, 보상 15%) — 사람 요율이 있으면
    그 사람 요율(하한 없음, 유영조 법원 3%) > 사람 요율 > 기본 3%.
    """
    work = str(work_type or "").strip()
    text = str(customer or "")
    for key, rate in COMMON_CUSTOMER_RATES:
        if key in text:
            return rate, 0.0, "CUSTOMER"
    if work in COMMON_WORK_RATES:
        rate, floor = COMMON_WORK_RATES[work]
        if person_rate is not None:
            return float(person_rate), 0.0, "PERSON"
        return rate, floor, "WORK"
    if person_rate is not None:
        return float(person_rate), 0.0, "PERSON"
    return COMMON_DEFAULT_RATE, 0.0, "DEFAULT"


# ── 국민약식 (KB 약식평가) ─────────────────────────────────────────────────
# 관리번호 400xxxxxx, 4010002 기타수수료 '약식평가수수료' — APW 마스터에 없고 엑셀은 매달 '국민약식' 한 줄(김형수, 가격자문).
# 실측 2025-11~2026-07: 엑셀 F = 그 입금월 전표 합의 50% (9개월 중 7개월 정확히 0.50, 나머지 0.52·0.53).
SIMPLE_APPRAISAL_PREFIX = "400"
SIMPLE_APPRAISAL = {"owner": "김형수", "share_pct": 50.0, "work_type": "가격자문", "label": "국민약식"}


def simple_appraisal_doc_id(perf_month: str) -> str:
    """합산 행의 감정서번호 — 달마다 하나 (KB약식-202607)."""
    return f"KB약식-{perf_month}"
