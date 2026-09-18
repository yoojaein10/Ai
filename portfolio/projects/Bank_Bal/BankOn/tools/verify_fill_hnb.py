"""하나은행 담보(TBNKHNB24DAMB) — 정품추출 → hnb 매핑 → "채울값 ↔ 화면" 대조 / 채우기.

수협판(verify_fill_ssb)의 하나판. 화면에 물건 하나씩 보이고 순번(일련번호)으로 넘긴다.
인계본(수협_하나_인계번들 2026-09-07) → 이 계통 이식 2026-09-10.
인계 라이브 검증: 토지·건물·집합건물 22건+ ✅18~20, 2026-09-08 재검증 4건 ❌0, 실입력 실측 2352 물건1 12칸.

  화면에 하나 담보폼 열어둔 상태에서:
    python tools/verify_fill_hnb.py 01-2609-3-2751
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
from bankon.mapping import hnb                  # noqa: E402
from bankon.parse import detail                 # noqa: E402
from bankon.ui import driver                    # noqa: E402
from bankon.ui import form as form_mod          # noqa: E402
import verify_form as vf                         # noqa: E402
import verify_fill_kb as VK                      # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

FORM_CLASS = "TBNKHNB24DAMB"
COMBO_LISTS = form_mod.load_combo_lists(_paths.RECON_DIR / f"combo_{FORM_CLASS}.md")
KNOWN_KINDS = frozenset({"토지", "건물"})       # 물건종류 콤보 4종 중 부동산(기계기구·특수부동산은 보류)


def norm(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text or "")
    return folded.replace(",", "").replace("-", "").replace(" ", "").strip()


def _property_rows(ctx):
    return [r for r in ctx.details if (r.is_land or r.is_building)]


def _banji(text: str) -> str:
    """번지 비교 정규화 — 본번-부번만(콤마·외·공백 제거). `424-67, 외` → `424-67`."""
    m = re.match(r"\s*(\d+)(?:\s*-\s*(\d+))?", str(text or ""))
    if not m:
        return ""
    return m.group(1) + ("-" + m.group(2) if m.group(2) else "")


def match_seq_by_banji(ctx, screen, seq=None):
    """화면 **번지**로 우리 물건 순번을 찾는다 — 빈 폼(감정값 없음)에서도 행을 가른다.

    반환: (순번문자열 or None, 방식). 화면 번지와 정확히 일치하는 물건이 하나면 그걸,
    없거나 여러 개면 순번 위치로 물러선다.
    """
    if seq:
        return str(seq), "지정"
    rows = _property_rows(ctx)
    scr_banji = _banji(screen.get("번지", ""))
    if scr_banji:
        hits = [i for i, r in enumerate(rows, 1)
                if _banji(r.jibun) == scr_banji or _banji(getattr(r, "location", "")) == scr_banji]
        if len(hits) == 1:
            return str(hits[0]), "번지매칭"
    s = _screen_seq(screen)
    return (s if s.isdigit() else "1"), "순번위치"


def _screen_seq(screen) -> str:
    """화면 물건 순번(일련번호) — 두 일련번호 칸 중 한 자리 숫자 쪽(9자리 serial 은 BANK24 자동생성)."""
    for key in ("일련번호", "일련번호_0", "일련번호_1"):
        v = norm(screen.get(key, ""))
        if v.isdigit() and len(v) <= 2:
            return v
    return norm(screen.get("일련번호", "")) or "1"


def resolve_seq(ctx, screen, seq=None) -> str | None:
    """화면 순번 → 채울 물건. 하나는 화면 순번 N = 소스 N번째(직접)."""
    if seq:
        return str(seq)
    s = _screen_seq(screen)
    return s if s.isdigit() else "1"


def seq_alignment(ctx, screen, seq=None) -> dict:
    """순번 정합 — 뽑은 물건의 감정평가액이 화면과 정확일치할 때만 safe(빈 폼은 순번 위치).

    화면 물건 수는 **단가별 행 + 평가외 행**이다(hnb.slots — 실측 2871: 4 + 옥탑 1 = 5행).
    """
    rows = _property_rows(ctx)
    total = len(hnb.slots(ctx))
    s = seq or _screen_seq(screen)
    picked = hnb._slot_item(ctx, str(s))
    scr_amt = norm(screen.get("감정평가액", ""))
    our_amt = str(int(picked.amount)) if (picked and picked.amount is not None) else ""
    by_amt = bool(scr_amt and our_amt and scr_amt == our_amt)
    # 빈 폼(감정평가액 미입력)은 금액으로 못 가리므로 **순번 위치**에 의존한다.
    # 폼에 금액이 이미 있으면(완료건) 우리 물건과 정확일치할 때만 safe.
    safe = by_amt or (not scr_amt)
    if total < 2:
        return {"total": total, "screen_seq": str(s), "resolved": str(s),
                "by": "단일물건", "safe": True}
    return {"total": total, "screen_seq": str(s), "resolved": str(s),
            "our_amt": our_amt, "screen_amt": scr_amt,
            "by": "금액매칭" if by_amt else ("빈폼순번" if not scr_amt else "불명확"),
            "safe": safe}


def guard_reasons(ctx, values: dict, resolved) -> list[str]:
    """실입력 보류 사유(빈 목록이면 실입력 가능). 미지원 물건종류(기계기구·특수부동산 등)만 본다.
    rollup 은 매핑이 면적·금액을 비우므로 여기서 막지 않는다(인계본 P0-B 이식)."""
    kind = values.get("물건종류")
    return [] if kind in KNOWN_KINDS else [f"미지원 물건종류={kind!r}(토지·건물 아님)"]


def build_fill_hnb(cfg, doc: str, form, seq=None):
    """정품추출 → hnb 매핑 → "채울값 ↔ 화면" 대조행."""
    gam = process_gam(cfg.gamexport_exe, str(VK.fetch_gam_local(cfg, doc)),
                      str(Path("output") / doc))
    ctx = vf.build_context(cfg, doc, gam.tables, vf.sections_from_gam(gam))
    screen = vf.screen_values(form)
    mine = hnb.build(ctx, resolve_seq(ctx, screen, seq))
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


def fill_hnb(cfg, doc: str, form, *, live: bool = False, overwrite: bool = False, seq=None):
    """하나 담보 폼에 매핑값을 채운다(기본 드라이런). 물건 하나."""
    gam = process_gam(cfg.gamexport_exe, str(VK.fetch_gam_local(cfg, doc)),
                      str(Path("output") / doc))
    ctx = vf.build_context(cfg, doc, gam.tables, vf.sections_from_gam(gam))
    screen = vf.screen_values(form)
    align = seq_alignment(ctx, screen, seq)
    values = hnb.build(ctx, align["resolved"])
    do_live = live and align["safe"] and not guard_reasons(ctx, values, align["resolved"])
    return form_mod.fill(form, values, live=do_live, overwrite=overwrite,
                         combo_lists=COMBO_LISTS), align


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="verify_fill_hnb")
    p.add_argument("doc_id")
    p.add_argument("--seq", default=None)
    p.add_argument("--env", default=None)
    args = p.parse_args(argv)
    cfg = load_config(args.env)
    forms = [f for f in driver.find_windows(driver.FORM_CLASS_PREFIX) if f.class_name == FORM_CLASS]
    if not forms:
        others = [f.class_name for f in driver.find_windows(driver.FORM_CLASS_PREFIX)]
        print(f"하나 담보폼({FORM_CLASS})이 안 열려 있습니다. (열린: {others or '없음'})", file=sys.stderr)
        return 1
    rows = build_fill_hnb(cfg, args.doc_id, forms[0], args.seq)
    print(f"===== {args.doc_id} — 하나 auto-fill 채울값 ↔ 화면 =====")
    order = {"❌불일치": 0, "🖊우리채움": 1, "📄화면만": 2, "✅일치": 3}
    for mark, label, ours, theirs in sorted(rows, key=lambda r: (order[r[0]], r[1])):
        print(f"  [{mark:6}] {label[:16]:18} 채울값={ours[:24]:26} 화면={theirs[:22]}")
    for m in ("✅일치", "❌불일치", "🖊우리채움", "📄화면만"):
        print(f"  {m}: {sum(1 for r in rows if r[0] == m)}", end="")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
