"""매출입력(Apw_Mae_GaPrice) 인정비율 — 공(XXX) 건에만 적용되는 사내 규정.

2026-07-29 사용자 확인 사항:
  · 유치자가 '공(홍길동)' 형태가 아니면 순수수료 전액
  · 공(XXX) + 거래처가 우리은행이면 업무 종류와 무관하게 무조건 50%
  · 그 밖의 공(XXX) 건은 아래 인정비율표를 따르고, 표의 %를 순수수료에 그대로 곱한다
    (담보 단독 15% → 순수수료 100만원이면 매출입력 15만원)
  · 단독처리 = 조사자가 공() 안의 본인뿐,  공동처리 = 조사자에 다른 사람이 끼어 있음
  · 표에 없는 업무(가격자문·컨설팅·기업관련·유동화자산·공시업무·
    기타 공공·도시개발사업)는 전액 (국공유재산은 2026-07-29 재무 답변으로 20/15 확정)

2026-07-30 전수 확인 — 과거 관행은 "공() = 실적 미인정(0%)"이었다:
  · 공() 건 872건(25~26년, 순수수료>0) 중 811건(93%)이 **매출입력 자체가 없다**
  · 매출입력이 있는 61건은 57건이 우리은행(56건 50%), 나머지 4건이 개별 예외
    (01-2603-1-0221 한남4 50%는 재무이사 구두지시가 원장 비고에 기록됨)
  · 표대로 입력된 건은 0건 → 인정비율표는 0%에서 부분 인정으로 바꾸는 신규 정책이다
  · 공() 표기는 직위와 무관하다(주주 328·예비주주 150·기타). 예비주주(Seat_UserInfo의
    Dept_Nm='yj') 신분 자체가 미인정 사유는 아니며, 자기 이름으로 유치한 993건은
    771건(78%)이 전액 인정된다 — 미인정을 만드는 것은 공() 표기다

⚠️ 그래서 expected_ratio()는 시행일 전까지 실제 관행과 다르다(코드 15% vs 관행 0%).
   data_quality의 점검은 GaPrice 행이 있는 건만 보므로 위 811건(순수수료 합 66.2억)은
   아예 점검 대상에서 빠진다 — 시행일 확정 시 "인정 누락" 검출을 같이 설계해야 한다.
"""

from datetime import date, datetime

WOORI = "우리은행"

# 인정비율표 시행일 — 재무팀 확정 대기(2026-07-30 기준 미정).
# None = 미시행: 공() 건은 현행 관행대로 '실적 미인정(0%)'을 기대값으로 쓴다.
# 날짜가 정해지면 date(YYYY, M, D)를 넣으면 그날 이후 입력분부터 RATES 표가 적용된다.
# (상·하한선도 그때 함께 반영해야 한다 — 아직 미구현)
TABLE_EFFECTIVE_DATE: "date | None" = None

# 표 항목 -> (단독처리 %, 공동처리 %)
# 국공유재산은 2026-07-29 재무팀 답변: "일반거래로 취급되어 단독 20% / 공동 15%,
# 상한 1천만·하한 30만(건별)". SH(서울주택도시공사) 건도 업무가 국공유재산이면 여기로.
# ⚠️ 상·하한선(전 업무 건별)은 아직 미적용 — 시행일 확정 후 한 번에 반영 예정.
RATES = {
    "소송평가": (100, 50),
    "보상·종전·SH": (30, 20),
    "일반거래": (30, 15),
    "국공유재산(일반거래 취급)": (20, 15),
    "종후평가": (15, 8),
    "담보평가": (15, 10),
    "경매(공매)평가": (15, 10),
}


def _text(value: "str | None") -> str:
    return str(value or "").strip()


def is_table_in_effect(input_date: "date | datetime | None") -> bool:
    """인정비율표가 이 입력분에 적용되는지. 시행일 미정이면 항상 False(현행 관행)."""
    if TABLE_EFFECTIVE_DATE is None:
        return False
    if input_date is None:  # 입력일을 모르면 미시행으로 본다(오탐 방지)
        return False
    day = input_date.date() if isinstance(input_date, datetime) else input_date
    return day >= TABLE_EFFECTIVE_DATE


def is_joint_case(manager: "str | None") -> bool:
    """유치자가 '공(홍길동)' 표기인가 — 인정비율표 적용 대상 여부."""
    return _text(manager).startswith("공(")


def joint_name(manager: "str | None") -> str:
    """'공(홍길동)' 에서 홍길동만 꺼낸다."""
    text = _text(manager)
    if not text.startswith("공(") or ")" not in text:
        return ""
    return text[2:text.index(")")].strip()


def is_solo_processing(manager: "str | None", charge: "str | None") -> bool:
    """조사자가 공() 안의 본인 하나뿐이면 단독처리."""
    name = joint_name(manager)
    people = {part.strip() for part in _text(charge).split(",") if part.strip()}
    return bool(name) and people == {name}


def category(
    work: "str | None", purpose: "str | None", customer: "str | None" = None
) -> "str | None":
    """감정서의 업무 종류를 인정비율표 항목으로 매핑한다 (없으면 None).

    종전·종후는 대분류(LWorkinfo)가 정비사업/보상/국공유재산/도시개발사업에 걸쳐 있어
    세부목적(LPurpose)으로 먼저 판정해야 한다.
    """
    work_text, purpose_text = _text(work), _text(purpose)
    if "종후" in purpose_text:
        return "종후평가"
    if "종전" in purpose_text:
        return "보상·종전·SH"
    if work_text == "보상":
        return "보상·종전·SH"
    if work_text == "국공유재산":
        return "국공유재산(일반거래 취급)"
    if work_text == "법원 및 공매":
        if "소송" in purpose_text:
            return "소송평가"
        if "경매" in purpose_text or "공매" in purpose_text:
            return "경매(공매)평가"
        return None
    if work_text == "담보":
        return "담보평가"
    if work_text == "일반거래":
        return "일반거래"
    return None


def expected_ratio(
    manager: "str | None",
    customer: "str | None" = None,
    work: "str | None" = None,
    purpose: "str | None" = None,
    charge: "str | None" = None,
    input_date: "date | datetime | None" = None,
) -> float:
    """순수수료 대비 기대 매출입력 비율.

    시행일 전(현재)에는 공() 건을 실적 미인정(0.0)으로 본다 — 전수 확인 결과
    실제 관행이 그렇다(872건 중 811건이 매출입력 없음). 우리은행만 예외로 절반.
    """
    if not is_joint_case(manager):
        return 1.0
    if WOORI in _text(customer):
        return 0.5
    if not is_table_in_effect(input_date):
        return 0.0
    matched = category(work, purpose, customer)
    if matched is None:
        return 1.0
    solo_pct, joint_pct = RATES[matched]
    pct = solo_pct if is_solo_processing(manager, charge) else joint_pct
    return pct / 100


def ratio_basis(
    manager: "str | None",
    customer: "str | None" = None,
    work: "str | None" = None,
    purpose: "str | None" = None,
    charge: "str | None" = None,
    input_date: "date | datetime | None" = None,
) -> str:
    """기대 비율이 그렇게 나온 근거를 한 줄로."""
    if not is_joint_case(manager):
        return "단독 유치(전액)"
    if WOORI in _text(customer):
        return "우리은행 공동유치(무조건 절반)"
    if not is_table_in_effect(input_date):
        return "공(이름) 유치 — 현행 관행상 실적 미인정(인정비율표 미시행)"
    matched = category(work, purpose, customer)
    if matched is None:
        return "인정비율표에 없는 업무(전액)"
    kind = "단독처리" if is_solo_processing(manager, charge) else "공동처리"
    solo_pct, joint_pct = RATES[matched]
    pct = solo_pct if kind == "단독처리" else joint_pct
    return f"{matched} {kind} {pct}%"
