"""수협 담보(TBNKSSB24DAMB) — 정품추출 → ssb 매핑 → "채울값 ↔ 화면" 대조 / 채우기.

농협판(verify_fill_nh)의 수협판. 읽기 전용(채우기는 fill_ssb 를 부르는 순회·러너에서만).
인계본(D:\\AI\\BankOn 계통, 수협_하나_인계번들 2026-09-07) → 이 계통 이식 2026-09-10.
인계 라이브 검증: 토지·집합물건 40건+ 전필드 일치, 2026-09-08 재검증 5건 ❌0.

  화면에 수협 담보폼 열어둔 상태에서:
    python tools/verify_fill_ssb.py 01-2608-3-2637
"""
from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bankon import paths as _paths              # noqa: E402
from bankon.config import load_config          # noqa: E402
from bankon.gam_bridge import process_gam       # noqa: E402
from bankon.mapping import ssb                  # noqa: E402
from bankon.parse import detail                 # noqa: E402
from bankon.ui import driver                    # noqa: E402
from bankon.ui import form as form_mod          # noqa: E402
import verify_form as vf                         # noqa: E402
import verify_fill_kb as VK                      # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

FORM_CLASS = "TBNKSSB24DAMB"
COMBO_LISTS = form_mod.load_combo_lists(_paths.RECON_DIR / f"combo_{FORM_CLASS}.md")
# 자동입력 대상 물건구분(부동산 3종). 선박·어업권·동산 등은 매핑이 없어 실입력 보류(인계본 미지원 가드 P0-A).
KNOWN_KINDS = frozenset({"토지", "집합물건(건물)", "건물"})
_CODE = re.compile(r"\((\d+)\)\s*$")


def norm(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text or "")
    return _CODE.sub("", folded).replace(",", "").replace(" ", "").strip()


ZERO_PADDED = ("본번지", "부번지")


def compare_text(label: str, text: str) -> str:
    value = norm(text)
    if label in ZERO_PADDED and value.isdigit():
        return value.lstrip("0") or "0"
    return value


def _property_rows(ctx):
    return [r for r in ctx.details if (r.is_land or r.is_building)]


def _mark(screen) -> str:
    return norm(screen.get("기   호", "") or screen.get("기호", ""))


def resolve_seq(ctx, screen, seq=None) -> str | None:
    """다물건 순번 정합 — 화면 `기   호`(가/1..) 로 우리 물건을 고른다.

    수협 화면 `기호` 는 명세행 NO(1/2/가/나)를 그대로 쓴다(실측 2660: 화면 '가' = 건물).
    기호가 명세에 한 번만 있으면 그대로, 아니면 면적·감정평가액으로 좁힌다.
    """
    if seq:
        return str(seq)
    rows = _property_rows(ctx)
    mark = _mark(screen)
    if mark and sum(1 for r in rows if r.seq_no == mark) == 1:
        return mark

    anchors = [r for r in rows if r.amount is not None]
    if len(anchors) < 2:
        return None
    area = norm(screen.get("사정면적", "") or screen.get("공부면적", ""))
    if area:
        for index, row in enumerate(anchors, 1):
            for candidate in (row.area_assessed, row.area_public):
                if candidate is not None and norm(f"{candidate:.2f}") == area:
                    return str(index)
    amount = norm(screen.get("감정평가액", ""))
    if amount.isdigit():
        matched = [i for i, r in enumerate(anchors, 1) if str(int(r.amount)) == amount]
        if len(matched) == 1:
            return str(matched[0])
    return mark or None


def seq_alignment(ctx, screen, seq=None) -> dict:
    """순번 정합 — safe 는 **실제 채워질 물건**이 화면과 정확히 일치할 때만 True.

    화면에 면적 문자열이 있다는 것만으로 safe 로 보면, resolve 가 형식차로 첫 물건에
    폴백해도 통과해 **다른 물건 값을 실입력**할 수 있다(인계본 감사 P0). 고른 물건의 면적·기호를 화면과 재확인한다.
    """
    rows = _property_rows(ctx)
    anchors = [r for r in rows if r.amount is not None]
    total = len(anchors)
    mark = _mark(screen)
    resolved = resolve_seq(ctx, screen, seq)
    if total < 2:
        return {"total": total, "screen_seq": mark or "1",
                "resolved": resolved or "1", "by": "단일물건", "safe": True}
    picked = detail.for_sequence(tuple(rows), resolved)
    screen_area = norm(screen.get("사정면적", "") or screen.get("공부면적", ""))
    picked_area = ""
    if picked is not None:
        for a in (picked.area_assessed, picked.area_public):
            if a is not None:
                picked_area = norm(f"{a:.2f}")
                break
    by_area = bool(screen_area and picked_area and screen_area == picked_area)
    by_mark = bool(mark and picked is not None and norm(picked.seq_no or "") == mark)
    by = "면적매칭" if by_area else ("기호매칭" if by_mark else "불명확")
    return {"total": total, "screen_seq": mark, "resolved": resolved or "1",
            "our_area": picked_area, "screen_area": screen_area,
            "by": by, "safe": bool(by_area or by_mark)}


def guard_reasons(ctx, values: dict, resolved) -> list[str]:
    """실입력을 보류해야 하는 이유들(빈 목록이면 실입력 가능). 드라이런·대조는 영향 없음.

    · 미지원 유형: 물건구분코드가 부동산 3종이 아니면(선박·어업권 등) — 매핑 없음(인계본 P0-A).
    · 집계형(rollup)·일단지 묶음머리: 소스로 면적·금액 결정 불가/규칙 미확정(2660·1158·1932) → 사람 확인(인계본 P0-3).
    """
    reasons = []
    kind = values.get("물건구분코드")
    if kind not in KNOWN_KINDS:
        reasons.append(f"미지원 물건구분코드={kind!r}(부동산 아님 — 선박·어업권 등)")
    rows = ctx.details
    if detail.is_rollup_only(rows):
        reasons.append("집계형(rollup) 명세")
    picked = detail.for_sequence(tuple(r for r in rows if r.is_land or r.is_building), resolved)
    if picked is not None and getattr(picked, "group_head", False):
        reasons.append("일단지(묶음머리) 물건")
    return reasons


def build_fill_ssb(cfg, doc: str, form, seq=None):
    """정품추출 → ssb 매핑 → "채울값 ↔ 화면" 대조행. 그리드 순회용."""
    gam = process_gam(cfg.gamexport_exe, str(VK.fetch_gam_local(cfg, doc)),
                      str(Path("output") / doc))
    ctx = vf.build_context(cfg, doc, gam.tables, vf.sections_from_gam(gam))
    screen = vf.screen_values(form)
    mine = ssb.build(ctx, resolve_seq(ctx, screen, seq))
    for label in mine:
        if form_mod.BAND_SPEC.match(str(label)):
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


def fill_ssb(cfg, doc: str, form, *, live: bool = False, overwrite: bool = False, seq=None):
    """수협 담보 폼에 매핑값을 채운다(기본 드라이런). 순회 채우기용."""
    gam = process_gam(cfg.gamexport_exe, str(VK.fetch_gam_local(cfg, doc)),
                      str(Path("output") / doc))
    ctx = vf.build_context(cfg, doc, gam.tables, vf.sections_from_gam(gam))
    screen = vf.screen_values(form)
    align = seq_alignment(ctx, screen, seq)
    resolved = None if (align["resolved"] == "1" and align["total"] < 2) else align["resolved"]
    values = ssb.build(ctx, resolved)
    do_live = live and align["safe"] and not guard_reasons(ctx, values, resolved)
    return form_mod.fill(form, values, live=do_live, overwrite=overwrite,
                         combo_lists=COMBO_LISTS), align


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="verify_fill_ssb")
    p.add_argument("doc_id")
    p.add_argument("--seq", default=None)
    p.add_argument("--env", default=None)
    args = p.parse_args(argv)
    cfg = load_config(args.env)

    forms = [f for f in driver.find_windows(driver.FORM_CLASS_PREFIX) if f.class_name == FORM_CLASS]
    if not forms:
        others = [f.class_name for f in driver.find_windows(driver.FORM_CLASS_PREFIX)]
        print(f"수협 담보폼({FORM_CLASS})이 안 열려 있습니다. (열린: {others or '없음'})",
              file=sys.stderr)
        return 1
    rows = build_fill_ssb(cfg, args.doc_id, forms[0], args.seq)
    print(f"===== {args.doc_id} — 수협 auto-fill 채울값 ↔ 화면 =====")
    order = {"❌불일치": 0, "🖊우리채움": 1, "📄화면만": 2, "✅일치": 3}
    for mark, label, ours, theirs in sorted(rows, key=lambda r: (order[r[0]], r[1])):
        print(f"  [{mark:6}] {label[:18]:20} 채울값={ours[:26]:28} 화면={theirs[:24]}")
    for m in ("✅일치", "❌불일치", "🖊우리채움", "📄화면만"):
        print(f"  {m}: {sum(1 for r in rows if r[0] == m)}", end="")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
