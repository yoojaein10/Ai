"""입금발송내역 — 알림 큐(a10_payment_notify) 이벤트 조회와 알림톡 발송·전송 기록.

- 목록: 큐 이벤트(입금이 늘어난 사건) 기준, 감지시각 기간으로 조회 (2026-07-31 전환).
  상태는 큐 행의 감지 시점 스냅샷(완납/부분입금), 거래처·담당자는 apw_masterex 조인.
- 발송 정책 검증(입금완료 판정)은 payment_status 기준(_send_targets)이지만,
  전송 기록·중복 방지는 큐의 sent_at·send_result만 쓴다 (2026-08-04 사용자 결정 —
  payment_status.sms_sent_at/sms_sent_by는 더 이상 갱신하지 않는 과거 기록 컬럼).
  발송·전송처리 시 해당 감정서의 미처리 큐 행을 send_result와 함께 닫는다.

지사 스코핑은 입금 현황과 동일하게 감정서번호 접두사(a10_office_map.docid_prefix)로
필터한다. 조회·갱신 모두 바인드 파라미터만 사용한다.

공통건 규칙 (2026-07-30 사용자 확정): 담당자(apw_masterex.Manager)가 공(이름)뿐인
감정서는 문자 보낼 담당자가 없어 목록에서 제외한다. 담당자가 쉼표 구분으로 여러 명이고
공(...)이 아닌 이름이 하나라도 있으면 포함하고 그 이름(들)이 문자 수신자다 —
예: KDB산업은행 건 '윤도,공(장재원)' → 수신자 윤도.
약식 감정(감정서번호 유형 '6')은 발송 대상이 아니라 목록에서 제외한다.
"""

from datetime import date, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.services.office_lookup import docid_prefixes
from app.services.receivables import management_no_filter

MAX_ROWS = 1000
MAX_MARK_DOCS = 200

# 매출총액이 빈 이유는 하나다 — APW_Bill 에 행이 없다(청구서 미작성).
# 화면·엑셀이 같은 글자를 쓰도록 여기 한 곳에 둔다.
NO_BILL_TEXT = "청구서 미작성"


class PaymentSmsError(ValueError):
    pass


def _source_db() -> str:
    name = get_settings().mssql_source_db
    if not name.replace("_", "").isalnum():
        raise RuntimeError("MSSQL_SOURCE_DB 이름이 올바르지 않습니다.")
    return name


def sms_recipients(manager: "str | None") -> "str | None":
    """담당자 문자열에서 알림 수신자를 뽑는다. 없으면 None.

    공(이름)·'공통'(공시업무 등)은 특정 수신자가 아니라서 제외한다.
    """
    names = [
        part.strip() for part in str(manager or "").split(",")
        if part.strip() and not part.strip().startswith("공(")
        and part.strip() != "공통"
    ]
    return ", ".join(names) or None


# 공(...)·'공통'뿐인 공통건 제외 — 그 외 담당자가 한 명이라도 있으면 포함(그 사람이 수신자).
# 담당자 미상(NULL)은 숨기지 않고 표시해 데이터 누락을 확인할 수 있게 한다.
_HAS_RECIPIENT_SQL = """(m.Manager IS NULL OR EXISTS (
    SELECT 1 FROM STRING_SPLIT(RTRIM(m.Manager), ',') parts
    WHERE LTRIM(RTRIM(parts.value)) <> '' AND LTRIM(RTRIM(parts.value)) NOT LIKE N'공(%'
      AND LTRIM(RTRIM(parts.value)) <> N'공통'
))"""

# 약식 감정(감정서번호 유형 자리 '6', 예: 01-2605-6-0359)은 발송 대상 아님
# (2026-07-30 재무팀 정책 — iCode 7월 로그 대조에서 확인)
_NOT_BRIEF_SQL = "p.doc_id NOT LIKE '__-____-6-%'"

# 전송으로 치는 큐 처리 결과 — '대상 아님'·'기한 경과'·'지사 건' 등 정책 사유로 닫힌
# 행은 전송이 아니므로 재발송을 막지 않는다.
# '발송 이력 확인'은 로그 대조로 자동 채운 것 — 실제로 나갔으므로 전송으로 친다.
_SENT_RESULT_SQL = (
    "(send_result LIKE N'알림톡 큐잉%' OR send_result = N'수동 전송처리(기록만)'"
    " OR send_result = N'발송 이력 확인(자동)')"
)

# 기전송 감정서 제외 — 전송 기록은 알림 큐에만 남긴다
# (2026-08-04 사용자 결정: payment_status의 sms_sent_at은 더 이상 갱신하지 않는다).
_NOT_SENT_SQL = f"""NOT EXISTS (
    SELECT 1 FROM dbo.a10_payment_notify q
    WHERE q.doc_id = p.doc_id AND q.sent_at IS NOT NULL
      AND {_SENT_RESULT_SQL.replace('send_result', 'q.send_result')}
)"""


def _queue_status_label(queue_status: Any, pay_result: Any) -> "str | None":
    """과거 큐 스냅샷보다 현재 정식 입금 판정을 우선 표시한다."""
    current = str(pay_result or "").strip()
    if current == "입금완료":
        return "완납"
    if current == "분할입금":
        return "부분입금"
    return str(queue_status or "").strip() or None


def _capped_received_sql(queue_amount: str, current_amount: str) -> str:
    """큐 누적액이 현재 정식 입금액보다 클 때 현재 금액으로 제한한다.

    큐는 append-only 이므로 일시적인 중복 집계가 나중에 바로잡혀도 잘못된 과거
    스냅샷은 남는다. 정상적인 과거 분할입금액(현재액보다 작음)은 그대로 보존한다.
    """
    return (
        f"CASE WHEN {queue_amount} IS NULL THEN {current_amount} "
        f"WHEN {current_amount} IS NOT NULL AND {queue_amount} > {current_amount} "
        f"THEN {current_amount} ELSE {queue_amount} END"
    )


# 화면에 보이는 입금상태를 SQL로 옮긴 것 — _queue_status_label 과 같은 규칙이다.
# 상태로 걸러 조회하려면 SQL 쪽에도 같은 규칙이 있어야 한다. 두 곳이 어긋나면
# '완납'으로 걸러 놓고 화면엔 '부분입금'이 뜬다. 같은지 시험으로 잠가 뒀다.
_STATUS_SQL = """CASE
    WHEN LTRIM(RTRIM(ISNULL(p.pay_result, ''))) = N'입금완료' THEN N'완납'
    WHEN LTRIM(RTRIM(ISNULL(p.pay_result, ''))) = N'분할입금' THEN N'부분입금'
    ELSE NULLIF(LTRIM(RTRIM(ISNULL(n.status, ''))), N'')
END"""

# 화면 선택값 → 걸러 낼 상태. 전체는 안 거른다.
PAY_STATUS_LABELS = {"full": "완납", "partial": "부분입금"}


def build_filters(
    sent: str, query: "str | None", pay_status: str = "all"
) -> "tuple[list[str], dict[str, Any]]":
    """처리여부·입금상태·검색어 WHERE 조각 — 값은 전부 바인드 파라미터로만 전달한다.

    sent/unsent는 큐 행의 처리 여부(n.sent_at)를 뜻한다 (구 화면의 전송여부 의미 계승).
    pay_status는 화면에 보이는 입금상태(완납/부분입금)다 — 큐 스냅샷이 아니라
    현재 정식 판정 기준이라 목록에 찍힌 글자와 항상 같다.
    """
    clauses: "list[str]" = []
    params: "dict[str, Any]" = {}
    if sent == "sent":
        clauses.append("n.sent_at IS NOT NULL")
    elif sent == "unsent":
        clauses.append("n.sent_at IS NULL")
    label = PAY_STATUS_LABELS.get(pay_status)
    if label:
        clauses.append(f"({_STATUS_SQL}) = :pay_status")
        params["pay_status"] = label
    query = (query or "").strip()
    if query:
        clauses.append(
            "(n.doc_id LIKE CAST(:query AS varchar(500)) OR m.CustName LIKE :query)"
        )
        params["query"] = f"%{query}%"
    return clauses, params


def list_queue(
    db: Session,
    date_from: date,
    date_to: date,
    office_code: "str | None",
    sent: str = "all",
    query: "str | None" = None,
    max_rows: int = MAX_ROWS,
    pay_status: str = "all",
) -> "dict[str, Any]":
    """알림 큐(a10_payment_notify) 이벤트 목록 + 합계 — 입금일 기간, 최신순.

    행 = 입금이 늘어난 사건 1건(분할입금이면 감정서당 여러 행). 정상적인 과거
    누적액은 큐 스냅샷을 유지하되, 중복 감지로 현재 정식 입금액보다 커진 값은
    현재액으로 제한한다. 상태도 현재 정식 판정을 우선한다. 과거 집계가 전표상
    청구액만 보고 완납으로 저장한 건을 발송 가능 건처럼 보이지 않게 한다.
    거래처·담당자는 마스터 조인으로 보강한다.
    공통건·약식 제외는 발송 정책과 동일.
    큐 재도입(2026-07-31) 이전 기간은 행이 없다 — 과거 대조는 엑셀/큐 이전 기록 참조.
    """
    prefixes = (
        docid_prefixes(db, office_code) if office_code
        else (docid_prefixes(db, None) or ["01"])
    )
    prefix_sql, params = management_no_filter(prefixes, column="n.doc_id")
    # 입금일 기준 조회 — 입금일이 없는 행(초기 적재분 등)은 감지일로 대체 판정
    where = [
        "COALESCE(n.last_received_date, CAST(n.detected_at AS date)) >= :date_from",
        "COALESCE(n.last_received_date, CAST(n.detected_at AS date)) <= CAST(:date_to AS date)",
        prefix_sql,
        _HAS_RECIPIENT_SQL,
        "n.doc_id NOT LIKE '__-____-6-%'",
    ]
    params |= {"date_from": date_from, "date_to": date_to}
    extra, extra_params = build_filters(sent, query, pay_status)
    where += extra
    params |= extra_params
    src = _source_db()
    # apw_masterex는 DocID 중복이 있어 GROUP BY로 1행화해서 조인한다 (payment_status MERGE와 동일)
    # 매출총액도 여기서 가져온다 — 알림톡 본문에 쓰는 값과 같은 칸이라 화면·문자가 어긋나지 않는다.
    base_sql = f"""
FROM dbo.a10_payment_notify n
LEFT JOIN dbo.a10_payment_status p ON p.doc_id = n.doc_id
LEFT JOIN (
    SELECT DocID, MAX(CustName) AS CustName, MAX(Manager) AS Manager,
           MAX([매출총액]) AS total_amount, MAX([청구금액]) AS bill_amount
    FROM [{src}].dbo.apw_masterex
    GROUP BY DocID
) m ON m.DocID = n.doc_id
WHERE {' AND '.join(where)}
"""
    rows = db.execute(
        text(f"""
SELECT TOP {int(max_rows) + 1} n.id, n.doc_id, n.detected_at,
       n.delta_amount,
       {_capped_received_sql('n.received_amount', 'p.paid_amount')} AS received_amount,
       n.last_received_date,
       n.status, p.pay_result, n.sent_at AS queue_at, n.send_result AS queue_result,
       RTRIM(m.CustName) AS customer_name, RTRIM(m.Manager) AS manager,
       m.total_amount, m.bill_amount
{base_sql}
ORDER BY COALESCE(n.last_received_date, CAST(n.detected_at AS date)) DESC,
         n.detected_at DESC, n.id DESC
"""),
        params,
    ).mappings().all()
    totals = db.execute(
        text(f"""
SELECT COUNT(*) AS total_count,
       ISNULL(SUM(n.delta_amount), 0) AS delta_total,
       SUM(CASE WHEN n.sent_at IS NOT NULL THEN 1 ELSE 0 END) AS done_count
{base_sql}
"""),
        params,
    ).mappings().one()

    def _minutes(value):
        return value.isoformat(sep=" ", timespec="minutes") if value else None

    items = [
        {
            "doc_id": row["doc_id"],
            "customer_name": (row["customer_name"] or "").strip() or None,
            "manager": (row["manager"] or "").strip() or None,
            "recipients": sms_recipients(row["manager"]),
            "detected_at": _minutes(row["detected_at"]),
            "paid_date": (
                row["last_received_date"].isoformat()
                if row["last_received_date"] else None
            ),
            # 매출총액 = APWorks 청구금액(apw_masterex.매출총액 = APW_Bill.TOTAL).
            # 전표가 아니라 원장 값이고, 알림톡 본문 '3. 매출총액'과 같은 칸이다.
            # 빈 값은 0원이 아니라 **청구서(APW_Bill)가 아직 없다**는 뜻이라 None으로
            # 구분해 내보낸다 — 0으로 뭉개면 화면에서 '무료 건'과 구별이 안 된다.
            # (2026-08-21 전수 확인: 청구서는 있는데 금액만 빈 행은 0건이다.)
            "total_amount": (
                None if row["total_amount"] is None else float(row["total_amount"])
            ),
            # 청구금액(APW_Bill.BILL) = 실제로 청구한 금액. 착수금을 미리 받은 건은
            # 잔금만 적혀 있어 매출총액과 다르다 (큐 1,467건 중 21건, 2026-08-21).
            "bill_amount": (
                None if row["bill_amount"] is None else float(row["bill_amount"])
            ),
            "delta_amount": float(row["delta_amount"] or 0),
            "received_amount": float(row["received_amount"] or 0),
            "status": _queue_status_label(row["status"], row["pay_result"]),
            "queue_done": row["queue_at"] is not None,
            "queue_result": (row["queue_result"] or "").strip() or None,
            "queue_at": _minutes(row["queue_at"]),
        }
        for row in rows[:max_rows]
    ]
    return {
        "items": items,
        "truncated": len(rows) > max_rows,
        "totals": {
            "count": int(totals["total_count"] or 0),
            "delta_total": float(totals["delta_total"] or 0),
            "done_count": int(totals["done_count"] or 0),
            "pending_count": int(totals["total_count"] or 0)
            - int(totals["done_count"] or 0),
        },
    }


# ── 알림톡 발송 (비즈뿌리오 DB 에이전트: KakaoMMs.dbo.BIZ_MSG INSERT) ──
# 템플릿 '입금내역알림'(1.png, 2026-07-30 등록)과 본문이 완전히 일치해야 발송된다.
ALIMTALK_BODY = """[감정물건 입금내역 안내]

감정물건에 대한 입금 처리 내역을 안내드립니다.

1. 감정번호: {docid}
2. 입금일자: {indate}
3. 매출총액: {totamt}
4. 입금합계: {sumamt}
5. 거래처: {custname}
6. 소재지: {addr}

상기 내역을 확인해 주시기 바라며, 관련하여 문의 사항이 있으시면 재무팀으로 연락 부탁드립니다."""

MAX_SEND_DOCS = 100


def _clean_phone(value: "str | None") -> "str | None":
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits if digits.startswith("01") and 10 <= len(digits) <= 11 else None


def build_alimtalk_body(doc: "dict[str, Any]") -> str:
    """감정서 1건의 템플릿 변수 치환 본문."""
    return ALIMTALK_BODY.format(
        docid=doc["doc_id"],
        indate=doc.get("paid_date") or "-",
        totamt=f"{int(doc.get('total_amount') or 0):,}원",
        sumamt=f"{int(doc.get('paid_amount') or 0):,}원",
        custname=doc.get("customer_name") or "-",
        addr=doc.get("address") or "-",
    )


def _recipient_cmid(doc_id: str, recipient_index: int, recipient_count: int) -> str:
    """여러 수신자의 BIZ_MSG 기본키를 감정서번호-1, -2 형태로 나눈다."""
    value = str(doc_id or "").strip()
    if recipient_count <= 1:
        return value[:32]
    suffix = f"-{recipient_index + 1}"
    return value[: 32 - len(suffix)] + suffix


# 발송 이력 대조 범위 — 알림톡은 입금 직후에 나가므로 몇 달 전 것과 겹칠 일이 없다.
# 표가 월별(BIZ_LOG_YYYYMM)이라 무한정 훑으면 느려진다.
SENT_LOG_MONTHS = 3


def _sent_log_tables(db: Session, today: date) -> "list[str]":
    """최근 몇 달치 발송 이력 표 이름. 실제로 있는 것만 돌려준다."""
    biz = get_settings().bizppurio_db
    wanted = []
    year, month = today.year, today.month
    for _ in range(SENT_LOG_MONTHS):
        wanted.append(f"BIZ_LOG_{year:04d}{month:02d}")
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    rows = db.execute(
        text(f"SELECT name FROM {biz}.sys.tables WHERE name IN (" +
             ", ".join(f":t{i}" for i in range(len(wanted))) + ")"),
        {f"t{i}": name for i, name in enumerate(wanted)},
    ).scalars().all()
    # 이름은 우리가 만든 형식이지만 SQL에 끼워 넣기 전에 한 번 더 막는다.
    return [n for n in rows if n.replace("_", "").isalnum()]


def already_sent_docs(db: Session, doc_ids: "list[str]") -> "set[str]":
    """알림톡이 실제로 나간 감정서 집합 — 비즈뿌리오 발송 이력이 근거다.

    큐의 sent_at 은 화면의 '미전송처리'로 지울 수 있어서, 지워 놓고 다시 보내면
    같은 손님이 문자를 두 번 받는다 (2026-08-21 실제로 9명이 두 번 받았다).
    BIZ_MSG 의 CMID 기본키는 대기열에 함께 있는 동안만 막아 준다 — 발송된 행은
    BIZ_LOG_YYYYMM 으로 옮겨져 대기열에서 사라지므로 다음 날이면 안 걸린다.
    지울 수 없는 발송 이력을 근거로 삼아야 확실하다.

    우리 템플릿(bizppurio_template_code)으로만 좁힌다 — 다른 시스템이 같은
    감정서로 보낸 문자까지 세면 멀쩡한 발송이 막힌다.
    """
    docs = [d for d in {str(x or "").strip() for x in doc_ids} if d]
    if not docs:
        return set()
    tables = _sent_log_tables(db, date.today())
    if not tables:
        raise PaymentSmsError(
            "발송 이력 표(BIZ_LOG)를 찾지 못해 중복 발송을 확인할 수 없습니다."
        )
    names = [f"doc_{i}" for i in range(len(docs))]
    in_clause = ", ".join(f":{n}" for n in names)
    params: "dict[str, Any]" = dict(zip(names, docs))
    params["tpl"] = get_settings().bizppurio_template_code
    biz = get_settings().bizppurio_db
    union = " UNION ".join(
        f"SELECT LTRIM(RTRIM(CINFO)) AS doc FROM [{biz}].dbo.{t} "
        f"WHERE TEMPLATE_CODE = :tpl AND LTRIM(RTRIM(CINFO)) IN ({in_clause})"
        for t in tables
    )
    return {row[0] for row in db.execute(text(union), params).all()}


def already_sent_docs_since(db: Session, since: date) -> "list[str]":
    """그 날 이후 알림톡이 나간 감정서 전부 — 발송 이력(BIZ_LOG)이 근거다.

    already_sent_docs 는 '이 번호들이 나갔나'를 묻고, 이쪽은 '무엇이 나갔나'를 묻는다.
    큐를 이력에 맞출 때 쓴다(reconcile_sent_from_log).
    """
    tables = _sent_log_tables(db, date.today())
    if not tables:
        raise PaymentSmsError(
            "발송 이력 표(BIZ_LOG)를 찾지 못해 발송 기록을 대조할 수 없습니다."
        )
    biz = get_settings().bizppurio_db
    union = " UNION ".join(
        f"SELECT DISTINCT LTRIM(RTRIM(CINFO)) AS doc FROM [{biz}].dbo.{t} "
        f"WHERE TEMPLATE_CODE = :tpl AND REQUEST_TIME >= :since "
        f"AND LTRIM(RTRIM(ISNULL(CINFO, ''))) <> ''"
        for t in tables
    )
    params = {"tpl": get_settings().bizppurio_template_code, "since": since}
    return sorted({row[0] for row in db.execute(text(union), params).all()})


def _recipient_phones(db: Session, names: "list[str]") -> "dict[str, str | None]":
    """담당자 이름 → Seat_userinfo.Uptel(휴대폰). 없는 이름은 None."""
    result: "dict[str, str | None]" = {name: None for name in names}
    if not names:
        return result
    params = {f"name_{index}": name for index, name in enumerate(names)}
    in_clause = ", ".join(f":{key}" for key in params)
    rows = db.execute(
        text(
            f"SELECT RTRIM(Uname) AS name, RTRIM(Uptel) AS phone "
            f"FROM [{_source_db()}].dbo.Seat_userinfo WHERE RTRIM(Uname) IN ({in_clause})"
        ),
        params,
    ).all()
    for name, phone in rows:
        if result.get(name) is None:
            result[name] = _clean_phone(phone)
    return result


def _send_targets(
    db: Session, doc_ids: "list[str] | None", auto_days: int
) -> "list[dict[str, Any]]":
    """발송 대상 상세 — 입금완료·미전송·수신자 있는 건만. 템플릿 변수 원천 포함.

    doc_ids 지정(수동 발송) 시 그 목록으로 한정하고, 미지정(자동)이면 최근
    auto_days일 입금완료·미전송 전체가 대상이다.
    알림톡은 본사(office=10) 건만 나간다 — 수동으로 지사 감정서를 넘겨도 걸러진다.
    입금합계·입금일은 알림 큐(a10_payment_notify) 최신 행의 스냅샷을 쓴다
    (2026-08-04 사용자 결정: 입금발송내역 화면에 보이는 금액과 발송 금액 일치).
    큐 도입(2026-07-31) 이전 입금 건은 큐 행이 없어 payment_status로 폴백.
    발송 정책 판정(입금완료·미전송)은 계속 payment_status 기준이다.
    """
    src = _source_db()
    hq_sql, params = management_no_filter(
        docid_prefixes(db, "10"), column="p.doc_id"
    )
    where = [
        "p.pay_result = N'입금완료'", _NOT_SENT_SQL,
        _HAS_RECIPIENT_SQL, _NOT_BRIEF_SQL, hq_sql,
    ]
    if doc_ids is not None:
        names = [f"doc_{index}" for index in range(len(doc_ids))]
        where.append(
            "p.doc_id IN (" + ", ".join(f"CAST(:{n} AS varchar(500))" for n in names) + ")"
        )
        params |= dict(zip(names, doc_ids))
    else:
        where.append("p.paid_date >= DATEADD(day, -:auto_days, CAST(GETDATE() AS date))")
        params["auto_days"] = int(auto_days)
    rows = db.execute(
        text(f"""
SELECT p.doc_id, COALESCE(n.last_received_date, p.paid_date) AS paid_date,
       {_capped_received_sql('n.received_amount', 'p.paid_amount')} AS paid_amount,
       RTRIM(m.CustName) AS customer_name, RTRIM(m.Manager) AS manager,
       m.total_amount, m.address
FROM dbo.a10_payment_status p
LEFT JOIN (
    SELECT doc_id, received_amount, last_received_date,
           ROW_NUMBER() OVER (PARTITION BY doc_id ORDER BY detected_at DESC, id DESC) AS rn
    FROM dbo.a10_payment_notify
) n ON n.doc_id = p.doc_id AND n.rn = 1
LEFT JOIN (
    SELECT DocID, MAX(CustName) AS CustName, MAX(Manager) AS Manager,
           MAX([매출총액]) AS total_amount, MAX(Address) AS address
    FROM [{src}].dbo.apw_masterex
    GROUP BY DocID
) m ON m.DocID = p.doc_id
WHERE {' AND '.join(where)}
ORDER BY p.paid_date, p.doc_id
"""),
        params,
    ).mappings().all()
    return [
        {
            "doc_id": row["doc_id"],
            "paid_date": row["paid_date"].isoformat() if row["paid_date"] else None,
            "paid_amount": float(row["paid_amount"] or 0),
            "customer_name": (row["customer_name"] or "").strip() or None,
            "manager": (row["manager"] or "").strip() or None,
            "total_amount": float(row["total_amount"] or 0),
            "address": (row["address"] or "").strip() or None,
            "recipients": sms_recipients(row["manager"]),
        }
        for row in rows
    ]


def send_alimtalk(
    db: Session,
    doc_ids: "list[str] | None",
    usr_seq: "int | None",
) -> "dict[str, Any]":
    """대상 건을 BIZ_MSG에 큐잉하고 알림 큐 행을 전송으로 닫는다.

    - 테스트 번호(payment_alert_test_phone)가 설정돼 있으면 전 건 그 번호로 발송.
    - 실제 발송 이력(BIZ_LOG)이 있는 감정서는 건너뛴다 — 큐의 sent_at 은 화면에서
      지울 수 있어 그것만으로는 중복 발송을 못 막는다 (2026-08-21 실측: 9명이
      같은 문자를 두 번 받았다). 테스트 발송 중에는 검사하지 않는다.
    - 수신자 전화(Seat_userinfo.Uptel)가 없는 건은 건너뛰고 skipped에 담는다.
    - 큐잉 성공 건만 전송 기록 — 수신자별 1행 INSERT.
      한 명이면 CMID=감정서번호, 여러 명이면 CMID=감정서번호-1/-2/...로 고유하게
      만들고 CINFO에는 원래 감정서번호를 유지한다.
    """
    settings = get_settings()
    if not settings.is_bizppurio_configured:
        raise PaymentSmsError("비즈뿌리오 설정(BIZPPURIO_*)이 없습니다.")
    if doc_ids is not None:
        doc_ids = [d.strip() for d in doc_ids if d and d.strip()]
        if not doc_ids:
            raise PaymentSmsError("발송할 감정서번호가 없습니다.")
        if len(doc_ids) > MAX_SEND_DOCS:
            raise PaymentSmsError(f"한 번에 {MAX_SEND_DOCS}건까지만 발송할 수 있습니다.")
    targets = _send_targets(db, doc_ids, settings.payment_alert_auto_days)
    test_phone = _clean_phone(settings.payment_alert_test_phone)

    # 큐 기록이 지워졌어도 실제 발송 이력이 있으면 다시 보내지 않는다.
    # 테스트 번호로 보내는 중이면 손님에게 갈 일이 없으므로 이 검사를 건너뛴다.
    already = set() if test_phone else already_sent_docs(
        db, [t["doc_id"] for t in targets]
    )
    skipped_sent: "list[dict[str, str]]" = [
        {"doc_id": t["doc_id"], "reason": "이미 알림톡이 발송된 이력 있음"}
        for t in targets if t["doc_id"] in already
    ]
    targets = [t for t in targets if t["doc_id"] not in already]

    all_names = sorted({
        name for target in targets
        for name in (target["recipients"] or "").split(", ") if name
    })
    phones = _recipient_phones(db, all_names)

    biz_db = settings.bizppurio_db
    if not biz_db.replace("_", "").isalnum():
        raise RuntimeError("BIZPPURIO_DB 이름이 올바르지 않습니다.")
    insert_sql = text(f"""
INSERT INTO [{biz_db}].dbo.BIZ_MSG (
    CMID, MSG_TYPE, STATUS, REQUEST_TIME, SEND_TIME,
    DEST_PHONE, SEND_PHONE, DEST_NAME, MSG_BODY, NATION_CODE,
    SENDER_KEY, TEMPLATE_CODE, RE_TYPE, RE_PART,
    COVER_FLAG, SMS_FLAG, REPLY_FLAG, USE_PAGE, USE_TIME, SN_RESULT, TEL_INFO, CINFO
) VALUES (
    :cmid, 6, 0, GETDATE(), GETDATE(),
    :dest_phone, :send_phone, :dest_name, :msg_body, '82',
    :sender_key, :template_code, 'N', 'S',
    0, 0, 0, 0, 0, 0, '-', :cinfo
)
""")
    sent_docs: "list[str]" = []
    skipped: "list[dict[str, str]]" = list(skipped_sent)
    queued = 0
    for target in targets:
        names = [n for n in (target["recipients"] or "").split(", ") if n]
        dests = []
        for name in names:
            phone = test_phone or phones.get(name)
            if phone:
                dests.append((name, phone))
        if not dests:
            skipped.append({"doc_id": target["doc_id"], "reason": "수신자 전화번호 없음"})
            continue
        body = build_alimtalk_body(target)
        for recipient_index, (name, phone) in enumerate(dests):
            db.execute(insert_sql, {
                "cmid": _recipient_cmid(
                    target["doc_id"], recipient_index, len(dests)
                ),
                "dest_phone": phone,
                "send_phone": settings.bizppurio_send_phone,
                "dest_name": name[:32],
                "msg_body": body,
                "sender_key": settings.bizppurio_sender_key,
                "template_code": settings.bizppurio_template_code,
                "cinfo": target["doc_id"][:32],
            })
            queued += 1
        sent_docs.append(target["doc_id"])
    if sent_docs:
        names_params = {f"sent_{index}": doc for index, doc in enumerate(sent_docs)}
        in_clause = ", ".join(f"CAST(:{key} AS varchar(500))" for key in names_params)
        # 전송 기록은 알림 큐에만 남긴다 (2026-08-04 사용자 결정 —
        # payment_status.sms_sent_at은 갱신하지 않고, 재발송 방지도 큐 기준).
        # 발송된 감정서의 미처리 행을 닫아야 다음 배치가 재검토하지 않는다.
        queue_result = "알림톡 큐잉(수동)" if usr_seq else "알림톡 큐잉(자동)"
        db.execute(
            text(f"""
UPDATE dbo.a10_payment_notify
SET sent_at = GETDATE(), send_result = :queue_result
WHERE doc_id IN ({in_clause}) AND sent_at IS NULL
"""),
            {**names_params, "queue_result": queue_result},
        )
        # 미처리 행이 하나도 없던 감정서(전부 '대상 아님' 등으로 닫힌 뒤 수동 발송)는
        # 위 UPDATE가 0행이라 기록이 안 남아 중복 발송이 가능해진다 — 최신 행에 남긴다.
        db.execute(
            text(f"""
UPDATE n
SET n.sent_at = GETDATE(), n.send_result = :queue_result
FROM dbo.a10_payment_notify n
JOIN (
    SELECT doc_id, MAX(id) AS max_id FROM dbo.a10_payment_notify
    WHERE doc_id IN ({in_clause}) GROUP BY doc_id
) last ON last.max_id = n.id
WHERE NOT EXISTS (
    SELECT 1 FROM dbo.a10_payment_notify q
    WHERE q.doc_id = n.doc_id AND q.sent_at IS NOT NULL
      AND {_SENT_RESULT_SQL.replace('send_result', 'q.send_result')}
)
"""),
            {**names_params, "queue_result": queue_result},
        )
    db.commit()
    return {
        "docs_sent": len(sent_docs),
        "messages_queued": queued,
        "skipped": skipped,
        "test_mode": bool(test_phone),
        "sent_doc_ids": sent_docs,
    }


def auto_send_pending(db: Session) -> "dict[str, Any] | None":
    """배치용 — 알림 큐(a10_payment_notify)의 미처리 건을 집어 발송한다.

    큐 행은 재집계가 '누적 입금액이 늘어난 감정서'를 적재한 것(Leeilwoo 방식).
    발송 정책(입금완료 100%·약식 제외·수신자 규칙·기전송 제외)은 send_alimtalk이
    payment_status 기준으로 다시 거른다. 정책 미달 큐 행(분할입금 등)은 사유를
    남기고 닫는다 — 완납되면 재집계가 새 delta 행을 다시 넣어 그때 발송된다.
    """
    settings = get_settings()
    if not settings.payment_alert_auto_send or not settings.is_bizppurio_configured:
        return None
    # 운영 시작일 필수 — 없으면 자동발송 자체를 하지 않는다 (과거 건 오발송 방지,
    # 2026-07-31 사용자 확정: 시작일 이후 입금분만 보내고 과거 건은 절대 금지).
    try:
        start_date = date.fromisoformat(
            (settings.payment_alert_start_date or "").strip()
        )
    except ValueError:
        return None
    auto_days = int(settings.payment_alert_auto_days)
    # 운영 시작일 이전 입금 건은 발송 없이 닫는다.
    db.execute(
        text("""
UPDATE dbo.a10_payment_notify
SET sent_at = GETDATE(), send_result = N'운영 시작 전 입금 - 발송 제외'
WHERE sent_at IS NULL
  AND COALESCE(last_received_date, CAST(detected_at AS date)) < :start_date
"""),
        {"start_date": start_date},
    )
    # 알림톡은 본사(office=10) 건만 — 지사 감정서의 큐 행은 발송 없이 닫는다.
    hq_sql, hq_params = management_no_filter(docid_prefixes(db, "10"), column="doc_id")
    db.execute(
        text(f"""
UPDATE dbo.a10_payment_notify
SET sent_at = GETDATE(), send_result = N'지사 건 - 발송 대상 아님'
WHERE sent_at IS NULL AND NOT ({hq_sql})
"""),
        hq_params,
    )
    # 오래된 미처리 행은 발송 없이 닫는다 — 스위치를 켠 첫날 과거 백로그가
    # 한꺼번에 나가는 사고 방지 (fail-closed).
    db.execute(
        text("""
UPDATE dbo.a10_payment_notify
SET sent_at = GETDATE(), send_result = N'기한 경과 - 자동발송 제외'
WHERE sent_at IS NULL AND detected_at < DATEADD(day, -:days, GETDATE())
"""),
        {"days": auto_days},
    )
    db.commit()
    rows = db.execute(
        text(f"""
SELECT id, doc_id FROM dbo.a10_payment_notify
WHERE sent_at IS NULL AND ({hq_sql}) ORDER BY detected_at, id
"""),
        hq_params,
    ).mappings().all()
    if not rows:
        return {
            "docs_sent": 0, "messages_queued": 0, "skipped": [],
            "test_mode": bool(_clean_phone(settings.payment_alert_test_phone)),
            "queue_docs": 0,
        }
    # 감정서 단위로 중복 제거, 한 회차 상한은 수동 발송과 동일 (나머지는 다음 회차)
    doc_ids: "list[str]" = []
    for row in rows:
        if row["doc_id"] not in doc_ids:
            doc_ids.append(row["doc_id"])
            if len(doc_ids) >= MAX_SEND_DOCS:
                break
    result = send_alimtalk(db, doc_ids, None)
    sent = set(result.get("sent_doc_ids") or [])
    no_phone = {item["doc_id"] for item in (result.get("skipped") or [])}
    # 발송된 건의 큐 행은 send_alimtalk이 이미 닫았다 — 여기선 미발송 사유만 기록
    for doc in doc_ids:
        if doc in sent:
            continue
        reason = (
            "수신자 전화번호 없음" if doc in no_phone
            else "대상 아님(미완납·약식·기전송 등)"
        )
        db.execute(
            text("""
UPDATE dbo.a10_payment_notify SET sent_at = GETDATE(), send_result = :reason
WHERE doc_id = :doc AND sent_at IS NULL
"""),
            {"reason": reason, "doc": doc},
        )
    db.commit()
    result["queue_docs"] = len(doc_ids)
    return result


def mark_sent(db: Session, doc_ids: "list[str]", sent: bool, usr_seq: int) -> int:
    """선택 건 전송 처리(sent=True)/취소(False). 갱신된 행 수를 반환한다.

    기록은 알림 큐(a10_payment_notify)에만 남긴다 (2026-08-04 사용자 결정 —
    payment_status.sms_sent_at은 갱신하지 않음). 전송 처리는 입금완료 건의
    미처리 행만 닫는다 — 분할입금 등 미완납 건의 행을 잘못 닫으면 완납 알림이
    누락된다. 취소는 전송 계열로 닫힌 행만 되돌린다 — '대상 아님'·'기한 경과'
    등 정책 사유로 닫힌 행은 취소 대상이 아니다.
    """
    doc_ids = [doc_id.strip() for doc_id in doc_ids if doc_id and doc_id.strip()]
    if not doc_ids:
        raise PaymentSmsError("처리할 감정서번호가 없습니다.")
    if len(doc_ids) > MAX_MARK_DOCS:
        raise PaymentSmsError(f"한 번에 {MAX_MARK_DOCS}건까지만 처리할 수 있습니다.")
    names = [f"doc_{index}" for index in range(len(doc_ids))]
    in_clause = ", ".join(f"CAST(:{name} AS varchar(500))" for name in names)
    params: "dict[str, Any]" = dict(zip(names, doc_ids))
    if sent:
        result = db.execute(
            text(f"""
UPDATE n
SET n.sent_at = GETDATE(), n.send_result = N'수동 전송처리(기록만)'
FROM dbo.a10_payment_notify n
JOIN dbo.a10_payment_status p ON p.doc_id = n.doc_id
WHERE n.doc_id IN ({in_clause}) AND n.sent_at IS NULL
  AND p.pay_result = N'입금완료'
"""),
            params,
        )
    else:
        result = db.execute(
            text(f"""
UPDATE dbo.a10_payment_notify
SET sent_at = NULL, send_result = NULL
WHERE doc_id IN ({in_clause}) AND sent_at IS NOT NULL AND {_SENT_RESULT_SQL}
"""),
            params,
        )
    db.commit()
    return int(result.rowcount or 0)


RECONCILE_DAYS = 3


def reconcile_sent_from_log(db: Session, days: int = RECONCILE_DAYS) -> int:
    """발송 이력에는 있는데 큐에 '보냄' 기록이 없는 건을 채운다. 채운 행 수를 돌려준다.

    화면의 '미전송처리'는 sent_at 을 NULL 로 지운다 — 발송이 실패한 줄 알고 누르면
    실제로 나간 건이 '미처리'로 남는다 (2026-08-21: 09:17 발송 성공 뒤 09:29~09:32
    에 미전송처리 3회, 4건의 기록이 사라졌다). 재발송은 발송 이력 대조가 막지만
    화면은 계속 안 보낸 것처럼 보인다.

    지울 수 없는 이력(BIZ_LOG_YYYYMM)을 기준으로 큐를 맞춘다. 최근 며칠만 본다 —
    알림톡은 입금 직후에 나가므로 오래된 것까지 되짚을 이유가 없다.
    감정서마다 가장 최근 큐 행 하나에만 적는다.
    """
    sent = already_sent_docs_since(db, date.today() - timedelta(days=days))
    if not sent:
        return 0
    fixed = 0
    for start in range(0, len(sent), 200):   # SQL Server 파라미터 상한
        chunk = sent[start:start + 200]
        names = [f"doc_{i}" for i in range(len(chunk))]
        in_clause = ", ".join(f"CAST(:{n} AS varchar(500))" for n in names)
        result = db.execute(
            text(f"""
UPDATE n
SET n.sent_at = GETDATE(), n.send_result = N'발송 이력 확인(자동)'
FROM dbo.a10_payment_notify n
JOIN (
    SELECT doc_id, MAX(id) AS max_id FROM dbo.a10_payment_notify
    WHERE doc_id IN ({in_clause}) GROUP BY doc_id
) last ON last.max_id = n.id
WHERE NOT EXISTS (
    SELECT 1 FROM dbo.a10_payment_notify q
    WHERE q.doc_id = n.doc_id AND q.sent_at IS NOT NULL
      AND {_SENT_RESULT_SQL.replace('send_result', 'q.send_result')}
)
"""),
            dict(zip(names, chunk)),
        )
        fixed += int(result.rowcount or 0)
    db.commit()
    return fixed
