"""전기이월 해 넘기기 — 지난해 이월 + 지난해 전표 누계로 새해 전기이월을 만든다.

왜 필요한가
    계정별원장의 전일이월은 **전기이월 + 그 해 누계**다. 전기이월은
    a10_account_opening 에 연도별로 들어 있는데, 2026년치는 아마란스 화면을 보고
    사람이 한 번 적어 넣은 것뿐이다(scripts/seed_account_opening.py).

    build_ledger 는 그 해 전기이월이 없으면 **0으로 두고 원장을 그대로 낸다.**
    그래서 아무도 손대지 않으면 2027-01-01 부터 지사 20곳 원장의 전일이월이 전부
    틀린 채로 나간다 — 화면에는 아무 표시도 없다. 그 사고를 막는 것이 이 스크립트다.

계산
    새해 전기이월 = 지난해 전기이월 + 지난해 차변 누계 - 지난해 대변 누계
    아마란스가 [전 기 이 월] 을 **차변 칸 한 곳에** 찍으므로(음수 가능) 우리도
    잔액을 debit 에 넣고 credit 은 0 으로 둔다 — 시드와 같은 규칙이라 전일이월
    계산 결과가 달라지지 않는다.

    지난해 전표는 우리 캐시(a10_voucher_cache)에서 읽는다. 그래서 **그 해 전표가
    캐시에 다 들어와 있어야** 정확하다. 소급 입력 전표가 나중에 들어오면 값이
    달라지므로, 연초에 한 번 돌리고 1월 말쯤 --force 로 한 번 더 돌려 굳히는 것을
    권한다. 결과는 아마란스 계정별원장 화면의 [전 기 이 월] 과 대조해 확인한다.

실행
    python -m scripts.roll_account_opening                        # 올해 것을 만든다
    python -m scripts.roll_account_opening --year 2027            # 연도를 직접 준다
    python -m scripts.roll_account_opening --year 2027 --dry-run  # 계산만 해 보기
    python -m scripts.roll_account_opening --year 2027 --force    # 이미 있는 값을 덮어쓴다

서버에서는 예약 작업 `A10Bridge_AccountOpeningRoll` 이 **매년 1월 2일 06:00** 에
연도 없이 실행한다(로그 `logs\account_opening_roll.log`). 그날 만들어지므로 1월
첫 발송부터 원장이 맞는다. 소급 전표가 늦게 들어오면 1월 말에 --force 로 한 번 더
굳히는 것은 사람이 한다 — 확인 없이 덮어쓰면 안 되기 때문이다.
"""

import argparse
from datetime import date

from sqlalchemy import select, text

from app.database import get_session_factory
from app.models.account_opening import AccountOpening

DIVISION_CODE = "1000"

# 지사가 아니어서 전기이월을 두지 않는 계정. 캐시에는 전표가 있지만 이월 명단에
# 없다고 매번 경고하면 진짜 새 지사가 묻힌다 (2026-08-24 확인).
#   1410001 본사      — 지사 원장 대상이 아니다
#   1410017 본지점(손익) — 본지점 상계용. 아마란스 회계단위 원장에서 계정으로 잡히지
#                       않아 [전 기 이 월] 을 읽을 수 없다.
NOT_BRANCH = {"1410001", "1410017"}

# 캐시 집계는 SQL 로 한다 — 큰 표라 varchar 컬럼에 CAST 를 붙여야 인덱스를 탄다
# (pyodbc 가 문자열을 NVARCHAR 로 바인드해 풀스캔이 되는 함정). ISNULL 대신
# COALESCE 를 쓰는 것은 표준이라 시험용 sqlite 에서도 같은 쿼리가 돌기 때문이다.
_YEAR_SUM_SQL = """
SELECT COALESCE(SUM(CASE WHEN debit_credit = '3' THEN amount ELSE 0 END), 0) AS debit,
       COALESCE(SUM(CASE WHEN debit_credit = '4' THEN amount ELSE 0 END), 0) AS credit
FROM dbo.a10_voucher_cache
WHERE division_code = CAST(:div AS varchar(10))
  AND account_code = CAST(:acct AS varchar(20))
  AND voucher_date >= :start AND voucher_date <= :end
"""

# 캐시에는 있는데 지난해 이월 명단에 없는 141 계정 — 새로 생긴 지사를 놓치지 않는다.
_CACHE_ACCOUNTS_SQL = """
SELECT DISTINCT account_code
FROM dbo.a10_voucher_cache
WHERE division_code = CAST(:div AS varchar(10))
  AND account_code LIKE '141%'
  AND voucher_date >= :start AND voucher_date <= :end
"""


def roll(db, year: int, *, force: bool = False, dry_run: bool = False) -> "dict":
    """year 의 전기이월을 year-1 자료로 만든다. 무엇을 했는지 돌려준다."""
    prev = year - 1
    start, end = date(prev, 1, 1), date(prev, 12, 31)
    # 지난해 이월이 있는 계정을 대상으로 삼는다 — 명단을 코드에 또 적으면 시드와 어긋난다.
    rows = db.scalars(
        select(AccountOpening)
        .where(AccountOpening.fiscal_year == prev)
        .order_by(AccountOpening.account_code)
    ).all()
    if not rows:
        raise SystemExit(
            f"{prev}년 전기이월이 하나도 없습니다. 먼저 그 해 이월을 넣어야 합니다."
        )

    written, skipped = [], []
    for row in rows:
        account_code = row.account_code
        totals = db.execute(text(_YEAR_SUM_SQL), {
            "div": DIVISION_CODE, "acct": account_code, "start": start, "end": end,
        }).mappings().one()
        opening = float(row.debit or 0) - float(row.credit or 0)
        closing = opening + float(totals["debit"] or 0) - float(totals["credit"] or 0)

        already = db.scalars(
            select(AccountOpening).where(
                AccountOpening.account_code == account_code,
                AccountOpening.fiscal_year == year,
            )
        ).first()
        item = {
            "account_code": account_code,
            "opening": opening,
            "year_debit": float(totals["debit"] or 0),
            "year_credit": float(totals["credit"] or 0),
            "closing": closing,
            "before": (float(already.debit or 0) - float(already.credit or 0))
            if already is not None else None,
        }
        if already is not None and not force:
            skipped.append(item)
            continue
        if not dry_run:
            if already is None:
                db.add(AccountOpening(
                    account_code=account_code, fiscal_year=year,
                    debit=closing, credit=0,
                ))
            else:
                already.debit = closing
                already.credit = 0
        written.append(item)

    # 지난해 이월 명단에 없던 계정이 캐시에 있으면 알린다 — 새 지사를 놓치면
    # 그 지사만 조용히 0 이월로 나간다.
    known = {row.account_code for row in rows}
    seen = {r[0] for r in db.execute(text(_CACHE_ACCOUNTS_SQL), {
        "div": DIVISION_CODE, "start": start, "end": end,
    }).all()}
    unknown = sorted(seen - known - NOT_BRANCH)

    if not dry_run:
        db.commit()
    return {"written": written, "skipped": skipped, "unknown": unknown,
            "year": year, "dry_run": dry_run}


def main() -> None:
    parser = argparse.ArgumentParser(description="전기이월 해 넘기기")
    # 생략하면 올해다. 1월 2일에 도는 예약 작업이 연도를 계산하지 않아도 되게 한다.
    parser.add_argument("--year", type=int, default=date.today().year,
                        help="만들 회계연도 (생략하면 올해)")
    parser.add_argument("--force", action="store_true", help="이미 있는 값을 덮어쓴다")
    parser.add_argument("--dry-run", action="store_true", help="계산만 하고 저장하지 않는다")
    args = parser.parse_args()

    db = get_session_factory()()
    try:
        result = roll(db, args.year, force=args.force, dry_run=args.dry_run)
    finally:
        db.close()

    head = f"{args.year}년 전기이월" + (" (계산만 해 봄)" if args.dry_run else "")
    print(f"== {head} ==")
    print(f"{'계정':<10}{'지난해이월':>16}{'차변':>16}{'대변':>16}{'새이월':>16}")
    for item in result["written"]:
        print(f"{item['account_code']:<10}{item['opening']:>16,.0f}"
              f"{item['year_debit']:>16,.0f}{item['year_credit']:>16,.0f}"
              f"{item['closing']:>16,.0f}")
    print(f"\n{'저장하지 않음' if args.dry_run else '저장'} {len(result['written'])}개")
    if result["skipped"]:
        print(f"이미 값이 있어 건너뜀 {len(result['skipped'])}개 — 덮어쓰려면 --force")
        for item in result["skipped"]:
            print(f"  {item['account_code']} 지금 {item['before']:,.0f}"
                  f" / 계산값 {item['closing']:,.0f}")
    if result["unknown"]:
        print(f"\n지난해 이월 명단에 없는 계정 {len(result['unknown'])}개 — "
              "새로 생긴 지사인지 확인하세요:")
        print("  " + ", ".join(result["unknown"]))
    print("\n확인: 아마란스 계정별원장 화면의 [전 기 이 월] 과 대조해 보세요.")


if __name__ == "__main__":
    main()
