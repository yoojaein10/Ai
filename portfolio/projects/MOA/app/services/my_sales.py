"""평가사 개인 매출 대시보드.

기간은 전표일자(voucher_date), 금액은 401 계열 순액이다.

금액 기준은 **공급가액(401 순액, 부가세 제외)** 이다 — 2026-08-10 사용자 확정.
한때 정산가이드를 따라 ×1.1(부가세 포함 매출총액)을 썼는데, 실측으로 회사의
실제 기준을 확인하고 되돌렸다:
  · 성과상여 정산(재무팀 엑셀·상여 화면)의 순수수료 = 부가세 제외
    (Basic_Susu·In_Price 모두 '부가세 포함과 일치 0건' 실측)
  · 기간별 매출실적 = 공급가액 (2026-07-23 재무팀 확정, TAMS 대사)
  · 옛 JSP(MAECUL·유치상여 통보 화면)도 전부 부가세 제외
  즉 부가세 포함인 화면은 이 화면 하나뿐이었다 — 혼자 다를 이유가 없다.
덕분에 기간별 매출실적과 숫자가 다리(×1.1) 없이 그대로 일치한다.
(정산가이드의 매출총액(부가세 포함)은 미수금·반제 화면의 기준으로는 옳다 —
입금이 부가세 포함으로 들어오기 때문. 실적 화면에는 해당하지 않는다.)

참고: 401 순액이 원장 SuSuSum(수수료합계)과 88.1% 정확히 일치함을 실측했다
— 401 전표는 매출 인식 시점의 총액이라 선수금 차감 문제(정산가이드가 막으려던
청구금액 오류)가 애초에 없다.

실적 귀속은 원장 apw_masterex 의 Manager(유치자) 칸이다.
공동 건은 이 칸에 '공(이름)' 으로 적히므로 단독/공동을 이 칸 하나로 가른다.

카드·차트·순위를 항목마다 따로 질의하면 같은 CTE를 여덟 번 돌아 2분이 넘는다.
그래서 기간(올해+전년) 감정서 단위 집계를 한 번에 받아 파이썬에서 나눈다.
"""

import logging
import re
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.services.office_lookup import docid_prefixes, get_office


# ── 교착 상태 재시도 ──────────────────────────────────────────────────────
# 이 화면은 원장(apworksdw)을 읽는데, 그 DB 에는 APWorks 가 지금도 쓰고 있다.
# 순수 읽기라도 쓰는 쪽과 잠금 순서가 엇갈리면 SQL Server 가 둘 중 하나를
# **교착 희생자**로 골라 끊는다(SQLSTATE 40001 · 오류 1205). 실제로 났다 —
# 목록·대시보드·연도별을 나란히 던지자 두 건이 500 으로 떨어졌다.
#
# 읽기 전용이라 그냥 다시 하면 된다. 되돌릴 부수효과가 없다.
# 세 번까지, 짧게 쉬었다가 — 교착은 순간이고 대개 첫 재시도에서 풀린다.
_DEADLOCK_TRIES = 3
_DEADLOCK_BACKOFF = 0.15


def _is_deadlock(exc: BaseException) -> bool:
    text_of = str(exc)
    return "40001" in text_of or "(1205)" in text_of


def _exec(db: Session, sql: str, params: "dict[str, Any] | None" = None):
    """읽기 한 방. 교착 희생자로 끊기면 다시 한다."""
    for attempt in range(_DEADLOCK_TRIES):
        try:
            return db.execute(text(sql), params or {})
        except SQLAlchemyError as exc:
            if attempt == _DEADLOCK_TRIES - 1 or not _is_deadlock(exc):
                raise
            logger.warning("교착으로 끊겨 다시 시도합니다 (%d/%d)",
                           attempt + 1, _DEADLOCK_TRIES)
            db.rollback()
            time.sleep(_DEADLOCK_BACKOFF * (attempt + 1))
    raise RuntimeError("unreachable")

logger = logging.getLogger(__name__)

# 공동 실적 표기. 원장 Manager 에 '공(홍길동)' 또는 '공(A),공(B)' 로 들어간다.
JOINT_PREFIX = "공("
# 사람 이름이 아닌 값 — 개인 순위에서 뺀다.
COMMON_MANAGER = "공통"

def _source_database() -> str:
    return get_settings().mssql_source_db


def _division_filter(db: Session, office_code: "str | None") -> "tuple[str, dict[str, Any]]":
    """지사 조건. 전표의 division_code 로 거른다 (sales_stats 와 같은 방식)."""
    if office_code is None:
        return "", {}
    office = get_office(db, office_code)
    if office is None:
        raise LookupError(f"지사 매핑을 찾을 수 없습니다: {office_code}")
    return " AND v.division_code = :division", {"division": office.division_code}


def previous_year_range(date_from: date, date_to: date) -> "tuple[date, date]":
    """전년 동기. 2월 29일은 28일로 내린다."""

    def shift(value: date) -> date:
        try:
            return value.replace(year=value.year - 1)
        except ValueError:
            return value.replace(year=value.year - 1, day=28)

    return shift(date_from), shift(date_to)


# 감정서 한 건이 한 줄. 전표를 여러 번 끊었어도 합쳐서 준다.
# 기간 판정은 전표일자다 — 매출이 인식된 날.
# 기간 판정은 **전표 줄 단위**다 — 기간별 매출실적과 같은 규칙. 감정서의 마지막
# 전표일로 건 전체를 한 기간에 몰면, 연도에 걸친 건(작년 취소 + 올해 재인식)의
# 작년분이 올해로 흡수된다. 실측(2026-01~07 본사): 12건 −1.37억이 이동해 기간별
# 합계와 0.69% 어긋났다. 줄 단위로 가르면 잔차 0원.
#
# 구현은 기간별 UNION ALL 이다. 처음에 GROUP BY 관리번호+bucket(CASE 식)으로
# 짰더니 실행계획이 무너져 0.9초짜리가 40초가 됐다(실측). 창마다 따로 긁어
# 상수 bucket 을 붙이면 각 가지가 날짜 범위 인덱스를 그대로 탄다.
_ROWS_SQL = """
WITH grouped AS (
    SELECT v.management_no,
           MAX(v.voucher_date) AS voucher_date,
           -- 공급가액(부가세 제외) — 상여·기간별과 같은 기준 (2026-08-10 확정).
           SUM(CASE WHEN v.debit_credit = '4' THEN v.amount
                    WHEN v.debit_credit = '3' THEN -v.amount ELSE 0 END) AS amount,
           'cur' AS bucket
    FROM dbo.a10_voucher_cache v
    WHERE v.account_code LIKE '401%'
      AND v.management_no IS NOT NULL{division_filter}
      AND v.voucher_date BETWEEN :cur_from AND :cur_to
    GROUP BY v.management_no
    UNION ALL
    SELECT v.management_no,
           MAX(v.voucher_date),
           SUM(CASE WHEN v.debit_credit = '4' THEN v.amount
                    WHEN v.debit_credit = '3' THEN -v.amount ELSE 0 END),
           'prev'
    FROM dbo.a10_voucher_cache v
    WHERE v.account_code LIKE '401%'
      AND v.management_no IS NOT NULL{division_filter}
      AND v.voucher_date BETWEEN :prev_from AND :prev_to
    GROUP BY v.management_no
)
SELECT g.management_no AS doc_id, g.voucher_date, g.amount, g.bucket,
       RTRIM(ISNULL(m.Manager, '')) AS manager,
       CASE WHEN RTRIM(ISNULL(m.LCategory, '')) = '' THEN N'(미분류)'
            ELSE RTRIM(m.LCategory) END AS category,
       RTRIM(ISNULL(m.LWorkinfo, '')) AS work_type,
       -- 소재지(m.Address)는 **여기서 안 가져온다** — _addresses() 가 따로 묻는다.
       -- 이유는 그 함수 주석에 있다: 이 한 열이 질의를 2.5초에서 38.6초로 만든다.
       m.CustName AS customer_name,
       -- 원장에 짝이 있는가. 소재지를 **있는 건만** 물으려고 같이 받는다 —
       -- 없는 번호를 섞어 물으면 계획이 무너진다(실측: 282개 물어 0건 회신에 21초).
       CASE WHEN m.DocID IS NULL THEN 0 ELSE 1 END AS in_ledger,
       -- 미수 탭용. 기간이 아니라 **지금 시점의 잔액**이다 — 이 기간에 매출로
       -- 인식한 건 중 아직 안 들어온 돈이 얼마인가를 본다. 요약표가 없으면 0.
       CAST(ISNULL(s.outstanding_amount, 0) AS float) AS outstanding,
       -- 매출총액(부가세 포함). **요약표의 실제 값**이지 401 순액 × 1.1 이 아니다
       -- — 부분 청구 건에서 어긋난다(실측 8건 중 2건: 01-2607-A-0104 는 요약표
       -- 1,107만인데 ×1.1 은 496만). 미수금현황 화면이 쓰는 바로 그 값이다.
       CAST(ISNULL(s.billed_amount, 0) AS float) AS billed
FROM grouped g
-- LOOP 을 못 박는다 (2026-08-11). apw_masterex 는 테이블이 아니라 **뷰**이고
-- 그 안에서 스칼라 UDF 를 부른다(dbo.fnBun · ufn_Fmt_smallDatetimeToYMD).
-- 옵티마이저는 해시 조인을 골라 **뷰 73만 행을 통째로 만든 뒤** 8천 행에
-- 붙이는데, 그게 이 화면의 가장 큰 비용이었다. 감정서번호로 하나씩 찾게
-- 하면(LOOP) 필요한 건만 만든다. 실측 —
--     본사 8개월(8,478행)   자동 5.10초 → LOOP 0.35초
--     전사 8개월(35,829행)  자동 4.47초 → LOOP 1.76초
--     전사 2년(120,481행)   자동 5.54초 → LOOP 4.94초
--     전사 5년(323,884행)   자동 7.14초 → LOOP 12.52초  ← 여기서 뒤집힌다
-- 이 화면은 기간을 **연도 하나**로만 고르므로(당해 + 전년 = 최대 2년) 뒤집히는
-- 구간에 닿지 않는다. 기간 선택을 여러 해로 넓히게 되면 이 힌트를 다시 재라.
LEFT OUTER LOOP JOIN [{database}].dbo.apw_masterex m ON m.DocID = g.management_no
LEFT JOIN dbo.a10_receivable_summary s ON s.doc_id = g.management_no
"""




def _fetch_rows(
    db: Session,
    office_code: "str | None",
    date_from: date,
    date_to: date,
    prev_from: "date | None" = None,
    prev_to: "date | None" = None,
) -> "list[dict[str, Any]]":
    """전표 줄을 감정서 단위로 접어 온다.

    prev 를 안 주면 같은 창을 두 번 넘긴다. **일부러 그렇게 둔다.**
    2026-08-10 에 '전년이 필요 없으면 UNION 가지를 빼자' 며 한 창짜리 SQL 을
    따로 만들었다가 물렀다 — 실측이 정반대였다:
        한 창(5,288행) 4.35초  ·  두 창(8,465행) 1.57초
    적게 긁는 쪽이 3배 느리다. 열을 줄이고 조인을 빼자 실행계획이 나빠진
    것으로 보인다. 데이터가 적으니 빠를 것이라는 짐작을 믿지 말 것.
    """
    div_sql, div_params = _division_filter(db, office_code)
    sql = _ROWS_SQL.format(division_filter=div_sql, database=_source_database())
    rows = _exec(
        db, sql,
        {
            **div_params,
            "cur_from": date_from, "cur_to": date_to,
            "prev_from": prev_from or date_from, "prev_to": prev_to or date_to,
        },
    ).mappings().all()
    # 감정서 하나에 한 줄 — apw_masterex 의 DocID 가 유일하지 않으면 LEFT JOIN 이
    # 그 건을 행 수만큼 불린다. 실측(2026-08-10): 73만 행 중 DocID 가 겹치는 건이
    # **3건**이다(08-1803-3-0357 · 06-1801-3-0357 · 09-2205-3-0252). 셋 다 유치자
    # 칸이 비어 개인 화면에는 원래 안 잡히고, 화면이 보여주는 최근 5년 안에 드는
    # 09-2205-3-0252 는 401 순액이 0원이라 **지금 실害는 0원**이다. 그래도 접는다
    # — 전체 보기는 이 합이 곧 회사 매출이라, 한 건만 겹쳐도 조용히 부푼다.
    # 겹친 줄들은 유치자·물건·업무가 모두 같아 어느 쪽을 남겨도 값이 같다.
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        key = (str(row["doc_id"]), str(row["bucket"]))
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(row))
    return out


def _bare(name: str) -> str:
    """'공(홍길동)' → '홍길동'. 표기를 벗겨 사람 이름만 남긴다."""
    name = name.strip()
    if name.startswith(JOINT_PREFIX) and name.endswith(")"):
        return name[len(JOINT_PREFIX):-1].strip()
    return name


def _names_of(manager: str) -> "list[tuple[str, bool]]":
    """유치자 칸을 (이름, 공동표기여부) 목록으로 쪼갠다.

    한 칸에 쉼표로 여러 명이 들어간다 — '조근렬,강무진,김형식', '윤도,공(장재원)'.
    """
    out = []
    for part in manager.split(","):
        part = part.strip()
        if not part or part == COMMON_MANAGER:
            continue
        out.append((_bare(part), part.startswith(JOINT_PREFIX)))
    return [(n, j) for n, j in out if n]


# 배분 없이 여럿이 걸린 건은 금액을 확정할 수 없어 공동(수기정산)으로 넘긴다.
SINGLE, JOINT = "single", "joint"



def _attribute(
    row: "dict[str, Any]", alloc_by_doc: "dict[str, dict[str, float]]"
) -> "list[tuple[str, float, str]]":
    """감정서 한 건을 사람별로 나눈다 → [(이름, 금액, 단독/공동), ...].

    **지분표(APW_Booking)가 있으면 언제나 그것을 쓴다.** 유치자 칸은 사람을
    가리키는 이름표일 뿐 금액의 근거가 아니다. 칸에는 '조근렬,강무진,김형식' 이
    한 덩어리로 들어 있고, 같은 세 명이어도 50/25/25 인 건과 33/33/33 인 건이
    있어 균등 배분으로 대신할 수 없다.

    지분이 없을 때만 유치자 칸으로 물러선다. 한 명이면 그 사람 몫이고, 여럿이면
    나눌 근거가 없으니 금액을 **지어내지 않고** 공동으로 넘겨 사람이 정산한다.
    (2026년 실측으로는 공동 표기인데 지분이 없는 건이 0건이라 이 길은 거의 안 탄다.)
    """
    manager = (row.get("manager") or "").strip()
    amount = float(row.get("amount") or 0)
    names = _names_of(manager)
    joint_by_name = dict(names)

    alloc = alloc_by_doc.get(row["doc_id"]) or {}
    total = sum(alloc.values())
    if total > 0:
        # 지분이 있으면 칸에 이름이 없는 사람도 제 몫을 받는다 — 칸은 자주 빠진다.
        # 지분으로 나뉜 금액은 **확정된 내 몫**이다 — 공동(수기정산)이 아니다.
        #
        # 예외: 지분표가 '공(장재원)' 같은 **공동계정** usr_seq 를 가리키는 건
        # (실측 2026-01~07 본사 16건·2.55억). 그대로 두면 유령 이름으로 귀속돼
        # 장재원 본인 화면 어디에도 안 잡히고, 실적자 목록·순위에까지 유령이
        # 낀다. 공동계정의 뜻 자체가 '수기정산 대상'이므로 실명으로 벗겨 공동
        # 대기로 넘긴다 — 이때만은 건 전체가 아니라 **정확한 지분 몫**이다.
        return [
            (_bare(name), amount * share / total,
             JOINT if name.startswith(JOINT_PREFIX) else SINGLE)
            for name, share in alloc.items()
        ]

    if not names:
        return []
    if len(names) == 1:
        name, is_joint = names[0]
        return [(name, amount, JOINT if is_joint else SINGLE)]
    return [(name, amount, JOINT) for name, _ in names]


# 배분 원천은 **유치자 지분표(APW_Booking)** 다. 2026-08-08 에 원장
# (Apw_Mae_GaPrice.Basic_Susu)에서 이리로 옮겼다.
#
# 왜 옮겼나 — 실측이다. 유치자 칸에 쉼표로 여럿이 걸린 건을 표본으로 보면
# APW_Booking 은 사람마다 한 줄을 갖고 있는데(2명이면 2줄) 원장은 **0줄**이다.
# 원장이 비어 있으니 종전 코드는 "금액을 모른다"며 참여자 **전원에게 건 전체
# 금액**을 공동으로 넘겼다. 나눌 근거가 이미 있는데 안 쓰고 중복 표시한 것이다.
# 2026년 감정서 2,496건 중 지분이 있는 건은 2,125건(85.1%)이고, 공동 표기인데
# 지분이 없는 건은 0건이다.
#
# 지분은 **합으로 정규화**한다. '100,100,100'(합 300)은 각자 100%가 아니라
# 균등분할 표기다(실측: 기초수수료를 정확히 3등분).
# 원장 대조: 1억 이상 53명의 배수 중앙 0.98(P25 0.95 / P75 1.06) — 회사가 손으로
# 확정한 배분을 재현한다.
# 사람 이름은 여기서 조인하지 않는다. usr_seq→이름 은 몇백 행짜리 표라 한 번
# 읽어 파이썬에서 붙이는 편이 싸다. 조인해 뒀더니 2개월 조회가 85초 걸렸다
# (CAST 비교라 인덱스를 못 탄다).
_SHARE_SQL = """
SELECT RTRIM(k.DocID) AS doc_id, RTRIM(b.Manager) AS usr_seq,
       CAST(b.Ratio AS float)
         / NULLIF(SUM(CAST(b.Ratio AS float)) OVER (PARTITION BY b.MasterID), 0) AS share
FROM [{database}].dbo.APW_Booking b
JOIN [{database}].dbo.APW_MASTER k ON k.MasterID = b.MasterID
-- 비교 칸에 RTRIM 을 씌우면 인덱스를 못 탄다 — 2개월 조회가 46초였다.
-- SQL Server 의 char/varchar 비교는 뒤 공백을 무시하므로 씌울 이유도 없다.
WHERE b.Ratio > 0 AND k.DocID IN ({placeholders})
"""

_NAME_SQL = """
SELECT CAST(USR_SEQ AS varchar(20)) AS usr_seq, RTRIM(EMP) AS emp_name
FROM [{database}].dbo.TMWCMN_USR_BAC_INFO
WHERE EMP IS NOT NULL AND RTRIM(EMP) <> ''
"""


def _names_by_usr_seq(db: Session) -> "dict[str, str]":
    """usr_seq → 이름. 요청 한 번에 한 번만 읽는다."""
    rows = _exec(db, _NAME_SQL.format(database=_source_database())).mappings()
    return {r["usr_seq"]: r["emp_name"] for r in rows}
# SQL Server 파라미터 2,100개 한계.
_ALLOC_CHUNK = 800


def _allocations(db: Session, docs: "list[str]") -> "dict[str, dict[str, float]]":
    """감정서별 사람 몫(지분). 값은 비율이라 _attribute 가 합으로 다시 나눈다.

    지분표는 사람을 usr_seq 로 가리키므로 이름으로 바꿔서 돌려준다 — 화면과
    순위가 이름을 키로 쓰기 때문이다. 이름으로 **찾지는** 않는다는 점이 중요하다.
    `Manager LIKE '%이영은%'` 는 '공(이영은)' 592건을 함께 물어 실측 과대였다.
    """
    if not docs:
        return {}
    by_seq = _names_by_usr_seq(db)
    out: dict[str, dict[str, float]] = defaultdict(dict)
    for offset in range(0, len(docs), _ALLOC_CHUNK):
        chunk = docs[offset : offset + _ALLOC_CHUNK]
        names = [f"al_{index}" for index in range(len(chunk))]
        rows = _exec(
            db,
            _SHARE_SQL.format(
                database=_source_database(),
                placeholders=",".join(":" + n for n in names),
            ),
            {n: chunk[index] for index, n in enumerate(names)},
        ).mappings().all()
        for r in rows:
            share = float(r["share"] or 0)
            name = by_seq.get(r["usr_seq"])
            # 이름을 못 찾는 usr_seq(퇴사·삭제 계정)는 건너뛴다. 지분 합으로
            # 정규화하므로 남은 사람들끼리 비율이 유지된다.
            if share > 0 and name:
                out[r["doc_id"]][name] = share
    return dict(out)


def _sum(rows: "list[dict[str, Any]]") -> dict[str, Any]:
    return {"count": len(rows), "amount": float(sum(float(r["amount"] or 0) for r in rows))}


def _monthly(rows: "list[dict[str, Any]]") -> "list[dict[str, Any]]":
    bucket: dict[str, list] = defaultdict(list)
    for r in rows:
        if r["voucher_date"]:
            bucket[r["voucher_date"].strftime("%Y-%m")].append(r)
    return [
        {"month": ym, "count": len(items),
         "amount": float(sum(float(i["amount"] or 0) for i in items))}
        for ym, items in sorted(bucket.items())
    ]


def _by_category(rows: "list[dict[str, Any]]") -> "list[dict[str, Any]]":
    bucket: dict[str, list] = defaultdict(list)
    for r in rows:
        bucket[r["category"]].append(r)
    out = [
        {"name": name, "count": len(items),
         "amount": float(sum(float(i["amount"] or 0) for i in items))}
        for name, items in bucket.items()
    ]
    out.sort(key=lambda x: -x["amount"])
    return out


# ── 발주처 정규화 ──────────────────────────────────────────────────────────
# 원장 발주처 칸은 사람이 받아 적은 그대로다: "기업은행 남동산단지점장",
# "주택도시보증공사 사장", "(주)서한", "한국투자증권 외". 그대로 묶으면 같은
# 기관이 지점·직함마다 딴 줄이 된다(실측: 원문 1,507종 → 정규화 844종.
# 기업은행 하나가 304건 9.3억으로 묶인다). 규칙 셋:
#   ① 꼬리의 직함을 벗긴다 — 마지막 어절이 직함일 때만(기관명 자체는 안 건드린다:
#      "…재개발정비사업조합장"은 한 어절이라 그대로 남는다).
#   ② 법인 표기((주)·주식회사·(재)…)와 "외 N인" 꼬리를 걷는다.
#   ③ 첫 어절이 금융기관이면 기관으로 묶는다 — 평가사의 거래처는 지점이 아니라
#      은행이다. 지점 내역은 툴팁·표에서 원문으로 확인한다.
_CUSTOMER_TITLE = re.compile(
    r"^(지점장|지점|출장소장|출장소|영업부장|영업점장|센터장|센터|본부장|본부|"
    r"사장|행장|조합장|이사장|은행장|지사장|지사|지역본부|금융센터장|금융센터|"
    r"사무소장|사무소|위원장|청장|시장|군수|구청장|도지사|법원장|원장|소장|서장|"
    r"국장|처장|단장|공장장|팀장)$"
)
_CUSTOMER_CORP = re.compile(r"^(\(주\)|주식회사\s*|㈜\s*|\(유\)|유한회사\s*|\(재\)|재단법인\s*|\(사\)|사단법인\s*)")
_CUSTOMER_CORP_TAIL = re.compile(r"(\(주\)|㈜)$")
_CUSTOMER_ETC = re.compile(r"\s+외\s*\d*\s*(인|명)?$")
_INSTITUTION = re.compile(r"(은행|금고|증권|생명|화재|해상|캐피탈|저축은행|농협|수협|신협|카드)$")
# 마지막 어절이 '든든전세임대센터장'처럼 부서+직함 복합어면 fullmatch 로는 못
# 벗긴다(실측: '주택도시보증공사'와 '주택도시보증공사 든든전세임대센터장'이 딴
# 줄로 남았다 — 합치면 437건 4.0억짜리 1위 발주처다). 어절이 둘 이상일 때
# 마지막 어절이 조직 단위로 **끝나면** 통째로 떨군다. '사장·행장' 같은 한 단어
# 직함은 endswith 로 걸면 '공장'·'시장'까지 물어 위험하므로 fullmatch 에만 둔다.
_CUSTOMER_UNIT_TAIL = re.compile(
    r"(지점장|지점|출장소장|출장소|영업부장|영업점장|금융센터장|금융센터|센터장|센터|"
    r"본부장|지역본부|본부|사무소장|사무소|조합장|이사장|팀장)$"
)


def normalize_customer(name: "str | None") -> str:
    stripped = (name or "").strip()
    if not stripped:
        return "(미기재)"
    stripped = _CUSTOMER_ETC.sub("", stripped)
    stripped = _CUSTOMER_CORP.sub("", stripped)
    stripped = _CUSTOMER_CORP_TAIL.sub("", stripped).strip()
    parts = stripped.split()
    while len(parts) > 1 and (
        _CUSTOMER_TITLE.fullmatch(parts[-1]) or _CUSTOMER_UNIT_TAIL.search(parts[-1])
    ):
        parts.pop()
    if parts and len(parts) > 1 and _INSTITUTION.search(parts[0]):
        return parts[0]
    return " ".join(parts) or "(미기재)"


def _by_customer(
    cur_rows: "list[dict[str, Any]]",
    prev_rows: "list[dict[str, Any]]",
    limit: int = 7,
) -> dict[str, Any]:
    """발주처별 내 실적 — 누가 내 일을 주나. 상위 limit + 나머지는 '기타'.

    전년 동기 금액을 같은 정규화로 붙여, 관계가 새로 생겼는지(is_new)
    식었는지(gone)를 화면이 말할 수 있게 한다. 정렬은 금액이다 —
    가격자문처럼 건수만 많고 금액이 미미한 축이 위로 오면 왜곡이다.

    설계 심사(2026-08-08)는 지점 단위 집계도 검토했지만 기관 단위로 확정했다.
    지점 단위면 기업은행 하나가 수십 줄로 조각나(실측 304건이 지점 3~7건씩)
    '누가 나를 먹여살리나'가 안 보인다. 지점·원문은 raw_top(툴팁)과 내역 표가
    갖고 있다. 기관으로 묶으니 '지점 이동을 이탈로 오인'하는 문제도 사라진다.
    """
    def rollup(rows: "list[dict[str, Any]]") -> "dict[str, list]":
        # [건수, 금액, 원문별 건수]
        agg: dict[str, list] = defaultdict(lambda: [0, 0.0, defaultdict(int)])
        for r in rows:
            key = normalize_customer(r.get("customer_name"))
            agg[key][0] += 1
            agg[key][1] += float(r.get("amount") or 0)
            agg[key][2][(r.get("customer_name") or "").strip() or "(미기재)"] += 1
        return agg

    cur, prev = rollup(cur_rows), rollup(prev_rows)
    ranked = sorted(cur.items(), key=lambda x: -x[1][1])
    top = []
    for name, (c, a, raws) in ranked[:limit]:
        raw_top = sorted(raws.items(), key=lambda x: -x[1])
        top.append({
            "name": name, "count": c, "amount": a,
            "prev_amount": prev.get(name, [0, 0.0, None])[1],
            "is_new": name not in prev,
            # 툴팁용: 대표 원문과, 몇 개 지점·부서가 묶였는지
            "raw_name": raw_top[0][0],
            "raw_kinds": len(raws),
        })
    rest = ranked[limit:]
    others = {
        "count": sum(c for _, (c, _a, _r) in rest),
        "amount": float(sum(a for _, (_c, a, _r) in rest)),
        "kinds": len(rest),
    }
    # 식은 관계: 전년엔 있었는데 올해 0건인 발주처 중 전년 금액 상위.
    # 이 화면의 유일한 '행동 지시'다 — 다음 분기 매출을 정하는 전화 목록.
    gone = sorted(
        ((n, v[1]) for n, v in prev.items() if n not in cur and n != "(미기재)"),
        key=lambda x: -x[1],
    )
    return {
        "top": top,
        "others": others,
        "gone": [{"name": n, "prev_amount": a} for n, a in gone[:5] if a > 0],
    }


# 공동 건의 정산은 지분표를 고치지 않는다 — 실측(2026-08-10): 24~25년 공동계정
# 지분 감정서 1,872건이 정산 뒤에도 전부 공동계정을 가리킨 채다. 시스템에 남는
# 유일한 확정 경로는 배분 원장(Apw_Mae_GaPrice)이고, 회사 확정이 지분표와 다른
# 사례도 실재한다(지분표 50/50 인데 원장 확정은 100/0). 그래서 **공동 후보 건에
# 한해** 원장에 실명 확정이 있으면 원장을 정본으로 쓴다 — '배분되면 개인에게
# 들어간다'가 이 폴백으로 실제 데이터에서 성립한다(2026 실측: 275건 중 31건 이동).
_LEDGER_SQL = """
SELECT RTRIM(g.Docid) AS doc_id, RTRIM(g.Manager) AS manager,
       SUM(CAST(ISNULL(g.Basic_Susu, 0) AS float)) AS amount
FROM [{database}].dbo.Apw_Mae_GaPrice g
WHERE g.Docid IN ({placeholders})
  AND g.Manager IS NOT NULL AND RTRIM(g.Manager) <> ''
  AND g.Manager NOT LIKE N'공(%'
GROUP BY RTRIM(g.Docid), RTRIM(g.Manager)
HAVING SUM(CAST(ISNULL(g.Basic_Susu, 0) AS float)) > 0
"""


def _ledger_allocations(db: Session, docs: "list[str]") -> "dict[str, dict[str, float]]":
    """감정서별 원장 실명 확정 배분. 공동 후보 건에만 묻는다."""
    out: dict[str, dict[str, float]] = defaultdict(dict)
    for offset in range(0, len(docs), _ALLOC_CHUNK):
        chunk = docs[offset : offset + _ALLOC_CHUNK]
        names = [f"ld_{index}" for index in range(len(chunk))]
        rows = _exec(
            db,
            _LEDGER_SQL.format(
                database=_source_database(),
                placeholders=",".join(":" + n for n in names),
            ),
            {n: chunk[index] for index, n in enumerate(names)},
        ).mappings().all()
        for r in rows:
            out[r["doc_id"]][r["manager"]] = float(r["amount"] or 0)
    return dict(out)


def _joint_candidates(
    rows: "list[dict[str, Any]]", alloc: "dict[str, dict[str, float]]"
) -> "list[str]":
    """공동 대기가 나올 수 있는 감정서 — 원장 확정을 물어볼 대상."""
    docs = set()
    for r in rows:
        a = alloc.get(r["doc_id"])
        if a:
            if any(n.startswith(JOINT_PREFIX) for n in a):
                docs.add(r["doc_id"])
            continue
        names = _names_of(r.get("manager") or "")
        if len(names) > 1 or any(j for _, j in names):
            docs.add(r["doc_id"])
    return sorted(docs)


def _with_ledger_settlement(
    db: Session,
    rows: "list[dict[str, Any]]",
    alloc: "dict[str, dict[str, float]]",
) -> "dict[str, dict[str, float]]":
    """공동 후보 건 중 원장 실명 확정이 있는 건은 원장 배분으로 덮는다."""
    settled = _ledger_allocations(db, _joint_candidates(rows, alloc))
    if not settled:
        return alloc
    merged = dict(alloc)
    merged.update(settled)
    return merged


def _mix_by(
    field: str,
    cur_rows: "list[dict[str, Any]]",
    prev_rows: "list[dict[str, Any]]",
) -> "list[dict[str, Any]]":
    """구성 축(업무종류·물건종류)별 금액·건수를 올해/전년 한 벌로. 금액 정렬.

    전년도 '금액'을 같이 내는 것이 핵심이다 — 종전 화면은 전년을 건수로만
    비교해서, 가격자문(실측 62건 0.03억) 같은 저단가 다건 축이 증감을 지배했다.
    """
    def rollup(rows: "list[dict[str, Any]]") -> "dict[str, list]":
        agg: dict[str, list] = defaultdict(lambda: [0, 0.0])
        for r in rows:
            key = (r.get(field) or "").strip() or "(미분류)"
            agg[key][0] += 1
            agg[key][1] += float(r.get("amount") or 0)
        return agg

    cur, prev = rollup(cur_rows), rollup(prev_rows)
    out = [
        {
            "name": name, "count": c, "amount": a,
            "prev_count": prev.get(name, [0, 0.0])[0],
            "prev_amount": prev.get(name, [0, 0.0])[1],
        }
        for name, (c, a) in cur.items()
    ]
    # 올해 0건이어도 전년에 있었으면 전년 줄에 그려야 한다.
    for name, (c, a) in prev.items():
        if name not in cur:
            out.append({"name": name, "count": 0, "amount": 0.0,
                        "prev_count": c, "prev_amount": a})
    out.sort(key=lambda x: (-x["amount"], -x["prev_amount"]))
    return out


def _by_work_type(
    cur_rows: "list[dict[str, Any]]",
    prev_rows: "list[dict[str, Any]]",
) -> "list[dict[str, Any]]":
    return _mix_by("work_type", cur_rows, prev_rows)


# 소재지는 **화면에 실제로 뜨는 건만** 따로 묻는다 (2026-08-11).
#
# 원장 APW_MASTEREX 는 테이블이 아니라 **뷰**이고, Address 는 그 안에서 스칼라
# UDF(dbo.fnBun)와 CASE 열 개를 이어 붙여 만드는 계산 열이다. 스칼라 UDF 는
# 행마다 따로 도는 데다 병렬 실행을 막는다. 그래서 이 열 하나를 같이 물으면
# 질의 전체가 무너진다 — 실측(본사 2026-01~08, 두 창 8,478건):
#
#     조인만              2.55초
#     + Manager           3.97초
#     + LCategory         2.78초
#     + CustName          2.35초
#     + Address          38.62초   ← 이 한 열
#
# 감정서번호를 못박아 물으면 다르다. 옵티마이저가 그 건들만 UDF 를 돌린다:
#     100건 0.16초 · 800건 0.90초 · 2,000건 33.78초
# 2,000 근처에서 계획이 '뷰 전체 훑기' 로 넘어가므로 **400건씩 끊는다** —
# 800건(0.90초)이 아직 빠른 쪽이라 400 은 넉넉한 안전선이다.
# 아래 표는 어차피 recent_limit(800) 까지만 그리므로 두 번이면 끝난다.
_ADDR_CHUNK = 200
_ADDR_WORKERS = 4


def _in_session(fn, *args):
    """스레드마다 **제 세션**을 연다. SQLAlchemy 세션은 스레드 안전하지 않다 —
    하나를 나눠 쓰면 커서가 엉킨다(가변비·상여가 쓰는 것과 같은 방식)."""
    from app.database import get_session_factory  # noqa: PLC0415

    db = get_session_factory()()
    try:
        return fn(db, *args)
    finally:
        db.close()


def _address_chunk(db: Session, chunk: "list[str]") -> "dict[str, str]":
    keys = [f"a{i}" for i in range(len(chunk))]
    sql = (
        f"SELECT DocID, Address FROM [{_source_database()}].dbo.apw_masterex "
        f"WHERE DocID IN ({', '.join(':' + k for k in keys)})"
    )
    return {
        str(r["DocID"]): r["Address"]
        for r in _exec(db, sql, dict(zip(keys, chunk))).mappings()
    }


def _addresses(db: Session, doc_ids: "list[str]") -> "dict[str, str]":
    """감정서번호 → 소재지. 화면에 뜨는 건만 물어야 한다(위 주석 참조).

    덩어리를 **동시에** 던진다. 한 덩어리는 UDF 가 도는 동안 서버 한 코어만
    쓰고 우리는 그냥 기다리므로, 나눠 던지면 그만큼 겹친다. 실측(800건) —
        400씩 직렬 939ms · 800 한 번에 752ms
        400씩 2줄 562ms · **200씩 4줄 325ms** · 100씩 4줄 335ms
    결과가 네 방식 모두 같은 것을 확인하고 200×4 로 정했다. 200 아래로는
    왕복이 늘어 더 안 줄고, 4줄은 상여·가변비(4·3줄)와 같은 눈금이다.
    """
    ids = [d for d in dict.fromkeys(doc_ids) if d]
    if not ids:
        return {}
    chunks = [ids[i:i + _ADDR_CHUNK] for i in range(0, len(ids), _ADDR_CHUNK)]
    if len(chunks) == 1:
        return _address_chunk(db, chunks[0])
    out: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=min(_ADDR_WORKERS, len(chunks))) as pool:
        for part in pool.map(lambda c: _in_session(_address_chunk, c), chunks):
            out.update(part)
    return out


def _recent(rows: "list[dict[str, Any]]", limit: int) -> "list[dict[str, Any]]":
    """당기 내역. '최근 몇 건'이 아니라 전건이 원칙이다(설계 심사 2026-08-08).

    중앙값이 14건이라 대다수에게 전건 표가 오히려 짧고, 잘린 표는 차트의
    table-view twin(툴팁 없이 모든 값에 닿는 경로) 역할을 못 한다. limit 는
    최다 실적자(실측 669건) 방어용 상한일 뿐이다.
    """
    ordered = sorted(
        rows,
        key=lambda r: (r["voucher_date"] or date.min, r["doc_id"]),
        reverse=True,
    )
    return [
        {
            "doc_id": r["doc_id"],
            "date": r["voucher_date"].isoformat() if r["voucher_date"] else None,
            # 소재지는 dashboard 가 나중에 채운다 — _addresses() 주석 참조.
            "address": r.get("address"),
            "customer_name": r["customer_name"],
            "customer_norm": normalize_customer(r.get("customer_name")),
            "work_type": r["work_type"],
            "category": r["category"],
            "kind": r.get("kind") or SINGLE,
            "amount": float(r["amount"] or 0),
            # 미수 내역 탭이 쓴다. 배분 비율만큼만 내 몫으로 — 매출과 같은 잣대다.
            # billed 는 요약표의 청구액(부가세 포함) — 미수금현황과 같은 값이다.
            "outstanding": (float(r.get("outstanding") or 0)
                            * float(r.get("share") or 1.0)),
            "billed": float(r.get("billed") or 0) * float(r.get("share") or 1.0),
        }
        for r in ordered[:limit]
    ]


def _single_totals(
    rows: "list[dict[str, Any]]", alloc: "dict[str, dict[str, float]]"
) -> "dict[str, float]":
    """사람별 단독 실적 합. 여럿이 걸린 건은 배분 비율만큼만 센다."""
    totals: dict[str, float] = defaultdict(float)
    for r in rows:
        for name, amount, kind in _attribute(r, alloc):
            if kind == SINGLE:
                totals[name] += amount
    return totals


_ACTIVE_SQL = """
SELECT RTRIM(u.EMP) AS emp_name
FROM [{database}].dbo.TMWCMN_USR_BAC_INFO u
WHERE RTRIM(u.EMP) IN ({placeholders})
GROUP BY RTRIM(u.EMP)
HAVING MIN(RTRIM(u.RTRM_FL)) = '0' AND MAX(RTRIM(u.USE_YN)) = 'Y'
"""
_ACTIVE_CHUNK = 800


def active_names(db: Session, names: "list[str]") -> "set[str]":
    """넘긴 이름 중 재직 중인 사람만 돌려준다.

    동명이인이 있어도 한 명이라도 재직이면 재직으로 본다 — 순위 모수에서 빼는 게
    목적이라, 애매하면 남기는 쪽이 덜 틀린다.
    """
    out: set[str] = set()
    for offset in range(0, len(names), _ACTIVE_CHUNK):
        chunk = names[offset : offset + _ACTIVE_CHUNK]
        keys = [f"ac_{index}" for index in range(len(chunk))]
        rows = _exec(
            db,
            _ACTIVE_SQL.format(
                database=_source_database(),
                placeholders=",".join(":" + k for k in keys),
            ),
            {k: chunk[index] for index, k in enumerate(keys)},
        ).scalars().all()
        out |= set(rows)
    return out


# ── 순위 그룹 (2026-08-13 요청) ─────────────────────────────────────────────
# 순위는 같은 소속끼리만 겨룬다 — 주주 계열은 주주끼리, 소속은 소속끼리, 수습은
# 수습끼리. 구분은 좌석 명부(Seat_userinfo.Dept_Nm)의 부서 코드다. 코드 뜻은
# apw_dept 명칭과 실명 대조로 확정했다(2026-08-13 실측):
#   jip=집행부(5명)·sim=심사부(9)·ju=주주평가사(27)·yj=예비주주평가사(10)
#   so=소속평가사·su=수습평가사
# mp(7명)·gam(1명)은 부서 코드표에 없지만 직급이 부회장·이사·주주평가사·감사라
# 전부 주주 계열이다 — 직급 실측으로 확인하고 주주에 묶는다.
# 좌석에 없는 재직 실적자(실측 2명: 김주환·김하림)는 그룹 미상 — 전체 기준으로
# 물러서고, 다른 그룹의 모수에도 끼지 않는다.
_RANK_GROUPS = {
    "주주평가사": frozenset({"jip", "sim", "ju", "yj", "mp", "gam"}),
    "소속평가사": frozenset({"so"}),
    "수습평가사": frozenset({"su"}),
}
_GROUP_SQL = """
SELECT RTRIM(s.Uname) AS name, RTRIM(ISNULL(s.Dept_Nm, '')) AS code
FROM [{database}].dbo.Seat_userinfo s
WHERE RTRIM(ISNULL(s.Uname, '')) <> ''
"""


def _rank_groups(db: Session) -> "dict[str, str]":
    """이름 → 순위 그룹. 좌석은 사람이 아니라 자리 단위라 한 사람이 여러 줄일
    수 있다 — 평가사 그룹에 닿는 줄이 하나라도 있으면 그 그룹으로 본다
    (실측: 그룹이 갈리는 동명이인 0명)."""
    out: dict[str, str] = {}
    for r in _exec(db, _GROUP_SQL.format(database=_source_database())).mappings():
        group = next(
            (g for g, codes in _RANK_GROUPS.items() if r["code"] in codes), None
        )
        if group:
            out.setdefault(r["name"], group)
    return out


def _ranking(
    rows: "list[dict[str, Any]]",
    alloc: "dict[str, dict[str, float]]",
    emp_name: str,
    active: "set[str] | None" = None,
    group_names: "set[str] | None" = None,
    group_label: "str | None" = None,
) -> dict[str, Any]:
    """같은 소속 안에서 내 순위. 타인 금액은 내보내지 않는다 (순위 블라인드).

    배분 전에는 '조근렬,강무진,김형식' 이 한 사람처럼 순위에 끼어 있었다.

    순위 모수는 **재직자만** 이다 (2026-08-07 사용자 결정, 운영 JSP 도 RTRM_FL<>'1').
    "지금 같이 일하는 사람들 중 내 위치"가 이 카드가 답하는 질문이기 때문이다.
    실측(2026-01~07 본사): 82명 → 76명. 퇴사자 6명이 전부 61위 이하라 **등수는
    아무도 안 바뀌고**, 평균이 1.805억 → 1.940억으로 정확해진다.

    2026-08-13 요청으로 **같은 소속끼리만** 겨룬다 — group_names 를 주면 그
    사람들(과 본인)만 모수로 남긴다. 본인 그룹을 모르면 안 넘기면 되고, 그때는
    종전처럼 전체 기준이다(group_label=None → 화면이 '지사 내'로 말한다).

    active 를 안 넘기면 거르지 않는다 — 조회에 실패해도 순위가 사라지지 않게.
    보고 있는 사람이 퇴사자면 그 사람만은 모수에 남긴다(등수가 없어지지 않게).
    """
    totals = _single_totals(rows, alloc)
    if active is not None:
        totals = {n: v for n, v in totals.items() if n in active or n == emp_name}
    if group_names is not None:
        totals = {
            n: v for n, v in totals.items() if n in group_names or n == emp_name
        }
    ranked = sorted(totals.items(), key=lambda x: -x[1])
    total = len(ranked)
    mine = next((i for i, (name, _) in enumerate(ranked, 1) if name == emp_name), None)
    average = sum(totals.values()) / total if total else 0.0
    return {
        "rank": mine,
        "total": total,
        "percentile": round(100.0 * mine / total, 1) if mine and total else None,
        # 익명 평균선만 준다 — 남의 금액은 못 보게 한다.
        "group_average": average,
        "group_label": group_label,
    }


# ── 거래처별현황: 접수·발송 미수 (2026-08-13 요청) ─────────────────────────
# 매출 TOP 은 전표(위 rows)에서 나오지만 접수·미수는 축이 다르다:
#   접수 — 원장 접수일(ReceiptDate) 기준. 전표가 아직 없어도 접수는 접수다.
#   미수 — **발송(SendDate)되면 미수다** (2026-08-13 사용자 확정). 종전에는
#          당기 매출 전표가 있는 건만 걸러서, 발송까지 했는데 전표도 입금도
#          없는 건 — 정작 제일 급한 무전표 미수 — 가 아예 안 보였다.
# 기준액은 미수금현황 화면과 같은 식: max(전표 청구액, 발송건 산정액) − 입금.
# 원장에는 회계단위가 없어 지사는 감정서번호 접두어로 거른다.
_INTAKE_SQL = """
SELECT RTRIM(a.DocID) AS doc_id,
       RTRIM(ISNULL(a.CustName, '')) AS customer_name,
       RTRIM(ISNULL(a.Manager, '')) AS manager,
       CASE WHEN a.ReceiptDate >= :cur_from THEN 'cur' ELSE 'prev' END AS bucket
FROM [{database}].dbo.apw_masterex a
WHERE ((a.ReceiptDate >= :cur_from AND a.ReceiptDate < :cur_end)
    OR (a.ReceiptDate >= :prev_from AND a.ReceiptDate < :prev_end))
  AND ({prefix})
"""

_SENT_SQL = """
SELECT RTRIM(a.DocID) AS doc_id,
       a.SendDate AS send_date,
       RTRIM(ISNULL(a.CustName, '')) AS customer_name,
       RTRIM(ISNULL(a.Manager, '')) AS manager,
       RTRIM(ISNULL(a.LWorkinfo, '')) AS work_type,
       CASE WHEN RTRIM(ISNULL(a.LCategory, '')) = '' THEN N'(미분류)'
            ELSE RTRIM(a.LCategory) END AS category,
       CAST(ISNULL(a.[청구금액], 0) AS float) AS assessed,
       CAST(ISNULL(s.billed_amount, 0) AS float) AS billed,
       CAST(ISNULL(s.received_amount, 0) AS float) AS received
FROM [{database}].dbo.apw_masterex a
LEFT JOIN dbo.a10_receivable_summary s ON s.doc_id = a.DocID
WHERE a.SendDate >= :date_from AND a.SendDate < :date_end
  AND ({prefix})
"""


def _prefix_filter(prefixes: "list[str]") -> "tuple[str, dict[str, Any]]":
    if not prefixes:
        return "1=1", {}
    parts = [f"a.DocID LIKE :px{i} + '%'" for i in range(len(prefixes))]
    return "(" + " OR ".join(parts) + ")", {
        f"px{i}": p for i, p in enumerate(prefixes)
    }


def _fetch_intake(
    db: Session, prefixes: "list[str]",
    cur_from: date, cur_to: date, prev_from: date, prev_to: date,
) -> "list[dict[str, Any]]":
    cond, params = _prefix_filter(prefixes)
    # 발송·접수일은 smalldatetime — BETWEEN 의 끝날 00:00 문제를 피해 < 다음날.
    return [dict(r) for r in _exec(
        db, _INTAKE_SQL.format(database=_source_database(), prefix=cond),
        {
            **params,
            "cur_from": cur_from, "cur_end": cur_to + timedelta(days=1),
            "prev_from": prev_from, "prev_end": prev_to + timedelta(days=1),
        },
    ).mappings()]


def _fetch_sent(
    db: Session, prefixes: "list[str]", date_from: date, date_to: date
) -> "list[dict[str, Any]]":
    cond, params = _prefix_filter(prefixes)
    return [dict(r) for r in _exec(
        db, _SENT_SQL.format(database=_source_database(), prefix=cond),
        {**params, "date_from": date_from, "date_end": date_to + timedelta(days=1)},
    ).mappings()]


def _doc_people(row: "dict[str, Any]", alloc) -> "set[str]":
    """이 감정서에 걸린 사람들(실명). 지분표가 있으면 그쪽이 명단이다 —
    유치자 칸은 자주 빠진다(_attribute 와 같은 원칙)."""
    a = alloc.get(row["doc_id"]) or {}
    if a:
        return {_bare(n) for n in a}
    return {n for n, _ in _names_of(row.get("manager") or "")}


def _intake_by_customer(
    rows: "list[dict[str, Any]]", emp_name: "str | None", alloc
) -> dict[str, Any]:
    """거래처별 접수 건수 — 올해/전년 한 벌. 건수 축이라 지분으로 쪼개지 않고
    '내가 낀 접수'를 1건으로 센다(0.33건짜리 접수는 없다). emp_name 이
    None(전체 모드)이면 전 건을 센다."""
    agg: dict[str, list] = defaultdict(lambda: [0, 0])
    totals = [0, 0]
    for r in rows:
        if emp_name is not None and emp_name not in _doc_people(r, alloc):
            continue
        key = normalize_customer(r.get("customer_name")) or "(미기재)"
        slot = 0 if r["bucket"] == "cur" else 1
        agg[key][slot] += 1
        totals[slot] += 1
    out = [
        {"name": n, "count": c, "prev_count": p}
        for n, (c, p) in agg.items() if c or p
    ]
    out.sort(key=lambda x: (-x["count"], -x["prev_count"]))
    return {"top": out, "total": totals[0], "prev_total": totals[1]}


def _sent_receivable(
    rows: "list[dict[str, Any]]", emp_name: str, alloc, whole: bool
) -> "tuple[dict[str, Any], list[dict[str, Any]]]":
    """발송 기준 미수 — 거래처별 합계와 하단 내역을 한 번에.

    개인 화면은 매출과 같은 잣대로 **지분 몫만** 센다. 공동(수기정산 대기)
    건은 매출 표와 같은 이유로 싣지 않는다 — 참여자마다 건 전체가 겹쳐 보인다.
    지분도 유치자도 없는 건은 개인 화면에 못 싣는다(매출과 같은 사각, 실측 0.2%).
    """
    per_customer: dict[str, list] = defaultdict(lambda: [0, 0.0, 0.0])
    details: list[dict[str, Any]] = []
    total = 0.0
    for r in rows:
        effective = max(float(r.get("billed") or 0), float(r.get("assessed") or 0))
        if effective <= 0:
            continue                  # 기준액이 없으면 분모에도 분자에도 못 든다
        if whole:
            share = 1.0
        else:
            mine_amt = sum(
                float(amount)
                for name, amount, kind in _attribute(
                    {**r, "amount": effective}, alloc
                )
                if name == emp_name and kind == SINGLE
            )
            if mine_amt <= 0:
                continue
            share = mine_amt / effective
        key = normalize_customer(r.get("customer_name")) or "(미기재)"
        slot = per_customer[key]
        # 분모(매출총액)는 **완납 건까지** 전부 쌓는다 — 미수율의 분모다.
        # 미납 건만 쌓으면 부분 입금이 없는 한 미수율이 항상 100%로 떠서
        # '결제 잘 하는 거래처'와 '안 하는 거래처'가 구분이 안 된다
        # (2026-08-14 검수에서 잡힌 회귀 — 종전 미수 탭은 완납도 분모에 넣었다).
        slot[2] += effective * share
        left = effective - float(r.get("received") or 0)
        if left <= 0:
            continue                  # 완납은 미수 건수·잔액·내역에는 없다
        slot[0] += 1
        slot[1] += left * share
        total += left * share
        sd = r.get("send_date")
        details.append({
            "doc_id": r["doc_id"],
            "date": str(sd)[:10] if sd else None,
            "customer_name": r.get("customer_name"),
            "customer_norm": key,
            "work_type": r.get("work_type"),
            "category": r.get("category"),
            "billed": effective * share,
            "outstanding": left * share,
        })
    # 완납만 있는 거래처는 목록에 안 싣는다(미수 화면이니까) — 분모 누적과는 별개.
    customers = [
        {"name": n, "count": c, "amount": a, "gross": g}
        for n, (c, a, g) in per_customer.items() if a > 0
    ]
    customers.sort(key=lambda x: -x["amount"])
    details.sort(key=lambda d: (d["date"] or "", d["doc_id"]), reverse=True)
    return {"customers": customers, "total": total}, details


def _alloc_targets(rows: "list[dict[str, Any]]") -> "list[str]":
    """접수·발송 건 중 지분을 물어볼 감정서 — 칸에 여럿이거나 칸이 비어
    지분표만이 명단인 건. 매출 쪽 _multi_docs 보다 넓게 잡는 이유: 접수 직후
    건은 전표가 없어 매출 경로의 검증을 못 물려받고, 칸이 빈 건이 실제로 있다."""
    return sorted({
        r["doc_id"] for r in rows
        if len(_names_of(r.get("manager") or "")) != 1
    })


def _multi_docs(rows: "list[dict[str, Any]]") -> "list[str]":
    """지분을 조회할 감정서 — 유치자 칸에 여럿이 든 건만.

    한때 전 건을 조회하게 바꿨다가 되돌렸다. 칸이 한 명이어도 지분은 여럿일 수
    있다고 봤는데, 실측하니 **0건**이었다(2026-06 이후 753건 중 '칸 한 명인데
    지분 여럿' 0건, '칸 여럿인데 지분 하나' 0건). 근거 없는 걱정이었고 대가는
    컸다 — 2개월 조회가 0.9초에서 46초로 늘었다. 칸이 한 명이면 그 사람 100%다.
    """
    return sorted({
        r["doc_id"] for r in rows if len(_names_of(r.get("manager") or "")) > 1
    })


# 연도별 추이용. 전 인원을 훑을 필요가 없어 유치자 칸에 이름이 든 건만 미리 거른다.
# LIKE 는 어디까지나 예선이다 — 정확한 귀속은 파이썬의 _attribute 가 다시 가른다
# ('박중현' LIKE 가 '박중현우' 를 물어도 이름 비교에서 떨어진다).
# 실측(2026-08-07 본사 5년): 박중현 241건 1.85초, 이동호 47건 1.07초.
_YEARLY_SQL = """
WITH sales AS (
    SELECT v.management_no,
           v.voucher_date,
           CASE WHEN v.debit_credit = '4' THEN v.amount
                WHEN v.debit_credit = '3' THEN -v.amount ELSE 0 END AS net_amount
    FROM dbo.a10_voucher_cache v
    WHERE v.account_code LIKE '401%'
      AND v.management_no IS NOT NULL{division_filter}
      AND v.voucher_date BETWEEN :year_from AND :year_to
), grouped AS (
    SELECT s.management_no,
           MAX(s.voucher_date) AS voucher_date,
           -- 월별 추이와 같은 기준이어야 한다 — 여기도 공급가액(부가세 제외)이다.
           SUM(s.net_amount) AS amount
    -- 연도 판정도 대시보드와 같은 전표 줄 단위다. 감정서 단위로 몰면 연도에
    -- 걸친 건이 마지막 전표의 해로 통째로 이동해 대시보드와 어긋난다
    -- (실측: 안창덕 2026 이 117만원 크게 나왔다).
    FROM sales s GROUP BY s.management_no, YEAR(s.voucher_date)
)
SELECT g.management_no AS doc_id, g.voucher_date, g.amount,
       RTRIM(ISNULL(m.Manager, '')) AS manager
FROM grouped g
JOIN [{database}].dbo.apw_masterex m ON m.DocID = g.management_no
WHERE m.Manager LIKE :name_like
"""

# 전체(지사·전사) 전용 — 사람을 안 가리므로 원장 조인이 통째로 필요 없다.
# 조인을 남기면 두 가지가 어긋난다: INNER 라서 **원장에 짝이 없는 401 매출**이
# 연도 차트에서만 빠지고(데이터 품질 점검의 C 항목), DocID 중복 3건이 그 해에
# 걸리면 금액이 두 배가 된다. 여기서 접어 오면 5년치 전 건을 파이썬으로 넘기지도
# 않는다. 연도 판정은 위 SQL 과 같은 **전표 줄 단위**다.
_YEARLY_ALL_SQL = """
SELECT YEAR(v.voucher_date) AS year,
       SUM(CASE WHEN v.debit_credit = '4' THEN v.amount
                WHEN v.debit_credit = '3' THEN -v.amount ELSE 0 END) AS amount,
       COUNT(DISTINCT v.management_no) AS docs
FROM dbo.a10_voucher_cache v
WHERE v.account_code LIKE '401%'
  AND v.management_no IS NOT NULL{division_filter}
  AND v.voucher_date BETWEEN :year_from AND :year_to
GROUP BY YEAR(v.voucher_date)
"""

YEARLY_SPAN = 5  # 올해 포함 최근 5년


def yearly_trend(
    db: Session,
    *,
    emp_name: "str | None",
    office_code: "str | None",
    end_year: int,
    span: int = YEARLY_SPAN,
    whole: bool = False,
) -> "list[dict[str, Any]]":
    """연도별 실적 추이. 월별 추이와 같은 기준(전표일자·401 순액)이다."""
    start_year = end_year - span + 1
    div_sql, div_params = _division_filter(db, office_code)
    if whole:
        # 이름 예선(LIKE)과 결선(_attribute)은 **한 몸**이다. LIKE 만 빼고
        # 배분 루프를 남기면 공동 건이 참여자 수만큼 더해져 조용히 두 배가 된다.
        found = {
            int(r["year"]): r
            for r in _exec(
                db, _YEARLY_ALL_SQL.format(division_filter=div_sql),
                {**div_params,
                 "year_from": date(start_year, 1, 1),
                 "year_to": date(end_year, 12, 31)},
            ).mappings().all()
        }
        # 화면(my-sales.js)은 single 칸만 읽는다 — 키 이름을 바꾸면 조용히 0 이 된다.
        return [
            {"year": y,
             "single": float(found[y]["amount"]) if y in found else 0.0,
             "single_count": int(found[y]["docs"]) if y in found else 0,
             "joint": 0.0, "joint_count": 0}
            for y in range(start_year, end_year + 1)
        ]
    sql = _YEARLY_SQL.format(
        division_filter=div_sql, database=_source_database()
    )
    rows = [
        dict(r)
        for r in _exec(
            db, sql,
            {
                **div_params,
                "year_from": date(start_year, 1, 1),
                "year_to": date(end_year, 12, 31),
                # LIKE 특수문자(%, _, [)가 이름에 들어갈 일은 없지만 막아 둔다.
                "name_like": "%" + emp_name.replace("[", "[[]").replace("%", "[%]")
                .replace("_", "[_]") + "%",
            },
        ).mappings().all()
    ]
    alloc = _with_ledger_settlement(
        db, rows, _allocations(db, _multi_docs(rows)))

    buckets = {
        year: {"year": year, "single": 0.0, "single_count": 0,
               "joint": 0.0, "joint_count": 0}
        for year in range(start_year, end_year + 1)
    }
    for row in rows:
        year = row["voucher_date"].year
        if year not in buckets:
            continue
        for name, amount, kind in _attribute(row, alloc):
            if name != emp_name:
                continue
            buckets[year][kind] += amount
            buckets[year][f"{kind}_count"] += 1
    return [buckets[year] for year in sorted(buckets)]


# 이름 목록 전용 질의 (2026-08-11). 대시보드의 _ROWS_SQL 을 빌려 쓰다가 뗐다.
# 그 질의는 이 함수가 안 쓰는 것을 잔뜩 들고 온다 — 거래처·물건·업무 이름,
# 미수 요약표 조인, 그리고 **전년 창까지**(prev 를 안 넘기면 같은 창을 두 번
# 긁도록 만들어져 있어 5,301건이 10,602건이 된다).
# 이름을 세는 데 필요한 건 감정서번호·금액·유치자 셋뿐이다. 실측 —
#     _ROWS_SQL 재사용  1,049ms   ·   전용 질의  296ms (이름까지 440ms)
# 결과가 같은 것을 확인했다(본사 2026 82명, 명단·순서 완전 일치).
_NAMES_SQL = """
WITH grouped AS (
    SELECT v.management_no,
           SUM(CASE WHEN v.debit_credit = '4' THEN v.amount
                    WHEN v.debit_credit = '3' THEN -v.amount ELSE 0 END) AS amount
    FROM dbo.a10_voucher_cache v
    WHERE v.account_code LIKE '401%'
      AND v.management_no IS NOT NULL{division_filter}
      AND v.voucher_date BETWEEN :cur_from AND :cur_to
    GROUP BY v.management_no
)
SELECT g.management_no AS doc_id, g.amount,
       RTRIM(ISNULL(m.Manager, '')) AS manager
FROM grouped g
-- LOOP 을 못 박는 이유는 _ROWS_SQL 주석과 같다.
LEFT OUTER LOOP JOIN [{database}].dbo.apw_masterex m ON m.DocID = g.management_no
"""


def appraiser_names(
    db: Session, office_code: "str | None", date_from: date, date_to: date
) -> "list[str]":
    """기간 안에 실적이 있는 사람 목록. 공동 표기·공통은 뺀다.

    **원장 확정 폴백(_with_ledger_settlement)을 타지 않는다.** 그 폴백은 1.9초가
    드는데(실측), 목록에 드는 사람을 바꾸지 않는다 — 금액만 바꾼다. 실측으로
    2026-01~08 82명, 2025 전체 89명 모두 폴백 유무와 **명단이 완전히 같았다**
    (폴백으로만 나타나는 사람 0, 사라지는 사람 0).
    이 함수는 이름만 쓰므로 그 값을 지불할 이유가 없다.
    """
    div_sql, div_params = _division_filter(db, office_code)
    rows = [
        dict(r)
        for r in _exec(
            db,
            _NAMES_SQL.format(
                division_filter=div_sql, database=_source_database()
            ),
            {**div_params, "cur_from": date_from, "cur_to": date_to},
        ).mappings()
    ]
    totals = _single_totals(rows, _allocations(db, _multi_docs(rows)))
    # 가나다순 (2026-08-13 요청). 처음엔 매출 내림차순이었는데, 드롭다운에서
    # 사람을 찾는 용도라 금액 순서는 오히려 찾기를 방해한다.
    return sorted(totals)


def dashboard(
    db: Session,
    *,
    emp_name: "str | None",
    office_code: "str | None",
    date_from: date,
    date_to: date,
    recent_limit: int = 800,
    whole: bool = False,
) -> dict[str, Any]:
    """대시보드 한 판. 올해 구간과 전년 동기를 같이 낸다.

    whole=True 면 **사람이 아니라 지사(또는 전사) 통짜**를 낸다 (2026-08-10 요청).

    전체의 정의는 **귀속 배분을 아예 안 한 401 순액 합**이다. 개인들의 합이
    아니다 — 둘은 양방향으로 어긋난다:
      · 아래로: 유치자 칸이 비었거나 '공통'인 건은 _attribute 가 빈 목록을
        돌려줘 누구의 화면에도 안 잡힌다(coverage.unassigned_ratio 가 그 몫.
        실측 2026-01~07 본사 4%, 울산 100%·충남 99%·경인 90%).
      · 위로: 지분표가 없는데 유치자 칸에 여러 명이 든 건은 참여자 **전원에게
        건 전체 금액**을 준다(공동). 사람별로 더하면 같은 돈이 N번 세어진다.
    그래서 전체 모드는 금액이 지나가는 길에 alloc·_attribute·mine 이 **한 번도
    등장하지 않는다.** 배분은 커버리지 판정(0원인가 아닌가)에만 쓴다.
    """
    prev_from, prev_to = previous_year_range(date_from, date_to)
    # 접수·발송(미수) 질의는 본 질의와 겹치게 **미리 던져 둔다** — 순차로 붙이면
    # 1.7초가 그대로 더해진다(실측: 접수 0.59초·발송 1.09초). 스레드는 제 세션을
    # 연다(_in_session) — 세션 하나를 나눠 쓰면 커서가 엉킨다.
    prefixes = docid_prefixes(db, office_code)
    side_pool = ThreadPoolExecutor(max_workers=2)
    intake_future = side_pool.submit(
        _in_session, _fetch_intake, prefixes,
        date_from, date_to, prev_from, prev_to,
    )
    sent_future = side_pool.submit(
        _in_session, _fetch_sent, prefixes, date_from, date_to,
    )
    side_pool.shutdown(wait=False)
    rows = _fetch_rows(db, office_code, date_from, date_to, prev_from, prev_to)
    # 원장 확정 폴백은 **건 안에서 사람 몫만** 바꾼다 — 합계를 정의상 못 바꾸는데
    # 1.9초가 든다. 전체 모드는 그 값을 지불할 이유가 없다.
    # 전체 모드는 배분표를 **아예 안 읽는다** (2026-08-11).
    # 배분표는 여기서 커버리지 판정(_attribute 가 빈 목록인가)에만 쓰이는데,
    # _multi_docs 가 **유치자 칸에 이름이 둘 이상인 건만** 묻기 때문에 배분표에
    # 든 건은 이미 이름이 있다 → 배분표가 있든 없든 '이름이 하나도 없는 건'
    # 집합이 같다. 실측으로도 같다(본사 2026: 미귀속 649,613,680원 · 3.56%,
    # 배분표 유무와 원 단위까지 동일). 0.24초를 그냥 아낀다.
    # 원장 확정 폴백도 마찬가지다 — 건 안에서 사람 몫만 바꾸므로 총합을 못 바꾼다.
    alloc: "dict[str, dict[str, float]]" = (
        {} if whole
        else _with_ledger_settlement(db, rows, _allocations(db, _multi_docs(rows)))
    )

    def mine(source: "list[dict[str, Any]]", kind: str) -> "list[dict[str, Any]]":
        """내 몫만 남긴다. 여럿이 걸린 건은 금액을 배분 비율만큼으로 바꿔 담는다.

        share 는 그 비율이다(내 금액 ÷ 건 전체 금액). 미수 탭이 잔액을 같은
        비율로 나눌 때 쓴다 — 매출은 내 몫만 세면서 미수는 건 전체를 세면
        두 숫자가 서로 다른 잣대가 된다.
        """
        out = []
        for r in source:
            whole = float(r.get("amount") or 0)
            for name, amount, attr in _attribute(r, alloc):
                if name == emp_name and attr == kind:
                    share = (float(amount) / whole) if whole else 1.0
                    out.append({**r, "amount": amount, "share": share})
        return out

    cur_rows = [r for r in rows if r["bucket"] == "cur"]
    prev_rows = [r for r in rows if r["bucket"] == "prev"]
    # 귀속 커버리지 — 이 지사 매출 중 유치자(지분) 미등록이라 누구의 개인 화면에도
    # 안 잡히는 몫. 실측(2026-01~07): 본사 4%지만 울산 100%·충남 99%·경인 90%로
    # 지사 편차가 크다. 비율이 높으면 화면이 스스로 알린다 — 지사 명단을 박아두면
    # 등록 관행이 좋아져도 안내가 안 사라진다. 금액이 아니라 **비율만** 내려보낸다:
    # 지사 총액은 이 화면 이용자 전원이 볼 권한이 있는 숫자가 아니다.
    # 순위 모수에서 퇴사자를 뺀다. 이름은 단독 실적자만 모으면 된다.
    office_total = sum(float(r["amount"] or 0) for r in cur_rows)
    unassigned = sum(
        float(r["amount"] or 0) for r in cur_rows if not _attribute(r, alloc)
    )
    unassigned_ratio = round(unassigned / office_total, 3) if office_total > 0 else 0.0

    if whole:
        # mine() 을 **부르지 않는다.** '이름 조건만 지우자' 는 우회가 제일
        # 자연스러워 보이지만, 그러면 3인 공동 건이 3줄이 되어 금액 합은 우연히
        # 보존되면서 건수만 참여자 수만큼 부풀고, 참여자가 단독·공동으로 갈린
        # 건은 두 카드에 동시에 든다. 원본 한 벌을 그대로 쓴다.
        # share 키를 안 넣는 것도 일부러다 — 미수 쪽이 `or 1.0` 으로 떨어져
        # 건 전체 잔액을 세고, 전체 모드에서는 그게 맞다.
        active: "list[str]" = []
        cur_single = [dict(r) for r in cur_rows]
        prev_single = [dict(r) for r in prev_rows]
        cur_joint: "list[dict[str, Any]]" = []
    else:
        active = active_names(db, sorted(_single_totals(cur_rows, alloc)))
        cur_single = mine(cur_rows, SINGLE)
        cur_joint = mine(cur_rows, JOINT)
        prev_single = mine(prev_rows, SINGLE)

    single, joint = _sum(cur_single), _sum(cur_joint)
    single_prev = _sum(prev_single)
    diff = single["amount"] - single_prev["amount"]
    # 전년이 0 이하면 증가율을 내지 않는다(None → 화면은 '비교 불가'로 쓴다).
    # 전표 취소가 인식분보다 많으면 전년 합계가 **음수**가 된다. 실측: 김남수
    # 2025-01~07 이 -5,438만이라 952.7% 라는 숫자가 떴다. 음수를 분모로 쓰면
    # 부호까지 뒤집혀 '늘었다/줄었다'가 거꾸로 읽힌다.
    rate = (
        round(100.0 * diff / single_prev["amount"], 1)
        if single_prev["amount"] > 0 else None
    )

    cur_cat = _by_category(cur_single)
    prev_cat = {c["name"]: c for c in _by_category(prev_single)}
    shift = []
    for c in cur_cat:
        before = prev_cat.get(c["name"], {"count": 0, "amount": 0.0})
        gap = c["count"] - before["count"]
        shift.append({
            "name": c["name"], "count": c["count"], "prev_count": before["count"],
            "count_diff": gap,
            "rate": round(100.0 * gap / before["count"], 1) if before["count"] else None,
        })
    for name, before in prev_cat.items():
        if name not in {c["name"] for c in cur_cat}:
            shift.append({
                "name": name, "count": 0, "prev_count": before["count"],
                "count_diff": -before["count"], "rate": -100.0,
            })
    shift.sort(key=lambda x: -x["count_diff"])

    # 접수·발송(미수) — 대시보드 첫머리에서 미리 던져 둔 질의를 여기서 받는다.
    intake_rows = intake_future.result()
    sent_rows = sent_future.result()
    alloc_extra = (
        {} if whole
        else _allocations(db, _alloc_targets(intake_rows + sent_rows))
    )
    # 병합 순서 주의 — **매출 쪽 alloc 이 이긴다.** alloc 에는 원장 실명 확정
    # (_with_ledger_settlement)이 덮여 있는데, alloc_extra(지분표 원본)를 뒤에
    # 두면 같은 감정서의 확정 배분이 원본으로 되돌아가 매출 귀속과 미수·접수
    # 귀속이 갈린다 (2026-08-14 검수에서 잡힘 — 현재 실측 0건이지만 잠복 결함).
    alloc_side = {**alloc_extra, **alloc}
    intake = _intake_by_customer(
        intake_rows, None if whole else emp_name, alloc_side
    )
    receivable, recv_rows_all = _sent_receivable(
        sent_rows, emp_name, alloc_side, whole
    )
    recv_rows = recv_rows_all[:recent_limit]

    # 소재지는 **표에 실제로 실리는 건만** 물어 채운다. 위 SQL 에 같이 넣으면
    # 질의가 2.5초에서 38.6초가 된다(_addresses 주석에 실측).
    recent = _recent([{**r, "kind": SINGLE} for r in cur_single], recent_limit)
    # 원장에 짝이 있는 건만 묻는다. 전사 조회에는 감정서가 아닌 관리번호(등본
    # 발급 수수료 등 400xxxxxx)가 섞이는데, 그런 번호를 같이 물으면 0건을
    # 돌려주면서 21초를 쓴다(실측 282개). 미수 내역은 원장에서 나온 번호라
    # 전부 짝이 있다 — 같은 질의에 실어 한 번에 채운다.
    in_ledger = {r["doc_id"] for r in cur_single if r.get("in_ledger")}
    addr = _addresses(
        db,
        [r["doc_id"] for r in recent if r["doc_id"] in in_ledger]
        + [r["doc_id"] for r in recv_rows],
    )
    for item in recent:
        item["address"] = addr.get(item["doc_id"])
    for item in recv_rows:
        item["address"] = addr.get(item["doc_id"])

    # 순위 그룹 — 같은 소속끼리만 겨룬다 (2026-08-13 요청).
    # 좌석 명부(Seat_userinfo)는 **본사 명부**다. 거기 없는 실적자는 본사
    # 사람이 아니라 지사 평가사가 본사 건을 유치한 경우다 — 실측(2026-08-13):
    # 명부 밖 재직 실적자 2명(김주환·김하림)은 둘 다 대전세종지사(유치 감정서
    # 15- 525건 vs 01- 13건). 그런 사람에게 본사 등수를 주면 이상하므로
    # 순위를 아예 매기지 않는다(칩이 안 뜬다). 실적·목록은 그대로 보인다.
    if whole:
        group_names: "set[str] | None" = None
        group_label: "str | None" = None
        no_rank = False
    else:
        groups = _rank_groups(db)
        group_label = groups.get(emp_name)
        group_names = (
            {n for n, g in groups.items() if g == group_label}
            if group_label else None
        )
        no_rank = group_label is None

    return {
        "emp_name": emp_name,
        "is_all": whole,
        "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
        "prev_period": {"from": prev_from.isoformat(), "to": prev_to.isoformat()},
        "kpi": {
            "single": single,
            # 전체 모드에선 모든 감정서가 이미 single 에 한 번 들어 있다.
            # 여기에 공동을 채우면 화면 어딘가에서 둘을 더해 정확히 두 배가 된다.
            "joint": joint,
            "growth": {
                "amount": single["amount"], "prev_amount": single_prev["amount"],
                "prev_count": single_prev["count"],
                "diff": diff, "rate": rate, "is_positive": diff >= 0,
            },
            # 전체는 등수를 매길 대상이 아니다 — 모수도 '1인당 평균' 도 딴 축이다.
            # 본사 명부에 없는 사람(지사 평가사의 본사 건)도 등수를 안 준다.
            "ranking": None if whole or no_rank else _ranking(
                cur_rows, alloc, emp_name, active, group_names, group_label
            ),
        },
        "monthly": {
            "current": _monthly(cur_single),
            "previous": _monthly(prev_single),
            "current_joint": _monthly(cur_joint),
        },
        "categories": cur_cat,
        "category_shift": shift,
        # 2026-08-08 전면개편에서 추가 — 데이터는 원래 내려받고 있었는데 화면이
        # 안 썼다. 발주처(누가 내 일을 주나)와 업무종류(수익 구조)가 평가사에게
        # 물건종류보다 먼저다. 추가 SQL 없음: 같은 행을 파이썬에서 다시 접는다.
        # 전체 모드에서는 같은 숫자의 뜻이 뒤집힌다 — 개인 화면에서는 '빠진 몫'
        # 이지만 전체 금액에는 그 몫이 **들어 있다**. 화면이 문구를 갈아 끼우게
        # basis 를 같이 싣는다. 비율의 분모(office_total)가 곧 전체 모드 금액이라
        # 두 숫자가 서로 맞물린다.
        "coverage": {
            "unassigned_ratio": unassigned_ratio,
            "basis": "whole" if whole else "mine",
        },
        "work_types": _by_work_type(cur_single, prev_single),
        "prop_types": _mix_by("category", cur_single, prev_single),
        "customers": _by_customer(cur_single, prev_single),
        # 거래처별현황의 접수 TOP (2026-08-13) — 원장 접수일 기준, 올해/전년.
        "intake": intake,
        # 미수 (2026-08-13 개편) — 축은 거래처, 모집단은 '발송된 건'이다.
        # 종전(당기 전표 있는 건만)은 발송했는데 전표가 없는 건을 놓쳤다.
        "receivable": {**receivable, "basis": "sent"},
        # 하단 '미수 내역' 표 — 발송일 기준 당기 발송분 중 잔액이 남은 건.
        "receivable_rows": recv_rows,
        "receivable_rows_total": len(recv_rows_all),
        "receivable_rows_truncated": len(recv_rows_all) > recent_limit,
        # 표는 단독·공동을 함께 싣는다 — 공동 건은 배지로 구분한다.
        # 공동(수기정산 대기) 건은 표에 싣지 않는다 (2026-08-10 요청).
        # 배분 전 건은 전체 금액이라 참여자끼리 겹쳐 보여 오해를 불렀다.
        # kpi.joint·monthly.current_joint 는 그대로 내려간다 — AI 분석 사실표가
        # 아직 쓰고, 화면만 안 그릴 뿐이다.
        "recent": recent,
        # 아래 표는 위 차트의 증빙이라 **잘렸으면 잘렸다고 말해야** 한다.
        # 개인은 한 해 수백 건이라 800 에 안 걸렸지만 전체는 본사만 수천 건이다.
        # 잘린 줄 모르면 '표 합계 ≠ 히어로 금액' 을 고장으로 신고하게 된다.
        "recent_total": single["count"],
        "recent_truncated": single["count"] > recent_limit,
    }


# ── AI 분석 (2026-08-09 사용자 요청) ────────────────────────────────────────
# '작년엔 있었는데 올해 조용한 곳' 같은 신호들을 Gemini 가 한 번에 읽어 준다.
# 예전 자동 브리핑(40cb09f)을 뺐던 이유와 그때의 교훈을 그대로 지킨다:
#   · 열 때마다가 아니라 **버튼을 눌렀을 때만** 돈다 (비용·소음)
#   · 숫자는 전부 서버가 계산·포맷해서 사실표로 준다 — 모델에게 계산을 시키면
#     숫자를 지어낸다. 모델의 일은 서술과 우선순위 판단뿐이다.
#   · thinking 토큰을 끈다 — 켜 두면 응답이 느리고 비싸지는데 품질 차가 없었다.

_ANALYZE_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# 2026-08-09 사용자 확정: 조언·권유는 하지 않는다("무섭다"). AI 는 숫자를 문장으로
# 풀어 주는 요약자일 뿐, 코치가 아니다 — '다음 행동'·'~해 보세요' 전부 금지.
_ANALYZE_PROMPT = """너는 감정평가법인의 실적 요약 도우미다. 아래는 평가사 한 명의 매출 사실표다.
숫자는 이미 계산되어 있다 — **사실표에 적힌 수치만 그대로 인용**하고, 더하거나 빼서
새 숫자를 만들지 마라(합계가 필요한 자리는 사실표에 이미 있다).

절대 규칙 — **사실만 말한다**:
- 조언·권유·행동 제안 금지: '~해 보세요', '~하시기 바랍니다', '연락', '관리',
  '다음 행동' 같은 표현을 쓰지 마라. 무엇을 하라고 말하는 순간 실패다.
- 평가·감상 금지: '좋습니다', '아쉽습니다', '인상적', '괄목할 만한' 같은 말 대신
  숫자가 말하게 하라 — '늘었습니다/줄었습니다/새로 생겼습니다/없습니다'면 충분하다.

출력 규칙:
- 읽는 사람은 연배 있는 감정평가사다. 정중하게, **쉬운 우리말**로 쓴다 —
  '페이스'·'포트폴리오' 같은 외래어와 회계 전문용어를 쓰지 마라.
- 문장은 전부 '~습니다' 체의 존댓말. 반말 금지.
- 인사·제목·맺음말 없이 **바로 본문부터** 시작한다. 마크다운 금지.
- **한 줄에 한 주제**, 이렇게 쓴다:  `제목|내용`
  세로줄(|) 왼쪽은 두 글자에서 다섯 글자 사이의 제목, 오른쪽은 한두 문장이다.
  세로줄은 줄마다 **정확히 하나**만 쓴다.
- 제목은 아래에서 골라 쓰고, 사실표에 그 내용이 없으면 그 줄을 건너뛴다:
    실적    올해 합계·건수·건당 평균과 전년 대비 증감 (반드시 첫 줄)
    순위    같은 소속(주주·소속·수습) 안에서의 등수
    흐름    월별에서 큰 달·작은 달
    연도     최근 5년의 흐름
    업무     업무종류 구성과 변화
    물건     물건종류 구성과 변화
    거래처   상위 거래처, 커진 곳·새로 생긴 곳
    미수     미수 잔액과 어디에 몰려 있는지
    끊긴 거래  작년에는 거래가 있었지만 올해는 없는 곳
    참고     유치자 미등록 안내가 사실표에 있을 때만
- '끊긴 거래' 는 사실표에 '식은 관계'가 있으면 **반드시** 넣는다 — 화면의
  발주처 카드에서 이 목록을 떼고 여기로 옮겼다. 여기서도 빠지면 사용자가 볼 곳이
  없다. 이름과 전년 금액을 전부 나열하되, 연락하라는 말은 하지 마라.
- 한 줄은 두 문장을 넘기지 않는다. 길면 읽다가 놓친다.
- '새로 생겼다/신규'라는 말은 사실표에 (신규) 표가 붙은 항목에만 쓴다 — 전년
  금액이 적힌 곳은 이미 거래하던 곳이다.
- 없는 항목은 언급하지 말고 건너뛰어라.

[사실표]
{facts}
"""


def _fmt_won(value: float) -> str:
    n = float(value or 0)
    if abs(n) >= 100000000:
        return f"{n/100000000:.1f}억원"
    if abs(n) >= 10000:
        return f"{n/10000:,.0f}만원"
    return f"{n:,.0f}원"


def briefing_facts(data: dict[str, Any], years: "list[dict[str, Any]] | None") -> str:
    """대시보드 페이로드를 모델용 사실표로 요약한다. 모든 수치는 여기서 확정된다."""
    k = data["kpi"]
    g = k["growth"]
    lines = [
        f"평가사: {data['emp_name']}",
        f"기간: {data['period']['from']} ~ {data['period']['to']} (전년 동기 {data['prev_period']['from']} ~ {data['prev_period']['to']})",
        f"확정 실적: {_fmt_won(k['single']['amount'])} · {k['single']['count']}건"
        + (f" · 건당 평균 {_fmt_won(k['single']['amount']/k['single']['count'])}" if k['single']['count'] else ""),
    ]
    if g["prev_amount"] > 0:
        direction = "증가" if g["is_positive"] else "감소"
        lines.append(
            f"전년 동기: {_fmt_won(g['prev_amount'])} → {_fmt_won(abs(g['diff']))} {direction}"
            + (f" ({'+' if g['is_positive'] else '-'}{abs(g['rate']):.1f}%)" if g["rate"] is not None else "")
        )
    else:
        lines.append("전년 동기: 실적 없음")
    r = k.get("ranking") or {}
    if r.get("rank"):
        # 순위는 같은 소속끼리다(2026-08-13) — 화면 칩과 같은 말로 서술해야
        # AI 가 '지사 내 82명'처럼 다른 모수를 지어내지 않는다.
        pool = f"{r['group_label']} " if r.get("group_label") else "지사 내 "
        lines.append(f"순위: {pool}{r['total']}명 중 {r['rank']}위")

    monthly = data.get("monthly", {}).get("current") or []
    if monthly:
        lines.append("월별 확정: " + ", ".join(
            f"{m['month'][5:]}월 {_fmt_won(m['amount'])}" for m in monthly))
    if years:
        lines.append("연도별(확정+공동): " + ", ".join(
            f"{y['year']}년 {_fmt_won(y.get('single') or 0)}" for y in years))

    def with_delta(cur: float, prev: float) -> str:
        # 증감액도 여기서 준다 — 안 주면 모델이 직접 빼서 만든다(실측: '6.2억
        # 늘었다'를 스스로 계산했다. 맞았지만 규칙 위반이고 언젠가 틀린다).
        if not prev:
            return "(전년 없음, 신규)"
        diff = cur - prev
        sign = "+" if diff >= 0 else "-"
        return f"(전년 {_fmt_won(prev)}, {sign}{_fmt_won(abs(diff))})"

    for label, key in (("업무종류", "work_types"), ("물건종류", "prop_types")):
        rows = [x for x in (data.get(key) or []) if x["amount"] > 0][:5]
        if rows:
            lines.append(f"{label} 구성: " + ", ".join(
                f"{x['name']} {_fmt_won(x['amount'])}{with_delta(x['amount'], x.get('prev_amount') or 0)}"
                for x in rows))

    customers = data.get("customers") or {}
    top = customers.get("top") or []
    if top:
        lines.append("발주처 상위: " + ", ".join(
            f"{t['name']} {_fmt_won(t['amount'])}·{t['count']}건"
            + ("(신규)" if t.get("is_new")
               else with_delta(t["amount"], t.get("prev_amount") or 0))
            for t in top))
    # 미수 — 화면에 탭이 있는데 사실표에는 통째로 빠져 있었다(2026-08-11 제보:
    # "내용들은 모든 내용 다 포함"). 미수는 부가세 포함이고 매출은 공급가액이라
    # 두 숫자를 그냥 나누면 안 된다 — 분모는 매출총액(요약표 청구액)이다.
    rec = data.get("receivable") or {}
    if (rec.get("total") or 0) > 0:
        # **전체 미수율은 주지 않는다.** 화면에 없는 숫자다. 잔액과 내역만
        # 사실로 준다. 2026-08-13 개편으로 축은 거래처, 모집단은 발송된 건이다.
        lines.append(f"미수 잔액: {_fmt_won(rec['total'])}"
                     " (부가세 포함 · 당기 발송 건의 지금 잔액. 매출은 부가세"
                     " 제외라 두 숫자를 직접 나누지 말 것)")
        rows = [x for x in (rec.get("customers") or [])
                if (x.get("amount") or 0) > 0][:5]
        if rows:
            lines.append("미수 거래처별: " + ", ".join(
                f"{x['name']} {_fmt_won(x['amount'])}·{x.get('count') or 0}건"
                for x in rows))

    # 유치자(지분) 미등록 몫 — 개인 합과 지사 총액이 왜 다른지의 유일한 설명이다.
    cov = (data.get("coverage") or {}).get("unassigned_ratio") or 0
    if cov > 0.15:
        lines.append(f"참고: 이 지사 매출의 {cov*100:.0f}%는 유치자(지분) 미등록이라"
                     " 개인 실적으로 안 잡힙니다")

    gone = customers.get("gone") or []
    if gone:
        gone_total = sum(float(x["prev_amount"] or 0) for x in gone)
        # 합계를 여기서 준다 — 안 주면 모델이 직접 더한다(실측: '총 3.0억'을 만들었다).
        lines.append(
            f"식은 관계(전년 거래, 올해 0건 · 전년 합계 {_fmt_won(gone_total)}): "
            + ", ".join(f"{x['name']}(전년 {_fmt_won(x['prev_amount'])})" for x in gone))
    return "\n".join(lines)


# AI 분석은 화면이 **방금 받은 것과 같은 숫자**를 서술한다. 그런데 종전에는
# 대시보드(3.1초)와 연도별(2.3초)을 처음부터 다시 계산했다 — 7.7초 중 5.3초가
# 거기였고 모델은 2.4초뿐이었다(실측).
#
# 화면이 그 둘을 부를 때 결과를 잠깐 적어 둔다. AI 버튼은 몇 초 안에 눌리므로
# 거의 항상 맞는다. 못 맞히면 그때 계산한다 — 답이 달라지지 않는다.
#
# 조회 버튼은 영향이 없다: /dashboard 는 언제나 새로 계산하고, 적어 두기만 한다.
# 여기서 읽기만 한다. 그래서 '조회했는데 옛 숫자가 나온다' 가 생길 수 없다.
_RECENT_TTL = 180.0
_recent_dash: "dict[tuple, tuple[float, Any]]" = {}
_recent_years: "dict[tuple, tuple[float, Any]]" = {}
_recent_lock = threading.Lock()


def _remember(store: dict, key: tuple, value: Any) -> None:
    with _recent_lock:
        store[key] = (time.monotonic(), value)
        if len(store) > 32:                       # 오래된 것부터 버린다
            for k in sorted(store, key=lambda k: store[k][0])[:16]:
                store.pop(k, None)


def _recall(store: dict, key: tuple, ttl: float = _RECENT_TTL) -> Any:
    with _recent_lock:
        hit = store.get(key)
    return hit[1] if hit and time.monotonic() - hit[0] < ttl else None


# 상여·가변비 재조회 캐시 (2026-08-16 요청 — "바로 조회").
# 둘 다 사람·달마다 원장 프로시저를 한 번씩 돌아 실측 10~11초가 걸린다.
# 같은 (사람·기간)을 다시 열 때까지 그 값을 물릴 이유가 없다.
#
# TTL 이 둘로 갈리는 건 취향이 아니라 원천의 성질이다:
#   가변비 — 원장 프로시저 집계라 사람이 당일에 고치는 값이 아니다. 넉넉히 10분.
#   상여   — 상여 화면에서 조정(a10_bonus_adjust)을 편집하면 값이 바뀐다.
#            편집하고 돌아왔는데 옛 숫자가 보이면 안 되므로 3분으로 짧게.
_VC_CACHE_TTL = 600.0
_BONUS_CACHE_TTL = 180.0
_recent_vc: "dict[tuple, tuple[float, Any]]" = {}
_recent_bonus: "dict[tuple, tuple[float, Any]]" = {}


def remember_dashboard(emp_name, office_code, date_from, date_to, whole, data) -> None:
    """화면이 방금 받은 대시보드를 적어 둔다 (AI 분석이 다시 계산하지 않게)."""
    _remember(_recent_dash, (emp_name, office_code, date_from, date_to, whole), data)


def remember_years(emp_name, office_code, end_year, whole, years) -> None:
    """연도별도 같은 이유로 적어 둔다."""
    _remember(_recent_years, (emp_name, office_code, end_year, whole), years)


def analyze_dashboard(
    db: Session,
    *,
    emp_name: str,
    office_code: "str | None",
    date_from: date,
    date_to: date,
) -> dict[str, Any]:
    """사실표를 만들어 Gemini 에게 서술만 시킨다. 키가 없거나 실패해도 조용히 알린다."""
    import os  # noqa: PLC0415

    import httpx  # noqa: PLC0415

    dash_key = (emp_name, office_code, date_from, date_to, False)
    year_key = (emp_name, office_code, date_to.year, False)
    data = _recall(_recent_dash, dash_key)
    years = _recall(_recent_years, year_key)
    # 둘 다 없으면 **나란히** 부른다 — 줄 세우면 5.3초, 나란히면 3.1초다.
    if data is None and years is None:
        with ThreadPoolExecutor(max_workers=2) as pool:
            fd = pool.submit(_in_session, lambda s: dashboard(
                s, emp_name=emp_name, office_code=office_code,
                date_from=date_from, date_to=date_to))
            fy = pool.submit(_in_session, lambda s: yearly_trend(
                s, emp_name=emp_name, office_code=office_code, end_year=date_to.year))
            data = fd.result()
            try:
                years = fy.result()
            except Exception:  # noqa: BLE001 — 연도별이 없어도 서술은 된다
                years = None
    else:
        if data is None:
            data = dashboard(db, emp_name=emp_name, office_code=office_code,
                             date_from=date_from, date_to=date_to)
        if years is None:
            try:
                years = yearly_trend(db, emp_name=emp_name, office_code=office_code,
                                     end_year=date_to.year)
            except Exception:  # noqa: BLE001
                years = None
    facts = briefing_facts(data, years)

    key = os.getenv("GEMINI_API_KEY") or get_settings().gemini_api_key.get_secret_value()
    if not key:
        return {"ok": False, "message": "AI 분석 키가 설정되어 있지 않습니다."}
    # 버튼 응답은 몇 초 안에 와야 한다. flash 는 실측 40초대라 챗봇과 같은
    # flash-lite 를 기본으로 쓴다 — 이 일(사실표 서술)에 모델 급 차이가 없다.
    model = os.getenv("MY_SALES_ANALYZE_MODEL", "gemini-2.5-flash-lite")
    try:
        with httpx.Client(timeout=20.0) as client:
            response = client.post(
                _ANALYZE_URL.format(model=model),
                params={"key": key},
                json={
                    "contents": [{"parts": [{"text": _ANALYZE_PROMPT.format(facts=facts)}]}],
                    # thinking 은 끈다 — 이 일에 사고 토큰은 낭비였다(40cb09f 실측).
                    "generationConfig": {"thinkingConfig": {"thinkingBudget": 0}},
                },
            )
            response.raise_for_status()
            text_out = response.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        return {"ok": False, "message": "AI 분석이 잠시 응답하지 않습니다. 다시 시도해 주세요."}
    return {"ok": True, "text": _tidy_analysis(text_out), "model": model}


def _tidy_analysis(text_out: str) -> str:
    """모델 출력 다듬기. '마크다운 금지'라고 해도 flash-lite 는 '*   ' 불릿과
    굵게(**)를 섞어 낸다(실측) — 프롬프트로 빌지 말고 코드로 정리한다."""
    lines = []
    for line in text_out.strip().splitlines():
        line = re.sub(r"^\s*[*\-•]+\s+", "· ", line)
        lines.append(line.replace("**", ""))
    return "\n".join(lines)

# ── 상여·가변비 (2026-08-10) ─────────────────────────────────────────────
# 대시보드와 따로 부른다. 상여 계산이 **월당 3.7초**(실측)라 대시보드에 얹으면
# 화면 첫 그림이 그만큼 늦어진다. 탭을 누를 때만 불러온다.

# 가변비는 **VariableCost_Web.jsp 와 같은 원천**을 쓴다 (2026-08-10 사용자 확정).
# 그 화면이 부르는 것: EXEC SP_IW_S_TaskStats_Mon @F_Date('YYYY-MM-01'), @Manager.
# 22개 항목의 수량·금액을 한 줄로 돌려주는 **순수 조회** 프로시저다(정의에 INSERT·
# UPDATE·DELETE 가 한 줄도 없음을 확인).
#
# 종전에는 APW_IW_MONGABUNBI 에서 월 총액 한 숫자만 읽었다. 그 표는 사람·월당
# 한 줄짜리 스냅숏이라 내역이 없고, 값도 사람에 따라 프로시저와 갈린다 —
# 2026-06 상위 14명 실측: 11명 일치, 3명 불일치(안창덕 +886만, 황인석 +561만,
# 이용훈 +1.1만). **상여 계산(bonus.py:_variable_costs)은 여전히 그 표를 쓴다.**
# 그래서 이 화면의 가변비 탭과 상여 탭의 가변비가 그 3명에서는 어긋난다 —
# 상여 쪽을 맞추는 건 상여 담당 영역이라 손대지 않았다.
def _months(date_from: date, date_to: date) -> "list[tuple[int, int]]":
    """기간이 걸친 달 목록. 하루라도 걸치면 그 달을 센다."""
    out, y, m = [], date_from.year, date_from.month
    while (y, m) <= (date_to.year, date_to.month):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


# SET NOCOUNT ON 이 없으면 프로시저가 결과셋 앞에 건수 메시지를 흘려서,
# 드라이버가 "행을 돌려주지 않는다"며 닫아 버린다(실측 ResourceClosedError).
# VariableCost_Web.jsp 도 상세 조회에 같은 접두를 붙인다.
#
# **_Mon → _MonPung 으로 갈아탔다 (2026-08-18).**
# _Mon 은 유치자 칸을 정확일치로 걸어서 공동(다인) 감정서를 한 건도 못 잡았다 —
# 유치자 칸에는 '강무진,조근렬,김형식' 처럼 쉼표 덩어리로 들어가기 때문이다.
# 그래서 공동 건이 많은 사람이 0원으로 뜨고(조근렬 2026-06 실측 0원), 상여는
# 같은 사람에게서 759,475원을 차감하는 모순이 있었다.
# _MonPung 은 부분일치로 덩어리를 물고 지분표(APW_Booking)로 안분한 몫을
# AFPrice 에 담아 준다 — 상여가 쓰는 _MonTot 과 문자 그대로 같은 안분식이다.
#
# 실측(2026-08-18, 본사 78명 × 2달 전수):
#   2026-06 합계 2.062억 → 2.236억(+8.4%). 13명 증가·65명 동일·**0명 감소**.
#   상여(APW_IW_MONGABUNBI) 대비 불일치 18명·2,127만 → 7명·240만.
#   단독 건은 지분이 100% 라 값이 그대로 보존되고 공동 건만 채워진다.
#
# 대가: 결과셋이 다르다. _Mon 은 1행 × 45열 집계였는데 _MonPung 은 **건별 상세**다
# (사람·달당 중앙값 27행·최대 2,567행). 그래서 아래 _vc_pivot 이 Gubun 으로 접어
# 같은 22항목 표를 만든다. 속도는 같은 급이다(실측 3.7~5.3초 vs 4.3~5.9초).
_TASKSTATS_PROC = (
    "SET NOCOUNT ON; EXEC [{database}].dbo.SP_IW_S_TaskStats_MonPung :f_date, :manager"
)

# _MonPung 의 Gubun → 화면 항목 이름. 여섯 개가 이름이 다르다.
# **주의: 인력 4항목의 Gubun 문자열은 하드코딩이 아니라 원장
# APW_YJI_StandardPrice.Bigo 에서 온다.** 거기서 이름을 고치면 이 표가 조용히
# 안 맞게 되므로, 매핑에 없는 Gubun 이 오면 _vc_pivot 이 경고를 남기고 금액은
# 합계에 살려 둔다(표에서 사라져 총액만 줄어드는 사고를 막는다).
_VC_GUBUN = {
    "남직원": "남직원",
    "수습남직원": "수습남",
    "소속평가사": "소속평가사",
    "수습평가사": "수습평가사",
    "접수": "접수",
    "발송": "발송",
    "심사": "심사",
    "탁상접수": "탁상접수",
    "KB탁상접수": "탁상접수 HF",
    "탁상감정": "탁상감정",
    "KB탁상감정": "탁상감정 HF",
    "비지오": "Visio",
    "수습비지오": "수습 Visio",
    "시조위": "시조위",
    "검산": "검산",
    "약식": "약식",
    "KB약식": "KB 약식",
    "협회심사": "협회심사비",
    "HUG탁상접수": "HUG 탁상접수",
    "HUG탁상감정": "HUG 탁상감정",
    # '감정서경비' 는 한 덩어리로 와서 문서 유무로 갈린다 — _vc_pivot 이 처리한다.
}

# (갈래, 수량단위, 이름, 수량컬럼, 금액컬럼) — VariableCost_Web.jsp 의 ITEMS 그대로.
# _MonPung 으로 갈아탄 뒤로 수량·금액 컬럼 이름은 쓰지 않는다(이름은 남겨 둔다 —
# 어느 항목이 어디서 왔는지의 기록이고, 되돌릴 때 그대로 쓴다).
_VC_ITEMS = (
    ("인력 투입", "time", "남직원", "M1Time", "M1Price"),
    ("인력 투입", "time", "수습남", "SMTime", "SMPrice"),
    ("인력 투입", "time", "소속평가사", "SoPTime", "SoPPrice"),
    ("인력 투입", "time", "수습평가사", "SuPTime", "SuPrice"),
    ("기본 처리", "count", "접수", "JubC", "JubP"),
    ("기본 처리", "count", "발송", "BalC", "BalP"),
    ("기본 처리", "count", "심사", "SimC", "SimP"),
    ("탁상 업무", "count", "탁상접수", "TSJubC", "TSJubP"),
    ("탁상 업무", "count", "탁상접수 HF", "TSJubC2", "TSJubP2"),
    ("탁상 업무", "count", "탁상감정", "TSC", "TSP"),
    ("탁상 업무", "count", "탁상감정 HF", "TSC2", "TSP2"),
    ("특수 업무", "count", "Visio", "VISIC", "VISIP"),
    ("특수 업무", "count", "수습 Visio", "SVISIC", "SVISIP"),
    ("특수 업무", "count", "시조위", "SIJOC", "SIJOP"),
    ("특수 업무", "count", "검산", "CHKC", "CHKP"),
    ("특수 업무", "count", "약식", "YAKC", "YAKP"),
    ("특수 업무", "count", "KB 약식", "KBYAKC", "KBYAKP"),
    ("비용·기타", "count", "협회심사비", "HSIMC", "HSIMP"),
    ("비용·기타", "count", "감정서경비(문서없음)", "GamX_Cnt", "GamX_Price"),
    ("비용·기타", "count", "감정서경비(문서있음)", "GamO_Cnt", "GamO_Price"),
    ("비용·기타", "count", "HUG 탁상접수", "HugJup_Cnt", "HugJup_Price"),
    ("비용·기타", "count", "HUG 탁상감정", "HugGam_Cnt", "HugGam_Price"),
)


def _vc_minutes(value: Any) -> int:
    """'7:30' → 450분. 콜론이 없으면 시간 숫자로 본다 (JSP vwToMinutes 와 같다)."""
    text_value = str(value or "").strip()
    if not text_value:
        return 0
    try:
        if ":" not in text_value:
            return int(round(float(text_value))) * 60
        hour, minute = text_value.split(":", 1)
        return int(hour) * 60 + int(minute)
    except ValueError:
        return 0


def _vc_number(value: Any) -> float:
    try:
        return float(str(value or "").strip() or 0)
    except ValueError:
        return 0.0


def _vc_one_month(ym: str, emp_name: str) -> "list[dict[str, Any]] | None":
    """한 달치 프로시저 한 방 — **건별 상세 목록**을 돌려준다.

    **제 세션을 연다** — 스레드마다 따로 써야 한다. SQLAlchemy 세션은 스레드
    안전하지 않아 하나를 나눠 쓰면 커서가 엉킨다.

    돌려주는 값의 뜻을 셋으로 가른다 — 화면이 이걸 구분해야 한다:
      None  조회 실패(교착·연결 등). 화면은 '해당 없음' 이 아니라 결측으로 본다.
      []    조회는 됐는데 그 달 일이 없다. 0 원이 맞다.
      [...] 건별 상세.
    """
    from app.database import get_session_factory  # noqa: PLC0415

    db = get_session_factory()()
    try:
        # _exec 을 거친다 — 교착으로 끊기면 다시 한다. 여기서 그냥 삼키면 그 달이
        # 조용히 0 원이 되는데, 화면은 '가변비가 없던 달' 과 구분하지 못한다.
        rows = _exec(
            db, _TASKSTATS_PROC.format(database=_source_database()),
            {"f_date": f"{ym}-01", "manager": emp_name},
        ).mappings().all()
        return [dict(r) for r in rows]
    except SQLAlchemyError:
        logger.warning("가변비 조회 실패 %s %s", emp_name, ym, exc_info=True)
        return None
    finally:
        db.close()


def _vc_pivot(
    rows: "list[dict[str, Any]]", emp_name: str, ym: str
) -> "tuple[dict[str, dict[str, Any]], float]":
    """건별 상세를 22항목 표로 접는다 — 금액=SUM(AFPrice)·건수=행수·시간=SUM(Time).

    **AFPrice(안분 후 내 몫)를 쓴다. Beprice(안분 전 100%)를 쓰면 공동 건이
    참여자 수만큼 중복 계상된다** (2026-06 실측: Be 합 2.708억 vs AF 합 2.236억).
    AFPrice 가 NULL 인 행이 0.28% 있는데(지분표 미등재) 상여도 같은 NULL 을 무시하므로
    0 으로 친다.

    시간은 _Mon 처럼 합산돼 오지 않고 행마다 온다 — 여기서 더한다. 다만 **시간은
    안분되지 않는다**(금액만 1/n). 공동 건은 '6시간·63,450원' 처럼 보이는데,
    시간은 실제로 그만큼 일한 것이 맞으므로 원장 값을 그대로 둔다.
    """
    kind_of = {label: kind for _g, kind, label, _q, _p in _VC_ITEMS}
    cells: "dict[str, dict[str, Any]]" = defaultdict(lambda: {"qty": 0, "amount": 0.0})
    unmapped: "dict[str, float]" = defaultdict(float)
    total = 0.0
    for row in rows:
        amount = _vc_number(row.get("AFPrice"))
        total += amount                      # 합계는 매핑 실패와 무관하게 지킨다
        gubun = str(row.get("Gubun") or "").strip()
        if gubun == "감정서경비":
            # 한 덩어리로 와서 감정서번호 유무로 갈린다(프로시저의 X 갈래가
            # isnull(A.Docid,'') 를 내보낸다).
            label = ("감정서경비(문서있음)" if str(row.get("Docid") or "").strip()
                     else "감정서경비(문서없음)")
        else:
            label = _VC_GUBUN.get(gubun)
        if label is None:
            unmapped[gubun] += amount
            continue
        cell = cells[label]
        cell["amount"] += amount
        if kind_of.get(label) == "time":
            cell["qty"] += _vc_minutes(row.get("Time"))
        else:
            cell["qty"] += 1
    if unmapped:
        # 조용히 사라지게 두지 않는다 — 원장에서 Bigo(항목 이름)를 고치면 여기 걸린다.
        logger.warning(
            "가변비 매핑 안 되는 구분값 %s %s: %s",
            emp_name, ym, {k: round(v) for k, v in unmapped.items()},
        )
    return dict(cells), total


def _vc_bonus_hint(db: Session, emp_name: str, ym: str) -> float:
    """상여가 그 달에 잡은 가변비(APW_IW_MONGABUNBI 스냅숏). 프로시저가 아니라
    한 줄 SELECT 라 싸다 — 상세가 0 건인 달에만 부른다.

    상여 화면(bonus.py _variable_costs)이 읽는 바로 그 표·그 키를 쓴다.
    """
    try:
        return float(_exec(
            db,
            f"SELECT SUM(Gabunbi) FROM [{_source_database()}].dbo.APW_IW_MONGABUNBI "
            "WHERE Standmon = CAST(:standmon AS varchar(10)) "
            "AND RTRIM(Manager) = :manager",
            {"standmon": ym, "manager": emp_name},
        ).scalar() or 0)
    except SQLAlchemyError:
        logger.warning("가변비 상여 대조 실패 %s %s", emp_name, ym, exc_info=True)
        return 0.0


# 달끼리는 서로 무관해서 동시에 돌린다. 한 달이 4~5초라(실측, 두 번째 호출도
# 3.5초로 서버 캐시 효과가 없다) 8개월을 줄 세우면 40초다.
# 4로 묶은 이유: 프로시저가 서버 CPU 를 쓰는 무거운 조회라 더 늘리면 다른
# 화면까지 느려진다. 4면 8개월이 두 바퀴로 끝난다.
_VC_WORKERS = 4


def variable_costs(
    db: Session, *, emp_name: str, date_from: date, date_to: date
) -> "dict[str, Any]":
    """월 × 항목 표 하나. 가변비 화면과 같은 프로시저를 쓴다.

    돌려주는 columns 는 **이 기간에 값이 있는 항목만**이다. 22개를 다 세우면
    대부분 0인 칸이라 표가 읽히지 않는다.

    같은 (사람·기간)은 캐시에서 즉시 돌려준다(_VC_CACHE_TTL) — 달마다 프로시저를
    도는 일이라 실측 11초다.
    """
    from concurrent.futures import ThreadPoolExecutor  # noqa: PLC0415

    cache_key = (emp_name, date_from, date_to)
    hit = _recall(_recent_vc, cache_key, _VC_CACHE_TTL)
    if hit is not None:
        return hit

    months = [f"{y:04d}-{m:02d}" for y, m in _months(date_from, date_to)]
    if not months:
        return {"months": [], "columns": [], "total": 0.0}
    with ThreadPoolExecutor(max_workers=min(_VC_WORKERS, len(months))) as pool:
        detail = list(pool.map(lambda ym: _vc_one_month(ym, emp_name), months))

    used: set[str] = set()
    out = []
    empty_months = []
    for ym, rows in zip(months, detail):
        if rows is None:                      # 조회 실패 — 0 원과 구분한다
            out.append({"ym": ym, "amount": 0.0, "found": False, "cells": {}})
            continue
        cells, total = _vc_pivot(rows, emp_name, ym)
        used.update(k for k, v in cells.items() if v["amount"] or v["qty"])
        out.append({"ym": ym, "amount": total, "found": True, "cells": cells})
        if not rows:
            empty_months.append(ym)
    # 상세가 0 건인 달은 상여 스냅숏과 대조한다 — _MonPung 의 '공(' 필터가
    # 앵커되지 않아 '윤도,공(장재원)' 처럼 **본인이 앞에 있는** 공동 표기를 통째로
    # 버리기 때문이다(실측 2026-08-18: 윤도 2026-06 은 상세 0건인데 상여는
    # 2,280,025원). 값을 지어내지 않고 '상여에는 잡힌다'는 사실만 알린다.
    if empty_months:
        for month in out:
            hint = _vc_bonus_hint(db, emp_name, month["ym"]) \
                if month["ym"] in empty_months else 0.0
            if hint > 0:
                month["bonus_only"] = hint
    columns = [
        {"group": g, "kind": k, "name": label}
        for g, k, label, _q, _p in _VC_ITEMS if label in used
    ]
    result = {
        "months": out,
        "columns": columns,
        "total": sum(m["amount"] for m in out),
    }
    # 한 달이라도 프로시저가 실패했으면 적어 두지 않는다 — 결측을 10분 동안
    # 정답인 양 돌려주면, 다시 눌러도 안 고쳐진다.
    if all(m["found"] for m in out):
        _remember(_recent_vc, cache_key, result)
    return result


# 상여 표에서 이 화면이 보여 줄 칸. bonus_report 의 totals 키를 그대로 쓴다.
_BONUS_FIELDS = (
    ("payout_base", "정산 기준액"),
    ("variable_cost", "가변비(전월)"),
    ("association_fee", "협회비"),
    ("bonus_selected", "상여"),
    ("pretax", "세전"),
    ("tax", "세금"),
    ("after_tax", "세후"),
    ("payment", "지급액"),
)

# 칸 이름만으로는 못 밝히는 것을 머리글 풍선말로 붙인다(있는 칸만).
#
# 왜 필요한가 (2026-08-12 실측): 이 표의 '가변비' 와 옆의 **가변비 탭**은 값이
# 다르다. 같은 이름이라 화면을 나란히 보면 한쪽이 틀린 것처럼 읽힌다. 실제로는
# 둘 다 제 원천에 충실하고, 다른 이유가 둘이다.
#   ① **달이 다르다.** 상여는 전월 가변비를 쓴다(벤더 주주상여 프로시저
#      SP_S_IW_JUJUBONUS_BASE 가 APW_IW_MONGABUNBI 를 Standmon=전월 로 읽는 것을
#      그대로 따랐다). 가변비 탭은 그 달 자신이다. 2026-06 안창덕 기준
#      상여 41,438,200(5월) vs 가변비 탭 16,216,280(6월) — 2.5배 차이가 여기서 온다.
#   ② **프로시저가 다르다 — 2026-08-13 규명.** 전에 이 자리에 '원인 미상, 저장소
#      밖이라 못 밝혔다'고 적어 두었는데 틀렸다. 상여가 읽는 스냅숏
#      APW_IW_MONGABUNBI 는 **SP_IW_S_TaskStats_MonTot** 이 채우고, 가변비 탭은
#      **SP_IW_S_TaskStats_Mon** 을 부른다. 이름이 한 글자 차이인 다른 프로시저다.
#      확인: MonTot 를 직접 돌려 스냅숏과 대조하니 5건 전부 **원 단위까지 일치**했다
#      (황인석 2026-06 7,062,357 · 2026-05 6,234,256 · 안창덕 2026-06 25,081,225 ·
#       2026-05 41,438,200 · 유승민 2026-06 20,160,020).
#      무엇이 달랐나: **공동(다인) 감정서의 지분 안분이다.** MonTot 는 항목마다
#      `Ratio / T_Ratio` 를 곱해 지분으로 나눠 배분하는데(정의에서 66곳), Mon 은
#      그 비율을 조인에만 쓰고 항목에 곱하지 않았다(2곳).
#   → **②는 2026-08-18 에 해소됐다.** 가변비 탭이 _Mon 에서 **_MonPung** 으로
#      갈아탔다(_TASKSTATS_PROC 주석 참조). _MonPung 은 MonTot 와 문자 그대로 같은
#      안분식을 쓰면서 건별 상세까지 준다 — 2026-06 본사 78명에서 상여 대비 불일치가
#      18명·2,127만 → 7명·240만으로 줄었다. 이제 남은 차이는 ①(달) 하나가 주다.
# 상여를 Mon 쪽으로 바꾸면 벤더 상여(SP_S_IW_JUJUBONUS_BASE)·재무팀 엑셀과
# 갈린다. 바꾸지 말 것.
_BONUS_NOTES = {
    "variable_cost": "상여는 전월 가변비로 계산합니다 — 옆의 '가변비' 탭(그 달 기준)과 "
                     "값이 다른 것이 정상입니다.",
}


# 상여 한 달치는 **사람과 무관한 계산**이다 — bonus_report(db, year, month) 는
# 그 달의 전 직원(주주 53 + 준회원 14)을 계산하고, 우리는 거기서 한 사람만
# 골라 낸다. 그래서 두 사람이 같은 기간을 열면 **똑같은 계산이 두 벌** 돈다.
# 부하 실측(동시 5명이 같은 8개월을 열 때): 상여 20초 → 52초.
#
# 60초짜리 기억으로 겹침을 없앤다. 같은 달을 이미 계산 중이면 **기다렸다 그
# 결과를 쓴다**(단일 비행) — 안 그러면 다섯이 동시에 캐시를 놓치고 다섯 벌이 돈다.
#
# 이건 표가 아니라 **프로세스 안 60초짜리 기억**이다. APW_IW_MONGABUNBI 가
# 프로시저와 값이 갈렸던 사고와는 성격이 다르다: 재기동하면 사라지고, 산식이
# 바뀌면 60초 뒤 저절로 따라간다. 상여 화면(bonus.py)은 이걸 안 쓴다 — 확정
# 숫자를 보는 곳은 늘 새로 계산한다.
_BONUS_TTL = 60.0
_bonus_memo: "dict[tuple[int, int], tuple[float, Any]]" = {}
_bonus_locks: "dict[tuple[int, int], threading.Lock]" = {}
_bonus_guard = threading.Lock()


def _bonus_report_memo(year: int, month: int) -> "dict[str, Any]":
    from app.database import get_session_factory  # noqa: PLC0415
    from app.services.bonus_legacy import bonus_report  # noqa: PLC0415

    key = (year, month)
    hit = _bonus_memo.get(key)
    if hit and time.monotonic() - hit[0] < _BONUS_TTL:
        return hit[1]
    with _bonus_guard:
        lock = _bonus_locks.setdefault(key, threading.Lock())
        # 지나간 달의 자물쇠까지 쌓아 두지 않는다(연도 하나면 12개 안팎이다).
        # **목록을 먼저 뜬 뒤 지운다.** 딕셔너리를 순회하면서 다른 스레드가 새
        # 달을 넣으면 '순회 중 크기 변경' 으로 터진다 — 넣는 쪽은 아래에서
        # 이 자물쇠(_bonus_guard)를 잡으므로 그 창이 실재한다.
        if len(_bonus_locks) > 64:
            now = time.monotonic()
            stale = [k for k, (t, _v) in list(_bonus_memo.items())
                     if now - t >= _BONUS_TTL and k != key]
            for k in stale:
                _bonus_locks.pop(k, None)
                _bonus_memo.pop(k, None)
    with lock:
        hit = _bonus_memo.get(key)
        if hit and time.monotonic() - hit[0] < _BONUS_TTL:
            return hit[1]
        db = get_session_factory()()
        try:
            report = bonus_report(db, year, month)
        finally:
            db.close()
        # 쓰기도 _bonus_guard 안에서 한다 — 위 정리 루프와 같은 자물쇠라야
        # 순회 중 삽입이 생기지 않는다.
        with _bonus_guard:
            _bonus_memo[key] = (time.monotonic(), report)
        return report


def _bonus_one_month(year: int, month: int, emp_name: str) -> "dict[str, Any] | None":
    """한 달치에서 내 줄만 뽑는다. 계산 자체는 사람과 무관하다(위 주석)."""
    try:
        report = _bonus_report_memo(year, month)
    except Exception:  # noqa: BLE001 — 그 달만 비운다
        logger.warning("상여 조회 실패 %s %s-%s", emp_name, year, month, exc_info=True)
        return None
    return next(
        (r for r in (report.get("shareholders") or [])
         + (report.get("associates") or []) if r.get("name") == emp_name),
        None,
    )


# 가변비와 같은 이유로 동시에 돈다. 한 달이 3.7초라 8개월을 줄 세우면 30초다.
# 3으로 묶은 이유: bonus_report 는 달마다 **전 직원**(주주 53 + 준회원 14)을
# 계산하는 무거운 일이라 가변비(4)보다 한 단 낮춘다.
_BONUS_WORKERS = 3


def bonus_months(
    db: Session, *, emp_name: str, date_from: date, date_to: date
) -> "dict[str, Any]":
    """월별 상여. 달마다 bonus_report 를 돌리되 동시에 돈다.

    한 달이 통째로 실패해도 그 달만 비우고 나머지를 살린다. 상여 계산은
    원천이 넓어(전표·조사비·조정) 한 달의 결측이 화면 전체를 죽이면 안 된다.

    같은 (사람·기간)은 캐시에서 즉시 돌려준다 — 다만 상여 조정 편집이 있어
    TTL 을 짧게 잡는다(_BONUS_CACHE_TTL).
    """
    from concurrent.futures import ThreadPoolExecutor  # noqa: PLC0415

    cache_key = (emp_name, date_from, date_to)
    hit = _recall(_recent_bonus, cache_key, _BONUS_CACHE_TTL)
    if hit is not None:
        return hit

    months = _months(date_from, date_to)
    if not months:
        return {"months": [], "fields": [], "total": 0.0}
    with ThreadPoolExecutor(max_workers=min(_BONUS_WORKERS, len(months))) as pool:
        found = list(pool.map(lambda ym: _bonus_one_month(ym[0], ym[1], emp_name),
                              months))

    out = []
    for (year, month), me in zip(months, found):
        ym = f"{year:04d}-{month:02d}"
        if me is None:
            out.append({"ym": ym, "found": False})
            continue
        totals = me.get("totals") or {}
        row = {"ym": ym, "found": True, "dept": me.get("dept") or ""}
        for key, _label in _BONUS_FIELDS:
            value = totals.get(key)
            row[key] = float(value) if isinstance(value, (int, float)) else 0.0
        out.append(row)
    paid = [r for r in out if r.get("found")]
    result = {
        "months": out,
        "fields": [
            {"key": k, "label": lab, **({"note": _BONUS_NOTES[k]} if k in _BONUS_NOTES else {})}
            for k, lab in _BONUS_FIELDS
        ],
        "total": sum(r.get("payment", 0.0) for r in paid),
    }
    # 상여는 지급이 없는 달이 정상이라(실측: 8개월 중 4달 0원) found=False 를
    # 결측으로 못 본다 — 다만 **전 달이 실패**한 건 조회가 깨진 것이므로 안 적는다.
    if paid:
        _remember(_recent_bonus, cache_key, result)
    return result
