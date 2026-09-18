"""기간별 매출실적 — 매출일 기준 공급가액을 목적별로 집계한다.

- 금액: 매출 계정(401계열: 수수료 4010001·여비/실비 4010002·공시 4010003·기타 4010005)
  전표 순액 = 대변 - 차변 (공급가액, 부가세 제외, 취소 차감).
  2026-07-23 재무팀 확정 — TAMS 매출내역의 전표매출액과 같은 범위. 4010001 단독 집계는
  여비·공시 등 6억+가 빠져 재무 자료와 어긋났던 원인.
- 시점: 매출 전표의 전표일자 = 매출일 (2026-07-22 사용자 결정 — 입금일 아님)
- 범위: 선택한 지사의 사업장(division_code) 전표 전체 — 타지사 감정서의 해당 사업장
  처리분 포함, 재무제표 매출과 일치 (2026-07-22 사용자 결정).
  office_code=None(전체)이면 전 사업장 합산. 지사 사용자는 화면에서 자기 지사로
  고정된다 (2026-07-23 사용자 결정 — 입금현황과 같은 패턴).
- 비교: 전기 기간을 직접 지정 (기본값은 전년 동기)
- 목적: apw_masterex.LWorkinfo → 고정 분류 14종.
  원장에서 못 찾으면 아마란스 전표의 업무구분(raw_json.l2Nm)으로 채운다
  (2026-08-03 재무팀 확인). 관리번호에 감정서번호가 아닌 값(사업명·거래처명·
  은행 의뢰번호)이 들어오는 매출이 있어, 예전에는 그게 전부 '기타'로 뭉쳤다.
  실측: 2026년 기타 4.66억 중 1.41억이 실제로는 보상·컨설팅·일반거래였다.
"""

from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.services.office_lookup import get_office

# 보고서 행 순서 (재무팀 양식 그대로)
CATEGORIES = [
    "보상", "국공유재산", "도시개발사업", "정비사업", "법원 및 공매", "담보",
    "일반거래", "컨설팅", "가격자문", "기업관련", "유동화자산", "PF", "공시업무", "기타",
]


def category_of(raw: "str | None") -> str:
    purpose = str(raw or "").strip()
    return purpose if purpose in CATEGORIES else "기타"


# 아마란스 전표의 업무구분(l2Nm) → 화면 분류. 원장에서 목적을 못 찾을 때만 쓴다.
# 아마란스는 12종으로 더 굵게 묶으므로 1:1이 아니다 — 우리 쪽에 대응 항목이
# 없는 '약식부분'·'기타(실비)'는 기타로 둔다 (재무팀 확인 2026-08-03).
AMARANTH_CATEGORY = {
    "담보부문": "담보",
    "일반거래부문": "일반거래",
    "보상부문": "보상",
    "컨설팅부문": "컨설팅",
    "공시업무": "공시업무",
    "경매부문": "법원 및 공매",
    "공매": "법원 및 공매",
    "재건축/재개발": "정비사업",
    "약식부분": "기타",
    "기타": "기타",
    "기타(실비)": "기타",
    "자산재평가": "기타",
    # 쟁송 = 소송 감정(민사·가사·행정). 원장에 있는 40줄이 전부 '법원 및 공매'라
    # 같은 곳으로 보낸다 (거래처가 제주·수원지방법원 등, 2026-08-03 실측).
    "쟁송": "법원 및 공매",
    # 아마란스 입력 오타. 원장 매칭되는 건은 어차피 제자리로 가고,
    # 매칭 실패한 것만 여기서 건진다.
    "담보": "담보",
    "담보부분": "담보",
    "보상": "보상",
    "경매": "법원 및 공매",
    "약식": "기타",
}


def _category_list() -> str:
    """고정 분류 14종을 SQL IN 절 문자열로. '기타'는 fallback 이라 뺀다."""
    return ", ".join(f"N'{c}'" for c in CATEGORIES if c != "기타")


def _amaranth_case(column: str = "v.raw_json") -> str:
    """전표 업무구분을 화면 분류로 바꾸는 SQL CASE. 모르는 값은 기타."""
    whens = " ".join(
        f"WHEN N'{src}' THEN N'{dst}'" for src, dst in AMARANTH_CATEGORY.items()
    )
    return f"CASE JSON_VALUE({column}, '$.l2Nm') {whens} ELSE N'기타' END"


def previous_year_range(date_from: date, date_to: date) -> "tuple[date, date]":
    """전년 동기 (2월 29일은 28일로 내린다)."""
    def back(value: date) -> date:
        try:
            return value.replace(year=value.year - 1)
        except ValueError:
            return value.replace(year=value.year - 1, day=28)
    return back(date_from), back(date_to)


def build_stat_rows(
    current: "dict[str, dict[str, Any]]", previous: "dict[str, dict[str, Any]]"
) -> "list[dict[str, Any]]":
    """분류별 집계 2개(당기·전년동기)를 고정 순서의 표 행 + 합계로 만든다."""
    rows = []
    for purpose in CATEGORIES:
        cur = current.get(purpose) or {}
        prev = previous.get(purpose) or {}
        rows.append(_stat_row(purpose, cur, prev))
    total_cur = {
        "docs": sum(row["docs"] for row in rows),
        "amount": sum(row["amount"] for row in rows),
    }
    total_prev = {
        "docs": sum(row["prev_docs"] for row in rows),
        "amount": sum(row["prev_amount"] for row in rows),
    }
    return rows + [_stat_row("합계", total_cur, total_prev)]


def _stat_row(
    purpose: str, cur: "dict[str, Any]", prev: "dict[str, Any]"
) -> "dict[str, Any]":
    amount = float(cur.get("amount") or 0)
    prev_amount = float(prev.get("amount") or 0)
    diff = amount - prev_amount
    return {
        "purpose": purpose,
        "docs": int(cur.get("docs") or 0),
        "amount": amount,
        "prev_docs": int(prev.get("docs") or 0),
        "prev_amount": prev_amount,
        "diff": diff,
        # 전기가 0 이하(취소 초과 등)면 비율이 왜곡되므로 표시하지 않는다
        "rate": round(diff / prev_amount * 100, 1) if prev_amount > 0 else None,
        # 달성률 = 당기 ÷ 전기 (증감률 + 100), 2026-07-22 사용자 확정
        "achievement": round(amount / prev_amount * 100, 1) if prev_amount > 0 else None,
    }


# 매출 = 401계열 순액. 건수는 감정서(관리번호) 수.
# 국민 약식 관리번호(400*)는 개별 번호 대신 '국민 약식수수료' 한 건으로 묶고
# 가격자문으로 분류한다. 그 밖의 하이픈 없는 값은 '(번호없음)'으로 묶는다.
# 하이픈 있는 유사 번호(012601-1-0001-1 등)는 TAMS처럼 개별 행 유지.
_STATS_SQL = """
WITH sales AS (
    SELECT v.management_no, v.voucher_date,
           CASE WHEN LTRIM(RTRIM(v.management_no)) LIKE '400%'
                THEN N'국민 약식수수료'
                WHEN LTRIM(RTRIM(v.management_no)) LIKE '%-%'
                THEN LTRIM(RTRIM(v.management_no)) ELSE N'(번호없음)' END AS doc_key,
           CASE WHEN LTRIM(RTRIM(v.management_no)) LIKE '400%'
                THEN 1 ELSE 0 END AS is_kb_yak,
           CASE WHEN v.debit_credit = '4' THEN v.amount
                WHEN v.debit_credit = '3' THEN -v.amount ELSE 0 END AS net_amount,
           CASE WHEN v.voucher_date BETWEEN :cur_from AND :cur_to THEN 'cur' ELSE 'prev' END AS bucket,
           -- 원장에서 목적을 못 찾을 때 쓸 전표 업무구분 (아마란스 l2Nm)
           {amaranth_case} AS voucher_purpose
    FROM dbo.a10_voucher_cache v
    WHERE v.account_code LIKE '401%'{division_filter}
      AND ((v.voucher_date BETWEEN :cur_from AND :cur_to)
        OR (v.voucher_date BETWEEN :prev_from AND :prev_to))
)
SELECT CASE WHEN s.is_kb_yak = 1 THEN N'가격자문'
            WHEN RTRIM(m.LWorkinfo) IN ({category_list})
            THEN RTRIM(m.LWorkinfo) ELSE s.voucher_purpose END AS purpose,
       s.bucket AS bucket,
       COUNT(DISTINCT s.doc_key) AS docs,
       SUM(s.net_amount) AS amount
FROM sales s
LEFT JOIN [{database}].dbo.apw_masterex m ON m.DocID = s.management_no
{person_filter}
-- GROUP BY 는 상류(main)가 바꾼 식을 그대로 쓴다 — SELECT 의 목적 계산과 같아야
-- 한다. person_filter 는 이 브랜치의 개인범위 조건이라 그 위에 그대로 둔다.
GROUP BY CASE WHEN s.is_kb_yak = 1 THEN N'가격자문'
              WHEN RTRIM(m.LWorkinfo) IN ({category_list})
              THEN RTRIM(m.LWorkinfo) ELSE s.voucher_purpose END, s.bucket
"""


def _source_database() -> str:
    database = get_settings().mssql_source_db
    if not database.replace("_", "").isalnum():
        raise RuntimeError("MSSQL_SOURCE_DB 이름이 올바르지 않습니다.")
    return database


_DIVISION_FILTER = "\n      AND division_code = CAST(:division AS varchar(10))"


def _division_params(db: Session, office_code: "str | None") -> "tuple[str, dict[str, Any]]":
    """office_code를 SQL 사업장 필터와 바인드 파라미터로 바꾼다. None이면 전체."""
    if office_code is None:
        return "", {}
    office = get_office(db, office_code)
    if office is None:
        raise LookupError(f"지사 매핑을 찾을 수 없습니다: {office_code}")
    return _DIVISION_FILTER, {"division": office.division_code}


def period_sales_stats(
    db: Session,
    date_from: date,
    date_to: date,
    prev_from: "date | None" = None,
    prev_to: "date | None" = None,
    office_code: "str | None" = "10",
    scope_person: "str | None" = None,
) -> "dict[str, Any]":
    """당기·전기 매출 실적(매출일 기준)을 목적별로 집계한 표 데이터.

    전기(prev_from~prev_to)를 지정하지 않으면 전년 동기를 쓴다.
    office_code=None이면 전 사업장 합산(전체).
    """
    if prev_from is None or prev_to is None:
        prev_from, prev_to = previous_year_range(date_from, date_to)
    division_filter, division_params = _division_params(db, office_code)
    person_filter = (
        "WHERE (m.Manager LIKE :scope_person OR m.Charge LIKE :scope_person)"
        if scope_person else ""
    )
    raw = db.execute(
        text(_STATS_SQL.format(
            database=_source_database(),
            division_filter=division_filter,
            # 이 브랜치의 개인범위 조건 — 병합 때 빠지면 남의 실적까지 보인다
            person_filter=person_filter,
            amaranth_case=_amaranth_case(), category_list=_category_list(),
        )),
        {
            **division_params,
            **({"scope_person": f"%{scope_person}%"} if scope_person else {}),
            "cur_from": date_from, "cur_to": date_to,
            "prev_from": prev_from, "prev_to": prev_to,
        },
    ).mappings().all()
    buckets: "dict[str, dict[str, dict[str, Any]]]" = {"cur": {}, "prev": {}}
    for row in raw:
        target = buckets[row["bucket"]]
        purpose = category_of(row["purpose"])
        entry = target.get(purpose) or {"docs": 0, "amount": 0.0}
        # 같은 분류로 합쳐지는 원본 값(기타 공공 등)이 있어 누적한다. 건수는 감정서 수 근사치.
        target[purpose] = {
            "docs": entry["docs"] + int(row["docs"] or 0),
            "amount": entry["amount"] + float(row["amount"] or 0),
        }
    return {
        "rows": build_stat_rows(buckets["cur"], buckets["prev"]),
        "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
        "prev_period": {"from": prev_from.isoformat(), "to": prev_to.isoformat()},
    }


# 왼쪽 근거 자료 — 당기 매출 전표를 감정서 단위로 묶고 감정서 정보를 보강한다.
# 400* 약식번호는 '국민 약식수수료'/가격자문 한 줄로 묶고, 그 밖의 감정서번호
# 형식이 아닌 관리번호는 '(번호없음)'으로 묶는다. 다만 분류까지 함께 묶어야 한다 —
# 성격이 다른 전표가 한 줄에 뭉쳤고(7/31: 주택도시보증공사 855만 + 국민은행 약식
# 17건이 9,659,632 한 줄), 집계표에서 분류를 클릭하면 상세 금액이 안 맞았다.
_DETAIL_SQL = """
WITH sales AS (
    SELECT CASE WHEN LTRIM(RTRIM(v.management_no)) LIKE '400%'
                THEN N'국민 약식수수료'
                WHEN LTRIM(RTRIM(v.management_no)) LIKE '%-%'
                THEN LTRIM(RTRIM(v.management_no)) ELSE N'(번호없음)' END AS doc_key,
           CASE WHEN LTRIM(RTRIM(v.management_no)) LIKE '%-%'
                THEN LTRIM(RTRIM(v.management_no)) END AS doc_id,
           v.voucher_date,
           CASE WHEN LTRIM(RTRIM(v.management_no)) LIKE '400%'
                THEN 1 ELSE 0 END AS is_kb_yak,
           CASE WHEN v.debit_credit = '4' THEN v.amount
                WHEN v.debit_credit = '3' THEN -v.amount ELSE 0 END AS net_amount,
           {amaranth_case} AS voucher_purpose
    FROM dbo.a10_voucher_cache v
    WHERE v.account_code LIKE '401%'{division_filter}
      AND v.voucher_date BETWEEN :date_from AND :date_to
), classified AS (
    -- 분류를 여기서 확정한다. 같은 관리번호라도 업무구분이 갈리는 전표가 있어
    -- (관리번호 '1' 처럼 여러 건에 두루 쓰이는 값), 분류까지 묶어야 집계와 맞는다.
    SELECT s.doc_key, s.doc_id, s.voucher_date, s.net_amount,
           CASE WHEN s.is_kb_yak = 1 THEN N'가격자문'
                WHEN RTRIM(m.LWorkinfo) IN ({category_list})
                THEN RTRIM(m.LWorkinfo) ELSE s.voucher_purpose END AS work_type
    FROM sales s
    LEFT JOIN [{database}].dbo.apw_masterex m ON m.DocID = s.doc_id
), grouped AS (
    SELECT doc_key, MAX(doc_id) AS doc_id, work_type,
           SUM(net_amount) AS voucher_amount, MAX(voucher_date) AS voucher_date
    FROM classified GROUP BY doc_key, work_type
    -- 매출 걸었다 같은 기간에 취소로 상쇄한 '(번호없음)' 전표(순액 0)는 0원 줄로만
    -- 남아 지저분하다 — 숨긴다(2026-09-04). 감정서번호가 붙은 건은 0원이라도 남긴다.
    HAVING NOT (doc_key = N'(번호없음)' AND SUM(net_amount) = 0)
)
SELECT g.doc_key AS doc_id, g.voucher_amount, g.voucher_date, g.work_type,
       RTRIM(m.LPurpose) AS purpose_detail,
       RTRIM(m.CustName) AS customer_name, RTRIM(m.Manager) AS manager,
       RTRIM(m.Charge) AS investigator, m.SendDate AS send_date,
       m.[기초수수료] AS base_fee, m.[청구금액] AS billed_amount
FROM grouped g
LEFT JOIN [{database}].dbo.apw_masterex m ON m.DocID = g.doc_id
{person_filter}
ORDER BY g.voucher_date DESC, g.doc_id DESC
"""


def sales_detail(
    db: Session,
    date_from: date,
    date_to: date,
    office_code: "str | None" = "10",
    scope_person: "str | None" = None,
) -> "list[dict[str, Any]]":
    """당기 매출 전표의 감정서별 상세 (표 오른쪽 집계의 근거 자료)."""
    division_filter, division_params = _division_params(db, office_code)
    person_filter = (
        "WHERE (m.Manager LIKE :scope_person OR m.Charge LIKE :scope_person)"
        if scope_person else ""
    )
    rows = db.execute(
        text(_DETAIL_SQL.format(
            database=_source_database(),
            division_filter=division_filter,
            # 이 브랜치의 개인범위 조건 — 병합 때 빠지면 남의 실적까지 보인다
            person_filter=person_filter,
            amaranth_case=_amaranth_case(), category_list=_category_list(),
        )),
        {
            **division_params,
            **({"scope_person": f"%{scope_person}%"} if scope_person else {}),
            "date_from": date_from,
            "date_to": date_to,
        },
    ).mappings().all()
    return [
        {
            "doc_id": row["doc_id"] or "(번호없음)",
            "purpose_detail": row["purpose_detail"],
            "work_type": category_of(row["work_type"]) if row["doc_id"] else "기타",
            "customer_name": row["customer_name"],
            "manager": row["manager"],
            "investigator": row["investigator"],
            "send_date": row["send_date"].date().isoformat() if row["send_date"] else None,
            "base_fee": float(row["base_fee"] or 0),
            "voucher_amount": float(row["voucher_amount"] or 0),
            "billed_amount": float(row["billed_amount"] or 0),
            "voucher_date": row["voucher_date"].isoformat() if row["voucher_date"] else None,
        }
        for row in rows
    ]
