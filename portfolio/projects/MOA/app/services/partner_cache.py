"""아마란스 거래처를 통째로 받아 사업자번호 색인을 만든다.

왜 필요한가 — 카드전표 검증은 가맹점 사업자번호로 거래처를 찾는데, 아마란스는
한 건씩만 답한다(한 왕복 0.22초). 한 달치면 가맹점이 500곳을 넘어 그것만으로
2분이다 (2026-08-20 실측). 전체 61,000건을 하루 한 번 받아두면 조회가 우리
DB에서 끝난다.

캐시가 비었거나 낡아도 화면은 죽지 않는다 — 모르는 사업자번호는 예전처럼
아마란스에 직접 묻는다. 캐시는 빠르게 하는 장치일 뿐 판단 근거가 아니다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.amaranth.client import AmaranthClient
from app.models.partner_cache import PartnerCache

PAGE_SIZE = 1000       # api16S11 한 페이지 (1000까지 받는 것을 실측 확인)
MAX_PAGES = 200        # 20만 건 안전장치 — 현재 6.1만 건
LOOKUP_CHUNK = 500     # IN 절 한 번에 넣을 사업자번호 수


def _digits(value: Any) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("resultData")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("data", "datas", "list"):
            rows = data.get(key)
            if isinstance(rows, list):
                return [item for item in rows if isinstance(item, dict)]
    return []


def refresh_partner_cache(
    db: Session,
    client: AmaranthClient,
    company_code: str,
    *,
    progress=print,
) -> dict[str, int]:
    """거래처 전체를 다시 받아 캐시를 갈아끼운다.

    전부 모은 뒤에 한 번에 바꾼다 — 중간에 끊겨도 옛 캐시가 그대로 남아
    화면이 빈 캐시를 보는 일이 없다.
    """
    collected: dict[str, dict[str, str]] = {}
    for page in range(MAX_PAGES):
        rows = _rows(client.post(
            "/apiproxy/api16S11",
            json_body={"coCd": company_code, "usePagination": True,
                       "pagingOffset": page * PAGE_SIZE, "pagingCount": PAGE_SIZE},
        ))
        for row in rows:
            code = str(row.get("trCd") or "").strip()
            if not code:
                continue
            collected[code] = {
                "reg_no": _digits(row.get("regNb"))[:10],
                "partner_name": str(row.get("trNm") or "").strip()[:200],
                "partner_type": str(row.get("trFg") or "").strip()[:2],
                "use_yn": str(row.get("useYn") or "").strip()[:1],
            }
        progress(f"거래처 수집 {len(collected):,}건")
        if len(rows) < PAGE_SIZE:
            break

    if not collected:
        # 아마란스가 빈 응답을 준 회차에 멀쩡한 캐시를 지우면 안 된다.
        raise RuntimeError("거래처를 한 건도 받지 못했습니다. 캐시를 그대로 둡니다.")

    batch = int(db.execute(select(func.max(PartnerCache.sync_batch))).scalar() or 0) + 1
    now = datetime.now()
    db.execute(delete(PartnerCache))
    db.bulk_insert_mappings(PartnerCache, [
        {"partner_code": code, "synced_at": now, "sync_batch": batch, **values}
        for code, values in collected.items()
    ])
    db.commit()
    progress(f"거래처 캐시 갱신 완료: {len(collected):,}건")
    return {"stored": len(collected), "batch": batch}


def find_partners_by_reg_no(db: Session, reg_nos: set[str]) -> dict[str, dict[str, str]]:
    """사업자번호 → 거래처. 캐시에 없으면 그냥 빠진다(호출부가 아마란스에 묻는다).

    같은 사업자번호에 거래처가 여럿이면 사용중(useYn='1')을 먼저 고르고,
    그 안에서는 최근 등록분(코드가 큰 쪽)을 쓴다 — 카드 거래처 고르는 규칙과 같다.
    """
    wanted = sorted(r for r in reg_nos if len(r) == 10)
    if not wanted:
        return {}
    best: dict[str, tuple[bool, str, str]] = {}
    for start in range(0, len(wanted), LOOKUP_CHUNK):
        rows = db.execute(
            select(PartnerCache.reg_no, PartnerCache.partner_code,
                   PartnerCache.partner_name, PartnerCache.use_yn)
            .where(PartnerCache.reg_no.in_(wanted[start:start + LOOKUP_CHUNK]))
        ).all()
        for reg_no, code, name, use_yn in rows:
            rank = (str(use_yn) == "1", str(code))
            current = best.get(reg_no)
            if current is None or rank > (current[0], current[1]):
                best[reg_no] = (rank[0], str(code), str(name or ""))
    return {reg: {"code": code, "name": name} for reg, (_u, code, name) in best.items()}


# 캐시가 이만큼 안에 적재된 것이면 '여기 없다 = 아마란스에 없다'로 믿는다.
# 하루 한 번 적재이므로 한 번 걸러도 살아남게 넉넉히 잡는다.
FRESH_HOURS = 36


def is_fresh(db: Session, *, max_age_hours: int = FRESH_HOURS) -> bool:
    """캐시가 최근 것이고 비어 있지 않은가 — '없음'을 믿어도 되는지 판단한다."""
    status = cache_status(db)
    synced = status["synced_at"]
    if not status["rows"] or synced is None:
        return False
    return (datetime.now() - synced).total_seconds() <= max_age_hours * 3600


def cache_status(db: Session) -> dict[str, Any]:
    """캐시가 얼마나 차 있고 언제 것인지 — 배치·진단용."""
    row = db.execute(
        select(func.count(PartnerCache.partner_code), func.max(PartnerCache.synced_at))
    ).one()
    return {"rows": int(row[0] or 0), "synced_at": row[1]}
