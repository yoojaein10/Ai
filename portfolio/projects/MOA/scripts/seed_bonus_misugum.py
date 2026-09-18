"""엑셀 미수금 탭의 미회수 잔액을 공제 대장(미수금 회수 OTHER_DEDUCT, 대기)으로 시딩.

미수금 탭(2016~)의 각 행은 회사가 대신 낸 돈(법인카드 사적사용·화환 사적사용 …)이고,
정산월(K)에 어느 지급월 AB 에서 회수했는지 적는다. 옛 행은 차감일(J) 열을 썼다.
→ 두 열이 모두 빈 행 = 아직 회수 못 한 돈. 이것만 대기 항목으로 올린다.
같은 (일자, 사람, 금액) 키는 두 번 들어가지 않는다(source_key).

  python -m scripts.seed_bonus_misugum --xlsx "C:\\...\\★★2026년 성과상여.xlsx"           # 미리보기
  python -m scripts.seed_bonus_misugum --xlsx "C:\\...\\★★2026년 성과상여.xlsx" --apply   # 실제 등록
"""

import argparse
import re
from datetime import date, datetime
from typing import Any

SHEET = "미수금"
_NAME_TAIL = re.compile(r"[-–/]\s*([가-힣]{2,4})(?:\s*(?:이사|대표|부회장|평가사))?(?:\s*\(.*\))?\s*$")


def _person_of(row: "tuple[Any, ...]") -> "str | None":
    """사람 찾기 — 최근 행은 F열, 그 전엔 적요 끝 '-이름(직함)', 더 옛날엔 담당자(I) 열."""
    name_col = row[5]
    if isinstance(name_col, str) and name_col.strip() and name_col.strip() != "미수금":
        return name_col.strip()
    match = _NAME_TAIL.search(str(row[3] or ""))
    if match:
        return match.group(1)
    manager = str(row[8] or "").strip()
    return manager or None


def _date_of(value: Any) -> "date | None":
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def parse_open_items(rows: "list[tuple[Any, ...]]") -> "tuple[list[dict[str, Any]], list[tuple[int, str, float]]]":
    """(시딩할 항목들, 사람을 못 읽은 행들). rows 는 시트 3행부터의 값 튜플."""
    items: "list[dict[str, Any]]" = []
    unknown: "list[tuple[int, str, float]]" = []
    key_counts: "dict[str, int]" = {}
    for index, row in enumerate(rows, 3):
        amount = row[4]
        if not isinstance(amount, (int, float)) or amount <= 0:
            continue
        settle = str(row[10] or "").strip()   # 정산월(K)
        deduct = str(row[9] or "").strip()    # 차감일(J) — 옛 방식
        if settle or deduct:
            continue
        person = _person_of(row)
        remark = str(row[3] or "").strip()
        if not person:
            unknown.append((index, remark[:60], float(amount)))
            continue
        occurred = _date_of(row[0])
        base_key = f"misu:{occurred:%Y%m%d}:{person}:{int(amount)}" if occurred else f"misu:r{index}:{person}:{int(amount)}"
        key_counts[base_key] = key_counts.get(base_key, 0) + 1
        items.append({
            "person": person, "kind": "OTHER_DEDUCT", "amount": float(amount), "doc_id": None,
            "occurred_on": occurred, "memo": (f"미수금 탭 {remark}"[:200] or None),
            "source": "EXCEL", "source_key": base_key + (f":{key_counts[base_key]}" if key_counts[base_key] > 1 else ""),
            "status": "PENDING",
        })
    return items, unknown


def main() -> None:
    import openpyxl

    from app.database import get_session_factory
    from app.services.bonus import deduction_items

    parser = argparse.ArgumentParser()
    parser.add_argument("--xlsx", required=True)
    parser.add_argument("--apply", action="store_true", help="실제로 등록 (없으면 미리보기)")
    args = parser.parse_args()

    workbook = openpyxl.load_workbook(args.xlsx, read_only=True, data_only=True)
    rows = list(workbook[SHEET].iter_rows(min_row=3, max_col=12, values_only=True))
    items, unknown = parse_open_items(rows)
    total = sum(item["amount"] for item in items)
    print(f"미회수 {len(items)}건 합계 {total:,.0f}원")
    for item in items:
        print(f"  {item['occurred_on']} {item['person']:6} {item['amount']:>14,.0f} | {item['memo']}")
    for index, remark, amount in unknown:
        print(f"  [사람 못 읽음] r{index} {amount:,.0f} | {remark}")
    if not args.apply:
        print("미리보기만 했습니다. 등록하려면 --apply")   # cp949 콘솔이라 대시 특수문자 금지
        return
    with get_session_factory()() as db:
        written, skipped = deduction_items.insert_seeded(db, items)
    print(f"등록 {written}건 · 이미 있어 건너뜀 {skipped}건")


if __name__ == "__main__":
    main()
