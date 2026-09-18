"""수수료 배분 초안 생성·승인 — Apw_Mae_GaPrice 반영.

초안 규칙 (재무팀 확인, 2026-07-21 / 완납 게이트 2026-09-01):
- 대상: **완납된**(a10_payment_status.pay_result = 입금완료) 감정서 중 GaPrice에
  아직 입금 행이 없는 건. 원래는 입금이 한 푼이라도 확인되면 만들었는데,
  대주단(감정서 하나·거래처 여럿)은 몇 주에 걸쳐 나눠 들어와 첫 입금에 전액
  배분 초안이 떴다(실측 미완납 등재 10건). 2026-09-01 사용자 결정: 다 들어올
  때까지 보류, 완납되면 그때 표시. 미완납인데 대기 중인 초안은 생성 때마다
  거둬들인다 — 완납되면 다음 생성에서 완납일 기준 in_date로 다시 만들어진다.
- 담당자·비율: APW_Charge_IDX의 iType=1 (Names/USR_SEQs/Ratios, 쉼표 구분)
- In_Price = 순수수료 × 비율. Basic_Susu도 같은 배분.
  순수수료 = 기초수수료 − 절사금액 (재무팀 실적인정금액 기준, 2026-08-03 Mae.xls
  7/30 입금 11건 대조로 확정 — 절사금액은 수수료합계를 천원 단위로 맞추는 끝수)
- 승인 시 GaPrice에 새 행 INSERT (Seq는 identity). 기존 0원 선등록 행은 무시

in_date(재무팀 화면의 기본 조회 기준) 규칙 (재무팀 확인, 2026-08-19):
- 원래는 입금일(a10_payment_status.paid_date) 그대로 썼는데, 착수금(선수금)으로
  받아둔 돈은 입금일과 매출 인식일이 몇 주씩 벌어진다(01-2608-A-0117 실례:
  입금 8/7, 완료·매출전환 8/18). 재무팀은 결재를 "그날 매출로 잡힌 것" 기준으로
  매일 돌리므로, 입금일로 남으면 전환된 날 결재 목록에 영영 안 뜬다.
- 그래서 아마란스 매출 계정(401xxxx, a10_voucher_cache) 전표가 있으면 전표일자를
  in_date로 쓰고, 매출 전표가 아직 없으면 그대로 입금일을 쓴다. 대상 건을
  정하는 조건(WHERE 절 — 입금일 하한 포함)은 그대로 둔다 — 입금일 백로그를
  막는 하한(DRAFT_MIN_PAID_DATE)까지 매출전표 날짜로 바꾸면, 외상거래처럼
  전표일자가 입금일보다 훨씬 이른 건이 하한에 걸려 조용히 빠질 수 있다.
  in_date는 화면에 보여줄 값만 바뀌는 것이지 대상 선정 기준이 아니다.
- 전표일자는 처음엔 MIN(가장 이른 것)이었는데 2026-09-01 완납 게이트와 함께
  **max(마지막 매출 전표일, 입금일)** 로 바꿨다. 완납돼야 초안이 생기므로
  "결재 가능해진 날"이 in_date여야 재무팀 일일 결재(기본 조회 기간)에 잡힌다 —
  대주단을 첫 전표일로 두면 완납 시점엔 몇 주 전 날짜라 목록 창 밖으로 밀린다.
- 실측으로 확인한 두 갈래: ① 착수금(선수금) → 나중에 매출 전환(이번 계기,
  전표일자가 입금일보다 늦다) ② 외상매출 → 나중에 정산 입금(전표일자가
  입금일보다 이르다, 예: 01-2606-4-0228 전표 7/7 vs 입금 8/14). 둘 다
  "매출로 잡힌 날"이 입금일과 다르다는 점은 같아서 같은 로직으로 잡힌다.
- 실측 계기: 같은 건에 8/14·8/18 두 번 "선수금→매출" 전표가 잡혀 있던 걸
  발견했다(재무팀 확인 후 8/14자 취소). 취소된 전표는 아마란스 동기화가
  캐시에서 지운다(voucher_cache_sync — 삭제돼도 신호가 없어 새 목록과
  대조해서 없어진 것만 걷어낸다). MIN(전표일자)은 정상 상태에서 매출 전표가
  하나뿐일 때를 위한 것일 뿐, 취소 안 된 중복이 남아 있는 동안엔 이 값도
  같이 틀리게 나온다 — 중복 자체는 재무팀이 아마란스에서 지워야 한다.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.gaprice_outbox import GapriceOutbox
from app.services.office_lookup import docid_prefixes

# 초안 생성 시작일 — 과거 미갱신분(1.4만 건)을 쏟아내지 않기 위한 하한.
DRAFT_MIN_PAID_DATE = date(2026, 1, 1)


def base_fee_sql(alias: str = "") -> str:
    """배분 기준액(실적인정금액) = 기초수수료 − 절사금액. 단 절사가 기초수수료 이상이면 절사를 무시한다.

    절사는 수수료합계를 천 원 단위로 맞추는 끝수다(전체 47만 건이 1,000원 미만). 그런데 최종 금액을
    절사 칸에 적은 오입력이 46건 있어(절사 = 수수료합계) 실적인정금액이 0 이하가 되고 배분에서 빠졌다
    (01-2604-7-0036: 기초 81,648,700 − 절사 95,100,000 = −13,451,300). 끝수 차감은 그대로 두고
    오입력만 걸러낸다 (2026-09-14 사용자 선택). 상여·데이터 품질 점검은 아직 옛 식이다.
    """
    t = f"{alias}." if alias else ""
    return (f"CASE WHEN ISNULL({t}[절사금액], 0) >= {t}[기초수수료] THEN {t}[기초수수료] "
            f"ELSE {t}[기초수수료] - ISNULL({t}[절사금액], 0) END")


def _source_database() -> str:
    database = get_settings().mssql_source_db
    if not database.replace("_", "").isalnum():
        raise RuntimeError("MSSQL_SOURCE_DB 이름이 올바르지 않습니다.")
    return database


def generate_gaprice_drafts(db: Session) -> int:
    """입금 확인 건의 배분 초안을 PENDING으로 적재한다. 이미 초안이 있으면 건너뜀.

    배분 승인은 본사 감정서만 해당한다 (2026-07-21 사용자 확인) — 접두사 필터.
    감정서번호는 표준형(01-2604-…) 외에 대시 없는 변형(012604-…-1, 재발행/사본)도
    있어 둘 다 잡는다 (2026-07-27 매출입력 화면에서 변형 누락 확인).
    """
    database = _source_database()
    prefix = (docid_prefixes(db, "10") or ["01"])[0]
    hq_dashed = prefix + "-%"
    hq_dashless = prefix + "[0-9]%"  # SQL Server LIKE 문자클래스
    # 미완납으로 남았거나 미완납으로 되돌아간 건의 대기 초안은 거둬들인다
    # (2026-09-01 사용자 결정 ②: 완납되면 그때 보여준다). 승인 이력이 전혀 없는
    # 행만 지운다 — 승인 취소로 PENDING 이 된 행의 수정값을 지키기 위해서인데,
    # 취소가 이력 칸을 비우므로 완전하지는 않다. 게이트 이후로는 승인 자체가
    # 완납 건에서만 일어나 이 경로가 실제로 밟힐 일은 드물다.
    db.execute(
        text(
            "DELETE o FROM dbo.a10_gaprice_outbox o "
            "LEFT JOIN dbo.a10_payment_status p ON p.doc_id = o.doc_id "
            "WHERE o.status = 'PENDING' AND o.applied_ga_seq IS NULL "
            "  AND o.approved_by IS NULL "
            "  AND (p.doc_id IS NULL OR ISNULL(p.pay_result, N'') <> N'입금완료' "
            # 실비 종결 건도 회수 — 순수수료 전액 기준 초안이 뜨면 안 된다.
            # 해제되면 다음 생성에서 (완납 조건 충족 시) 다시 만들어진다.
            "       OR EXISTS (SELECT 1 FROM dbo.a10_expense_close ec "
            "                  WHERE ec.doc_id = o.doc_id AND ec.released_at IS NULL))"
        )
    )
    candidates = db.execute(
        text(
            f"""
            WITH revenue AS (
                SELECT management_no AS doc_id, MAX(voucher_date) AS voucher_date
                FROM dbo.a10_voucher_cache
                WHERE account_code LIKE '401%'
                GROUP BY management_no
            )
            SELECT p.doc_id,
                   CASE WHEN r.voucher_date IS NULL OR p.paid_date > r.voucher_date
                        THEN p.paid_date ELSE r.voucher_date END AS in_date,
                   m.Masterid AS masterid,
                   {base_fee_sql('x')} AS base_fee,
                   x.price AS appraisal_amount,
                   c.Names AS names, c.USR_SEQs AS usr_seqs, c.Ratios AS ratios
            FROM dbo.a10_payment_status p
            JOIN [{database}].dbo.APW_Master m ON m.DocID = p.doc_id
            JOIN [{database}].dbo.apw_masterex x ON x.DocID = p.doc_id
            JOIN [{database}].dbo.APW_Charge_IDX c
              ON c.MasterID = m.Masterid AND c.iType = 1
            LEFT JOIN revenue r ON r.doc_id = p.doc_id
            WHERE (p.doc_id LIKE CAST(:hq_dashed AS varchar(500))
                   OR p.doc_id LIKE CAST(:hq_dashless AS varchar(500)))
              AND p.pay_result = N'입금완료'
              -- 실비 종결 건 제외 — 실비만 받고 끝난 건에 순수수료 전액 배분
              -- 초안이 뜨면 안 된다. 필요한 예외는 재무팀이 수기로 처리한다.
              AND NOT EXISTS (
                  SELECT 1 FROM dbo.a10_expense_close ec
                  WHERE ec.doc_id = p.doc_id AND ec.released_at IS NULL
              )
              AND p.paid_date >= :min_paid_date
              AND {base_fee_sql('x')} > 0
              AND NOT EXISTS (
                  SELECT 1 FROM [{database}].dbo.Apw_Mae_GaPrice g
                  WHERE RTRIM(g.Docid) = p.doc_id AND g.In_Price > 0
              )
              AND NOT EXISTS (
                  SELECT 1 FROM dbo.a10_gaprice_outbox o WHERE o.doc_id = p.doc_id
              )
            """
        ),
        {"min_paid_date": DRAFT_MIN_PAID_DATE, "hq_dashed": hq_dashed, "hq_dashless": hq_dashless},
    ).mappings().all()

    created = 0
    for row in candidates:
        drafts = _split_rows(row)
        if not drafts:
            continue
        db.add_all(drafts)
        created += len(drafts)
    db.commit()
    return created


def _split_rows(row: Any) -> "list[GapriceOutbox]":
    """Charge_IDX의 쉼표 목록을 담당자별 초안 행으로 만든다. 형식이 깨졌으면 빈 목록."""
    names = [name.strip() for name in str(row["names"] or "").split(",") if name.strip()]
    seqs = [seq.strip() for seq in str(row["usr_seqs"] or "").split(",")]
    ratios = [ratio.strip() for ratio in str(row["ratios"] or "").split(",")]
    if not names:
        return []
    if len(ratios) != len(names):
        # 비율이 없거나 개수가 어긋나면 균등 배분으로 초안을 만든다 (승인 화면에서 수정).
        ratios = [str(round(100 / len(names), 2))] * len(names)
    base_fee = Decimal(str(row["base_fee"] or 0))
    # 비율 합이 100을 넘으면 퍼센트가 아니라 상대 비중이다 — 공동유치 '100,100' 은 50%·50%
    # (2026-09-14 사용자). 합이 100 이하면 적힌 그대로 둔다: 혼자 '50' 은 절반만 우리 몫인
    # 공동유치 관행이라 100% 로 부풀리면 안 된다.
    parsed = []
    for index, name in enumerate(names):
        try:
            parsed.append(Decimal(ratios[index]))
        except Exception:
            parsed.append(Decimal(0))
    total_ratio = sum(parsed)
    divisor = total_ratio if total_ratio > 100 else Decimal(100)
    result = []
    for index, name in enumerate(names):
        ratio = (parsed[index] * 100 / total_ratio).quantize(Decimal("0.01")) if divisor != 100 else parsed[index]
        share = (base_fee * parsed[index] / divisor).quantize(Decimal("1"))
        result.append(
            GapriceOutbox(
                doc_id=row["doc_id"],
                masterid=int(row["masterid"]),
                manager=name[:30],
                usr_seq=int(seqs[index]) if index < len(seqs) and seqs[index].isdigit() else None,
                ratio=ratio,
                # 관찰된 기존 데이터 관행: 평가액은 단독 배분일 때만 채워져 있다.
                pung_price=Decimal(str(row["appraisal_amount"] or 0)) if len(names) == 1 else None,
                basic_susu=share,
                in_price=share,
                in_date=row["in_date"],
            )
        )
    return result


def list_outbox(
    db: Session,
    status: str = "PENDING",
    date_from: "date | None" = None,
    date_to: "date | None" = None,
    doc_id: "str | None" = None,
    manager: "str | None" = None,
    office_code: "str | None" = None,
    scope_person: "str | None" = None,
) -> "list[dict[str, Any]]":
    """감정서 단위로 묶은 승인 대기 목록 (거래처명·순수수료는 원본 뷰에서 보강).

    doc_id·manager는 부분 일치 검색. 유치자 검색은 공동 배분 건의 화면 묶음이
    깨지지 않도록 행이 아니라 감정서 단위로 거른다 (한 명이라도 일치하면 전체 표시).
    office_code·scope_person은 권한 범위 제한(지사/유치자 격리)이며 감정서 단위로 거른다.
    """
    query = (
        select(GapriceOutbox)
        .where(GapriceOutbox.status == status)
        .order_by(GapriceOutbox.in_date.desc(), GapriceOutbox.doc_id.desc(), GapriceOutbox.id)
    )
    if date_from:
        query = query.where(GapriceOutbox.in_date >= date_from)
    if date_to:
        query = query.where(GapriceOutbox.in_date <= date_to)
    if office_code:
        # 권한 범위: 지정 지사 접두사(01-…) 감정서만. 매핑이 없으면 빈 목록.
        prefixes = docid_prefixes(db, office_code)
        if not prefixes:
            return []
        query = query.where(
            or_(*[GapriceOutbox.doc_id.startswith(f"{prefix}-") for prefix in prefixes])
        )
    if scope_person:
        # 권한 범위: 다른 직원 조회 권한이 없으면 본인이 유치자인 감정서만 (감정서 단위).
        own_docs = select(GapriceOutbox.doc_id).where(
            GapriceOutbox.status == status,
            GapriceOutbox.manager == scope_person,
        )
        query = query.where(GapriceOutbox.doc_id.in_(own_docs))
    if doc_id and doc_id.strip():
        query = query.where(GapriceOutbox.doc_id.contains(doc_id.strip(), autoescape=True))
    if manager and manager.strip():
        matched_docs = select(GapriceOutbox.doc_id).where(
            GapriceOutbox.status == status,
            GapriceOutbox.manager.contains(manager.strip(), autoescape=True),
        )
        query = query.where(GapriceOutbox.doc_id.in_(matched_docs))
    rows = db.scalars(query).all()
    if not rows:
        return []
    database = _source_database()
    doc_ids = list(dict.fromkeys(row.doc_id for row in rows))
    meta: dict[str, Any] = {}
    paid: dict[str, float] = {}
    approvers: dict[int, str] = {}
    for start in range(0, len(doc_ids), 500):
        chunk = doc_ids[start:start + 500]
        names = [f"doc_{index}" for index in range(len(chunk))]
        params = {name: chunk[index] for index, name in enumerate(names)}
        for m in db.execute(
            text(
                f"SELECT DocID, CustName, "
                f"{base_fee_sql()} AS base_fee "
                f"FROM [{database}].dbo.apw_masterex "
                f"WHERE DocID IN ({','.join(':' + name for name in names)})"
            ),
            params,
        ).mappings():
            meta[m["DocID"]] = m
        # 실입금액(전표 집계 기준) — CAST는 NVARCHAR 바인드로 인한 풀스캔 방지
        placeholders = ",".join(f"CAST(:{name} AS varchar(50))" for name in names)
        for p in db.execute(
            text(
                f"SELECT doc_id, paid_amount FROM dbo.a10_payment_status "
                f"WHERE doc_id IN ({placeholders})"
            ),
            params,
        ).mappings():
            paid[p["doc_id"]] = float(p["paid_amount"] or 0)

    approver_ids = sorted(
        {int(row.approved_by) for row in rows if row.approved_by is not None}
    )
    for start in range(0, len(approver_ids), 500):
        chunk = approver_ids[start:start + 500]
        names = [f"approver_{index}" for index in range(len(chunk))]
        params = {name: chunk[index] for index, name in enumerate(names)}
        for employee in db.execute(
            text(
                f"SELECT USR_SEQ AS usr_seq, RTRIM(EMP) AS emp_name "
                f"FROM [{database}].dbo.TMWCMN_USR_BAC_INFO "
                f"WHERE USR_SEQ IN ({','.join(':' + name for name in names)})"
            ),
            params,
        ).mappings():
            approvers[int(employee["usr_seq"])] = str(employee["emp_name"] or "").strip()

    return _group_outbox_rows(rows, meta, paid, approvers)


def _group_outbox_rows(
    rows: "list[GapriceOutbox]",
    meta: "dict[str, Any]",
    paid: "dict[str, float]",
    approvers: "dict[int, str]",
) -> "list[dict[str, Any]]":
    """목록 행을 감정서 단위로 묶고 승인 이력을 함께 직렬화한다."""
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        approved_by = int(row.approved_by) if row.approved_by is not None else None
        group = grouped.setdefault(
            row.doc_id,
            {
                "doc_id": row.doc_id,
                "in_date": row.in_date.isoformat() if row.in_date else None,
                "customer_name": (meta.get(row.doc_id) or {}).get("CustName"),
                "base_fee": float((meta.get(row.doc_id) or {}).get("base_fee") or 0),
                "paid_amount": paid.get(row.doc_id),
                "status": row.status,
                "approved_by": approved_by,
                "approved_by_name": approvers.get(approved_by, "") if approved_by else "",
                "approved_at": (
                    row.approved_at.isoformat(timespec="seconds")
                    if row.approved_at else None
                ),
                "rows": [],
            },
        )
        group["rows"].append(
            {
                "id": row.id,
                "manager": row.manager,
                "usr_seq": row.usr_seq,
                "ratio": float(row.ratio or 0),
                "in_price": float(row.in_price),
                "basic_susu": float(row.basic_susu or 0),
                "applied_ga_seq": row.applied_ga_seq,
            }
        )
    return list(grouped.values())


def search_employees(db: Session, keyword: str, limit: int = 20) -> "list[dict[str, Any]]":
    """담당자 추가용 재직자 검색 (이름 부분 일치). CAST는 NVARCHAR 풀스캔 방지."""
    database = _source_database()
    rows = db.execute(
        text(
            f"""
            SELECT TOP {int(limit)}
                USR_SEQ AS usr_seq, RTRIM(EMP) AS emp_name, RTRIM(OFFICE_ID) AS office_id
            FROM [{database}].dbo.TMWCMN_USR_BAC_INFO
            WHERE USE_YN = 'Y' AND RTRM_FL = '0'
              AND EMP LIKE CAST(:pattern AS varchar(60))
            ORDER BY EMP
            """
        ),
        {"pattern": f"%{keyword.strip()}%"},
    ).mappings().all()
    return [dict(row) for row in rows]


class GapriceApprovalError(ValueError):
    pass


def approve(
    db: Session,
    doc_id: str,
    row_amounts: "dict[int, dict[str, Any]]",
    approved_by: int,
    new_rows: "list[dict[str, Any]] | None" = None,
) -> "list[int]":
    """PENDING 초안을 GaPrice에 INSERT하고 APPROVED로 마킹한다.

    row_amounts: {outbox_id: {"in_price": ..., "basic_susu": ..., "ratio": ...}} — 화면 수정분.
    new_rows: 화면에서 추가한 담당자 [{"manager", "usr_seq", "ratio", "in_price", "basic_susu"}].
    비율·담당자 변경은 이번 배분(GaPrice)에만 반영하고 원본 APW_Charge_IDX는 건드리지 않는다
    (2026-07-22 사용자 결정).
    """
    seqs = _apply_approval(db, doc_id, row_amounts, approved_by, new_rows or [])
    db.commit()
    return seqs


def _new_outbox_rows(
    template: GapriceOutbox, new_rows: "list[dict[str, Any]]"
) -> "list[GapriceOutbox]":
    """추가 담당자 입력을 기존 초안 행(template)의 감정서 정보로 outbox 행으로 만든다."""
    result = []
    for item in new_rows:
        manager = str(item.get("manager") or "").strip()
        if not manager:
            raise GapriceApprovalError("추가한 담당자의 이름이 비어 있습니다.")
        in_price = Decimal(str(item.get("in_price", 0)))
        basic_susu = Decimal(str(item.get("basic_susu", 0)))
        if in_price < 0 or basic_susu < 0:
            raise GapriceApprovalError("금액은 0 이상이어야 합니다.")
        usr_seq = item.get("usr_seq")
        result.append(
            GapriceOutbox(
                doc_id=template.doc_id,
                masterid=template.masterid,
                manager=manager[:30],
                usr_seq=int(usr_seq) if usr_seq is not None else None,
                ratio=Decimal(str(item.get("ratio", 0))),
                pung_price=None,
                basic_susu=basic_susu,
                in_price=in_price,
                in_date=template.in_date,
            )
        )
    return result


def _apply_approval(
    db: Session,
    doc_id: str,
    row_amounts: "dict[int, dict[str, Any]]",
    approved_by: int,
    new_rows: "list[dict[str, Any]]",
) -> "list[int]":
    rows = db.scalars(
        select(GapriceOutbox).where(
            GapriceOutbox.doc_id == doc_id, GapriceOutbox.status == "PENDING"
        )
    ).all()
    if not rows:
        raise GapriceApprovalError("승인 대기 중인 초안이 없습니다.")
    if new_rows:
        added = _new_outbox_rows(rows[0], new_rows)
        db.add_all(added)
        rows = list(rows) + added
    database = _source_database()
    inserted: "list[int]" = []
    for row in rows:
        override = row_amounts.get(row.id, {}) if row.id is not None else {}
        in_price = Decimal(str(override.get("in_price", row.in_price)))
        basic_susu = Decimal(str(override.get("basic_susu", row.basic_susu or 0)))
        if in_price < 0 or basic_susu < 0:
            raise GapriceApprovalError("금액은 0 이상이어야 합니다.")
        if override.get("ratio") is not None:
            row.ratio = Decimal(str(override["ratio"]))
        seq = db.execute(
            text(
                f"""
                INSERT INTO [{database}].dbo.Apw_Mae_GaPrice
                    (Docid, Masterid, Pung_Price, Basic_Susu, In_Price, Manager, In_Date, Bigo)
                OUTPUT INSERTED.Seq
                VALUES (:doc_id, :masterid, :pung_price, :basic_susu, :in_price,
                        :manager, :in_date, '')
                """
            ),
            {
                "doc_id": row.doc_id,
                "masterid": row.masterid,
                "pung_price": row.pung_price,
                "basic_susu": basic_susu,
                "in_price": in_price,
                "manager": row.manager,
                "in_date": row.in_date,
            },
        ).scalar_one()
        row.in_price = in_price
        row.basic_susu = basic_susu
        row.status = "APPROVED"
        row.approved_by = approved_by
        row.approved_at = datetime.now()
        row.applied_ga_seq = int(seq)
        inserted.append(int(seq))
    return inserted


def reject(db: Session, doc_id: str, approved_by: int) -> int:
    rows = db.scalars(
        select(GapriceOutbox).where(
            GapriceOutbox.doc_id == doc_id, GapriceOutbox.status == "PENDING"
        )
    ).all()
    if not rows:
        raise GapriceApprovalError("승인 대기 중인 초안이 없습니다.")
    for row in rows:
        row.status = "REJECTED"
        row.approved_by = approved_by
        row.approved_at = datetime.now()
    db.commit()
    return len(rows)


def cancel_approval(db: Session, doc_id: str, approved_by: int) -> "dict[str, int]":
    """승인을 되돌린다 — 원장(Apw_Mae_GaPrice)에서 지우고 초안을 PENDING 으로 돌린다.

    2026-08-21 사용자 결정: 원장에서 실제로 지운다(상쇄 행을 넣지 않는다).
    권한은 승인과 같다 — 본사 재무팀·집행부(라우터에서 검사).

    지울 행은 승인할 때 적어 둔 applied_ga_seq 로 찾는다. 다만 Seq 하나만 믿고
    지우면 그 번호가 다른 감정서 행으로 바뀌어 있을 때 남의 실적을 지운다.
    그래서 **Docid 까지 같을 때만** 지운다. 이미 손으로 지워져 0행이면 그대로
    두고 넘어간다 — '원장에 없다'는 목표는 이미 이뤄진 것이라 막을 이유가 없다.

    승인할 때 화면에서 추가한 담당자 행도 함께 PENDING 으로 돌아간다. 그때 고친
    비율·금액은 행에 남아 있어, 다시 승인하면 고친 값 그대로 들어간다.
    """
    rows = db.scalars(
        select(GapriceOutbox).where(
            GapriceOutbox.doc_id == doc_id, GapriceOutbox.status == "APPROVED"
        )
    ).all()
    if not rows:
        raise GapriceApprovalError("승인된 배분이 없습니다.")
    database = _source_database()
    deleted = 0
    for row in rows:
        if row.applied_ga_seq is not None:
            result = db.execute(
                text(
                    f"""
                    DELETE FROM [{database}].dbo.Apw_Mae_GaPrice
                    WHERE Seq = :seq AND Docid = :doc_id
                    """
                ),
                {"seq": int(row.applied_ga_seq), "doc_id": row.doc_id},
            )
            deleted += int(result.rowcount or 0)
        row.status = "PENDING"
        row.applied_ga_seq = None
        row.approved_by = None
        row.approved_at = None
    db.commit()
    return {"rows": len(rows), "deleted": deleted}
