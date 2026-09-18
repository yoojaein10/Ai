"""감정서번호로 Amaranth 원장을 여러 달 훑어 관련 전표를 찾는다 (읽기 전용).

diagnose_missing_voucher.py는 --date 하루만 보지만, 이 스크립트는 기간을 월별로
훑으며 **관리번호(ctNb)와 적요(rmkDc) 둘 다**에서 감정서번호를 찾는다. 대화 더존은
합산청구·분기정산 전표에서 감정서번호를 적요에만 적으므로(관리번호는 '○○○외'·'4'·빈값),
적요를 안 보면 "미계상"으로 오판한다(2026-07-24 실제 3회 오판 후 추가).

사용법:
  python -m scripts.find_voucher_by_docid --docid 01-2512-5-0189
  python -m scripts.find_voucher_by_docid --docid 01-2601-4-0003 --from 2025-11 --to 2026-07
"""

import argparse
from datetime import date, timedelta

from app.amaranth.client import AmaranthClient
from app.database import get_session_factory
from scripts.find_management_numbers import _company_code, _division_codes


def _month_iter(y1: int, m1: int, y2: int, m2: int):
    y, m = y1, m1
    while (y, m) <= (y2, m2):
        first = date(y, m, 1)
        last = (date(y + (m == 12), (m % 12) + 1, 1)) - timedelta(days=1)
        yield first, last
        m += 1
        if m > 12:
            y, m = y + 1, 1


def _needles(docid: str) -> "list[str]":
    """감정서번호를 여러 표기로: 원형, 하이픈제거, '01-' 접두어 제거(합산 적요는 접두어 없음)."""
    forms = {docid, docid.replace("-", "")}
    if "-" in docid:  # 01-2512-5-0189 -> 2512-5-0189 (합산 적요 표기)
        rest = docid.split("-", 1)[1]
        forms.add(rest)
        forms.add(rest.replace("-", ""))
    return [f for f in forms if len(f) >= 6]


def _hit(docid: str, row: dict) -> str:
    needles = _needles(docid)
    ctnb = str(row.get("ctNb") or "")
    # 라인 적요(rmkDc) + 전표 요약 적요(isuDoc). 합산청구 개별번호는 isuDoc에만 있다.
    remark = f"{row.get('rmkDc') or ''} {row.get('isuDoc') or ''}"
    if any(n in ctnb or n in ctnb.replace("-", "") for n in needles):
        return "관리번호"
    if any(n in remark or n in remark.replace("-", "") for n in needles):
        return "적요"
    return ""


def _parse_ym(value: str, default: "tuple[int, int]") -> "tuple[int, int]":
    if not value:
        return default
    v = value.replace("-", "").replace(".", "")
    return int(v[:4]), int(v[4:6])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--docid", required=True, help="감정서(관리)번호")
    parser.add_argument("--from", dest="ym_from", default="", help="시작 YYYY-MM (기본 2025-11)")
    parser.add_argument("--to", dest="ym_to", default="", help="종료 YYYY-MM (기본 2026-07)")
    args = parser.parse_args()

    y1, m1 = _parse_ym(args.ym_from, (2025, 11))
    y2, m2 = _parse_ym(args.ym_to, (2026, 7))
    print(f"검색: {args.docid} / {y1}-{m1:02d} ~ {y2}-{m2:02d} (관리번호 + 적요)\n")

    with get_session_factory()() as db:
        client = AmaranthClient(db)
        company_code = _company_code(db, client)
        division_filter = "|".join(_division_codes(client, company_code)) + "|"

        hits = []
        for d1, d2 in _month_iter(y1, m1, y2, m2):
            page = 1
            while True:
                payload = client.post(
                    "/apiproxy/api11A14",
                    json_body={
                        "coCd": company_code, "divCds": division_filter,
                        "isuDtFr": d1.strftime("%Y%m%d"), "isuDtTo": d2.strftime("%Y%m%d"),
                        "viewPage": page, "viewCount": 1000, "isAllTrCd": "1", "trCds": "",
                        "docuStStr": "1|0|", "docuTyStr": "1|2|3|4|5|6|7|8|9|",
                    },
                )
                data = payload.get("resultData") or {}
                rows = data.get("datas") or data.get("data") or []
                total = int(data.get("allCount") or data.get("totalCount") or len(rows))
                for row in rows:
                    where = _hit(args.docid, row)
                    if where:
                        hits.append((where, row))
                if not rows or page * 1000 >= total:
                    break
                page += 1
            print(f"  스캔 {d1.strftime('%Y-%m')} 완료", flush=True)

        print(f"\n=== 결과: {len(hits)}건 ===")
        has_sales = False
        for where, r in hits:
            acct = str(r.get("acctCd") or "")
            if acct.startswith("401"):
                has_sales = True
            print(f"  {r.get('isuDt')} 전표{r.get('isuSq')} div={r.get('divCd')} "
                  f"{acct}({r.get('acctNm')}) 차대={r.get('drcrFg')} {r.get('acctAm')} "
                  f"관리번호=[{r.get('ctNb')}] <{where}> 적요={str(r.get('rmkDc') or '')[:35]}")

        print("\n=== 판정 ===")
        if not hits:
            print("  더존에 전표 없음 -> 진짜 미계상. 회계팀 신규 계상 대상.")
        elif has_sales:
            only_remark = all(w == "적요" for w, _ in hits if str(_.get("acctCd") or "").startswith("401"))
            note = " (관리번호엔 없고 적요에만 -> 합산청구/정산에 묶임)" if only_remark else ""
            print(f"  매출(401) 전표 있음 -> 장부·합계에 포함. 미계상 아님{note}.")
        else:
            print("  매출(401) 라인은 없고 채권/부가세만 있음 -> 매출 계상 누락 가능. 전표 상세 확인 필요.")


if __name__ == "__main__":
    main()
