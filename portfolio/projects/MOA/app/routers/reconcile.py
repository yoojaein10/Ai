"""엑셀 업로드 대사 API (본사 관리 화면).

업로드한 엑셀에서 감정서번호 열·금액 열을 자동 감지(또는 지정)해 우리 매출과 대사한다.
"""

import io
import re
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from openpyxl import load_workbook
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import AccessContext, require_menu, resolve_office_scope
from app.schemas.common import ApiResponse
from app.services.excel_export import XLSX_MEDIA_TYPE, build_xlsx, xlsx_headers
from app.services.reconcile import DOC_RE, reconcile

router = APIRouter(prefix="/api/reconcile", tags=["reconcile"])

_MAX_ROWS = 100_000


def _to_number(value: Any) -> "float | None":
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.replace(",", "").strip()
        if re.fullmatch(r"-?\d+(\.\d+)?", s):
            return float(s)
    return None


def _read_matrix(data: bytes) -> "list[list[Any]]":
    wb = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    ws = wb.worksheets[0]
    rows = []
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i >= _MAX_ROWS:
            break
        rows.append(list(row))
    return rows


_AMOUNT_HEADER = ("전표매출액", "매출액", "매출", "공급가", "금액", "청구")
# 금액이 아닌데 숫자가 큰 열(오인 방지): 사업자·문서·계좌번호 등
_ID_HEADER = ("사업자", "번호", "등록", "계좌", "전화", "코드", "일자", "날짜", "docid", "no")


def _analyze_columns(matrix: "list[list[Any]]") -> "dict[str, Any]":
    """열별 통계 + 헤더 추정으로 감정서/금액 열 자동 추천."""
    width = max((len(r) for r in matrix), default=0)
    # 감정서 열 = DOC 매칭 최다, 그리고 첫 매칭 행의 바로 윗줄을 헤더로 본다.
    first_doc_row = None
    cols = []
    doc_col, best_doc_hits = -1, 0
    for c in range(width):
        doc_hits = num_hits = 0
        num_sum = 0.0
        sample = ""
        for ri, r in enumerate(matrix):
            if c >= len(r) or r[c] is None:
                continue
            cell = r[c]
            if not sample:
                sample = str(cell)[:20]
            if DOC_RE.search(str(cell)):
                doc_hits += 1
                if first_doc_row is None or ri < first_doc_row:
                    first_doc_row = ri
            n = _to_number(cell)
            if n is not None:
                num_hits += 1
                num_sum += n
        cols.append({"index": c, "sample": sample, "doc_hits": doc_hits,
                     "num_hits": num_hits, "num_sum": num_sum, "header": ""})
        if doc_hits > best_doc_hits:
            best_doc_hits, doc_col = doc_hits, c

    # 헤더 행 = 첫 감정서 행보다 위에서 '문자 셀'이 가장 많은 행 (TAMS는 헤더 위에 빈 행 있음)
    header_idx = None
    if first_doc_row is not None:
        best_text = 0
        for ri in range(first_doc_row):
            text_cells = sum(1 for cell in matrix[ri]
                             if isinstance(cell, str) and cell.strip() and not DOC_RE.search(cell))
            if text_cells > best_text:
                best_text, header_idx = text_cells, ri
    header_row = matrix[header_idx] if header_idx is not None else None
    if header_row:
        for col in cols:
            i = col["index"]
            col["header"] = str(header_row[i]).strip() if i < len(header_row) and header_row[i] is not None else ""

    # 금액 열: ① 헤더 키워드 우선순위대로(전표매출액→매출액→…) 매칭.  ② 없으면 숫자열 휴리스틱.
    amount_col = -1
    for kw in _AMOUNT_HEADER:
        hit = next((c for c in cols if c["index"] != doc_col and c["num_hits"] >= 3
                    and kw in c["header"]
                    and not any(x in c["header"].lower() for x in _ID_HEADER)), None)
        if hit:
            amount_col = hit["index"]
            break
    if amount_col < 0:
        best = -1.0
        for col in cols:
            if col["index"] == doc_col or col["num_hits"] < max(3, best_doc_hits // 2):
                continue
            if any(k in col["header"].lower() for k in _ID_HEADER):
                continue
            avg = abs(col["num_sum"]) / col["num_hits"] if col["num_hits"] else 0
            if avg > 1e11:   # 사업자/문서번호처럼 비정상적으로 큰 값 열 제외
                continue
            if abs(col["num_sum"]) > best:
                best, amount_col = abs(col["num_sum"]), col["index"]
    return {"columns": cols, "suggested_doc_col": doc_col, "suggested_amount_col": amount_col,
            "header_row": (first_doc_row - 1) if first_doc_row else None}


@router.post("", response_model=ApiResponse)
async def run_reconcile(
    file: UploadFile = File(...),
    doc_col: int = Form(-1),
    amount_col: int = Form(-1),
    office_code: str = Form("10"),
    date_from: str = Form(""),
    date_to: str = Form(""),
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("reconcile")),
) -> ApiResponse:
    data = await file.read()
    try:
        matrix = _read_matrix(data)
    except Exception as exc:  # 손상·비엑셀 파일
        return ApiResponse(success=False, code="BAD_FILE",
                           message=f"엑셀을 읽지 못했습니다: {exc}", data=None)
    analysis = _analyze_columns(matrix)
    dcol = doc_col if doc_col >= 0 else analysis["suggested_doc_col"]
    acol = amount_col if amount_col >= 0 else analysis["suggested_amount_col"]
    if dcol < 0 or acol < 0:
        return ApiResponse(
            success=False, code="NO_COLUMN",
            message="감정서번호/금액 열을 찾지 못했습니다. 열을 직접 지정하세요.",
            data={"analysis": analysis, "filename": file.filename},
        )
    pairs = []
    for r in matrix:
        if dcol >= len(r) or acol >= len(r):
            continue
        doc = r[dcol]
        if not doc or not DOC_RE.search(str(doc)):
            continue
        amt = _to_number(r[acol])
        if amt is None:
            continue
        pairs.append((str(doc), amt))
    df = date.fromisoformat(date_from) if date_from else None
    dt = date.fromisoformat(date_to) if date_to else None
    scoped_office = resolve_office_scope(access, office_code)
    result = reconcile(db, pairs, scoped_office or "10", df, dt)
    result["date_from"] = date_from
    result["date_to"] = date_to
    result["used_doc_col"] = dcol
    result["used_amount_col"] = acol
    result["analysis"] = analysis
    result["filename"] = file.filename
    result["parsed_rows"] = len(pairs)
    # 데스크톱 앱은 화면에서 만든 Blob을 저장할 수 없어(GET 다운로드만 가능)
    # 결과를 서버에 잠시 보관하고 토큰으로 내보내기를 제공한다.
    result["export_token"] = _remember_result(result)
    return ApiResponse(success=True, code="0000", message="대사 완료", data=result)


# 대사 결과 임시 보관 (내보내기용). 프로세스 메모리라 재시작하면 사라진다 —
# 그 경우 화면에서 "다시 대사 후 내보내기" 안내만 뜨면 된다.
_RESULT_TTL_SECONDS = 3600
_RESULTS: "dict[str, tuple[float, dict[str, Any]]]" = {}

_EXPORT_COLUMNS = {
    "matched": [("doc", "감정서번호"), ("amount", "금액")],
    "amount_diff": [("doc", "감정서번호"), ("excel", "엑셀 금액"),
                    ("ours", "우리 매출"), ("diff", "차이(우리-엑셀)")],
    "excel_only": [("doc", "감정서번호"), ("amount", "금액"), ("partner", "장부번호 추정")],
    "cache_only": [("doc", "감정서번호"), ("amount", "금액")],
}


def _remember_result(result: "dict[str, Any]") -> str:
    import secrets
    import time

    now = time.time()
    for token in [t for t, (ts, _) in _RESULTS.items() if now - ts > _RESULT_TTL_SECONDS]:
        _RESULTS.pop(token, None)
    token = secrets.token_urlsafe(16)
    _RESULTS[token] = (now, result)
    return token


@router.get("/export.xlsx", response_model=None)
def export_group(token: str, key: str) -> Response:
    stored = _RESULTS.get(token)
    if stored is None:
        return Response(
            content="대사 결과가 만료되었습니다. 다시 대사한 뒤 내보내세요.",
            status_code=410, media_type="text/plain; charset=utf-8",
        )
    result = stored[1]
    group = next((g for g in result.get("groups", []) if g["key"] == key), None)
    if group is None:
        return Response(content="해당 그룹이 없습니다.", status_code=404)
    columns = _EXPORT_COLUMNS.get(key, [("doc", "감정서번호"), ("amount", "금액")])
    name = f"대사_{group['title']}_{result.get('date_from') or ''}_{result.get('date_to') or ''}"
    return Response(
        content=build_xlsx(str(group["title"])[:31], columns, group["items"]),
        media_type=XLSX_MEDIA_TYPE,
        headers=xlsx_headers(name),
    )
