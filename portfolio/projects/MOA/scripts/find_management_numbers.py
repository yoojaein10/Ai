"""Amaranth 자동전표에서 특정 관리번호 접두사를 읽기 전용으로 찾는다."""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select

from app.amaranth.client import AmaranthClient
from app.config import get_settings
from app.database import get_session_factory
from app.models.api_log import ApiLog


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", default="01-")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--max-pages", type=int, default=20)
    args = parser.parse_args()

    settings = get_settings()
    today = date.today()
    date_from = today - timedelta(days=args.days - 1)

    with get_session_factory()() as db:
        client = AmaranthClient(db, settings=settings)
        company_code = _company_code(db, client)
        divisions = _division_codes(client, company_code)
        matches: list[dict[str, Any]] = []
        scanned = 0

        for division_code in divisions:
            for page in range(1, args.max_pages + 1):
                payload = client.post(
                    "/apiproxy/api11A16",
                    json_body={
                        "coCd": company_code,
                        "groupSeq": settings.a10_group_seq,
                        "divCd": division_code,
                        "frDt": date_from.strftime("%Y%m%d"),
                        "toDt": today.strftime("%Y%m%d"),
                        "viewPage": page,
                        "viewCount": 100,
                    },
                )
                rows, total = _rows_and_total(payload)
                scanned += len(rows)
                for row in rows:
                    for line in _walk_dicts(row):
                        management_no = str(
                            line.get("maNb")
                            or line.get("MANB")
                            or line.get("ma_nb")
                            or ""
                        ).strip()
                        if management_no.startswith(args.prefix):
                            matches.append(
                                {
                                    "management_no": management_no,
                                    "voucher_date": line.get("menuDt")
                                    or line.get("isuDt")
                                    or row.get("menuDt")
                                    or row.get("isuDt"),
                                    "voucher_no": line.get("menuSq")
                                    or line.get("isuSq")
                                    or row.get("menuSq")
                                    or row.get("isuSq"),
                                    "division_code": division_code,
                                    "account_code": line.get("acctCd"),
                                    "amount": line.get("acctAm"),
                                }
                            )
                if not rows or page * 100 >= total:
                    break

    unique = list({json.dumps(item, ensure_ascii=False, sort_keys=True): item for item in matches}.values())
    unique.sort(key=lambda item: str(item.get("voucher_date") or ""), reverse=True)
    print(
        json.dumps(
            {
                "date_from": date_from.isoformat(),
                "date_to": today.isoformat(),
                "scanned_rows": scanned,
                "match_count": len(unique),
                "matches": unique[:50],
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )


def _company_code(db: Any, client: AmaranthClient) -> str:
    latest = db.scalars(
        select(ApiLog)
        .where(ApiLog.endpoint == "/apiproxy/api16S08", ApiLog.http_status == 200)
        .order_by(ApiLog.id.desc())
        .limit(1)
    ).first()
    if latest and latest.res_body:
        rows = _result_rows(json.loads(latest.res_body))
        if rows:
            value = rows[0].get("coCd") or rows[0].get("outCoCd")
            if value:
                return str(value)
    payload = client.post("/apiproxy/api16S08", json_body={})
    rows = _result_rows(payload)
    if not rows:
        raise RuntimeError("회사코드를 찾지 못했습니다.")
    return str(rows[0].get("coCd") or rows[0].get("outCoCd"))


def _division_codes(client: AmaranthClient, company_code: str) -> list[str]:
    payload = client.post(
        "/apiproxy/api16S09", json_body={"coCd": company_code}
    )
    values = []
    for row in _result_rows(payload):
        code = row.get("divCd") or row.get("outDivCd")
        if code:
            values.append(str(code))
    if not values:
        raise RuntimeError("회계단위 코드를 찾지 못했습니다.")
    return list(dict.fromkeys(values))


def _rows_and_total(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    data = payload.get("resultData")
    if not isinstance(data, dict):
        rows = _result_rows(payload)
        return rows, len(rows)
    rows = _result_rows(payload)
    total = int(data.get("totalCount") or data.get("allCount") or len(rows))
    return rows, total


def _result_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("resultData")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("data", "datas", "list"):
            rows = data.get(key)
            if isinstance(rows, list):
                return [item for item in rows if isinstance(item, dict)]
    return []


def _walk_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _walk_dicts(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_dicts(item)


if __name__ == "__main__":
    main()
