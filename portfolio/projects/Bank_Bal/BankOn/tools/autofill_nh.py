"""농협 담보 폼(TBNKNHB24DAMB) 자동입력 — 단일 물건 폼(화면이 보고 있는 물건 슬롯 하나).

기본은 **드라이런**(계획만, 화면 안 건드림). 실제 입력은 `--live` 로만. 저장은 여기서 하지 않는다.
농협 폼은 국민·기업과 달리 물건 행/세부내역 표가 없고, 화면이 `일련번호` 슬롯으로 물건을 넘긴다.
다물건 문서는 화면이 보고 있는 물건이 우리 몇 번째인지 `verify_fill_nh.resolve_seq` 로 정합한다
(면적 → 호 → 금액 → 화면 일련번호 순, 인계본 규칙).
    (화면에 농협 담보폼 열어둔 상태)
    python tools/autofill_nh.py 01-2608-3-2625            # 드라이런
    python tools/autofill_nh.py 01-2608-3-2625 --live     # 실제 입력(연습건에서만!)
    --seq N      우리 물건 순번을 직접 지정(정합 건너뜀)
매핑 근거: 인계본 D:\\AI\\BankOn(2026-08-28) — 실폼 14건 정답지 ✅400/❌6 + 무인 순회 116건. 2026-09-07 이식.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bankon.config import load_config          # noqa: E402
from bankon.gam_bridge import process_gam       # noqa: E402
from bankon.mapping import nh                   # noqa: E402
from bankon.ui import driver, form              # noqa: E402
import verify_form as vf                         # noqa: E402
import verify_fill_kb as VK                      # noqa: E402
import verify_fill_nh as VN                      # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

FORM_CLASS = "TBNKNHB24DAMB"
ORDER = {"거부": 0, "덮어씀": 1, "선택(덮어씀)": 1, "미발견": 2, "채움": 3, "선택": 3, "수동(선택형)": 4, "일치": 5, "빈값": 6}
from bankon import paths as _paths               # noqa: E402
COMBO_LISTS = form.load_combo_lists(_paths.RECON_DIR / f"combo_{FORM_CLASS}.md")
LAST_ALIGN: dict = {}     # 마지막 실행의 다물건 정합 정보(run_nh_full 이 요약에 쓴다)
EXIT_UNALIGNED = 2        # 다물건 정합 불명확으로 실입력을 건너뛴 경우(exit 1 = 거부 칸 있음, 채우긴 했음)


def _report(results, totals):
    for r in sorted(results, key=lambda x: (ORDER.get(x.action.split("(")[0] if x.action.startswith("거부") else x.action, 9), x.label)):
        if r.action == "빈값":
            continue
        mark = "✍" + ("완료" if r.wrote else "") if r.action in ("채움", "덮어씀", "선택", "선택(덮어씀)") else r.action
        name = form.display_label(r.label)
        print(f"  [{mark:9}] {name[:18]:20} 넣을값={r.ours[:24]:26} 현재={r.current[:20]}")
    totals["채움"] += sum(1 for x in results if x.action in ("채움", "덮어씀", "선택", "선택(덮어씀)"))
    totals["일치"] += sum(1 for x in results if x.action == "일치")
    totals["수동"] += sum(1 for x in results if x.action == "수동(선택형)")
    totals["미발견"] += sum(1 for x in results if x.action == "미발견")
    totals["거부"] += sum(1 for x in results if x.action.startswith("거부"))
    totals["완료"] += sum(1 for x in results if x.wrote)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="autofill_nh")
    p.add_argument("doc_id")
    p.add_argument("--live", action="store_true")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--no-touch", action="store_true", help="(호환용) 농협 폼은 드라이런에서 아무것도 안 건드린다")
    p.add_argument("--seq", default=None, help="우리 물건 순번(다물건 정합 건너뜀)")
    p.add_argument("--env", default=None)
    args = p.parse_args(argv)
    cfg = load_config(args.env)

    forms = [f for f in driver.find_windows(driver.FORM_CLASS_PREFIX) if f.class_name == FORM_CLASS]
    if not forms:
        print(f"농협 담보 화면({FORM_CLASS})이 안 열려 있습니다.", file=sys.stderr)
        return 1
    form_ref = forms[0]

    gam = process_gam(cfg.gamexport_exe, str(VK.fetch_gam_local(cfg, args.doc_id)),
                      str(Path("output") / args.doc_id))
    ctx = vf.build_context(cfg, args.doc_id, gam.tables, vf.sections_from_gam(gam))
    screen = vf.screen_values(form_ref)
    align = VN.seq_alignment(ctx, screen, args.seq)
    LAST_ALIGN.clear(); LAST_ALIGN.update(align)
    seq = align["resolved"] if align["total"] >= 2 else None
    values = nh.build(ctx, seq)
    variant = "지역농협" if nh.is_local_coop(ctx) else "농협은행"
    kind = "토지형" if "공부지목" in values else ("건물형" if "건물명" in values else "?")

    mode = "🔴 실제입력(LIVE)" if args.live else "🟢 드라이런(계획만)"
    print(f"===== {args.doc_id} 농협 자동입력 — {mode} · {variant}·{kind} · 물건 {align['total']}개 "
          f"(화면 슬롯 {align.get('screen_seq') or '?'} → 우리 {align['resolved']} · {align['by']}) =====")
    if align["total"] >= 2 and not align["safe"]:
        print("  ⚠ 다물건 정합이 불명확 — 실입력은 보류(드라이런만).")
        if args.live:
            return EXIT_UNALIGNED      # 아무것도 안 채움 — 러너는 이걸 '거부'와 구분해 저장 없이 실패로 끝내야 한다
    totals = {"채움": 0, "일치": 0, "수동": 0, "미발견": 0, "거부": 0, "완료": 0}
    results = form.fill(form_ref, values, live=args.live, overwrite=args.overwrite, combo_lists=COMBO_LISTS)
    _report(results, totals)

    label = "입력완료" if args.live else "채울계획"
    print(f"\n[전체] {label} {totals['완료'] if args.live else totals['채움']} · 일치 {totals['일치']} · "
          f"수동 {totals['수동']} · 칸못찾음 {totals['미발견']} · 거부 {totals['거부']}")
    return 1 if totals["거부"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
