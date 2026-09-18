"""우리은행 담보(TBNKWRB24DAMB) — 정품추출 → wrb 매핑 → "채울값 ↔ 화면" 대조.

하나판(verify_fill_hnb)의 우리판. 화면에 물건 하나씩 보이고 순번(일련번호)으로 넘긴다.

  화면에 우리 담보폼 열어둔 상태에서:
    python tools/verify_fill_wrb.py 01-2608-3-2668
"""
from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bankon.config import load_config          # noqa: E402
from bankon.gam_bridge import process_gam       # noqa: E402
from bankon.mapping import wrb                  # noqa: E402
from bankon.parse import detail                 # noqa: E402
from bankon.ui import driver                    # noqa: E402
from bankon.ui import form as form_mod          # noqa: E402
import verify_form as vf                         # noqa: E402
import verify_fill_kb as VK                      # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

FORM_CLASS = "TBNKWRB24DAMB"


def norm(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text or "")
    return folded.replace(",", "").replace("-", "").replace(" ", "").strip()


def _property_rows(ctx):
    return [r for r in ctx.details if (r.is_land or r.is_building)]


def _banji(text: str) -> str:
    m = re.match(r"\s*(\d+)(?:\s*-\s*(\d+))?", str(text or ""))
    return (m.group(1) + ("-" + m.group(2) if m.group(2) else "")) if m else ""


def _screen_seq(screen) -> str:
    v = norm(screen.get("일련번호", ""))
    return v if (v.isdigit() and len(v) <= 3) else "1"


def resolve_seq(ctx, screen, seq=None) -> str:
    if seq:
        return str(seq)
    s = _screen_seq(screen)
    return s if s.isdigit() else "1"


def match_seq_by_banji(ctx, screen, seq=None):
    """화면 물건 순번을 찾는다. (순번, 방식).

    우리은행은 실측(2470) 화면 **일련번호(순번) = 소스 순번**이 정확히 일치한다(순번1~6
    금액 대조 확인). 그래서 순번을 1차로 쓰고, 번지가 유일하게 맞으면 그걸로 교차확인.
    본번지는 다물건에서 대표번지로 고정되기도 해(469-3) 번지 단독으론 못 가른다.
    """
    if seq:
        return str(seq), "지정"
    rows = _property_rows(ctx)
    s = _screen_seq(screen)
    scr = _banji(screen.get("본번지", "") + ("-" + screen.get("부번지", "")
                 if screen.get("부번지") else ""))
    if scr:
        hits = [i for i, r in enumerate(rows, 1) if _banji(r.jibun) == scr]
        if len(hits) == 1:
            return str(hits[0]), "번지매칭"        # 번지가 유일 → 가장 확실
    return (s if s.isdigit() else "1"), "순번위치"   # 화면순번=소스순번(실측)


def seq_alignment(ctx, screen, seq=None) -> dict:
    """순번 정합 — 뽑은 물건이 화면과 정확히 일치할 때만 safe(감정평가액 or 번지)."""
    rows = _property_rows(ctx)
    anchors = [r for r in rows if r.amount is not None]
    total = len(anchors)
    s = seq or _screen_seq(screen)
    picked = detail.for_sequence(tuple(rows), str(s))
    scr_amt = norm(screen.get("감정평가액", ""))
    our_amt = str(int(picked.amount)) if (picked and picked.amount is not None) else ""
    scr_banji = _banji(screen.get("본번지", "") + ("-" + screen.get("부번지", "")
                       if screen.get("부번지") else ""))
    our_banji = _banji(picked.jibun) if picked else ""
    by_amt = bool(scr_amt and our_amt and scr_amt == our_amt)
    by_banji = bool(scr_banji and our_banji and scr_banji == our_banji)
    if total < 2:
        return {"total": total, "screen_seq": str(s), "resolved": str(s),
                "by": "단일물건", "safe": True}
    return {"total": total, "screen_seq": str(s), "resolved": str(s),
            "by": "금액매칭" if by_amt else ("번지매칭" if by_banji else "불명확"),
            "safe": bool(by_amt or by_banji or not scr_amt)}   # 빈폼(금액없음)은 번지로


def build_fill_wrb(cfg, doc: str, form, seq=None):
    gam = process_gam(cfg.gamexport_exe, str(VK.fetch_gam_local(cfg, doc)),
                      str(Path("output") / doc))
    ctx = vf.build_context(cfg, doc, gam.tables, vf.sections_from_gam(gam))
    screen = vf.screen_values(form)
    mine = wrb.build(ctx, resolve_seq(ctx, screen, seq))
    rows = []
    for label in sorted(set(mine) | set(screen)):
        name = form_mod.display_label(label)
        ours = norm(mine.get(label) or "")
        theirs = norm(screen.get(label) or "")
        if not ours and not theirs:
            continue
        mark = ("✅일치" if ours == theirs else "❌불일치") if (ours and theirs) else \
               ("🖊우리채움" if ours else "📄화면만")
        rows.append((mark, name, ours or "-", theirs or "-"))
    return rows


def fill_wrb(cfg, doc: str, form, *, live: bool = False, overwrite: bool = False,
             select: bool = False, seq=None):
    gam = process_gam(cfg.gamexport_exe, str(VK.fetch_gam_local(cfg, doc)),
                      str(Path("output") / doc))
    ctx = vf.build_context(cfg, doc, gam.tables, vf.sections_from_gam(gam))
    screen = vf.screen_values(form)
    align = seq_alignment(ctx, screen, seq)
    values = wrb.build(ctx, align["resolved"])
    return form_mod.fill(form, values, live=live and align["safe"], overwrite=overwrite,
                         select=select), align


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="verify_fill_wrb")
    p.add_argument("doc_id")
    p.add_argument("--seq", default=None)
    p.add_argument("--env", default=None)
    args = p.parse_args(argv)
    cfg = load_config(args.env)
    forms = [f for f in driver.find_windows(driver.FORM_CLASS_PREFIX) if f.class_name == FORM_CLASS]
    if not forms:
        print(f"우리 담보폼({FORM_CLASS})이 안 열려 있습니다.", file=sys.stderr)
        return 1
    rows = build_fill_wrb(cfg, args.doc_id, forms[0], args.seq)
    print(f"===== {args.doc_id} — 우리 auto-fill 채울값 ↔ 화면 =====")
    order = {"❌불일치": 0, "🖊우리채움": 1, "📄화면만": 2, "✅일치": 3}
    for mark, label, ours, theirs in sorted(rows, key=lambda r: (order[r[0]], r[1])):
        print(f"  [{mark:6}] {label[:16]:18} 채울값={ours[:24]:26} 화면={theirs[:22]}")
    for m in ("✅일치", "❌불일치", "🖊우리채움", "📄화면만"):
        print(f"  {m}: {sum(1 for r in rows if r[0] == m)}", end="")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
