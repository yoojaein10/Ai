"""문서번호 목록을 받아 `.gam` 을 내려받고 추출만 한다(화면 불필요).

새 은행 매핑을 만들 때 먼저 이걸로 표본을 `output/<문서번호>/` 에 깔아 두면, 그 뒤로는
`gam_bridge.load_extracted` 로 몇 초 만에 매핑을 돌려 볼 수 있다(FTP·gamexport 재실행 없음).

    python tools/fetch_docs.py 01-2608-3-2625 01-2608-3-2603
    python tools/fetch_docs.py --bank 농협 --limit 12        # DB에서 실사완료 최근건을 골라서
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bankon.config import load_config          # noqa: E402
from bankon.db import connect                  # noqa: E402
from bankon.gam_bridge import process_gam      # noqa: E402
import verify_fill_kb as VK                     # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parent.parent


def pick_docs(cfg, bank: str, limit: int) -> list[str]:
    """의뢰처에 `bank` 가 들어가는 **실사완료** 담보 문서를 최근 순으로.

    실사완료(`ConductDate` 있음)여야 `.gam` 에 감정결과가 있다 — 실사 전 건은 채울 소스가 없다.
    """
    with connect(cfg.source_sql, readonly=True) as source:
        cursor = source.cursor()
        cursor.execute(
            """SELECT TOP (?) DocID FROM apw_masterex
               WHERE LWorkinfo=N'담보' AND CustName LIKE ?
                 AND DocID LIKE '01-2[56]%-3-%' AND ConductDate IS NOT NULL
               ORDER BY DocID DESC""", limit, f"%{bank}%")
        return [row[0] for row in cursor.fetchall()]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="fetch_docs")
    p.add_argument("doc_id", nargs="*")
    p.add_argument("--bank", default=None, help="의뢰처 부분일치로 고른다(예: 농협)")
    p.add_argument("--limit", type=int, default=12)
    p.add_argument("--force", action="store_true", help="이미 추출돼 있어도 다시 받는다")
    p.add_argument("--env", default=None)
    args = p.parse_args(argv)
    cfg = load_config(args.env or str(ROOT / ".env"))

    docs = list(args.doc_id)
    if args.bank:
        docs += [d for d in pick_docs(cfg, args.bank, args.limit) if d not in docs]
    if not docs:
        p.error("문서번호나 --bank 중 하나가 필요합니다.")

    ok = skip = fail = 0
    for doc in docs:
        out = ROOT / "output" / doc
        if out.is_dir() and any(out.glob("gam_info.json")) and not args.force:
            print(f"  · {doc} 이미 추출됨")
            skip += 1
            continue
        try:
            gam = process_gam(cfg.gamexport_exe, str(VK.fetch_gam_local(cfg, doc)), str(out))
        except (Exception, SystemExit) as error:
            print(f"  ⛔ {doc} {type(error).__name__}: {str(error)[:70]}")
            fail += 1
            continue
        tables = sorted(t for t in gam.tables if gam.tables[t])
        print(f"  ✅ {doc} 테이블 {len(tables)} · 의견서 {len(gam.opinions)}")
        ok += 1
    print(f"\n[합계] 추출 {ok} · 기존 {skip} · 실패 {fail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
