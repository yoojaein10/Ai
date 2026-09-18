"""계좌↔아마란스 금융거래처 매핑 시드 — 과거 거래·전표 대조 투표.

사이버브랜치 거래(입금·출금)를 아마란스 보통예금(1030000) 전표줄(차변·대변)과
금액+일자(±5일)로 유일 매칭하고, 계좌별 최다 득표 거래처를 채택한다.
2026-08 검증: 35계좌가 사실상 만장일치(신한역삼 131/131 등).
2026-08-26: 일계표 대사가 전 계좌를 봐야 해서 출금·대변과 메모 없는 거래까지 넓혔다.
그래도 남는 계좌는 --add 로 사람이 넣는다.

  python -m scripts.seed_bank_account_map --days 120          # 미리보기
  python -m scripts.seed_bank_account_map --days 120 --apply  # 저장
  python -m scripts.seed_bank_account_map --add 10000004 04393704008465 0000001234 --name 국민이수역
  python -m scripts.seed_bank_account_map --add 10000004 19460104017375 9000000060 --reconcile-only
    (지사 계좌: 입금전표 배치는 쓰지 않고 일계표 대사만 쓴다 → active='N', reconcile_only='Y')
  python -m scripts.seed_bank_account_map --days 120 --apply --skip 19460104017375
"""

import argparse
from collections import Counter, defaultdict
from datetime import date, timedelta

from sqlalchemy import select

from app.database import get_session_factory
from app.models.bank_account_map import BankAccountMap
from app.models.voucher_cache import VoucherCache
from app.services.deposit_source import fetch_transactions

MIN_VOTES = 3          # 이 미만이면 사람이 확인해 넣는다
MIN_AGREEMENT = 0.9    # 최다 득표가 전체의 90% 미만이면 채택하지 않는다
_DRCR = {"2": "3", "1": "4"}   # 입금 → 차변, 출금 → 대변


def _vote(deposits, lines) -> "dict[tuple[str, str, str], Counter]":
    by_key = defaultdict(list)
    for vd, drcr, amount, pcode, pname in lines:
        if pcode:
            by_key[(str(drcr), float(amount))].append((vd, str(pcode).strip(), pname))
    votes: "dict[tuple[str, str, str], Counter]" = defaultdict(Counter)
    for row in deposits:
        drcr = _DRCR.get(str(row.get("INOUT_GUBUN") or "").strip())
        txday = str(row["ACCT_TXDAY"])
        if not drcr or len(txday) != 8:
            continue
        d0 = date(int(txday[:4]), int(txday[4:6]), int(txday[6:8]))
        hits = {
            (pcode, pname)
            for vd, pcode, pname in by_key.get((drcr, float(row["TX_AMT"])), [])
            if abs((vd - d0).days) <= 5
        }
        if len(hits) == 1:
            key = (
                str(row["BANK_CD"] or "").strip(),
                str(row["ACCT_NO"] or "").strip(),
                str(row["ACCT_NICKNAME"] or "").strip(),
            )
            votes[key][next(iter(hits))] += 1
    return votes


def _add(db, bank_cd: str, acct_no: str, partner_code: str, name: "str | None",
         reconcile_only: bool = False, nickname: "str | None" = None) -> None:
    """사람이 확인한 계좌 한 줄 — 있으면 거래처를 고치고 없으면 넣는다."""
    active = "N" if reconcile_only else "Y"
    partner_name = name or db.execute(
        select(VoucherCache.partner_name).where(VoucherCache.partner_code == partner_code)
        .order_by(VoucherCache.voucher_date.desc()).limit(1)
    ).scalar()
    row = db.execute(select(BankAccountMap).where(
        BankAccountMap.bank_cd == bank_cd, BankAccountMap.acct_no == acct_no)).scalar_one_or_none()
    if row is None:
        db.add(BankAccountMap(bank_cd=bank_cd, acct_no=acct_no, nickname=nickname, partner_code=partner_code,
                              partner_name=partner_name, active=active,
                              reconcile_only="Y" if reconcile_only else "N"))
        print(f"[추가] {acct_no}: {partner_code} {partner_name}{' (대사 전용)' if reconcile_only else ''}")
    else:
        row.partner_code, row.partner_name, row.active = partner_code, partner_name, active
        row.reconcile_only = "Y" if reconcile_only else "N"
        if nickname:
            row.nickname = nickname
        print(f"[수정] {acct_no}: {partner_code} {partner_name}{' (대사 전용)' if reconcile_only else ''}")
    db.commit()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=120)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--add", nargs=3, metavar=("BANK_CD", "ACCT_NO", "PARTNER_CODE"))
    parser.add_argument("--name", help="--add 때 거래처명 (없으면 전표 캐시에서 찾는다)")
    parser.add_argument("--nickname", help="--add 때 계좌 별명 (사이버브랜치에 별명이 없는 새 계좌)")
    parser.add_argument("--reconcile-only", action="store_true",
                        help="--add 때 대사 전용(입금전표 배치는 쓰지 않는 지사 계좌 등)")
    parser.add_argument("--skip", nargs="*", default=[], metavar="ACCT_NO",
                        help="투표 채택에서 뺄 계좌번호 (지사 계좌 등)")
    args = parser.parse_args()

    if args.add:
        with get_session_factory()() as db:
            _add(db, *args.add, args.name, reconcile_only=args.reconcile_only, nickname=args.nickname)
        return

    date_to = date.today()
    date_from = date_to - timedelta(days=args.days - 1)
    deposits = fetch_transactions(date_from.strftime("%Y%m%d"), date_to.strftime("%Y%m%d"))

    with get_session_factory()() as db:
        lines = db.execute(
            select(
                VoucherCache.voucher_date, VoucherCache.debit_credit, VoucherCache.amount,
                VoucherCache.partner_code, VoucherCache.partner_name,
            ).where(
                VoucherCache.account_code == "1030000",
                VoucherCache.debit_credit.in_(("3", "4")),
                VoucherCache.voucher_date >= date_from,
            )
        ).fetchall()
        votes = _vote(deposits, lines)

        existing = {
            (m.bank_cd, m.acct_no)
            for m in db.scalars(select(BankAccountMap))
        }
        adopted = skipped = 0
        for (bank_cd, acct_no, nickname), counter in sorted(
            votes.items(), key=lambda item: -sum(item[1].values())
        ):
            (pcode, pname), top = counter.most_common(1)[0]
            total = sum(counter.values())
            ok = top >= MIN_VOTES and top / total >= MIN_AGREEMENT
            already = (bank_cd, acct_no) in existing
            skipped_by_user = acct_no in args.skip
            mark = "기존" if already else ("건너뜀" if skipped_by_user else ("채택" if ok else "보류"))
            print(f"[{mark}] {nickname or acct_no}: {pcode} {pname} ({top}/{total}표)")
            if already or not ok or skipped_by_user:
                skipped += 1
                continue
            adopted += 1
            if args.apply:
                db.add(BankAccountMap(
                    bank_cd=bank_cd, acct_no=acct_no, nickname=nickname or None,
                    partner_code=pcode, partner_name=pname, active="Y",
                ))
        if args.apply:
            db.commit()
            print(f"저장 완료: {adopted}건 (보류/기존 {skipped}건)")
        else:
            print(f"미리보기: 채택 가능 {adopted}건 (--apply로 저장)")


if __name__ == "__main__":
    main()
