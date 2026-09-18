"""최근 일반/승인 전표에서 특정 값 접두사를 읽기 전용으로 찾는다."""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from typing import Any

from app.amaranth.client import AmaranthClient
from app.config import get_settings
from app.database import get_session_factory
from scripts.find_management_numbers import _company_code, _division_codes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", default="01-")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--max-pages", type=int, default=30)
    args = parser.parse_args()

    today = date.today()
    date_from = today - timedelta(days=args.days - 1)
    settings = get_settings()
    matches: list[dict[str, Any]] = []
    scanned = 0

    with get_session_factory()() as db:
        client = AmaranthClient(db, settings=settings)
        company_code = _company_code(db, client)
        divisions = _division_codes(client, company_code)
        division_filter = "|".join(divisions) + "|"

        for page in range(1, args.max_pages + 1):
            payload = client.post(
                "/apiproxy/api11A14",
                json_body={
                    "coCd": company_code,
                    "divCds": division_filter,
                    "isuDtFr": date_from.strftime("%Y%m%d"),
                    "isuDtTo": today.strftime("%Y%m%d"),
                    "viewPage": page,
                    "viewCount": 100,
                    "isAllTrCd": "1",
                    "trCds": "",
                    "docuStStr": "1|0|",
                    "docuTyStr": "1|2|3|4|5|6|7|8|9|",
                },
            )
            data = payload.get("resultData") or {}
            rows = data.get("datas") or data.get("data") or []
            total = int(data.get("allCount") or data.get("totalCount") or len(rows))
            scanned += len(rows)
            for row in rows:
                for path, value in _walk_values(row):
                    if isinstance(value, str) and value.strip().startswith(args.prefix):
                        matches.append(
                            {
                                "matched_field": path,
                                "matched_value": value.strip(),
                                "voucher_date": row.get("isuDt"),
                                "voucher_no": row.get("isuSq"),
                                "line_no": row.get("lnSq"),
                                "account_code": row.get("acctCd"),
                                "account_name": row.get("acctNm"),
                                "amount": row.get("acctAm"),
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
                "scanned_lines": scanned,
                "match_count": len(unique),
                "matches": unique[:100],
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )


def _walk_values(value: Any, path: str = ""):
    if isinstance(value, dict):
        for key, item in value.items():
            current = f"{path}.{key}" if path else str(key)
            yield from _walk_values(item, current)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk_values(item, f"{path}[{index}]")
    else:
        yield path, value


if __name__ == "__main__":
    main()
