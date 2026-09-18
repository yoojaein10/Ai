"""성과상여 마스터 초기값 시딩 — 재무팀 엑셀에서 사람·요율·지분을 읽어 넣는다.

    python -m scripts.seed_bonus_master --xlsx "C:\\...\\★★2026년 성과상여.xlsx" --dry-run
    python -m scripts.seed_bonus_master --xlsx "..." [--force]

- 이미 값이 있는 사람(요율)·감정서(지분)는 건너뛴다(skipped). --force 면 덮어쓴다.
- 라벨을 날짜로 못 읽은 블록이 있는 사람은 요율을 **안 넣는다**(unknown_labels) —
  반쪽짜리 요율표는 없는 것보다 위험하다.
- 직원 명부에 없는 이름은 넣되 unknown_names 로 보고한다.
"""

import argparse
from collections import defaultdict
from typing import Any

from sqlalchemy import select, text

from app.database import get_session_factory
from app.models.bonus_person import BonusPerson
from app.services.bonus import excel_seed
from app.services.bonus.schedule import (
    BonusMasterError,
    RateBlock,
    load_schedule,
    normalize_blocks,
    parse_rate_label,
    save_rates,
)
from app.services.bonus.shares import load_shares, save_shares


def _seed_persons(db, people, *, dry_run: bool, force: bool) -> "dict[str, int]":
    counts = {"written": 0, "skipped": 0}
    existing = {row.person: row for row in db.scalars(select(BonusPerson)).all()}
    for person in people:
        row = existing.get(person["person"])
        if row is not None and row.active == "Y" and not force:
            counts["skipped"] += 1
            continue
        counts["written"] += 1
        if dry_run:
            continue
        if row is None:
            db.add(BonusPerson(
                person=person["person"], kind=person["kind"], pay_ratio=person["pay_ratio"],
                tax_rate=person["tax_rate"], active="Y",
            ))
        else:
            row.kind, row.pay_ratio, row.tax_rate, row.active = (
                person["kind"], person["pay_ratio"], person["tax_rate"], "Y"
            )
    if not dry_run:
        db.commit()
    return counts


def _rate_rows(person: str, blocks: "list[dict[str, Any]]") -> "tuple[list[dict[str, Any]], list[str]]":
    rows, unknown = [], []
    for block in blocks:
        if block["rate"] is None:
            continue  # 요율 수식이 없는 블록(빈 옛 구간)은 표가 아니다
        intervals = parse_rate_label(block["label"])
        if not intervals:
            unknown.append(block["label"])
            continue
        rows += [
            {"from_date": start, "to_date": end, "rate": block["rate"], "label": block["label"]}
            for start, end in intervals
        ]
    return rows, unknown


def _seed_rates(db, rate_blocks, report, *, dry_run: bool, force: bool) -> None:
    counts = report["rates"]
    existing = set(load_schedule(db))
    for person, info in rate_blocks.items():
        rows, unknown = _rate_rows(person, info["blocks"])
        if unknown:
            report["unknown_labels"] += [(person, label) for label in unknown]
            continue
        if not rows:
            continue
        if person in existing and not force:
            counts["skipped"] += 1
            continue
        try:
            normalize_blocks([RateBlock(person, r["from_date"], r["to_date"], r["rate"], r["label"]) for r in rows])
        except BonusMasterError as exc:
            counts["conflict"].append((person, str(exc)))
            continue
        counts["written"] += 1
        if not dry_run:
            save_rates(db, person, rows, source="SEED")


def _seed_shares(db, share_rows, counts, *, dry_run: bool, force: bool) -> None:
    by_doc: "dict[str, list[dict[str, Any]]]" = defaultdict(list)
    for row in share_rows:
        by_doc[row["doc_id"]].append(row)
    existing = set(load_shares(db, list(by_doc)))
    for doc, rows in by_doc.items():
        if doc in existing and not force:
            counts["skipped"] += 1
            continue
        counts["written"] += 1
        if not dry_run:
            save_shares(db, doc, [
                {"person": r["person"], "share_pct": r["share_pct"], "bc_pct": r["bc_pct"], "note": r["note"]}
                for r in rows
            ], source="SEED")


def seed(
    db, workbook_path, *, dry_run: bool = False, force: bool = False,
    known_names: "set[str] | None" = None,
) -> "dict[str, Any]":
    """엑셀 → 마스터. 무엇을 했는지(하려는지) 돌려준다."""
    wb_f = excel_seed.open_formulas(workbook_path)
    wb_v = excel_seed.open_values(workbook_path)
    rate_blocks = excel_seed.read_rate_blocks(wb_f)
    params = excel_seed.read_associate_params(wb_f)
    share_rows = excel_seed.read_share_rows(wb_f, wb_v)
    people = excel_seed.read_person_list(rate_blocks, params)

    report: "dict[str, Any]" = {
        "dry_run": dry_run,
        "persons": {"written": 0, "skipped": 0},
        "rates": {"written": 0, "skipped": 0, "conflict": []},
        "shares": {"written": 0, "skipped": 0},
        "unknown_labels": [],
        "unknown_names": [],
    }
    report["persons"] = _seed_persons(db, people, dry_run=dry_run, force=force)
    _seed_rates(db, rate_blocks, report, dry_run=dry_run, force=force)
    _seed_shares(db, share_rows, report["shares"], dry_run=dry_run, force=force)
    if known_names is not None:
        report["unknown_names"] = sorted(p["person"] for p in people if p["person"] not in known_names)
    return report


def known_names_from_db(db) -> "set[str] | None":
    """직원 명부(TMWCMN_USR_BAC_INFO.EMP ∪ Seat_userinfo.Uname). 원천 DB가 없으면 None."""
    from app.config import get_settings

    database = get_settings().mssql_source_db
    try:
        rows = db.execute(text(
            f"SELECT RTRIM(EMP) FROM [{database}].dbo.TMWCMN_USR_BAC_INFO WHERE EMP IS NOT NULL "
            f"UNION SELECT RTRIM(Uname) FROM [{database}].dbo.Seat_userinfo WHERE Uname IS NOT NULL"
        )).all()
    except Exception:  # noqa: BLE001 — 명부 없이도 시딩은 되어야 한다
        return None
    return {row[0] for row in rows if row[0]}


def main() -> None:
    parser = argparse.ArgumentParser(description="성과상여 마스터 초기값 시딩")
    parser.add_argument("--xlsx", required=True, help="재무팀 성과상여 엑셀 경로")
    parser.add_argument("--force", action="store_true", help="이미 있는 사람·감정서 값을 덮어쓴다")
    parser.add_argument("--dry-run", action="store_true", help="읽기만 하고 저장하지 않는다")
    parser.add_argument("--history", action="store_true", help="월 시트를 EXCEL 마감 이력(a10_bonus_close/result)으로 넣는다")
    parser.add_argument("--periods", help="--history/--deductions 대상 지급월 목록 (예: 202607,202608). 없으면 전부")
    parser.add_argument("--deductions", action="store_true", help="공제내역 두 시트를 공제 대장(a10_bonus_deduction)으로 넣는다")
    args = parser.parse_args()

    db = get_session_factory()()
    try:
        if args.deductions:
            from app.services.bonus.excel_deductions import seed_deductions

            periods = [p.strip() for p in args.periods.split(",")] if args.periods else None
            result = seed_deductions(db, args.xlsx, periods=periods, dry_run=args.dry_run, force=args.force)
            mode = "미리보기" if result["dry_run"] else "저장"
            print(f"[{mode}] 공제 대장 {result['written']}건 · 건너뜀 {result['skipped']}건 · 달별 {result['by_period']}")
            if result["pending_people"]:
                print("대기(미처리)로 남는 사람:", ", ".join(f"{p} {int(a):,}" for p, a in sorted(result["pending_people"].items())))
            return
        if args.history:
            from app.services.bonus.excel_history import seed_history

            periods = [p.strip() for p in args.periods.split(",")] if args.periods else None
            history = seed_history(db, args.xlsx, periods=periods, dry_run=args.dry_run, force=args.force)
            mode = "미리보기" if history["dry_run"] else "저장"
            print(f"[{mode}] 이력 마감 {history['written']} (행수 {history['rows']}) · 건너뜀 {history['skipped']} · MOA 마감이라 보호 {history['protected']}")
            return
        report = seed(db, args.xlsx, dry_run=args.dry_run, force=args.force, known_names=known_names_from_db(db))
    finally:
        db.close()

    mode = "미리보기" if report["dry_run"] else "저장"
    print(f"[{mode}] 사람 {report['persons']}")
    print(f"[{mode}] 요율 {report['rates']}")
    print(f"[{mode}] 지분 {report['shares']}")
    if report["unknown_labels"]:
        print("라벨을 못 읽어 요율을 넣지 않은 사람:")
        for person, label in report["unknown_labels"]:
            print(f"  - {person}: {label!r}")
    if report["unknown_names"]:
        print("직원 명부에 없는 이름:", ", ".join(report["unknown_names"]))
    print("확인: 상여 설정 화면에서 노승환(2025-07-07 승격)·이영준(2026-07-08)·김치암 요율을 대조해 보세요.")


if __name__ == "__main__":
    main()
