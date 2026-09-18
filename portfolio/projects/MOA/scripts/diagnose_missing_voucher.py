"""특정 전표가 Amaranth API 응답에 실제로 들어오는지 확인하는 읽기 전용 진단.

캐시(a10_voucher_cache)를 전혀 건드리지 않는다 - 동기화가 쓰는 것과 똑같은
API(/apiproxy/api11A14)를 같은 파라미터로 호출해 원본 응답을 뒤진다.

목적: "더존엔 있는데 우리 화면엔 없는" 전표의 원인 구분
  (A) API가 아예 안 넘겨줌     -> 동기화 필터 문제, 백필해도 소용없음
  (B) API는 넘겨주는데 캐시에 없음 -> 소급 입력 등, 백필로 해결
  (C) API가 넘겨주고 캐시에도 있음 -> 집계/조회 조건 문제

사용법 (서버 또는 개발 PC에서):
  python -m scripts.diagnose_missing_voucher --date 2026-01-02 --docid 01-2512-A-0187
  python -m scripts.diagnose_missing_voucher --date 2026-01-02 --voucher 00201 --amount 2727273
"""

import argparse
import json
from datetime import date

from sqlalchemy import text

from app.amaranth.client import AmaranthClient
from app.database import get_session_factory
from scripts.find_management_numbers import _company_code, _division_codes


def _parse_date_arg(value: str) -> date:
    v = value.replace("-", "").replace(".", "")
    return date(int(v[:4]), int(v[4:6]), int(v[6:8]))


def _needles(docid: str) -> "list[str]":
    """감정서번호 표기 변형: 원형, 하이픈제거, '01-' 접두어 제거(합산 적요는 접두어 없음)."""
    forms = {docid, docid.replace("-", "")}
    if "-" in docid:
        rest = docid.split("-", 1)[1]
        forms.add(rest)
        forms.add(rest.replace("-", ""))
    return [f for f in forms if len(f) >= 6]


def _docid_in(docid: str, row: dict) -> str:
    """감정서번호가 관리번호(ctNb) 또는 적요(rmkDc/isuDoc)에 있으면 어디서 찾았는지 반환.

    대화 더존은 합산청구/분기정산 전표에서 감정서번호를 관리번호에 안 넣고(관리번호는
    '○○○외'·'4'·빈값) 전표 요약 적요(isuDoc)에만 '2512-5-0189'처럼 접두어 없이 적는다.
    그래서 관리번호+라인적요(rmkDc)+요약적요(isuDoc)를, 접두어/하이픈 변형까지 본다.
    """
    needles = _needles(docid)
    ctnb = str(row.get("ctNb") or "")
    remark = f"{row.get('rmkDc') or ''} {row.get('isuDoc') or ''}"
    if any(n in ctnb or n in ctnb.replace("-", "") for n in needles):
        return "관리번호"
    if any(n in remark or n in remark.replace("-", "") for n in needles):
        return "적요"
    return ""


def _matches(row: dict, docid: str, voucher: str, amount: str) -> bool:
    if docid and not _docid_in(docid, row):
        return False
    if voucher and str(row.get("isuSq") or "").strip() != voucher:
        return False
    if amount and str(row.get("acctAm") or "").replace(".0", "") != amount:
        return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="전표일자 YYYY-MM-DD")
    parser.add_argument("--docid", default="", help="감정서(관리)번호로 필터")
    parser.add_argument("--voucher", default="", help="전표번호(isuSq)로 필터")
    parser.add_argument("--amount", default="", help="금액으로 필터")
    args = parser.parse_args()

    target = _parse_date_arg(args.date)
    filters = {k: v for k, v in (("docid", args.docid), ("voucher", args.voucher), ("amount", args.amount)) if v}
    print(f"진단 대상: {target} / 필터 {filters or '(없음 - 그날 전체)'}\n")

    with get_session_factory()() as db:
        client = AmaranthClient(db)
        company_code = _company_code(db, client)
        divisions = _division_codes(client, company_code)
        division_filter = "|".join(divisions) + "|"
        print(f"회사코드={company_code}, 회계단위 {len(divisions)}개: {divisions}\n")

        # ── 1) API 원본 응답에서 대상 전표 탐색 (동기화와 동일 파라미터) ──
        found_rows = []
        day_total = 0
        page = 1
        while True:
            payload = client.post(
                "/apiproxy/api11A14",
                json_body={
                    "coCd": company_code,
                    "divCds": division_filter,
                    "isuDtFr": target.strftime("%Y%m%d"),
                    "isuDtTo": target.strftime("%Y%m%d"),
                    "viewPage": page,
                    "viewCount": 1000,
                    "isAllTrCd": "1",
                    "trCds": "",
                    "docuStStr": "1|0|",
                    "docuTyStr": "1|2|3|4|5|6|7|8|9|",
                },
            )
            data = payload.get("resultData") or {}
            page_rows = data.get("datas") or data.get("data") or []
            day_total = int(data.get("allCount") or data.get("totalCount") or len(page_rows))
            for row in page_rows:
                if _matches(row, args.docid, args.voucher, args.amount):
                    found_rows.append(row)
            if not page_rows or page * 1000 >= day_total:
                break
            page += 1

        print(f"[API] {target} 전체 전표 라인 {day_total:,}건 조회")
        print(f"[API] 대상 조건 일치: {len(found_rows)}건")
        for r in found_rows:
            where = _docid_in(args.docid, r) if args.docid else ""
            tag = f" <매칭:{where}>" if where else ""
            print(f"   전표{r.get('isuSq')} div={r.get('divCd')} 계정={r.get('acctCd')}({r.get('acctNm')}) "
                  f"차대={r.get('drcrFg')} 금액={r.get('acctAm')} 관리번호=[{r.get('ctNb')}] "
                  f"문서상태={r.get('docuSt')} 적요={str(r.get('rmkDc') or '')[:40]}{tag}")

        # ── 2) 같은 조건이 현재 캐시에 있는지 (관리번호 OR 적요) ──
        where = ["voucher_date = :d"]
        params = {"d": target}
        if args.docid:
            # 관리번호에 있거나 적요에 있으면 잡는다 (합산청구·정산 전표 대응)
            where.append("(LTRIM(RTRIM(management_no)) LIKE CAST(:doclike AS varchar(120)) "
                         "OR remark LIKE CAST(:doclike AS nvarchar(200)))")
            params["doclike"] = f"%{args.docid}%"
        if args.voucher:
            where.append("voucher_no = CAST(:vno AS varchar(50))")
            params["vno"] = args.voucher
        cache_rows = db.execute(
            text(f"SELECT account_code, division_code, debit_credit, amount, "
                 f"LTRIM(RTRIM(management_no)) AS mgmt, remark FROM dbo.a10_voucher_cache "
                 f"WHERE {' AND '.join(where)}"),
            params,
        ).mappings().all()
        print(f"\n[캐시] 같은 조건 저장분(관리번호 또는 적요): {len(cache_rows)}건")
        for r in cache_rows:
            src = "적요" if args.docid and args.docid not in (r["mgmt"] or "") else "관리번호"
            print(f"   {r['account_code']} div={r['division_code']} dc={r['debit_credit']} "
                  f"{float(r['amount']):,.0f} [{r['mgmt']}] <{src}> {str(r['remark'] or '')[:30]}")

        # ── 3) 판정 ──
        # 매출(401) 라인 기준으로 본다. 401 라인이 적요로만 잡히고 관리번호엔 없으면
        # 합산청구/정산 전표에 묶인 것(매출은 합계에 있으나 감정서 attribution만 어긋남).
        sales_rows = [r for r in found_rows if str(r.get("acctCd") or "").startswith("401")]
        via_remark = (
            args.docid and sales_rows
            and all(_docid_in(args.docid, r) == "적요" for r in sales_rows)
        )
        print("\n=== 판정 ===")
        if via_remark:
            print("  (D) 관리번호엔 없고 적요에만 있음 -> 합산청구/정산 전표에 묶여 계상됨.")
            print("      매출은 장부·합계에 이미 포함(관리번호가 '○○○외'·'4'·빈값이라 감정서 attribution만 어긋남).")
            print("      => 미계상 아님. 회계팀 신규 계상 대상 아님.")
        elif found_rows and not cache_rows:
            print("  (B) API는 넘겨주는데 캐시에 없음 -> 소급 입력 등. 해당 기간 백필하면 반영됨.")
            print("      div/문서상태를 위에서 확인 - 우리가 긁는 회계단위·문서상태 범위 안인지 볼 것.")
        elif found_rows and cache_rows:
            print("  (C) API·캐시 모두 있음 -> 집계/조회 조건(계정·사업장·기간) 문제. 위 계정코드 확인.")
        elif not found_rows:
            print("  (A) API가 이 전표를 안 넘겨줌 -> 백필해도 안 들어옴.")
            print("      원인 후보: 회계단위(divCds) 밖 / 문서상태(docuStStr) 밖 / 문서유형(docuTyStr) 밖.")
            print("      단, 이 스크립트는 --date 하루만 본다. 합산청구는 다른 날짜 전표일 수 있으니")
            print("      관리번호/적요로 여러 날짜를 훑는 verify_douzone류 스캔으로 재확인할 것.")

        # ── 4) 참고: 그날 API가 준 div·계정 분포 (필터 진단용) ──
        if not args.docid and not args.voucher:
            return
        print(f"\n[참고] {target} API 응답의 회계단위 분포:")
        div_seen = {}
        page = 1
        while True:
            payload = client.post(
                "/apiproxy/api11A14",
                json_body={
                    "coCd": company_code, "divCds": division_filter,
                    "isuDtFr": target.strftime("%Y%m%d"), "isuDtTo": target.strftime("%Y%m%d"),
                    "viewPage": page, "viewCount": 1000, "isAllTrCd": "1", "trCds": "",
                    "docuStStr": "1|0|", "docuTyStr": "1|2|3|4|5|6|7|8|9|",
                },
            )
            data = payload.get("resultData") or {}
            page_rows = data.get("datas") or data.get("data") or []
            for row in page_rows:
                div_seen[str(row.get("divCd"))] = div_seen.get(str(row.get("divCd")), 0) + 1
            if not page_rows or page * 1000 >= int(data.get("allCount") or len(page_rows)):
                break
            page += 1
        print(f"   {div_seen}")


if __name__ == "__main__":
    main()
