"""기업은행 담보(TBNKKIB24DAMB) — 정품추출 → ibk 매핑 → "채울값 ↔ 화면" 대조.

국민판 verify_fill_kb 의 기업판. 읽기 전용.

  화면에 기업은행 담보폼 열어둔 상태에서:
    python tools/verify_fill_ibk.py 01-2608-3-2683
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bankon.config import load_config          # noqa: E402
from bankon.gam_bridge import process_gam       # noqa: E402
from bankon.mapping import ibk                  # noqa: E402
from bankon.ui import driver                    # noqa: E402
import verify_form as vf                         # noqa: E402
import verify_fill_kb as VK                      # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

FORM_CLASS = "TBNKKIB24DAMB"
_CODE = re.compile(r"\((\d+)\)\s*$")


def norm(t: str) -> str:
    return _CODE.sub("", (t or "").replace(",", "")).strip()


def resolve_seq(ctx, screen, seq=None):
    """다물건 순번 정합 — 화면 감정평가액(또는 일련번호)으로 채울 물건 순번을 정한다.

    기업 물건 = 토지/건물 명세행(기계·선박 제외). 단일이면 None(기존 동작).
    """
    if seq:
        return str(seq)
    anchors = [r for r in ctx.details if (r.is_land or r.is_building) and r.amount is not None]
    if len(anchors) < 2:
        return None
    amt = norm(screen.get("감정평가액", ""))
    if amt.isdigit():
        for i, row in enumerate(anchors, 1):
            if str(int(row.amount)) == amt:
                return str(i)                       # 금액 = 확정키
    scr = norm(screen.get("일련번호", ""))
    return scr if scr.isdigit() else None            # 폴백: 화면 일련번호


def seq_alignment(ctx, screen, seq=None) -> dict:
    """다물건 순번 정합 정보 — 국민 `verify_fill_kb.seq_alignment` 의 기업판.

    기업 물건 = 토지/건물 명세행(기계·선박은 별도 평가금액 칸이라 순번 대상 아님).
    반환 키는 국민과 같다(total·screen_seq·resolved·by·safe) — 순회 도구가 공용으로 쓴다.
    """
    anchors = [r for r in ctx.details if (r.is_land or r.is_building) and r.amount is not None]
    total = len(anchors)
    screen_seq = norm(screen.get("일련번호", ""))
    resolved = resolve_seq(ctx, screen, seq)
    if total < 2:
        return {"total": total, "screen_seq": screen_seq or "1",
                "resolved": resolved or "1", "by": "단일물건", "safe": True}
    idx = (int(resolved) - 1) if (resolved and resolved.isdigit()) else 0
    our_amt = str(int(anchors[idx].amount)) if 0 <= idx < total else ""
    scr_amt = norm(screen.get("감정평가액", ""))
    if scr_amt and scr_amt == our_amt:
        by, safe = "금액매칭", True                       # 화면 물건 = 우리 물건 확정
    elif screen_seq.isdigit() and 1 <= int(screen_seq) <= total:
        by, safe = "일련번호", True                        # 빈 폼: 슬롯 번호로 정합
    else:
        by, safe = "불명확", False                         # 어느 물건인지 확신 못함
    return {"total": total, "screen_seq": screen_seq, "resolved": resolved or "1",
            "our_amount": our_amt, "screen_amount": scr_amt, "by": by, "safe": safe}


def fill_ibk(cfg, doc: str, form, *, live: bool = False, overwrite: bool = False, seq=None):
    """기업 담보 폼에 매핑값을 채운다(기본 드라이런). 자동순회 채우기 모드용.

    국민 `verify_fill_kb.fill_kb` 와 같은 계약: (results, align) 을 돌려준다.
    다물건인데 어느 물건인지 확신 못하면 실입력을 막는다(순번 오채움 방지).
    """
    from bankon.ui import form as form_mod
    gam = process_gam(cfg.gamexport_exe, str(VK.fetch_gam_local(cfg, doc)),
                      str(Path("output") / doc))
    ctx = vf.build_context(cfg, doc, gam.tables, vf.sections_from_gam(gam))
    screen = vf.screen_values(form)
    align = seq_alignment(ctx, screen, seq)
    resolved = None if (align["resolved"] == "1" and align["total"] < 2) else align["resolved"]
    values = ibk.build(ctx, resolved)
    return form_mod.fill(form, values, live=live and align["safe"], overwrite=overwrite), align


def build_fill_ibk(cfg, doc: str, form, seq=None):
    """정품추출 → ibk 매핑 → "채울값 ↔ 화면" 대조행. 그리드 순회용(build_fill_kb 대응)."""
    gam = process_gam(cfg.gamexport_exe, str(VK.fetch_gam_local(cfg, doc)),
                      str(Path("output") / doc))
    ctx = vf.build_context(cfg, doc, gam.tables, vf.sections_from_gam(gam))
    screen = vf.screen_values(form)
    mine = ibk.build(ctx, resolve_seq(ctx, screen, seq))
    rows = []
    for label in sorted(set(mine) | set(screen)):
        ours, theirs = norm(mine.get(label) or ""), norm(screen.get(label) or "")
        if not ours and not theirs:
            continue
        mark = ("✅일치" if ours == theirs else "❌불일치") if (ours and theirs) else \
               ("🖊우리채움" if ours else "📄화면만")
        rows.append((mark, label, ours or "-", theirs or "-"))
    return rows


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="verify_fill_ibk")
    p.add_argument("doc_id")
    p.add_argument("--seq", default=None)
    p.add_argument("--env", default=None)
    args = p.parse_args(argv)
    cfg = load_config(args.env)

    forms = [f for f in driver.find_windows(driver.FORM_CLASS_PREFIX) if f.class_name == FORM_CLASS]
    if not forms:
        print(f"기업은행 담보폼({FORM_CLASS})이 안 열려 있습니다. "
              f"(열린: {[f.class_name for f in driver.find_windows(driver.FORM_CLASS_PREFIX)] or '없음'})",
              file=sys.stderr)
        return 1
    gam = process_gam(cfg.gamexport_exe, str(VK.fetch_gam_local(cfg, args.doc_id)),
                      str(Path("output") / args.doc_id))
    ctx = vf.build_context(cfg, args.doc_id, gam.tables, vf.sections_from_gam(gam))
    screen = vf.screen_values(forms[0])
    mine = ibk.build(ctx, resolve_seq(ctx, screen, args.seq))

    rows = []
    for label in sorted(set(mine) | set(screen)):
        ours, theirs = norm(mine.get(label) or ""), norm(screen.get(label) or "")
        if not ours and not theirs:
            continue
        mark = ("✅일치" if ours == theirs else "❌불일치") if (ours and theirs) else \
               ("🖊우리채움" if ours else "📄화면만")
        rows.append((mark, label, ours or "-", theirs or "-"))
    print(f"===== {args.doc_id} — 기업은행 auto-fill 채울값 ↔ 화면 =====")
    order = {"❌불일치": 0, "🖊우리채움": 1, "📄화면만": 2, "✅일치": 3}
    for mark, label, ours, theirs in sorted(rows, key=lambda r: (order[r[0]], r[1])):
        print(f"  [{mark:6}] {label[:18]:20} 채울값={ours[:26]:28} 화면={theirs[:24]}")
    for m in ("✅일치", "❌불일치", "🖊우리채움", "📄화면만"):
        print(f"  {m}: {sum(1 for r in rows if r[0]==m)}", end="")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
