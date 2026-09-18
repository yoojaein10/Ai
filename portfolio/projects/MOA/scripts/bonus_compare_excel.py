"""새 상여 엔진 ↔ 재무팀 엑셀 지급 시트 대조 (2단계 15 오라클).

    python -m scripts.bonus_compare_excel --xlsx "C:\\...\\★★2026년 성과상여.xlsx" --period 202608 [--json out.json]

지급월 202608 = 시트 '26.08월-주주'·'26.08월-평.동' (입금월 2026-07). 목표: 감정서 ≥ 515/528,
(감정서,사람) 산정 1% 이내 ≥ 269, 수기 항목 없는 사람의 Y·소득세·지급 일치.
"""

import argparse
import json
import time
from datetime import date

from openpyxl import load_workbook

from app.database import get_session_factory
from app.services.bonus.excel_compare import compare, read_associate_sheet, read_shareholder_sheet
from app.services.bonus import closing
from app.services.bonus.report import Readers, bonus_report_v2


def sheet_names(period: str) -> "tuple[str, str]":
    tag = f"{period[2:4]}.{period[4:6]}월"
    return f"{tag}-주주", f"{tag}-평.동"


def run(db, workbook_path: str, period: str, *, recompute: bool = False) -> "dict":
    started = time.time()
    readers = None
    if recompute:   # 마감된 달도 스냅샷 대신 다시 계산해 본다 (공제 대장 시딩 검증용) — 그 달 자신의 스냅샷은 기지급에서 뺀다
        readers = Readers(
            close_status=lambda db, p: None,
            already_paid=lambda db, docs: closing.already_paid(db, docs, exclude_period=period),
            sync_voucher_candidates=lambda db, rows, ratios, **kw: [],
        )
    report = bonus_report_v2(db, period, readers=readers)
    took = time.time() - started
    wb = load_workbook(workbook_path, data_only=True, read_only=False)
    ju, pd = sheet_names(period)
    result = compare(report, read_shareholder_sheet(wb[ju]), read_associate_sheet(wb[pd]))
    result["took_seconds"] = round(took, 1)
    result["warnings"] = report.get("warnings", [])
    result["held"] = report.get("held", [])
    result["status"] = report.get("status")
    return result


def print_report(result: "dict") -> None:
    docs, pairs = result["docs"], result["pairs"]
    print(f"[감정서] 엑셀 {docs['excel']} · 엔진 {docs['engine']} · 겹침 {docs['both']} · 엑셀만 {len(docs['excel_only'])} · 엔진만 {len(docs['engine_only'])} · 보류인데 엑셀에 있음 {len(docs['held_in_excel'])}  ({result['took_seconds']}s)")
    print(f"  엑셀만: {docs['excel_only'][:12]}")
    print(f"  엔진만: {docs['engine_only'][:12]}")
    print(f"[감정서×사람] 엑셀 {pairs['excel']} · 엔진 {pairs['engine']} · 겹침 {pairs['both']} · 산정 1% 이내 {pairs['close']}")
    persons = result["persons"]
    exact = sum(1 for p in persons if p["payment_exact"])
    close = sum(1 for p in persons if p["pretax_close"])
    print(f"[사람] {len(persons)}명 · 지급액 정확 일치 {exact} · 산정금액 1% 이내 {close}")
    print("  차이 큰 순:")
    for p in persons[:25]:
        e, x = p["engine"], p["excel"]
        print(f"   {p['name']:5s} {p['kind'][:4]:4s} 산정 엔진 {e['pretax']:>13,.0f} 엑셀 {x['pretax']:>13,.0f} 차 {p['gap']:>+13,.0f} | 지급 엔진 {e['payment']:>12,.0f} 엑셀 {x['payment']:>12,.0f}")
    print(f"[경고] {len(result['warnings'])}건 (앞 8건)")
    for w in result["warnings"][:8]:
        print("   -", w)


def main() -> None:
    parser = argparse.ArgumentParser(description="새 상여 엔진 ↔ 엑셀 지급 시트 대조")
    parser.add_argument("--xlsx", required=True)
    parser.add_argument("--period", required=True, help="지급월 YYYYMM (시트 'YY.MM월-주주')")
    parser.add_argument("--json", help="결과를 JSON 으로 저장할 경로")
    parser.add_argument("--recompute", action="store_true", help="마감된 달도 스냅샷 대신 엔진으로 다시 계산해 대조한다")
    args = parser.parse_args()
    db = get_session_factory()()
    try:
        result = run(db, args.xlsx, args.period, recompute=args.recompute)
    finally:
        db.close()
    print_report(result)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=1, default=str)
        print("저장:", args.json)


if __name__ == "__main__":
    main()
