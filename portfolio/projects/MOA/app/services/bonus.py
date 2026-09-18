"""성과상여 실적 집계 — 재무팀 '성과상여' 엑셀(주주/평·동/총괄표)의 자동 계산 부분.

실적 기준 (2026-07-22, 26.06월 시트 대조로 확정 — GaPrice 기준이 엑셀과 94% 일치):
- 상여월 실적 = Apw_Mae_GaPrice에서 In_Date가 실적월인 본사 행 (인별 분할 그대로)
- 인별 순수수료: In_Price(매출입력 승인 배분액) > 0이면 그 값,
  0원 선등록 행이면 기초수수료 × APW_Charge_IDX 담당자 비율로 추정 (estimated 표시)
- 주주/평·동 구분: Seat_userinfo.Dept_Nm — 'so'(소속평가사)만 평·동, 그 외는 주주
- 감정서 담당자가 '공(이름)'이면 공통건 → 평·동 탭, 요율은 수기(3%/20% 혼재)라 계산하지 않음

자동 계산 (엑셀 수식 검증 완료):
- 주주: 산정금액=순수수료+토지조사비, 손해배상충당금=순수수료×(담보·가격자문 1.5%, 그외 1%),
  협회비·공제료=순수수료×1.48%(컨설팅·가격자문·유동화자산 면제),
  산출액=산정-손배-협회비, 상여 참고=산출액×40/45/35/30%
  (적용률은 감정서 행별 수기 선택, 기본 40% — 공제는 행별 산출액 비율로 안분 후
   행별 요율 적용. 전 행이 같은 요율이면 기존 '산출액 전체 × 요율'과 동일하다)
- 평·동: 손배=ROUND(순수수료×(담보 1.5%, 그외 1%)), 협회비 면제. 주주와 같은 19컬럼
  정산 구조를 쓴다 — 기존 '산정금액(합계-손배)' = 새 구조의 상여기준액(10),
  '상여참고(20%)' = 산정상여금(11, 행별 요율 콤보·기본 20%). 공통건 요율(3%/20% 수기)도
  행별 콤보로 선택한다.

주주 정산표(재무팀 시트 19컬럼, 2026-07-30):
- 산정수수료(4) = 순수수료 - 부족출장비 + 토지조사비. 부족출장비 = 조사자 출장 청구
  (APW_YJI_ManCulJang.Cul_In+Cul_Out 합)가 고객 청구 여비(apw_masterex.여비)를
  초과하는 부족분만 — 여비가 남으면 0 (2026-07-30 사용자 확정: 여비 40,000/청구
  60,000 → 20,000 차감, 여비 10,000/청구 3,000 → 차감 없음).
  부족출장비·물건조사비·공부발급비·기타실비는 감정서 값을 수수료 배분 비율로 안분한다.
- 상여기준액(10) = 4 - (가변비 + 손배 + 미납비이월 + 당월감정서경비 + 협회비 + 수기공제).
- 가변비(5) 자동값 = 전월 APW_IW_MONGABUNBI(Manager·Standmon·Gabunbi) 인별 합
  (2026-08-03 Sung.xlsx 26.06월가변비 시트 = 2026-05 Standmon과 6/8명 일치로 확정 —
  나머지는 시트 '수정 가변비' 수기 조정분). 원천에 감정서번호가 없어 행별로 뿌리지
  않고 합계 행(5)에만 더한다(사용자 확정) — 상여 계산에는 자유 공제(DEDUCT)처럼
  행별 산출액 비율로 내부 안분만 한다. 행별 가변비 입력은 추가 조정분으로 합산된다.
  당월감정서경비 자동값 = 아마란스 본사(회계단위 10) 경비 전표(용역비·세금과공과금·
  잡급·도서인쇄비) 중 적요에 감정서번호가 있는 건을 감정서로 귀속해 안분한 값
  (2026-08-03 재무팀 issue 5번 — 기존 공부발급비+기타실비 안분을 대체, 행별 덮어쓰기 유지).
  적요에 이름만 있고 감정서번호가 없는 전표는 합산하지 않고 사람별 참고 목록으로 보여준다.
- 물건조사비(13) = 안분하지 않는다. 평가자(감정서 담당자 첫 이름) 행에만
  '통합 업로드값(apw_masterex.물건조사비) - 타 조사자 청구(APW_YJI_ManCulJang.Mul_Amt)'를
  지급한다 (2026-08-03 재무팀 issue 4번 확정).
- 조사자 청구(부족출장비·물건조사비)는 승인 완료(ApproState=3) 행만 집계한다
  (2026-08-03 사용자 확정 — 이전에는 조건 없이 전 행 합산).
- 세전상여금(14) = 산정상여금(행별 적용률 합) - 화환공제 + 물건조사비, 천원 절사.
  제세공과(15) = 세전 × 33% (재무팀 실측과 수백원 단위 오차 있음 — 원천세 계산 확인 전).
  지급상여금(18) = 세후 - 기타공제. 카드(19) = 산정수수료 × 5% 천원 절사.

수기 항목(FIELD 보정, 감정서 행 단위 — 합계 행은 합만 표시): 가변비, 미납비이월,
감정서경비(행 자동값 덮어쓰기), 화환공제, 기타공제. 행별 값은 그 행의 산출액에서 차감되고
(화환·기타공제는 세전/지급 단계), 자유 항목 공제(DEDUCT)만 행별 산출액 비율로 안분한다.
"""

import re
from datetime import date, timedelta
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.bonus_adjust import BonusAdjust

SHAREHOLDER_RATES = (0.4, 0.45, 0.35, 0.3)
# 행별 적용률 허용값 — 주주 40/45/35/30, 평·동 20 기본(구간 10~40)·공통건 3
ALLOWED_RATES = (3, 10, 15, 20, 25, 30, 35, 40, 45)
ASSOCIATE_DEPTS = ("so",)
INDEMNITY_HIGH = ("담보", "가격자문")
ASSOCIATION_FEE_EXEMPT = ("컨설팅", "가격자문", "유동화자산")
# 주주 정산표의 인별 수기 입력 항목 (FIELD 보정 label)
FIELD_LABELS = ("가변비", "미납비이월", "감정서경비", "화환공제", "기타공제")
TAX_RATE = 0.33  # 제세공과 = 세전상여금 × 33% (재무팀 원천세 계산과 오차 — 확인 전 잠정)
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


def _source_database() -> str:
    database = get_settings().mssql_source_db
    if not database.replace("_", "").isalnum():
        raise RuntimeError("MSSQL_SOURCE_DB 이름이 올바르지 않습니다.")
    return database


_DOCS_SQL = """
SELECT RTRIM(g.Docid) AS doc_id, RTRIM(g.Manager) AS person,
       g.In_Price AS in_price, g.In_Date AS paid_date,
       RTRIM(m.LWorkinfo) AS work_type, RTRIM(m.CustName) AS customer_name,
       RTRIM(m.Manager) AS doc_manager, RTRIM(m.Charge) AS investigator,
       m.[기초수수료] AS base_fee, m.[토지조사비] AS land_fee,
       m.[여비] AS travel_billed, ISNULL(cj.claim_total, 0) AS travel_claimed,
       m.[물건조사비] AS survey_fee,
       m.[공부발급비] AS record_fee, m.[기타실비] AS misc_fee,
       c.Names AS ratio_names, c.Ratios AS ratio_values
FROM [{database}].dbo.Apw_Mae_GaPrice g
JOIN [{database}].dbo.apw_masterex m ON m.DocID = RTRIM(g.Docid)
LEFT JOIN [{database}].dbo.APW_Charge_IDX c
  ON c.MasterID = m.MasterID AND c.iType = 1
LEFT JOIN (
    SELECT Docid, SUM(Cul_In + Cul_Out) AS claim_total
    FROM [{database}].dbo.APW_YJI_ManCulJang
    WHERE ApproState = 3
    GROUP BY Docid
) cj ON cj.Docid = RTRIM(g.Docid)
WHERE g.In_Date >= :date_from AND g.In_Date <= :date_to
  AND g.Docid LIKE CAST(:hq_prefix AS varchar(50))
  {person_filter}
ORDER BY RTRIM(g.Manager), RTRIM(g.Docid)
"""


def _voucher_expenses(
    db: Session, date_from: date, date_to: date,
    known_docs: "set[str] | None" = None,
) -> "tuple[dict[str, float], list[dict[str, Any]]]":
    """당월 경비 전표(본사 1000, 4개 계정, 차변)를 감정서별로 귀속한다.

    반환: (감정서별 합계, 귀속 못 한 전표 목록 — 사람별 참고 표시용).
    한 적요에 감정서가 여럿이면 균등 분할한다 (예: '…-0359/…-3640 전자수입인지').
    known_docs를 주면 그 밖의 감정서를 적은 전표도 참고 목록으로 보낸다 —
    이번 달 상여 목록에 없는 감정서면 행 귀속이 불가능해 조용히 사라지기 때문.
    """
    placeholders = ", ".join(f":a{i}" for i in range(len(EXPENSE_ACCOUNTS)))
    rows = db.execute(
        text(f"""
SELECT voucher_date, account_code, RTRIM(account_name) AS account_name,
       amount, RTRIM(remark) AS remark
FROM dbo.a10_voucher_cache
WHERE voucher_date >= :date_from AND voucher_date <= :date_to
  AND division_code = '1000' AND debit_credit = '3'
  AND account_code IN ({placeholders})
-- 귀속 합계는 순서와 무관하지만, 귀속 못 한 전표 참고 목록은 최근 것부터 본다.
ORDER BY voucher_date DESC
"""),
        {"date_from": date_from, "date_to": date_to}
        | {f"a{i}": code for i, code in enumerate(EXPENSE_ACCOUNTS)},
    ).mappings().all()
    by_doc: "dict[str, float]" = {}
    unmatched: "list[dict[str, Any]]" = []
    for row in rows:
        amount = float(row["amount"] or 0)
        doc_ids = extract_doc_ids(row["remark"] or "")
        if known_docs is not None:
            doc_ids = [doc for doc in doc_ids if doc in known_docs]
        if doc_ids:
            share = amount / len(doc_ids)
            for doc_id in doc_ids:
                by_doc[doc_id] = by_doc.get(doc_id, 0.0) + share
        else:
            unmatched.append({
                "voucher_date": row["voucher_date"].isoformat()[:10]
                if row["voucher_date"] else None,
                "account_name": row["account_name"],
                "amount": amount,
                "remark": row["remark"],
            })
    return by_doc, unmatched


def _variable_costs(
    db: Session, database: str, year: int, month: int
) -> "dict[str, float]":
    """전월 가변비(APW_IW_MONGABUNBI) 인별 합 — 상여 시트 '5.가변비(전월)' 자동값."""
    prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
    rows = db.execute(
        text(
            f"SELECT RTRIM(Manager) AS person, SUM(Gabunbi) AS amount "
            f"FROM [{database}].dbo.APW_IW_MONGABUNBI "
            f"WHERE Standmon = CAST(:standmon AS varchar(10)) "
            f"GROUP BY RTRIM(Manager)"
        ),
        {"standmon": f"{prev_year:04d}-{prev_month:02d}"},
    ).mappings().all()
    return {row["person"]: float(row["amount"] or 0) for row in rows if row["person"]}


def _survey_claims(
    db: Session, database: str, doc_ids: "list[str]"
) -> "dict[str, dict[str, float]]":
    """감정서별 조사자 물건조사비 청구(APW_YJI_ManCulJang.Mul_Amt) — {doc: {조사자: 합}}.

    승인 완료(ApproState=3) 청구만 집계한다 — 부족출장비와 동일 기준 (2026-08-03 사용자 확정).
    """
    result: "dict[str, dict[str, float]]" = {}
    for start in range(0, len(doc_ids), 500):
        chunk = doc_ids[start:start + 500]
        names = [f"doc_{i}" for i in range(len(chunk))]
        params = dict(zip(names, chunk))
        rows = db.execute(
            text(f"""
SELECT RTRIM(Docid) AS doc_id, RTRIM(Write_Name) AS who, SUM(Mul_Amt) AS amount
FROM [{database}].dbo.APW_YJI_ManCulJang
WHERE Docid IN ({", ".join(f"CAST(:{n} AS varchar(50))" for n in names)})
  AND Mul_Amt > 0 AND ApproState = 3
GROUP BY RTRIM(Docid), RTRIM(Write_Name)
"""),
            params,
        ).mappings().all()
        for row in rows:
            result.setdefault(row["doc_id"], {})[row["who"]] = float(row["amount"] or 0)
    return result


class BonusAdjustError(ValueError):
    pass


def load_adjustments(db: Session, year: int, month: int) -> "dict[str, dict[str, Any]]":
    """실적월의 수기 보정을 사람별로 묶는다."""
    rows = db.scalars(
        select(BonusAdjust).where(
            BonusAdjust.period_year == year, BonusAdjust.period_month == month
        ).order_by(BonusAdjust.id)
    ).all()
    result: "dict[str, dict[str, Any]]" = {}
    for row in rows:
        entry = result.setdefault(
            row.person,
            {"fees": {}, "assessed": {}, "rows": [], "deductions": [],
             "rate": None, "doc_rates": {}, "fields": {}},
        )
        if row.adjust_type == "FIELD" and row.label and row.doc_id:
            entry["fields"].setdefault(row.label, {})[row.doc_id] = float(row.amount or 0)
        elif row.adjust_type == "FEE" and row.doc_id:
            entry["fees"][row.doc_id] = float(row.amount or 0)
        elif row.adjust_type == "ASSESSED" and row.doc_id:
            entry["assessed"][row.doc_id] = float(row.amount or 0)
        elif row.adjust_type == "ROW":
            entry["rows"].append({
                "doc_id": row.doc_id or "(수기)",
                "work_type": row.work_type or "",
                "customer_name": row.customer_name,
                "amount": float(row.amount or 0),
                "memo": row.memo,
            })
        elif row.adjust_type == "DEDUCT":
            entry["deductions"].append(
                {"label": row.label or "공제", "amount": float(row.amount or 0)}
            )
        elif row.adjust_type == "RATE":
            # doc_id가 있으면 행별 적용률, 없으면 과거(사람 단위) 저장분 — 기본값으로 유지
            if row.doc_id:
                entry["doc_rates"][row.doc_id] = int(row.amount or 0)
            else:
                entry["rate"] = int(row.amount or 0)
    return result


def save_person_adjustments(
    db: Session,
    year: int,
    month: int,
    person: str,
    fees: "list[dict[str, Any]]",
    assessed_overrides: "list[dict[str, Any]]",
    rows: "list[dict[str, Any]]",
    deductions: "list[dict[str, Any]]",
    doc_rates: "list[dict[str, Any]]",
    created_by: int,
    fields: "list[dict[str, Any]] | None" = None,
) -> int:
    """(실적월, 사람)의 보정을 전체 교체 저장한다. 저장 건수 반환."""
    person = person.strip()
    if not person:
        raise BonusAdjustError("담당자 이름이 비어 있습니다.")
    for item in doc_rates:
        if item["rate"] not in ALLOWED_RATES:
            raise BonusAdjustError(
                f"적용률은 {'/'.join(str(r) for r in ALLOWED_RATES)} 중 하나여야 합니다."
            )
    for item in fields or []:
        if item["label"] not in FIELD_LABELS:
            raise BonusAdjustError(f"정산 항목은 {'/'.join(FIELD_LABELS)}만 가능합니다.")
        if not item.get("doc_id"):
            raise BonusAdjustError("정산 항목은 감정서 행 단위로 저장합니다.")
    db.execute(
        delete(BonusAdjust).where(
            BonusAdjust.period_year == year,
            BonusAdjust.period_month == month,
            BonusAdjust.person == person,
        )
    )
    entries: "list[BonusAdjust]" = []
    common = {"period_year": year, "period_month": month, "person": person, "created_by": created_by}
    for item in fees:
        entries.append(BonusAdjust(
            **common, adjust_type="FEE",
            doc_id=str(item["doc_id"])[:50], amount=item["fee"],
        ))
    for item in assessed_overrides:
        entries.append(BonusAdjust(
            **common, adjust_type="ASSESSED",
            doc_id=str(item["doc_id"])[:50], amount=item["assessed"],
        ))
    for item in rows:
        entries.append(BonusAdjust(
            **common, adjust_type="ROW",
            doc_id=str(item.get("doc_id") or "")[:50] or None,
            work_type=str(item.get("work_type") or "")[:20] or None,
            customer_name=str(item.get("customer_name") or "")[:100] or None,
            amount=item["amount"], memo=str(item.get("memo") or "")[:200] or None,
        ))
    for item in deductions:
        entries.append(BonusAdjust(
            **common, adjust_type="DEDUCT",
            label=str(item.get("label") or "공제")[:30], amount=item["amount"],
        ))
    for item in doc_rates:
        entries.append(BonusAdjust(
            **common, adjust_type="RATE",
            doc_id=str(item["doc_id"])[:50], amount=item["rate"],
        ))
    for item in fields or []:
        entries.append(BonusAdjust(
            **common, adjust_type="FIELD", doc_id=str(item["doc_id"])[:50],
            label=str(item["label"])[:30], amount=item["amount"],
        ))
    db.add_all(entries)
    db.commit()
    return len(entries)


def month_range(year: int, month: int) -> "tuple[date, date]":
    """해당 월의 1일~말일."""
    first = date(year, month, 1)
    next_first = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return first, next_first - timedelta(days=1)


def bonus_report(
    db: Session,
    year: int,
    month: int,
    scope_person: "str | None" = None,
) -> "dict[str, Any]":
    """실적월(GaPrice In_Date) 기준 주주/평·동/총괄 집계."""
    database = _source_database()
    date_from, date_to = month_range(year, month)
    rows = db.execute(
        text(_DOCS_SQL.format(
            database=database,
            person_filter="AND RTRIM(g.Manager) = :scope_person" if scope_person else "",
        )),
        {
            "hq_prefix": "01-%",
            "date_from": date_from,
            "date_to": date_to,
            **({"scope_person": scope_person} if scope_person else {}),
        },
    ).mappings().all()

    # 같은 (감정서, 담당자)의 중복 행(0원 선등록 + 승인 행)은 하나로 합친다
    merged: "dict[tuple[str, str], dict[str, Any]]" = {}
    person_count: "dict[str, set[str]]" = {}
    for row in rows:
        person = (row["person"] or "").strip()
        key = (row["doc_id"], person)
        entry = merged.get(key)
        if entry is None:
            merged[key] = dict(row) | {"in_price": float(row["in_price"] or 0)}
        else:
            entry["in_price"] += float(row["in_price"] or 0)
        person_count.setdefault(row["doc_id"], set()).add(person)

    # 당월감정서경비(전표 귀속)·물건조사비 청구(조사자별) — 감정서 단위 선조회
    expense_by_doc, expense_unmatched = _voucher_expenses(
        db, date_from, date_to, known_docs=set(person_count)
    )
    survey_claims = _survey_claims(db, database, sorted(person_count))

    depts = _dept_by_name(db)
    shareholders: "dict[str, dict[str, Any]]" = {}
    associates: "dict[str, dict[str, Any]]" = {}
    for (doc_id, person), row in merged.items():
        work = (row["work_type"] or "").strip()
        doc_manager = (row["doc_manager"] or "").strip()
        common = doc_manager.startswith("공(")
        share = person_share(
            person=person,
            in_price=row["in_price"],
            base_fee=float(row["base_fee"] or 0),
            land_fee=float(row["land_fee"] or 0),
            ratio_names=row["ratio_names"],
            ratio_values=row["ratio_values"],
            doc_person_count=len(person_count.get(doc_id) or ()) or 1,
            travel_fee=travel_shortfall(
                float(row["travel_billed"] or 0), float(row["travel_claimed"] or 0)
            ),
            expense_fee=expense_by_doc.get(doc_id, 0.0),
        )
        fee, land, travel = share["fee"], share["land_fee"], share["travel_fee"]
        # 물건조사비 — 평가자(담당자 첫 이름) 행에만: 업로드값 - 타 조사자 청구
        doc_managers = manager_names(doc_manager)
        survey = (
            survey_payout(
                float(row["survey_fee"] or 0), survey_claims.get(doc_id), doc_managers
            )
            if doc_managers and person == doc_managers[0] else 0.0
        )
        base = {
            "doc_id": doc_id,
            "work_type": work,
            "customer_name": row["customer_name"],
            "manager": doc_manager,
            "investigator": row["investigator"],
            "base_fee": fee,
            "land_fee": land,
            "travel_fee": travel,
            "survey_fee": survey,
            "expense_fee": share["expense_fee"],
            "estimated": share["estimated"],
            "paid_date": row["paid_date"].isoformat()[:10] if row["paid_date"] else None,
        }
        base["auto_fee"] = fee  # 보정 전 자동 계산값 (화면에서 수정 여부 판단용)
        if not common and depts.get(person) not in ASSOCIATE_DEPTS:
            calc = shareholder_doc_calc(work, fee, land, travel)
            group = shareholders.setdefault(person, {
                "name": person, "dept": depts.get(person), "docs": [],
            })
            # auto_assessed = 보정 전 자동 산정금액 (화면에서 수정 여부 판단용)
            group["docs"].append({**base, **calc, "auto_assessed": calc["assessed"]})
        else:
            calc = associate_doc_calc(work, fee, land, travel)
            group = associates.setdefault(person, {
                "name": person, "dept": depts.get(person), "docs": [],
            })
            group["docs"].append({**base, **calc, "common": common})

    # 감정서번호가 없는 경비 전표는 적요에 이름이 든 사람에게 참고로만 붙인다
    # (합산하지 않음 — 필요하면 행별 감정서경비 입력으로 반영)
    variable_costs = _variable_costs(db, database, year, month)
    for group in list(shareholders.values()) + list(associates.values()):
        notes = [
            item for item in expense_unmatched
            if group["name"] and group["name"] in (item["remark"] or "")
        ]
        if notes:
            group["expense_notes"] = notes
        # 전월 가변비 자동값 — 사람 단위(원천에 감정서 구분 없음), 합계 행에만 반영
        group["variable_auto"] = variable_costs.get(group["name"], 0.0)

    # 조정값은 개인 범위로 들어온 요청이면 본인 것만 남긴다 (이 브랜치의 권한 처리).
    # 상류(main)에는 scope_person 이 없어 이 자리가 그냥 load_adjustments 였다 —
    # 병합할 때마다 이 걸러내기가 사라지지 않게 주의할 것.
    adjustments = load_adjustments(db, year, month)
    if scope_person:
        adjustments = (
            {scope_person: adjustments[scope_person]}
            if scope_person in adjustments else {}
        )
    _merge_adjustments(adjustments, shareholders, associates, depts)
    active = _active_names(db)
    shareholder_groups = [
        _shareholder_totals({**group, "retired": group["name"] not in active})
        for group in shareholders.values()
    ]
    associate_groups = [
        _associate_totals({**group, "retired": group["name"] not in active})
        for group in associates.values()
    ]
    shareholder_groups.sort(key=lambda g: g["name"])
    associate_groups.sort(key=lambda g: g["name"])
    return {
        "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
        "shareholders": shareholder_groups,
        "associates": associate_groups,
        "summary": _summary(shareholder_groups, associate_groups),
    }


def _merge_adjustments(
    adjustments: "dict[str, dict[str, Any]]",
    shareholders: "dict[str, dict[str, Any]]",
    associates: "dict[str, dict[str, Any]]",
    depts: "dict[str, str]",
) -> None:
    """수기 보정(금액 수정·행 추가·공제·적용률)을 그룹에 반영한다."""
    for person, adj in adjustments.items():
        if person in shareholders:
            group, is_shareholder = shareholders[person], True
        elif person in associates:
            group, is_shareholder = associates[person], False
        else:
            is_shareholder = depts.get(person) not in ASSOCIATE_DEPTS
            group = {"name": person, "dept": depts.get(person), "docs": []}
            (shareholders if is_shareholder else associates)[person] = group
        for doc in group["docs"]:
            fee = adj["fees"].get(doc["doc_id"])
            if fee is None:
                continue
            land = doc["land_fee"]
            travel = doc.get("travel_fee") or 0
            calc = (
                shareholder_doc_calc(doc["work_type"], fee, land, travel)
                if is_shareholder else associate_doc_calc(doc["work_type"], fee, land, travel)
            )
            doc.update(base_fee=fee, estimated=False, adjusted=True, **calc)
        # 산정금액 직접 보정 (주주) — 순수수료·손배·협회비는 자동값 유지, 산정만 교체
        for doc in group["docs"]:
            assessed = adj["assessed"].get(doc["doc_id"])
            if assessed is not None:
                doc.update(assessed=assessed, adjusted=True)
        for item in adj["rows"]:
            amount = item["amount"]
            if is_shareholder:
                # 주주 수기 행 입력값 = 산정금액 (순수수료·손배·협회비 없음)
                group["docs"].append({
                    "doc_id": item["doc_id"], "work_type": item["work_type"],
                    "customer_name": item["customer_name"], "manager": person,
                    "investigator": None, "base_fee": 0.0, "auto_fee": None,
                    "auto_assessed": None, "land_fee": 0.0, "travel_fee": 0.0,
                    "survey_fee": 0.0, "expense_fee": 0.0, "estimated": False,
                    "manual": True, "memo": item.get("memo"), "paid_date": None,
                    "assessed": amount, "indemnity": 0.0, "association_fee": 0.0,
                })
            else:
                calc = associate_doc_calc(item["work_type"], amount, 0)
                group["docs"].append({
                    "doc_id": item["doc_id"], "work_type": item["work_type"],
                    "customer_name": item["customer_name"], "manager": person,
                    "investigator": None, "base_fee": amount, "auto_fee": None,
                    "land_fee": 0.0, "travel_fee": 0.0, "survey_fee": 0.0,
                    "expense_fee": 0.0, "estimated": False, "manual": True,
                    "memo": item.get("memo"), "paid_date": None, **calc,
                })
        group["deductions"] = adj["deductions"]
        group["rate"] = adj["rate"]
        # 행별 수기 항목(FIELD)·적용률 — 수기 행(ROW) 포함 전체에 적용.
        # 적용률의 사람 단위 저장분(adj["rate"])은 행별 미선택 시 기본값.
        field_keys = {
            "가변비": "variable_cost", "미납비이월": "unpaid_carry",
            "감정서경비": "expense_override", "화환공제": "wreath",
            "기타공제": "other_deduct",
        }
        for doc in group["docs"]:
            for label, key in field_keys.items():
                value = adj["fields"].get(label, {}).get(doc["doc_id"])
                if value is not None:
                    doc[key] = value
            doc_rate = adj["doc_rates"].get(doc["doc_id"], adj["rate"])
            if doc_rate:
                doc["rate"] = doc_rate


def _active_names(db: Session) -> "set[str]":
    """재직자 이름 집합 — 상여 화면 퇴사 배지용 (동명이인은 한 명이라도 재직이면 재직 취급)."""
    database = _source_database()
    rows = db.execute(
        text(
            f"SELECT DISTINCT RTRIM(EMP) FROM [{database}].dbo.TMWCMN_USR_BAC_INFO "
            f"WHERE USE_YN = 'Y' AND RTRM_FL = '0'"
        )
    ).all()
    return {row[0] for row in rows if row[0]}


def _dept_by_name(db: Session) -> "dict[str, str]":
    database = _source_database()
    rows = db.execute(
        text(
            f"SELECT RTRIM(Uname) AS name, RTRIM(Dept_Nm) AS dept "
            f"FROM [{database}].dbo.Seat_userinfo WHERE Uname IS NOT NULL"
        )
    ).all()
    result: "dict[str, str]" = {}
    for name, dept in rows:
        if name and name not in result:
            result[name] = dept or None
    return result


def _shareholder_totals(group: "dict[str, Any]", default_rate: int = 40) -> "dict[str, Any]":
    docs = group["docs"]
    fee = sum(doc["base_fee"] for doc in docs)
    travel = sum(doc.get("travel_fee") or 0 for doc in docs)
    land = sum(doc.get("land_fee") or 0 for doc in docs)
    survey = sum(doc.get("survey_fee") or 0 for doc in docs)
    expense_auto = sum(doc.get("expense_fee") or 0 for doc in docs)
    assessed = sum(doc["assessed"] for doc in docs)
    indemnity = sum(doc["indemnity"] for doc in docs)
    association = sum(doc["association_fee"] for doc in docs)

    # 행별 수기 항목 — 감정서경비는 행 자동값(전표 귀속 안분) 덮어쓰기 가능
    for doc in docs:
        doc["variable_cost"] = float(doc.get("variable_cost") or 0)
        doc["unpaid_carry"] = float(doc.get("unpaid_carry") or 0)
        doc["doc_expense"] = float(
            doc["expense_override"] if doc.get("expense_override") is not None
            else doc.get("expense_fee") or 0
        )
        doc["wreath"] = float(doc.get("wreath") or 0)
        doc["other_deduct"] = float(doc.get("other_deduct") or 0)
    # 전월 가변비(사람 단위 자동값) — 행별로 뿌리지 않고 합계(5)에만 더한다.
    # 행별 가변비 입력은 추가 조정분으로 함께 합산된다.
    person_variable = float(group.get("variable_auto") or 0)
    variable_cost = sum(doc["variable_cost"] for doc in docs) + person_variable
    unpaid_carry = sum(doc["unpaid_carry"] for doc in docs)
    doc_expense = sum(doc["doc_expense"] for doc in docs)
    wreath = sum(doc["wreath"] for doc in docs)
    other_deduct = sum(doc["other_deduct"] for doc in docs)

    deduction_total = sum(
        float(item.get("amount") or 0) for item in group.get("deductions") or []
    )
    payout_base = (
        assessed - indemnity - association
        - variable_cost - unpaid_carry - doc_expense - deduction_total
    )

    # 행 산출액 = 산정 - 손배 - 협회비 - 행별 수기(가변비·미납비·경비).
    # 자유 항목 공제(DEDUCT)와 사람 단위 가변비는 행별 산출액 비율로 안분한 뒤
    # 행별 적용률을 곱한다.
    spread_total = deduction_total + person_variable
    payouts = [
        doc["assessed"] - doc["indemnity"] - doc["association_fee"]
        - doc["variable_cost"] - doc["unpaid_carry"] - doc["doc_expense"]
        for doc in docs
    ]
    positive_total = sum(max(value, 0) for value in payouts)
    bonus_sum = 0.0
    for doc, payout in zip(docs, payouts):
        doc_rate = doc.get("rate") or default_rate
        doc["rate"] = doc_rate
        deduction_share = (
            spread_total * (max(payout, 0) / positive_total)
            if positive_total > 0 else 0.0
        )
        net = max(max(payout, 0) - deduction_share, 0.0)
        # 행별 상여기준액(안분 공제 반영, 음수 그대로) — 합계 10과 합이 일치한다
        doc["payout_base"] = payout - deduction_share
        doc["bonus_amount"] = round(net * doc_rate / 100, 2)
        bonus_sum += doc["bonus_amount"]

    # 세전(14) = 산정상여(11) - 화환공제(12) + 물건조사비(13), 천원 절사
    pretax = _floor_thousand(bonus_sum - wreath + survey)
    tax = round(pretax * TAX_RATE)
    after_tax = pretax - tax
    payment = after_tax - other_deduct
    return {
        **group,
        "totals": {
            "count": len(docs),
            "base_fee": fee,
            "travel_fee": travel,
            "land_fee": land,
            "assessed": assessed,
            "variable_cost": variable_cost,
            "variable_auto": person_variable,
            "indemnity": indemnity,
            "unpaid_carry": unpaid_carry,
            "doc_expense": doc_expense,
            "doc_expense_auto": expense_auto,
            "association_fee": association,
            "deduction_total": deduction_total,
            "payout_base": payout_base,
            "bonus_refs": {
                str(int(value * 100)): round(max(payout_base, 0) * value, 2)
                for value in SHAREHOLDER_RATES
            },
            "bonus_selected": round(bonus_sum, 2) if docs else None,
            "wreath": wreath,
            "survey_fee": survey,
            "pretax": pretax,
            "tax": tax,
            "after_tax": after_tax,
            "other_deduct": other_deduct,
            "payment": payment,
            "card": _floor_thousand(assessed * 0.05),
        },
    }


def _associate_totals(group: "dict[str, Any]") -> "dict[str, Any]":
    """평·동 = 주주와 같은 19컬럼 정산, 기본 요율만 20%. 공통건 수는 별도 표기."""
    result = _shareholder_totals(group, default_rate=20)
    result["totals"]["common_count"] = sum(
        1 for doc in group["docs"] if doc.get("common")
    )
    return result


def _summary(
    shareholder_groups: "list[dict[str, Any]]",
    associate_groups: "list[dict[str, Any]]",
) -> "list[dict[str, Any]]":
    result = []
    for group in shareholder_groups:
        totals = group["totals"]
        result.append({
            "name": group["name"], "kind": "주주", "dept": group["dept"],
            "count": totals["count"], "base_fee": totals["base_fee"],
            "assessed": totals["assessed"], "payout_base": totals["payout_base"],
            # 적용률을 선택했으면 확정 상여, 아니면 40% 참고치
            "bonus_ref": totals["bonus_selected"] or totals["bonus_refs"]["40"],
            "rate": group.get("rate"),
        })
    for group in associate_groups:
        totals = group["totals"]
        result.append({
            "name": group["name"], "kind": "평·동", "dept": group["dept"],
            "count": totals["count"], "base_fee": totals["base_fee"],
            "assessed": totals["assessed"], "payout_base": totals["payout_base"],
            "bonus_ref": totals["bonus_selected"],
            "rate": group.get("rate"),
        })
    result.sort(key=lambda row: (row["kind"], row["name"]))
    return result
