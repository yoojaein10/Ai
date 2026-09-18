"""외부 발행 계산서 수기 등록 (2026-09-09) — 나라장터·나라빌·홈택스 등 팝빌·TAMS 밖에서 끊은
세금계산서·현금영수증을 발급 원장(a10_issued_taxinvoice)에 넣는다.

계산서 일괄발급 화면의 '외부 발행 등록' 탭이 쓴다. 단건 폼과 엑셀(우리 양식)이 같은 열이라
같은 검증·저장을 탄다. 엑셀은 우리 양식(template_xlsx) 또는 국세청 매출 자료(.xls — 2026-09-11 재무팀
양식, external_issue_nts)를 그대로 올린다. 국세청 자료에는 이미 원장에 있는 건도 다 들어 있어 검증이 가른다:
같은 승인번호가 원장에 있으면 막고, 승인번호가 없는 TAMS 원장 행과는 감정서·작성일·금액으로 맞춘다.
승인번호 가운데 8자리로 발급처를 가린다: 위하고(41000096)는 출처 '위하고'로 넣고, MOA 팝빌(41000203)은
팝빌 동기화로 들어오므로 막는다 (2026-09-11 사용자).

중복은 국세청 승인번호로 막는다(팝빌 동기화와 같은 규칙). 부호는 원장 관례 그대로 —
세금취소는 음수, 현금취소는 양수 취소금액(읽는 쪽이 -ABS 로 뺀다).
"""

from datetime import date, datetime
from io import BytesIO
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings

COLUMNS = ("감정서번호", "출처", "종류", "작성일자", "승인번호", "사업자번호", "상호", "공급가액", "세액")
SOURCES = ("나라장터", "나라빌", "국세청", "위하고", "기타")
DOC_TYPES = ("세금계산서", "세금취소", "현금영수증", "현금취소")
MAX_ROWS = 3000   # 국세청 자료 한 달치를 통째로 올린다 (2026-09-11, 예전 200)
MGT_KEY_PREFIX = "EXT-"
_CHUNK = 500      # SQL Server 매개변수 2,100개 상한 — IN 목록을 나눈다


class ExternalIssueError(ValueError):
    pass


def _source_view() -> str:
    database = get_settings().mssql_source_db
    if not database.replace("_", "").isalnum():
        raise RuntimeError("MSSQL_SOURCE_DB 이름이 올바르지 않습니다.")
    return f"[{database}].dbo.apw_masterex"


# ── 순수 규칙 ──────────────────────────────────────────────────────────────


def parse_date(value: Any) -> "date | None":
    """'2026-09-01' · '20260901' · '2026.09.01' · 엑셀 날짜 셀 → date. 못 읽으면 None."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = str(value or "").strip()[:10].replace("-", "").replace(".", "").replace("/", "")
    if len(raw) != 8 or not raw.isdigit():
        return None
    try:
        return date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
    except ValueError:
        return None


def parse_amount(value: Any) -> int:
    """'1,234,000' · '-55000' · 1234000.0 → 정수. 빈값·글자는 0."""
    if isinstance(value, (int, float)):
        return int(round(value))
    raw = str(value or "").strip().replace(",", "").replace("원", "")
    negative = raw.startswith("-")
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return 0
    return -int(digits) if negative else int(digits)


def normalize_row(raw: "dict[str, Any]") -> "dict[str, Any]":
    """화면·엑셀 한 행 → 검증·저장에 쓰는 정규화된 행(원본 문자열은 버린다)."""
    def s(key: str) -> str:
        return str(raw.get(key) or "").strip()
    write_date = parse_date(raw.get("write_date"))
    nts = raw.get("nts")
    return {
        "doc_id": s("doc_id"),
        "source": s("source"),
        "doc_type": s("doc_type"),
        "write_date": write_date.isoformat() if write_date else "",
        "nts_confirm": s("nts_confirm").replace("-", "").replace(" ", ""),
        "receiver_corp_num": "".join(ch for ch in s("receiver_corp_num") if ch.isdigit()),
        "receiver_name": s("receiver_name")[:200],
        "supply_cost": parse_amount(raw.get("supply_cost")),
        "tax": parse_amount(raw.get("tax")),
        # 국세청 자료의 원래 칸 값(분류·발급유형·품목명…) — 목록 표시용, 검증·저장엔 안 쓴다
        "nts": {str(k)[:20]: str(v if v is not None else "")[:300] for k, v in nts.items()} if isinstance(nts, dict) else None,
    }


def check_row(row: "dict[str, Any]") -> "list[str]":
    """DB 없이 잡히는 형식 문제 목록. 비면 형식은 통과."""
    problems = []
    if not row["doc_id"]:
        problems.append("감정서번호 없음")
    if row["source"] not in SOURCES:
        problems.append("출처는 " + "·".join(SOURCES) + " 중 하나")
    if row["doc_type"] not in DOC_TYPES:
        problems.append("종류는 " + "·".join(DOC_TYPES) + " 중 하나")
    if not row["write_date"]:
        problems.append("작성일자 형식(YYYY-MM-DD)")
    if not row["nts_confirm"]:
        problems.append("승인번호 없음(중복 확인 열쇠)")
    if row["supply_cost"] == 0 and row["tax"] == 0:
        problems.append("금액 0")
    if row["receiver_corp_num"] and len(row["receiver_corp_num"]) != 10:
        problems.append("사업자번호 10자리")
    return problems


def is_kb_simple(doc_id: str) -> bool:
    """국민약식 번호(400581444) — APWorks 감정서가 아니라 감정서 확인을 건너뛴다(원장엔 이 번호로 들어간다)."""
    return len(doc_id) == 9 and doc_id.isdigit() and doc_id.startswith("4")


def ledger_amounts(doc_type: str, supply_cost: int, tax: int) -> "tuple[int, int]":
    """원장 부호 규칙 — 세금취소 음수, 현금취소·발행분 양수. 입력 부호는 무시한다."""
    supply, vat = abs(supply_cost), abs(tax)
    if doc_type == "세금취소":
        return -supply, -vat
    return supply, vat


# ── 검증(DB) ────────────────────────────────────────────────────────────────


def _appraisals_of(db: Session, doc_ids: "list[str]") -> "dict[str, dict[str, Any]]":
    """감정서 존재·청구금액·거래처 — 없는 번호는 빠진다."""
    ids = sorted({d for d in doc_ids if d and not is_kb_simple(d)})
    result: "dict[str, dict[str, Any]]" = {}
    for start in range(0, len(ids), _CHUNK):
        chunk = ids[start:start + _CHUNK]
        placeholders = ", ".join(f"CAST(:d{i} AS VARCHAR(50))" for i in range(len(chunk)))
        params = {f"d{i}": v for i, v in enumerate(chunk)}
        rows = db.execute(
            text(f"SELECT DocID, CustName, [청구금액] AS bill FROM {_source_view()} WHERE DocID IN ({placeholders})"),
            params,
        ).mappings().all()
        for r in rows:
            result[str(r["DocID"]).strip()] = {"customer_name": (r["CustName"] or "").strip(), "bill": float(r["bill"] or 0)}
    return result


def _registered_confirms(db: Session, confirms: "list[str]") -> "dict[str, str]":
    """이미 원장에 있는 승인번호 → 출처."""
    keys = sorted({c for c in confirms if c})
    result: "dict[str, str]" = {}
    for start in range(0, len(keys), _CHUNK):
        chunk = keys[start:start + _CHUNK]
        placeholders = ", ".join(f":c{i}" for i in range(len(chunk)))
        params = {f"c{i}": v for i, v in enumerate(chunk)}
        rows = db.execute(
            text(f"SELECT nts_confirm, source FROM dbo.a10_issued_taxinvoice WHERE nts_confirm IN ({placeholders}) AND is_test = 0"),
            params,
        ).all()
        result.update({str(r[0]): str(r[1]) for r in rows})
    return result


def _ledger_by_doc(db: Session, doc_ids: "list[str]") -> "dict[str, list[tuple[str, int, str]]]":
    """감정서별 원장 (작성일, 합계, 출처). TAMS 세금계산서 행은 승인번호가 비어 있어(17.9만 건) 승인번호로는
    못 막는다 — 같은 감정서·작성일·금액이면 같은 계산서로 본다. MOA 팝빌 행은 작성일이 비어 발행일시 앞 8자리."""
    ids = sorted({d for d in doc_ids if d})
    result: "dict[str, list[tuple[str, int, str]]]" = {}
    for start in range(0, len(ids), _CHUNK):
        chunk = ids[start:start + _CHUNK]
        placeholders = ", ".join(f"CAST(:d{i} AS VARCHAR(100))" for i in range(len(chunk)))
        params = {f"d{i}": v for i, v in enumerate(chunk)}
        rows = db.execute(
            text(f"""
                SELECT doc_id, CONVERT(varchar(10), COALESCE(write_date, TRY_CONVERT(date, LEFT(issue_dt, 8), 112)), 23) AS day,
                       total, source
                FROM dbo.a10_issued_taxinvoice
                WHERE is_test = 0 AND is_pool = 0 AND doc_id IN ({placeholders})
            """),
            params,
        ).all()
        for doc, day, total, source in rows:
            result.setdefault(str(doc).strip(), []).append((str(day or ""), int(round(float(total or 0))), str(source)))
    return result


def _ledger_by_corp(db: Session, rows: "list[dict[str, Any]]") -> "dict[str, list[tuple[str, int, str, str]]]":
    """거래처(사업자번호)별 원장 (작성일, 합계, 감정서번호, 출처) — 올린 행들의 작성일 범위 안에서만."""
    corps = sorted({r["receiver_corp_num"] for r in rows if r["receiver_corp_num"]})
    days = sorted({r["write_date"] for r in rows if r["write_date"]})
    result: "dict[str, list[tuple[str, int, str, str]]]" = {}
    if not corps or not days:
        return result
    for start in range(0, len(corps), _CHUNK):
        chunk = corps[start:start + _CHUNK]
        placeholders = ", ".join(f"CAST(:p{i} AS VARCHAR(20))" for i in range(len(chunk)))
        params: "dict[str, Any]" = {f"p{i}": v for i, v in enumerate(chunk)}
        params.update(dmin=days[0], dmax=days[-1])
        found = db.execute(
            text(f"""
                SELECT receiver_corp_num,
                       CONVERT(varchar(10), COALESCE(write_date, TRY_CONVERT(date, LEFT(issue_dt, 8), 112)), 23) AS wday,
                       total, doc_id, source
                FROM dbo.a10_issued_taxinvoice
                WHERE is_test = 0 AND is_pool = 0 AND receiver_corp_num IN ({placeholders})
                  AND COALESCE(write_date, TRY_CONVERT(date, LEFT(issue_dt, 8), 112)) BETWEEN :dmin AND :dmax
            """),
            params,
        ).all()
        for corp, day, total, doc, source in found:
            result.setdefault(str(corp).strip(), []).append(
                (str(day or ""), int(round(float(total or 0))), str(doc or "").strip(), str(source)))
    return result


def _docs_of_confirms(db: Session, confirms: "list[str]") -> "dict[str, str]":
    """승인번호 → 감정서번호 (수정세금계산서의 '당초 승인번호'로 감정서를 찾는다)."""
    keys = sorted({c for c in confirms if c})
    result: "dict[str, str]" = {}
    for start in range(0, len(keys), _CHUNK):
        chunk = keys[start:start + _CHUNK]
        placeholders = ", ".join(f":c{i}" for i in range(len(chunk)))
        params = {f"c{i}": v for i, v in enumerate(chunk)}
        rows = db.execute(
            text(f"SELECT nts_confirm, doc_id FROM dbo.a10_issued_taxinvoice WHERE nts_confirm IN ({placeholders}) AND is_test = 0"),
            params,
        ).all()
        result.update({str(r[0]): str(r[1]).strip() for r in rows if r[1]})
    return result


def validate_rows(db: Session, raw_rows: "list[dict[str, Any]]") -> "list[dict[str, Any]]":
    """행마다 problems(막힘)·warnings(참고)·감정서 정보를 붙여 돌려준다. 순서 보존."""
    if len(raw_rows) > MAX_ROWS:
        raise ExternalIssueError(f"한 번에 {MAX_ROWS}건까지 등록할 수 있습니다.")
    rows = [normalize_row(r) for r in raw_rows]
    from app.services.external_issue_nts import issuer_of

    appraisals = _appraisals_of(db, [r["doc_id"] for r in rows])
    registered = _registered_confirms(db, [r["nts_confirm"] for r in rows])
    ledger = _ledger_by_doc(db, [r["doc_id"] for r in rows])
    by_corp = _ledger_by_corp(db, rows)
    seen: dict[str, int] = {}
    result = []
    for index, row in enumerate(rows, start=1):
        problems = check_row(row)
        warnings = []
        known = False   # 이미 원장에 있거나 다른 동기화로 들어올 건 — 화면에서 접어 둔다
        kb = is_kb_simple(row["doc_id"])
        info = {"customer_name": row["receiver_name"], "bill": 0.0} if kb else appraisals.get(row["doc_id"])
        if row["doc_id"] and info is None:
            problems.append("감정서 없음")
        if row["nts_confirm"] in registered:
            problems.append(f"이미 등록됨(출처 {registered[row['nts_confirm']]})")
            known = True
        elif issuer_of(row["nts_confirm"]) == "MOA 팝빌":
            problems.append("MOA 팝빌 발급분 — 팝빌 동기화로 들어옵니다")
            known = True
        elif row["write_date"] and row["doc_type"] in DOC_TYPES:
            supply, vat = ledger_amounts(row["doc_type"], row["supply_cost"], row["tax"])
            same = [src for day, total, src in ledger.get(row["doc_id"], ())
                    if day == row["write_date"] and total == supply + vat]
            if same:
                problems.append(f"이미 등록됨(같은 감정서·작성일·금액, 출처 {same[0]})")
                known = True
        if not known and row["receiver_corp_num"] and row["write_date"] and row["doc_type"] in DOC_TYPES:
            # 감정서번호만 다르고 같은 날·금액·거래처인 원장 행 — TAMS 에 번호가 틀리게 적힌 경우('25' 등) 이중 등록 경고.
            # 막지는 않는다: 국민약식은 같은 지점·같은 날·같은 금액이 여러 장이다 (2026-09-11)
            s_amt, v_amt = ledger_amounts(row["doc_type"], row["supply_cost"], row["tax"])
            twins = [(doc, src) for day, total, doc, src in by_corp.get(row["receiver_corp_num"], ())
                     if day == row["write_date"] and total == s_amt + v_amt and doc != row["doc_id"]]
            if twins:
                warnings.append(f"같은 날·금액·거래처 계산서가 원장에 있음(감정서번호 {twins[0][0] or '없음'}, 출처 {twins[0][1]}) — 중복인지 확인")
        if row["nts_confirm"]:
            if row["nts_confirm"] in seen:
                problems.append(f"{seen[row['nts_confirm']]}행과 승인번호 중복")
            else:
                seen[row["nts_confirm"]] = index
        total = row["supply_cost"] + row["tax"]
        if info and not kb and row["doc_type"] == "세금계산서" and info["bill"] and abs(info["bill"] - total) >= 1:
            warnings.append(f"청구금액 {info['bill']:,.0f}원과 다름")
        result.append({
            **row,
            "row_no": index,
            "customer_name": info["customer_name"] if info else "",
            "bill_amount": info["bill"] if info else None,
            "problems": problems,
            "warnings": warnings,
            "known": known,
            "ok": not problems,
        })
    return result


# ── 저장 ────────────────────────────────────────────────────────────────────


def register_rows(db: Session, raw_rows: "list[dict[str, Any]]") -> "dict[str, Any]":
    """검증을 다시 돌려 통과한 행만 원장에 넣는다. 결과는 행마다 돌려준다."""
    from app.models import IssuedTaxInvoice

    checked = validate_rows(db, raw_rows)
    registered = 0
    for row in checked:
        if not row["ok"]:
            continue
        supply, vat = ledger_amounts(row["doc_type"], row["supply_cost"], row["tax"])
        db.add(IssuedTaxInvoice(
            doc_type=row["doc_type"], doc_id=row["doc_id"],
            mgt_key=(MGT_KEY_PREFIX + row["nts_confirm"])[:100],
            receiver_corp_num=row["receiver_corp_num"] or None,
            receiver_name=row["receiver_name"] or None,
            supply_cost=supply, tax=vat, total=supply + vat,
            nts_confirm=row["nts_confirm"][:30],
            issue_dt=row["write_date"].replace("-", ""),
            is_test=False, source=row["source"],
            write_date=date.fromisoformat(row["write_date"]),
        ))
        row["registered"] = True
        registered += 1
    db.commit()
    return {"registered": registered, "skipped": len(checked) - registered, "results": checked}


# ── 엑셀 ────────────────────────────────────────────────────────────────────

_FIELD_OF = dict(zip(COLUMNS, (
    "doc_id", "source", "doc_type", "write_date", "nts_confirm",
    "receiver_corp_num", "receiver_name", "supply_cost", "tax",
)))


def parse_excel(data: bytes) -> "list[dict[str, Any]]":
    """우리 양식(template_xlsx) 첫 시트 → 행 목록(정규화 전). 머리글은 이름으로 찾는다."""
    from openpyxl import load_workbook

    ws = load_workbook(BytesIO(data), data_only=True, read_only=True).worksheets[0]
    it = ws.iter_rows(values_only=True)
    try:
        header = [str(v or "").replace(" ", "").strip() for v in next(it)]
    except StopIteration as exc:
        raise ExternalIssueError("빈 엑셀입니다.") from exc
    missing = [c for c in COLUMNS if c not in header]
    if missing:
        raise ExternalIssueError("엑셀에 없는 열: " + ", ".join(missing) + " — 양식을 내려받아 쓰세요.")
    positions = {header.index(c): _FIELD_OF[c] for c in COLUMNS}
    rows = []
    for raw in it:
        values = {field: raw[pos] if pos < len(raw) else None for pos, field in positions.items()}
        if any(v not in (None, "") for v in values.values()):
            rows.append(values)
        if len(rows) > MAX_ROWS:
            raise ExternalIssueError(f"한 번에 {MAX_ROWS}건까지 등록할 수 있습니다.")
    return rows


def parse_upload(db: Session, data: bytes, filename: str) -> "list[dict[str, Any]]":
    """올린 엑셀 → 행 목록(검증 전). 국세청 매출 자료면 그 형식으로, 아니면 우리 양식(.xlsx)으로 읽는다.
    수정세금계산서에 감정서번호가 안 보이면 비고의 '당초 승인번호'로 원장에서 찾아 채운다."""
    from app.services import external_issue_nts as nts

    sheets = nts.read_sheets(data, filename)
    if not nts.is_nts(sheets):
        if filename.lower().endswith(".xls"):
            raise ExternalIssueError("국세청 매출 자료나 우리 양식(.xlsx)만 읽을 수 있습니다.")
        return parse_excel(data)
    rows = nts.parse_nts(sheets)
    if len(rows) > MAX_ROWS:
        raise ExternalIssueError(f"한 번에 {MAX_ROWS}건까지 등록할 수 있습니다.")
    originals = _docs_of_confirms(db, [r["original_confirm"] for r in rows if not r["doc_id"]])
    return [{**r, "doc_id": r["doc_id"] or originals.get(r["original_confirm"], "")} for r in rows]


def template_xlsx() -> bytes:
    """머리글 + 보기 행 하나. 출처·종류 허용값은 둘째 시트에 적어 둔다."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "외부발행"
    ws.append(list(COLUMNS))
    ws.append(["01-2609-3-0001", "나라장터", "세금계산서", "2026-09-01", "20260901410002030000abcd",
               'REDACTED_CONFIGURE_LOCALLY7890', "거래처 상호", 500000, 50000])
    guide = wb.create_sheet("안내")
    guide.append(["출처", "·".join(SOURCES)])
    guide.append(["종류", "·".join(DOC_TYPES)])
    guide.append(["승인번호", "국세청 승인번호(세금계산서 24자리·현금영수증 승인번호) — 같은 번호는 두 번 안 들어간다"])
    guide.append(["금액", "취소분도 양수로 적는다 — 부호는 종류로 정한다"])
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
