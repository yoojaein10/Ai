"""국민 약식 지점코드 매핑 시드 — 복호화 없이 코드↔지점명을 잇는다.

BANK_KB_REQUEST_MASTER(KB_Code 평문·지점명 암호)와 APW_TS_Master(지점명 평문)를
400 접수번호로 조인해 코드별 최다 득표 지점명을 채택하고, 이어서 아마란스
거래처까지 이름으로 매칭해 둔다.

  python -m scripts.seed_kb_branch_map                # 미리보기
  python -m scripts.seed_kb_branch_map --apply        # 저장
  python -m scripts.seed_kb_branch_map --apply --link # 아마란스 거래처까지 매칭
"""

import argparse
from collections import Counter, defaultdict

from sqlalchemy import select, text

from app.amaranth.client import AmaranthClient
from app.config import get_settings
from app.database import get_session_factory
from app.models.kb_branch_map import KbBranchMap
from app.services.deposit_vouchers import DepositVoucherService
from scripts.find_management_numbers import _company_code

MIN_VOTES = 2
MIN_AGREEMENT = 0.6


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--since-seq", type=int, default=200000)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--link", action="store_true", help="아마란스 거래처까지 매칭")
    args = parser.parse_args()

    source_db = get_settings().mssql_source_db
    with get_session_factory()() as db:
        rows = db.execute(
            text(
                f"""
                SELECT r.KB_Code, r.KB_Name, t.CustName
                FROM [{source_db}].dbo.BANK_KB_REQUEST_MASTER r
                JOIN [{source_db}].dbo.APW_TS_Master t
                  ON LTRIM(t.HFDocid) = LTRIM(r.RequestNm)
                WHERE r.KB_Code IS NOT NULL AND t.CustName IS NOT NULL
                  AND r.SEQ > :seq
                """
            ),
            {"seq": args.since_seq},
        ).fetchall()
        print(f"조인 {len(rows):,}행")

        votes: "dict[str, Counter]" = defaultdict(Counter)
        encrypted: "dict[str, str]" = {}
        for code, enc, name in rows:
            code = str(code or "").strip()
            name = str(name or "").strip()
            if not code or not name:
                continue
            votes[code][name] += 1
            if enc:
                encrypted[code] = str(enc).strip()

        existing = {m.kb_code: m for m in db.scalars(select(KbBranchMap))}
        service = DepositVoucherService(db) if args.link else None
        company_code = _company_code(db, AmaranthClient(db)) if args.link else ""

        adopted = linked = skipped = 0
        for code, counter in sorted(votes.items(), key=lambda x: -sum(x[1].values())):
            name, top = counter.most_common(1)[0]
            total = sum(counter.values())
            if top < MIN_VOTES or top / total < MIN_AGREEMENT:
                skipped += 1
                continue
            entry = existing.get(code)
            if entry is None:
                entry = KbBranchMap(kb_code=code, branch_name=name, active="Y")
                db.add(entry)
                existing[code] = entry
                adopted += 1
            entry.branch_name = name
            entry.encrypted_name = encrypted.get(code)
            if service and not entry.partner_code:
                partner = service._branch_partner(company_code, name)
                if partner:
                    entry.partner_code = partner
                    linked += 1
        print(f"코드 {len(votes)}개 → 채택 {adopted} · 거래처 연결 {linked} · 보류 {skipped}")
        if args.apply:
            db.commit()
            print("저장 완료")
        else:
            db.rollback()
            print("미리보기 (--apply로 저장)")


if __name__ == "__main__":
    main()
