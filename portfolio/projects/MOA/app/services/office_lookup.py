"""지사(apw_office) ↔ Amaranth 사업장(회계단위) 매칭과 a10_office_map 조회 헬퍼."""

import json
import re
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.amaranth.client import AmaranthClient
from app.config import get_settings
from app.models.api_log import ApiLog
from app.models.office_map import OfficeMap


def normalize_office_name(value: Any) -> str:
    name = str(value or "").lower()
    name = re.sub(r"\(주\)|주식회사|대화감정평가법인", "", name)
    name = re.sub(r"[^0-9a-z가-힣]", "", name)
    aliases = {
        "": "본사",
        "대구": "대구경북",
        "부산": "부산경남",
        "경남중앙지사": "경남중앙",
    }
    name = name.removesuffix("지사")
    return aliases.get(name, name)


def result_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("resultData")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("result", "list", "data", "rows"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def fetch_divisions(db: Session) -> tuple[list[dict[str, Any]], str]:
    """Amaranth 사업장 목록. ApiLog 캐시 우선, 장애 시 빈 목록으로 폴백."""
    divisions: list[dict[str, Any]] = []
    source = "apw_office"
    try:
        cached = db.scalars(
            select(ApiLog)
            .where(
                ApiLog.endpoint == "/apiproxy/api16S09",
                ApiLog.http_status == 200,
            )
            .order_by(ApiLog.id.desc())
            .limit(1)
        ).first()
        if cached and cached.res_body:
            divisions = result_rows(json.loads(cached.res_body))
            source = "apw_office+amaranth_cache"
        else:
            client = AmaranthClient(db)
            companies = result_rows(client.post("/apiproxy/api16S08", json_body={}))
            company_code = str(
                (companies[0].get("coCd") or companies[0].get("outCoCd"))
                if companies else ""
            )
            if company_code:
                divisions = result_rows(
                    client.post("/apiproxy/api16S09", json_body={"coCd": company_code})
                )
                source = "apw_office+amaranth"
    except Exception:
        # 외부 회계단위 조회 장애가 지사 목록 조회 자체를 막지 않도록 한다.
        db.rollback()
    return divisions, source


def match_offices_to_divisions(db: Session) -> dict[str, Any]:
    """apw_office 활성 지사에 Amaranth 사업장(회계단위)을 이름 정규화로 매칭한다."""
    database = _source_database()
    rows = db.execute(
        text(
            f"SELECT RTRIM(OfficeID) AS office_code, RTRIM(Name) AS office_name, SEQ AS seq "
            f"FROM [{database}].dbo.apw_office "
            "WHERE Active = 'Y' ORDER BY SEQ"
        )
    ).mappings().all()
    divisions, source = fetch_divisions(db)
    division_by_name = {
        normalize_office_name(item.get("divNm") or item.get("outDivNm")): item
        for item in divisions
    }
    items = []
    for row in rows:
        division = division_by_name.get(normalize_office_name(row["office_name"]))
        items.append(
            {
                "office_code": row["office_code"],
                "office_name": row["office_name"],
                "sort_order": row["seq"],
                "division_code": (
                    str(division.get("divCd") or division.get("outDivCd"))
                    if division else None
                ),
                "division_name": (
                    division.get("divNm") or division.get("outDivNm")
                    if division else None
                ),
            }
        )
    return {"items": items, "count": len(items), "source": source}


def get_office(db: Session, office_code: str) -> OfficeMap | None:
    return db.scalars(
        select(OfficeMap).where(
            OfficeMap.office_id == office_code, OfficeMap.active == "Y"
        )
    ).first()


def active_offices(db: Session) -> list[OfficeMap]:
    return list(
        db.scalars(
            select(OfficeMap)
            .where(OfficeMap.active == "Y")
            .order_by(OfficeMap.sort_order, OfficeMap.office_id)
        ).all()
    )


def docid_prefixes(db: Session, office_code: str | None) -> list[str]:
    """지사 지정 시 해당 접두사 1개, None(전체)이면 활성 지사 접두사 전체.

    지정 지사가 매핑에 없으면 LookupError.
    """
    if office_code:
        office = get_office(db, office_code)
        if office is None:
            raise LookupError(f"지사 매핑이 없습니다: {office_code}")
        return [office.docid_prefix]
    return [office.docid_prefix for office in active_offices(db)]


def _source_database() -> str:
    database = get_settings().mssql_source_db
    if not database.replace("_", "").isalnum():
        raise RuntimeError("MSSQL_SOURCE_DB 이름이 올바르지 않습니다.")
    return database
