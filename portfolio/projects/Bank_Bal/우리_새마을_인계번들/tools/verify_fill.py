"""정품추출(gamexport) → 매핑 → "auto-fill 이 채울 값 전체" ↔ 화면 대조.

"우리가 모든 칸을 채운다" 관점의 검증. 사람이 화면에 넣은 값뿐 아니라
**사람이 비워둔 칸을 우리가 채울 값**까지 다 보여준다. gamexport 필요.

  화면에 신한 담보 폼을 열어둔 상태에서:
    python tools/verify_fill.py 01-2504-3-1436

읽기 전용(화면 안 건드림). 결과 구분:
  ❌불일치   우리 채울값 ≠ 사람 입력값     → 봐야 함(대개 0패딩=우리가 맞음)
  🖊우리채움  우리가 채울값, 화면은 빈칸     → 우리 추출이 이걸 채운다(등기·용도지역·연수…)
  📄화면만    화면엔 있는데 우리 매핑엔 없음  → 좌표칸(동미만주소)·부번0000 등
  ✅일치     우리 채울값 = 사람 입력값
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bankon.config import load_config          # noqa: E402
from bankon.db import connect                  # noqa: E402
from bankon.downloader import download_to, ftp_session  # noqa: E402
from bankon.resolver import resolve_document   # noqa: E402
from bankon.gam_bridge import process_gam      # noqa: E402
from bankon.mapping import shinhan             # noqa: E402
from bankon.ui import driver                   # noqa: E402
import verify_form as vf                       # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

_CODE = re.compile(r"\((\d+)\)\s*$")


def norm(t: str) -> str:
    return _CODE.sub("", (t or "").replace(",", "")).strip()


def digs0(t: str) -> str:
    return re.sub(r"\D", "", t or "").lstrip("0")


def fetch_gam_local(cfg, doc: str) -> Path:
    dest = Path("work") / doc / f"{doc}.gam"
    if dest.exists() and dest.stat().st_size > 1000:
        return dest
    with connect(cfg.source_sql, readonly=True) as s, ftp_session(cfg.ftp) as ftp:
        remote = resolve_document(s, doc).remote("gam")
        if not remote:
            raise SystemExit(f"{doc}: .gam 원격경로 없음")
        return download_to(ftp, remote, dest)


_COMBOS = None


def build_fill(cfg, doc: str, form, seq: int | None = None):
    """정품추출(gamexport) → 매핑 → 화면대조. (meta, rows[(mark,label,ours,theirs)]).

    seq=None 이면 화면의 물건순번에 맞는 물건을, 없으면 1번 물건을 쓴다.
    """
    global _COMBOS
    gam = process_gam(cfg.gamexport_exe, str(fetch_gam_local(cfg, doc)), str(Path("output") / doc))
    ctx = vf.build_context(cfg, doc, gam.tables, vf.sections_from_gam(gam))
    if _COMBOS is None:
        _COMBOS = vf.load_combos(Path(__file__).resolve().parent.parent / "recon" / "combo_shinhan.md")
    built = shinhan.build(ctx, _COMBOS)
    screen = vf.screen_values(form)
    if seq is None:
        scr = norm(screen.get("물건순번", ""))
        seq = int(scr) if scr.isdigit() else 1
    idx = min(max(seq - 1, 0), len(built) - 1)
    mine = built[idx]
    rows = []
    for label in sorted(set(mine) | set(screen)):
        ours = norm(mine.get(label) or "")
        theirs = norm(screen.get(label) or "")
        if not ours and not theirs:
            continue
        if ours and theirs:
            mark = "❌불일치" if ours != theirs else "✅일치"
        elif ours:
            mark = "🖊우리채움"
        else:
            mark = "📄화면만"
        rows.append((mark, label, ours or "-", theirs or "-"))
    meta = {"seq": idx + 1, "total": len(built),
            "screen_bun": norm(screen.get("본번지", "")), "mine_bun": norm(mine.get("본번지") or "")}
    return meta, rows


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="verify_fill")
    p.add_argument("doc_id")
    p.add_argument("--seq", type=int, default=None, help="물건순번(기본=화면 물건순번)")
    p.add_argument("--env", default=None)
    args = p.parse_args(argv)
    cfg = load_config(args.env)

    forms = [f for f in driver.find_windows(driver.FORM_CLASS_PREFIX)
             if f.class_name == "TBNKSHG24DAMB"]
    if not forms:
        print("신한 담보 화면이 열려 있지 않습니다.", file=sys.stderr)
        return 1
    meta, rows = build_fill(cfg, args.doc_id, forms[0], args.seq)
    if meta["screen_bun"] and meta["mine_bun"] and digs0(meta["screen_bun"]) != digs0(meta["mine_bun"]):
        print(f"⚠️  화면 본번지({meta['screen_bun']}) ≠ 문서 본번지({meta['mine_bun']}) — 다른 문서/물건일 수 있음\n")
    print(f"===== {args.doc_id} (물건 {meta['seq']}/{meta['total']}) — auto-fill 채울 값 ↔ 화면 =====")
    order = {"❌불일치": 0, "🖊우리채움": 1, "📄화면만": 2, "✅일치": 3}
    for mark, label, ours, theirs in sorted(rows, key=lambda r: (order[r[0]], r[1])):
        print(f"  [{mark:6}] {label[:20]:22} 채울값={ours[:26]:28} 화면={theirs[:24]}")

    fill = sum(1 for r in rows if r[0] == "🖊우리채움")
    same = sum(1 for r in rows if r[0] == "✅일치")
    diff = sum(1 for r in rows if r[0] == "❌불일치")
    scr = sum(1 for r in rows if r[0] == "📄화면만")
    print(f"\n일치 {same} · 불일치 {diff} · 🖊우리가 새로채움 {fill} · 화면만 {scr}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
