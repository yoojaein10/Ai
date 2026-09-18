"""여러 달에 걸친 업무실적 누락분 스캔 (2026-09-07 사용자 요청).

업무실적 화면은 한 회차(연·월·반월·기준)의 미등록만 보여준다. 이 모듈은 기간을
지정해 여러 달을 한 번에 훑어, "그 달 보고 대상인데 협회에 아직 등록되지 않은" 건을
모아 준다. 사용자가 목록에서 골라 현재 열어둔 회차의 수기 추가(extra)로 넣어 함께
제출하는 흐름이라, '추가'는 기존 배관을 그대로 쓰고 여기서는 '찾기'만 한다.

누락 판정
  보고 대상 = build_kapa_rows(basis) (회차별, 상·하반)
  등록분    = fetch_registered_doc_ids(appcode, bungi, month) (협회 서버, 달별 1회)
  누락 = 보고 대상 중, (조회 범위 + 현재 보고달)의 등록분 합집합에 없는 것
        → 현재 보고달 등록분을 합치므로, 누락분을 현재달에 몰아 넣고 다시 스캔하면
          목록에서 사라진다(사용자가 택한 '현재달로 몰기' 방식과 맞물린다).
"""

from datetime import date
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.services.kapa_submit import fetch_registered_doc_ids
from app.services.work_report import Basis, Half, build_kapa_rows, quarter_bungi

# 협회 서버를 달마다 호출하고 회차마다 원본 DB를 훑으므로, 한 번에 도는 범위를 막는다.
MAX_MONTHS = 12

_HALVES: tuple[Half, Half] = ("상반", "하반")


def _month_sequence(
    from_year: int, from_month: int, to_year: int, to_month: int
) -> list[tuple[int, int]]:
    """[시작월, 끝월] 사이의 (년, 월) 목록. 시작이 끝보다 늦으면 빈 목록."""
    start = from_year * 12 + (from_month - 1)
    end = to_year * 12 + (to_month - 1)
    return [(index // 12, index % 12 + 1) for index in range(start, end + 1)]


def _missing_row(row: dict[str, Any], year: int, month: int, half: Half) -> dict[str, Any]:
    """누락 목록 한 줄 — 화면 표시에 필요한 값만 추린다(전송 화이트리스트와 무관)."""
    no_fee = bool(row.get("NO_FEE"))
    out_of_scope = bool(row.get("OUT_OF_SCOPE"))
    return {
        "year": year,
        "month": month,
        "half": half,
        "period_label": f"{year}.{month:02d} {half}",
        "ID_NUM": row.get("ID_NUM"),
        "GNAME": row.get("GNAME"),
        "CUST": row.get("CUST"),
        "PNAME": row.get("PNAME"),
        "GAMGA": row.get("GAMGA"),
        "FEE": row.get("FEE"),
        "SUSU": row.get("SUSU"),
        "NO_FEE": no_fee,
        "OUT_OF_SCOPE": out_of_scope,
        "NOT_SENT": bool(row.get("NOT_SENT")),
        # 화면의 autoExcluded(실비만 입금·컨설팅 초과)와 같은 기준으로 기본 체크 여부를 정한다.
        "default_include": not (no_fee or out_of_scope),
    }


def scan_missing(
    db: Session,
    *,
    office_id: str,
    basis: Basis,
    from_year: int,
    from_month: int,
    to_year: int,
    to_month: int,
    current_year: int,
    current_month: int,
    max_months: int = MAX_MONTHS,
    registry_fetcher: Callable[..., set[str]] = fetch_registered_doc_ids,
) -> dict[str, Any]:
    """기간 내 회차별 보고 대상 중 협회 미등록(누락) 건을 모아 돌려준다."""
    months = _month_sequence(from_year, from_month, to_year, to_month)
    if not months:
        raise ValueError("시작 월이 끝 월보다 늦습니다.")
    if len(months) > max_months:
        raise ValueError(f"한 번에 최대 {max_months}개월까지만 조회할 수 있습니다.")

    # 1) 회차별 보고 대상 수집 (원본 DB). 같은 지사라 appcode 는 어느 회차에서 얻어도 같다.
    reportable: list[dict[str, Any]] = []
    appcode: str | None = None
    for year, month in months:
        for half in _HALVES:
            result = build_kapa_rows(
                db, office_id=office_id, year=year, month=month, half=half, basis=basis
            )
            appcode = result.get("appcode") or appcode
            for row in result.get("rows", []):
                reportable.append(_missing_row(row, year, month, half))

    # 2) 등록분 조회 (협회 서버, 달별 1회). 현재 보고달을 합쳐, 몰아 넣은 뒤 재스캔 시 사라지게 한다.
    if appcode is None:
        # 회차 전체가 0건이라 build 로 appcode 를 못 얻었다 — 누락도 없다.
        return _empty_result(basis, months, current_year, current_month)
    registry_months = {*months, (current_year, current_month)}
    registered_union: set[str] = set()
    for year, month in sorted(registry_months):
        registered_union |= registry_fetcher(appcode, quarter_bungi(year, month), month)

    # 3) 누락 = 보고 대상 − 등록분. 같은 감정서가 두 회차에 잡히면 한 번만(먼저 것) 남긴다.
    missing: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in reportable:
        doc_id = str(row.get("ID_NUM") or "").strip()
        if not doc_id or doc_id in registered_union or doc_id in seen:
            continue
        seen.add(doc_id)
        missing.append(row)

    return {
        "basis": basis,
        "from": f"{from_year}.{from_month:02d}",
        "to": f"{to_year}.{to_month:02d}",
        "current": {"year": current_year, "month": current_month},
        "scanned_months": [f"{y}.{m:02d}" for y, m in months],
        "registered_count": len(registered_union),
        "count": len(missing),
        "rows": missing,
    }


def _empty_result(
    basis: Basis, months: list[tuple[int, int]], current_year: int, current_month: int
) -> dict[str, Any]:
    return {
        "basis": basis,
        "from": f"{months[0][0]}.{months[0][1]:02d}",
        "to": f"{months[-1][0]}.{months[-1][1]:02d}",
        "current": {"year": current_year, "month": current_month},
        "scanned_months": [f"{y}.{m:02d}" for y, m in months],
        "registered_count": 0,
        "count": 0,
        "rows": [],
    }
