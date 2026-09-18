"""세금계산서 일괄 발급 (2026-08-27 사용자 요청) — 입금된 건을 골라 한 번에 팝빌 발행.

탭 셋 (kind):
  general   일반     감정서 하나 · 거래처 하나 (매출 전표 401 계열의 거래처가 한 곳)
  syndicate 대주단   감정서 하나 · 거래처 여럿 → (감정서, 거래처) 행마다 1장, 금액은 그 거래처 전표 공급가
                    (TAMS 관행: 01-2607-2-0092 새마을금고 23곳에 각각 2,340,091×1.1)
  kb        국민약식 400으로 시작하는 의뢰번호 → 번호마다 국민은행 지점 앞 1장 (TAMS 관행 그대로).
            금액은 **조회기간 안의 매출 전표 합계** (2026-09-10 사용자 확정: 27일만 고르면 그날
            2,200, 27~31일이면 2,200+78,000). 같은 번호에 매출이 여러 날 잡히는 400580642 실측.
            같은 기간에 발행된 계산서(작성일자 기준)는 빼서 두 번 안 나가게 한다.

사용자 확정: 대상은 입금된 건(부분입금·완납 모두, 조회조건으로 가름), 작성일자 = 입금일,
목적 '영수', 담당자 이메일이 없으면 DEFAULT_EMAIL. 발행 여부는 TAMS 캐시 + MOA 원장
(입금현황·감정서 LIST 의 '발행' 칸과 같은 원천). 금액 기본값은 완납이면 청구액, 부분입금이면
입금액(둘 다 부가세 포함 → 공급가·세액으로 역산). 화면에서 행마다 고칠 수 있다.

2026-09-02 재무팀 규칙: 계산서는 입금된 만큼만 — 같은 거래처 앞 기발행 몫을 빼고
발급한다. 실측 400580103: 완납 55,000 중 2,200 은 8/12 TAMS 선발행 → 이번엔 52,800 만.
일반·국민약식에 적용, 대주단은 거래처별 전표 정액이라 종전 그대로(합계 일치 판정).
"""

from datetime import date
from typing import Any, Callable

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.services import popbill_tax
from app.services.office_lookup import docid_prefixes, get_office
from app.services.receivables import card_sales_docs, card_sales_sql, management_no_filter  # noqa: F401 — 테스트·호환

KINDS = ("general", "syndicate", "kb")
PAY_STATUSES = ("전체", "완납", "부분입금")
DEFAULT_EMAIL = 'contact@example.com'   # 담당자 이메일이 없을 때 (2026-08-27 사용자 지정)
MAX_DAYS = 92
MAX_ROWS = 500
MAX_ISSUE = 50
_CHUNK = 400
_PURPOSE = "영수"


class TaxBulkError(ValueError):
    pass


# ── 순수 계산 ──────────────────────────────────────────────────────────────


def split_vat(total: float) -> "tuple[int, int]":
    """부가세 포함 금액 → (공급가, 세액). 단건 팝업(appraisal_tax_draft)과 같은 역산."""
    amount = int(round(float(total or 0)))
    supply = int(round(amount / 1.1))
    return supply, amount - supply


def vat_of(supply: float) -> int:
    return int(round(float(supply or 0) * 0.1))


def pay_status_of(billed: float, received: float, outstanding: float) -> str:
    """요약 캐시 기준 — 미수가 남았으면 부분입금, 아니면 완납 (입금된 건만 들어온다)."""
    return "부분입금" if float(outstanding or 0) > 0 or float(received or 0) < float(billed or 0) else "완납"


def default_amount(pay_status: str, billed: float, received: float) -> float:
    """완납은 청구액, 부분입금은 받은 만큼(영수 계산서) — 둘 다 부가세 포함 금액."""
    return float(billed or 0) if pay_status == "완납" else float(received or 0)


def syndicate_mgt_key(doc_id: str, seq: int) -> str:
    """대주단은 감정서 하나에 여러 장 → 팝빌 관리번호(회사 내 유일, 24자 제한)를 -L{n} 으로 나눈다."""
    return f"{doc_id}-L{int(seq)}"


def item_name_for(kind: str, doc_id: str) -> str:
    return (f"약식평가수수료 {doc_id}" if kind == "kb" else f"감정평가수수료 {doc_id}")[:100]


def digits(value: Any) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def row_key(kind: str, doc_id: str, tr_cd: str) -> str:
    return f"{kind}|{doc_id}|{tr_cd}"


# ── 후보 목록 ──────────────────────────────────────────────────────────────


def _chunked(values: "list[str]") -> "list[list[str]]":
    return [values[i:i + _CHUNK] for i in range(0, len(values), _CHUNK)]


def _in_params(prefix: str, values: "list[str]") -> "tuple[str, dict[str, Any]]":
    names = [f"{prefix}_{i}" for i in range(len(values))]
    return ",".join(f"CAST(:{n} AS VARCHAR(100))" for n in names), {n: values[i] for i, n in enumerate(names)}


def candidate_docs_sql(kind: str, *, division_code: "str | None", prefix_sql: str) -> str:
    """입금된 감정서(요약 캐시) — 일반·대주단(지사 접두사). 국민약식은 kb_period_sql 이 전표에서 뽑는다."""
    if kind == "kb":
        raise TaxBulkError("국민약식은 kb_period_sql 을 쓴다.")
    return f"""
        SELECT b.doc_id, b.billed_amount, b.received_amount, b.outstanding_amount, b.last_received_date,
               m.CustName AS customer_name, m.Manager AS manager, m.LWorkinfo AS purpose
        FROM dbo.a10_receivable_summary b
        LEFT JOIN {popbill_tax_source_view()} m ON m.DocID = b.doc_id
        WHERE {prefix_sql} AND b.received_amount > 0
          AND b.last_received_date >= :date_from AND b.last_received_date < DATEADD(day, 1, :date_to)
        ORDER BY b.last_received_date DESC, b.doc_id DESC
    """


def kb_period_sql(division_code: "str | None") -> str:
    """국민약식 — 조회기간 안의 매출(401 계열) 전표를 (의뢰번호, 거래처)로 묶은 공급가 합계.

    요약 캐시의 '마지막 입금일'로 고르면 같은 번호에 매출이 두 번 잡힌 건(400580642:
    8/27 2,000 + 8/31 78,000)이 앞 날짜 조회에서 빠진다 — 전표대로 기간 합계를 낸다
    (2026-09-10). 입금 상태 표시용으로 요약 캐시는 곁들이기만 한다.
    """
    division = "AND v.division_code = :division " if division_code else ""
    return f"""
        SELECT v.management_no AS doc_id, ISNULL(RTRIM(v.partner_code), '') AS tr_cd,
               MAX(v.partner_name) AS partner_name,
               SUM(CASE WHEN v.debit_credit = '4' THEN v.amount ELSE -v.amount END) AS supply,
               MAX(v.voucher_date) AS last_date,
               MAX(b.billed_amount) AS billed_amount, MAX(b.received_amount) AS received_amount,
               MAX(b.outstanding_amount) AS outstanding_amount, MAX(b.last_received_date) AS last_received_date
        FROM dbo.a10_voucher_cache v
        LEFT JOIN dbo.a10_receivable_summary b ON b.doc_id = v.management_no
        WHERE v.management_no LIKE '400%' AND v.account_code LIKE '401%' {division}
          AND v.voucher_date >= :date_from AND v.voucher_date < DATEADD(day, 1, :date_to)
        GROUP BY v.management_no, ISNULL(RTRIM(v.partner_code), '')
        HAVING SUM(CASE WHEN v.debit_credit = '4' THEN v.amount ELSE -v.amount END) > 0
        ORDER BY MAX(v.voucher_date) DESC, v.management_no DESC
    """


def popbill_tax_source_view() -> str:
    from app.services.receivables import _source_view
    return _source_view()


def partner_lines_sql(placeholders: str) -> str:
    """감정서별 매출(401 계열) 거래처와 공급가 — 대주단은 거래처마다 한 장이라 거래처 단위로 묶는다."""
    return f"""
        SELECT v.management_no AS doc_id, RTRIM(v.partner_code) AS tr_cd, MAX(v.partner_name) AS partner_name,
               SUM(CASE WHEN v.debit_credit = '4' THEN v.amount ELSE -v.amount END) AS supply,
               MAX(v.voucher_date) AS last_date
        FROM dbo.a10_voucher_cache v
        WHERE v.account_code LIKE '401%' AND v.management_no IN ({placeholders})
          AND v.partner_code IS NOT NULL AND RTRIM(v.partner_code) <> ''
        GROUP BY v.management_no, RTRIM(v.partner_code)
    """


def issued_sql(placeholders: str) -> str:
    """발행 이력 — 발급 원장(is_test=0) 하나. 출처(source)는 MOA팝빌·팝빌동기화·TAMS.

    기발행 몫을 거래처별 '합계'로 차감하므로(2026-09-02 입금된 만큼만 발급 규칙)
    변형번호(사본발급류) 몫과, TAMS 대장에도 적힌 MOA 발행의 중복은 여기서
    걸러야 과차감이 없다 — 감정서 LIST 계산서 합계와 같은 공용 가드를 쓴다.
    """
    from app.services.receivables import _variant_doc_invoice_guard
    return f"""
        -- 발급 원장 하나로 본다 (2026-09-09): MOA 팝빌·팝빌 동기화·TAMS 이관분, 출처는 source.
        -- 세금취소는 음수 행, 현금취소는 양수 취소금액이라 부호를 맞춰 더한다 —
        -- 끊었다 취소한 몫이 상계되고(01-2606-1-0388), 현금영수증으로 나간 몫도 기발행이다.
        SELECT i.doc_id, ISNULL(i.receiver_corp_num, '') AS corp_num, ISNULL(i.receiver_name, '') AS corp_name,
               i.source,
               ISNULL(CONVERT(varchar(8), i.write_date, 112), LEFT(ISNULL(i.issue_dt, ''), 8)) AS issued_date,
               CASE WHEN i.doc_type = N'현금취소'
                    THEN -ABS(CAST(ISNULL(i.total, ISNULL(i.supply_cost, 0) + ISNULL(i.tax, 0)) AS float))
                    ELSE CAST(ISNULL(i.total, ISNULL(i.supply_cost, 0) + ISNULL(i.tax, 0)) AS float) END AS issued_total
        FROM dbo.a10_issued_taxinvoice i
        WHERE i.doc_id IN ({placeholders}) AND i.is_test = 0 AND i.is_pool = 0
          AND {_variant_doc_invoice_guard("i.doc_id", "i.total")}
    """


CARD_SALES_NOTE = "카드매출(계산서 불필요)"


def _mark_card_sales(items: "list[dict[str, Any]]", card_docs: "set[str]") -> "list[dict[str, Any]]":
    """카드매출 건은 '발행 불필요'로 — 미발행만 보기에서 빠지고, 전체 보기에서는 사유가 보인다."""
    if not card_docs:
        return items
    return [
        _finish({**item, "issued": True, "issued_note": CARD_SALES_NOTE}) if item["doc_id"] in card_docs else item
        for item in items
    ]


def partner_cache_sql(placeholders: str) -> str:
    return f"SELECT partner_code, reg_no, partner_name FROM dbo.a10_partner_cache WHERE partner_code IN ({placeholders})"


def _rows(db: Session, sql_builder: Callable[[str], str], prefix: str, values: "list[str]") -> "list[dict[str, Any]]":
    result: "list[dict[str, Any]]" = []
    for chunk in _chunked(values):
        placeholders, params = _in_params(prefix, chunk)
        result.extend(dict(r) for r in db.execute(text(sql_builder(placeholders)), params).mappings().all())
    return result


def _normalize_name(value: Any) -> str:
    return "".join(str(value or "").split()).replace("(주)", "").replace("주식회사", "")


def _issued_for_partner(
    issued: "list[dict[str, Any]]", corp_num: str, partner_name: str, total: "float | int",
) -> "dict[str, Any] | None":
    """같은 거래처에 같은 합계로 발행한 이력만 찾는다.

    TAMS 캐시에는 감정서번호만 같고 현재 청구와 무관한 소액 전표도 들어오므로,
    문서번호 존재만으로는 발행 완료로 판단할 수 없다. 대주단(거래처별 정액)과
    발급 직전 재검사가 쓴다 — 일반·국민약식 목록은 합계 차감 방식으로 바뀌었다.
    """
    name = _normalize_name(partner_name)
    target_total = int(round(float(total or 0)))
    for row in issued:
        issued_total = int(round(float(row.get("issued_total") or 0)))
        if issued_total != target_total:
            continue
        if corp_num and digits(row.get("corp_num")) == corp_num:
            return row
        issued_name = _normalize_name(row.get("corp_name"))
        if name and issued_name and (
            issued_name in name or name in issued_name
        ):
            return row
    return None


def issued_rows_for_partner(
    issued: "list[dict[str, Any]]", corp_num: str, partner_name: str,
) -> "list[dict[str, Any]]":
    """같은 거래처 앞으로 발행된 이력만 골라낸다 — 사업자번호 우선, 상호는 보조."""
    name = _normalize_name(partner_name)
    result = []
    for row in issued:
        if corp_num and digits(row.get("corp_num")) == corp_num:
            result.append(row)
            continue
        issued_name = _normalize_name(row.get("corp_name"))
        if name and issued_name and (issued_name in name or name in issued_name):
            result.append(row)
    return result


def issued_in_period(issued: "list[dict[str, Any]]", date_from: date, date_to: date) -> "list[dict[str, Any]]":
    """작성일자(없으면 발급일)가 조회기간 안인 발행분 — 국민약식 기간 합계에서 뺄 몫.

    날짜를 모르는 행은 남긴다(빼는 쪽이 안전 — 두 번 발행보다 낫다).
    """
    lo, hi = date_from.strftime("%Y%m%d"), date_to.strftime("%Y%m%d")
    result = []
    for row in issued:
        stamp = str(row.get("issued_date") or "")[:8]
        if not stamp.isdigit() or len(stamp) != 8 or lo <= stamp <= hi:
            result.append(row)
    return result


def apply_prior_issued(total: float, prior: float) -> "tuple[int, int, bool, str]":
    """입금된 만큼만 발급 (2026-09-02 재무팀 규칙) — 기발행 몫을 뺀 잔여로 역산.

    (공급가, 세액, 이미 다 발행됐는지, 비고)를 돌려준다. 잔여가 없으면 금액은
    기본값 그대로 두고 '이미 발행'으로 넘긴다 — 미발행만 보기에서 걸러지는
    행이라 금액보다 상태가 중요하다.
    """
    prior_amount = int(round(float(prior or 0)))
    base = int(round(float(total or 0)))
    if prior_amount <= 0:
        supply, tax = split_vat(base)
        return supply, tax, False, ""
    if base - prior_amount <= 0:
        supply, tax = split_vat(base)
        return supply, tax, True, ""
    supply, tax = split_vat(base - prior_amount)
    return supply, tax, False, f"기발행 {prior_amount:,}원 제외"


def list_candidates(
    db: Session, *, kind: str, date_from: date, date_to: date, office_code: "str | None" = "10",
    pay_status: str = "전체", only_unissued: bool = True,
) -> "dict[str, Any]":
    if kind not in KINDS:
        raise TaxBulkError(f"모르는 구분입니다: {kind}")
    if pay_status not in PAY_STATUSES:
        raise TaxBulkError(f"입금상태는 {'/'.join(PAY_STATUSES)} 중 하나여야 합니다.")
    if date_from > date_to or (date_to - date_from).days + 1 > MAX_DAYS:
        raise TaxBulkError(f"입금일 구간은 {MAX_DAYS}일 이내로, 시작이 끝보다 앞이어야 합니다.")

    params: "dict[str, Any]" = {"date_from": date_from, "date_to": date_to}
    if kind == "kb":
        office = get_office(db, office_code) if office_code else None
        division_code = office.division_code if office else None
        if division_code:
            params["division"] = division_code
        return _kb_candidates(db, division_code, params, date_from, date_to, pay_status, only_unissued)
    prefixes = docid_prefixes(db, office_code) if office_code else (docid_prefixes(db, None) or ["01"])
    prefix_sql, prefix_params = management_no_filter(prefixes, column="b.doc_id")
    params.update(prefix_params)
    docs = [dict(r) for r in db.execute(
        text(candidate_docs_sql(kind, division_code=None, prefix_sql=prefix_sql)), params,
    ).mappings().all()]
    truncated = len(docs) > MAX_ROWS
    docs = docs[:MAX_ROWS]
    doc_ids = [str(d["doc_id"]) for d in docs]
    if not doc_ids:
        return {"kind": kind, "items": [], "truncated": False}

    lines = _rows(db, partner_lines_sql, "pl", doc_ids)
    by_doc: "dict[str, list[dict[str, Any]]]" = {}
    for line in lines:
        by_doc.setdefault(str(line["doc_id"]).strip(), []).append(line)
    issued_rows = _rows(db, issued_sql, "is", doc_ids)
    issued_by_doc: "dict[str, list[dict[str, Any]]]" = {}
    for row in issued_rows:
        issued_by_doc.setdefault(str(row["doc_id"]).strip(), []).append(row)
    tr_cds = sorted({str(line["tr_cd"]).strip() for line in lines if line.get("tr_cd")})
    cache = {str(r["partner_code"]).strip(): r for r in _rows(db, partner_cache_sql, "pc", tr_cds)} if tr_cds else {}

    items: "list[dict[str, Any]]" = []
    for doc in docs:
        doc_id = str(doc["doc_id"]).strip()
        billed, received = float(doc["billed_amount"] or 0), float(doc["received_amount"] or 0)
        status = pay_status_of(billed, received, doc["outstanding_amount"])
        if pay_status != "전체" and status != pay_status:
            continue
        partners = by_doc.get(doc_id, [])
        if kind == "syndicate" and len(partners) < 2:
            continue
        if kind != "syndicate" and len(partners) > 1:
            continue                                         # 거래처 여럿은 대주단 탭 몫
        base = {
            "doc_id": doc_id, "customer_name": doc.get("customer_name"), "manager": doc.get("manager"),
            "purpose": doc.get("purpose"), "pay_status": status, "billed_amount": billed,
            "received_amount": received, "outstanding_amount": float(doc["outstanding_amount"] or 0),
            "last_received_date": doc["last_received_date"],
        }
        issued_here = issued_by_doc.get(doc_id, [])
        if kind == "syndicate":
            for line in sorted(partners, key=lambda l: (str(l["last_date"] or ""), str(l["tr_cd"]))):
                tr_cd = str(line["tr_cd"]).strip()
                cached = cache.get(tr_cd, {})
                corp_num = digits(cached.get("reg_no"))
                corp_num = corp_num if len(corp_num) == 10 else ""
                supply = int(round(float(line["supply"] or 0)))
                tax = vat_of(supply)
                hit = _issued_for_partner(issued_here, corp_num, str(line["partner_name"] or ""), supply + tax)
                items.append(_finish({
                    **base, "kind": kind, "tr_cd": tr_cd, "partner_name": line["partner_name"], "corp_num": corp_num,
                    "write_date": line["last_date"] or doc["last_received_date"],
                    "supply_cost": supply, "tax": tax, "issued": hit is not None,
                    "issued_note": f"{hit['source']} 발행" if hit else "",
                }))
        else:
            line = partners[0] if partners else {}
            tr_cd = str(line.get("tr_cd") or "").strip()
            cached = cache.get(tr_cd, {})
            corp_num = digits(cached.get("reg_no"))
            corp_num = corp_num if len(corp_num) == 10 else ""
            # 입금된 만큼만 발급 (2026-09-02) — 같은 거래처 기발행 합계를 빼고 역산
            mine = issued_rows_for_partner(issued_here, corp_num, str(line.get("partner_name") or ""))
            prior = sum(float(r.get("issued_total") or 0) for r in mine)
            supply, tax, done, note = apply_prior_issued(default_amount(status, billed, received), prior)
            sources = "·".join(sorted({str(r.get("source") or "") for r in mine}))
            items.append(_finish({
                **base, "kind": kind, "tr_cd": tr_cd, "partner_name": line.get("partner_name"), "corp_num": corp_num,
                "write_date": doc["last_received_date"], "supply_cost": supply, "tax": tax,
                "issued": done, "issued_note": f"{sources} 발행" if done else note,
            }))
    items = _mark_card_sales(items, card_sales_docs(db, doc_ids))
    if only_unissued:
        items = [item for item in items if not item["issued"]]
    return {"kind": kind, "items": items, "truncated": truncated}


def _kb_candidates(
    db: Session, division_code: "str | None", params: "dict[str, Any]", date_from: date, date_to: date,
    pay_status: str, only_unissued: bool,
) -> "dict[str, Any]":
    """국민약식 — 조회기간 안 매출 전표 합계대로 (의뢰번호, 거래처)마다 한 장."""
    groups = [dict(r) for r in db.execute(text(kb_period_sql(division_code)), params).mappings().all()]
    truncated = len(groups) > MAX_ROWS
    groups = groups[:MAX_ROWS]
    doc_ids = sorted({str(g["doc_id"]).strip() for g in groups})
    if not doc_ids:
        return {"kind": "kb", "items": [], "truncated": False}
    issued_by_doc: "dict[str, list[dict[str, Any]]]" = {}
    for row in issued_in_period(_rows(db, issued_sql, "is", doc_ids), date_from, date_to):
        issued_by_doc.setdefault(str(row["doc_id"]).strip(), []).append(row)
    tr_cds = sorted({str(g["tr_cd"]).strip() for g in groups if g.get("tr_cd")})
    cache = {str(r["partner_code"]).strip(): r for r in _rows(db, partner_cache_sql, "pc", tr_cds)} if tr_cds else {}

    items: "list[dict[str, Any]]" = []
    for g in groups:
        doc_id = str(g["doc_id"]).strip()
        billed, received = float(g["billed_amount"] or 0), float(g["received_amount"] or 0)
        status = pay_status_of(billed, received, g["outstanding_amount"])
        if pay_status != "전체" and status != pay_status:
            continue
        tr_cd = str(g.get("tr_cd") or "").strip()
        cached = cache.get(tr_cd, {})
        corp_num = digits(cached.get("reg_no"))
        corp_num = corp_num if len(corp_num) == 10 else ""
        period_supply = int(round(float(g["supply"] or 0)))
        mine = issued_rows_for_partner(issued_by_doc.get(doc_id, []), corp_num, str(g.get("partner_name") or ""))
        prior = sum(float(r.get("issued_total") or 0) for r in mine)
        supply, tax, done, note = apply_prior_issued(period_supply + vat_of(period_supply), prior)
        sources = "·".join(sorted({str(r.get("source") or "") for r in mine}))
        items.append(_finish({
            "doc_id": doc_id, "customer_name": g.get("partner_name"), "manager": None, "purpose": None,
            "pay_status": status, "billed_amount": billed, "received_amount": received,
            "outstanding_amount": float(g["outstanding_amount"] or 0), "last_received_date": g["last_received_date"],
            "kind": "kb", "tr_cd": tr_cd, "partner_name": g.get("partner_name"), "corp_num": corp_num,
            "write_date": g["last_date"], "supply_cost": supply, "tax": tax,
            "issued": done, "issued_note": f"{sources} 발행" if done else note,
        }))
    items = _mark_card_sales(items, card_sales_docs(db, doc_ids))
    if only_unissued:
        items = [item for item in items if not item["issued"]]
    return {"kind": "kb", "items": items, "truncated": truncated}


def _finish(item: "dict[str, Any]") -> "dict[str, Any]":
    reason = ""
    if item["issued"]:
        reason = item["issued_note"] or "이미 발행"
    elif not item.get("tr_cd"):
        reason = "매출 전표에 거래처가 없음"
    elif not item.get("corp_num"):
        reason = "사업자번호 없음 (현금영수증 대상)"
    elif item["supply_cost"] <= 0:
        reason = "금액 0"
    write = item.get("write_date")
    return {
        **item, "key": row_key(item["kind"], item["doc_id"], item.get("tr_cd") or ""),
        "write_date": write.isoformat() if hasattr(write, "isoformat") else (str(write)[:10] if write else None),
        "last_received_date": (item["last_received_date"].isoformat() if hasattr(item["last_received_date"], "isoformat")
                               else item["last_received_date"]),
        "total": int(item["supply_cost"]) + int(item["tax"]),
        "issuable": not reason, "reason": reason,
    }


# ── 일괄 발급 ──────────────────────────────────────────────────────────────


def _already_issued(
    db: Session, kind: str, doc_id: str, corp_num: str, partner_name: str, total: "float | int",
) -> "str | None":
    """발급 직전 재검사 — 목록을 띄운 사이에 누가 발행했으면 건너뛴다(중복 발행 방지). 카드매출도 여기서 막는다."""
    if doc_id in card_sales_docs(db, [doc_id]):
        return CARD_SALES_NOTE
    rows = _rows(db, issued_sql, "is", [doc_id])
    hit = _issued_for_partner(rows, corp_num, partner_name, total)
    return f"이미 발행됨({hit['source']})" if hit else None


def next_syndicate_mgt_key(db: Session, doc_id: str) -> str:
    settings = get_settings()
    count = db.execute(
        text(
            "SELECT COUNT(*) FROM dbo.a10_issued_taxinvoice WHERE doc_id = :doc AND doc_type = N'세금계산서' "
            "AND mgt_key LIKE :pattern AND is_test = :t"
        ),
        {"doc": doc_id, "pattern": f"{doc_id}-L%", "t": 1 if settings.popbill_is_test else 0},
    ).scalar() or 0
    return syndicate_mgt_key(doc_id, int(count) + 1)


def issue_bulk(
    db: Session, items: "list[dict[str, Any]]", *,
    lookup: Callable[..., "dict[str, Any]"] = popbill_tax.lookup_customer,
    already: Callable[..., "str | None"] = _already_issued,
    next_key: "Callable[[Session, str, str], str] | None" = None,
    register: Callable[..., "dict[str, Any]"] = popbill_tax.register_issue,
    info: Callable[[str], "dict[str, Any]"] = popbill_tax.get_info,
    save: Callable[..., None] = popbill_tax.save_issued,
    supplier: "dict[str, Any] | None" = None,
) -> "dict[str, Any]":
    """한 건씩 순서대로 발행한다. 실패해도 다음 건으로 간다 — 결과는 행마다 돌려준다."""
    if len(items) > MAX_ISSUE:
        raise TaxBulkError(f"한 번에 {MAX_ISSUE}건까지 발급할 수 있습니다.")
    supplier = supplier or popbill_tax.supplier_info(db)
    results: "list[dict[str, Any]]" = []
    for item in items:
        kind, doc_id, tr_cd = item["kind"], str(item["doc_id"]).strip(), str(item.get("tr_cd") or "").strip()
        entry: "dict[str, Any]" = {"key": row_key(kind, doc_id, tr_cd), "doc_id": doc_id, "tr_cd": tr_cd}
        try:
            receiver = dict(lookup(db, tr_cd)) if tr_cd else {}
            corp_num = digits(receiver.get("corp_num")) or digits(item.get("corp_num"))
            if len(corp_num) != 10:
                raise TaxBulkError("공급받는자 사업자번호(10자리)가 없습니다.")
            receiver["corp_num"] = corp_num
            receiver["corp_name"] = receiver.get("corp_name") or item.get("partner_name") or ""
            receiver["email"] = (item.get("email") or receiver.get("email") or DEFAULT_EMAIL).strip()
            supply, tax = int(item["supply_cost"]), int(item["tax"])
            if supply <= 0:
                raise TaxBulkError("공급가가 0입니다.")
            skip = already(db, kind, doc_id, corp_num, receiver["corp_name"], supply + tax)
            if skip:
                results.append({**entry, "success": False, "skipped": True, "message": skip})
                continue
            write_date = digits(item["write_date"])[:8]
            if len(write_date) != 8:
                raise TaxBulkError("작성일자를 확인하세요.")
            inv = popbill_tax.build_taxinvoice(
                write_date=write_date, supplier=supplier, receiver=receiver,
                items=[{
                    "date": write_date, "name": (item.get("item_name") or item_name_for(kind, doc_id))[:100],
                    "spec": "", "qty": "1", "unit_cost": str(supply), "supply_cost": supply, "tax": tax, "remark": "",
                }],
                purpose=_PURPOSE, memo="",
            )
            if kind == "syndicate":
                mgt_key = next_key(db, kind, doc_id) if next_key else next_syndicate_mgt_key(db, doc_id)
            else:
                mgt_key = next_key(db, kind, doc_id) if next_key else popbill_tax.next_issue_mgt_key(db, doc_id)
            result = register(inv, mgt_key, memo=f"감정 {doc_id}")
            if not result.get("success"):
                results.append({**entry, "success": False, "message": result.get("message") or "발급 실패", "code": result.get("code")})
                continue
            detail = info(mgt_key)
            save(
                db, doc_type="세금계산서", doc_id=doc_id, mgt_key=mgt_key,
                receiver_corp_num=corp_num, receiver_name=receiver["corp_name"],
                supply_cost=supply, tax=tax, info=detail,
                account_code="4010002" if kind == "kb" else "4010001",
            )
            results.append({
                **entry, "success": True, "mgt_key": mgt_key, "message": "발급 완료",
                "nts_confirm": detail.get("nts_confirm") or detail.get("confirm_num"), "email": receiver["email"],
            })
        except TaxBulkError as exc:
            results.append({**entry, "success": False, "message": str(exc)})
        except Exception as exc:  # noqa: BLE001 — 한 건의 예외가 나머지 발급을 막으면 안 된다
            results.append({**entry, "success": False, "message": f"오류: {exc}"})
    issued = sum(1 for r in results if r.get("success"))
    skipped = sum(1 for r in results if r.get("skipped"))
    return {"results": results, "issued": issued, "skipped": skipped, "failed": len(results) - issued - skipped,
            "is_test": get_settings().popbill_is_test}
