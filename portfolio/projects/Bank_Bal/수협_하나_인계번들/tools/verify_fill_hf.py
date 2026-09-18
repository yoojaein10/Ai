"""주택도시보증공사 HUG 담보(TBNKHUG24DAMB) — 정품추출 → hf 매핑 → "채울값 ↔ 화면" 대조.

농협판(verify_fill_nh)의 HUG판. 읽기 전용(채우기는 --live 있는 순회 도구에서만).

  화면에 HUG 담보폼 열어둔 상태에서:
    python tools/verify_fill_hf.py 05-2509-3-1221
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
from bankon.mapping import hf                   # noqa: E402
from bankon.ui import driver                    # noqa: E402
from bankon.ui import form as form_mod          # noqa: E402
from bankon.parse import address as _address    # noqa: E402
import verify_form as vf                         # noqa: E402
import verify_fill_kb as VK                      # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

FORM_CLASS = "TBNKHUG24DAMB"
_CODE = re.compile(r"\((\d+)\)\s*$")


def norm(text: str) -> str:
    """비교용 정규화 — 콤보 코드·콤마·공백·전각을 없앤다."""
    folded = unicodedata.normalize("NFKC", text or "")
    return _CODE.sub("", folded).replace(",", "").replace(" ", "").strip()


ZERO_PADDED = ("본번", "부번")


def compare_text(label: str, text: str) -> str:
    value = norm(text)
    if label in ZERO_PADDED and value.isdigit():
        return value.lstrip("0") or "0"
    return value


def _property_rows(ctx):
    return [r for r in ctx.details if (r.is_land or r.is_building)]


def resolve_seq(ctx, screen, seq=None) -> str | None:
    """다물건 순번 정합 — 화면이 보고 있는 물건이 우리 몇 번째인지.

    HUG 화면 키: `감정가액`·`사정면적`/`공부면적`·`호`·`물건일련번호`.
    금액이 겹칠 수 있어 **면적 → 호 → 금액 → 일련번호** 순으로 좁힌다(농협과 동일).
    """
    if seq:
        return str(seq)
    rows = _property_rows(ctx)
    anchors = [r for r in rows if r.amount is not None]
    if len(anchors) < 2:
        return None

    area = norm(screen.get("사정면적", "") or screen.get("공부면적", ""))
    if area:
        for index, row in enumerate(anchors, 1):
            for candidate in (row.area_assessed, row.area_public):
                if candidate is not None and norm(f"{candidate:.2f}") == area:
                    return str(index)

    ho = norm(screen.get("호", ""))
    if ho:
        for index, row in enumerate(anchors, 1):
            found = _address.ho_of(row.location)
            if found and norm(found) == ho:
                return str(index)

    amount = norm(screen.get("감정가액", ""))
    if amount.isdigit():
        matched = [i for i, r in enumerate(anchors, 1) if str(int(r.amount)) == amount]
        if len(matched) == 1:
            return str(matched[0])

    screen_seq = norm(screen.get("물건일련번호", ""))
    return screen_seq if screen_seq.isdigit() else None


def seq_alignment(ctx, screen, seq=None) -> dict:
    """순번 정합 정보(순회 채우기가 공용으로 쓴다)."""
    anchors = [r for r in _property_rows(ctx) if r.amount is not None]
    total = len(anchors)
    screen_seq = norm(screen.get("물건일련번호", ""))
    resolved = resolve_seq(ctx, screen, seq)
    if total < 2:
        return {"total": total, "screen_seq": screen_seq or "1",
                "resolved": resolved or "1", "by": "단일물건", "safe": True}
    index = (int(resolved) - 1) if (resolved and resolved.isdigit()) else -1
    if 0 <= index < total:
        row = anchors[index]
        our_area = f"{row.area_assessed or row.area_public:.2f}" \
            if (row.area_assessed or row.area_public) is not None else ""
        screen_area = norm(screen.get("사정면적", "") or screen.get("공부면적", ""))
        by = "면적매칭" if (screen_area and norm(our_area) == screen_area) else "순번"
        safe = by == "면적매칭" or (screen_seq.isdigit() and 1 <= int(screen_seq) <= total)
        return {"total": total, "screen_seq": screen_seq, "resolved": resolved or "1",
                "our_area": our_area, "screen_area": screen_area, "by": by, "safe": safe}
    return {"total": total, "screen_seq": screen_seq, "resolved": resolved or "1",
            "by": "불명확", "safe": False}


def build_fill_hf(cfg, doc: str, form, seq=None):
    """정품추출 → hf 매핑 → "채울값 ↔ 화면" 대조행. 그리드 순회용."""
    gam = process_gam(cfg.gamexport_exe, str(VK.fetch_gam_local(cfg, doc)),
                      str(Path("output") / doc))
    ctx = vf.build_context(cfg, doc, gam.tables, vf.sections_from_gam(gam))
    screen = vf.screen_values(form)
    mine = hf.build(ctx, resolve_seq(ctx, screen, seq))
    for label in mine:
        if form_mod.POSITIONAL.match(str(label)):
            screen[label] = form_mod.read_field(form, label)
            screen.pop(form_mod.display_label(label), None)
    rows = []
    for label in sorted(set(mine) | set(screen)):
        name = form_mod.display_label(label)
        ours = compare_text(name, mine.get(label) or "")
        theirs = compare_text(name, screen.get(label) or "")
        if not ours and not theirs:
            continue
        mark = ("✅일치" if ours == theirs else "❌불일치") if (ours and theirs) else \
               ("🖊우리채움" if ours else "📄화면만")
        rows.append((mark, name, ours or "-", theirs or "-"))
    return rows


def fill_hf(cfg, doc: str, form, *, live: bool = False, overwrite: bool = False,
            select: bool = False, seq=None):
    """HUG 담보 폼에 매핑값을 채운다(기본 드라이런). 순회 채우기용."""
    gam = process_gam(cfg.gamexport_exe, str(VK.fetch_gam_local(cfg, doc)),
                      str(Path("output") / doc))
    ctx = vf.build_context(cfg, doc, gam.tables, vf.sections_from_gam(gam))
    screen = vf.screen_values(form)
    align = seq_alignment(ctx, screen, seq)
    resolved = None if (align["resolved"] == "1" and align["total"] < 2) else align["resolved"]
    values = hf.build(ctx, resolved)
    return form_mod.fill(form, values, live=live and align["safe"], overwrite=overwrite,
                         select=select), align


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="verify_fill_hf")
    p.add_argument("doc_id")
    p.add_argument("--seq", default=None)
    p.add_argument("--env", default=None)
    args = p.parse_args(argv)
    cfg = load_config(args.env)

    forms = [f for f in driver.find_windows(driver.FORM_CLASS_PREFIX) if f.class_name == FORM_CLASS]
    if not forms:
        others = [f.class_name for f in driver.find_windows(driver.FORM_CLASS_PREFIX)]
        print(f"HUG 담보폼({FORM_CLASS})이 안 열려 있습니다. (열린: {others or '없음'})",
              file=sys.stderr)
        return 1
    rows = build_fill_hf(cfg, args.doc_id, forms[0], args.seq)
    print(f"===== {args.doc_id} — HUG auto-fill 채울값 ↔ 화면 =====")
    order = {"❌불일치": 0, "🖊우리채움": 1, "📄화면만": 2, "✅일치": 3}
    for mark, label, ours, theirs in sorted(rows, key=lambda r: (order[r[0]], r[1])):
        print(f"  [{mark:6}] {label[:18]:20} 채울값={ours[:26]:28} 화면={theirs[:24]}")
    for m in ("✅일치", "❌불일치", "🖊우리채움", "📄화면만"):
        print(f"  {m}: {sum(1 for r in rows if r[0] == m)}", end="")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
