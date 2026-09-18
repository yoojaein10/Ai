"""국민 담보 폼 자동입력 — 매핑값을 화면에 채운다(되읽기 검증).

verify_fill_kb 가 "채울 값 ↔ 화면"을 보여주는 검증이라면, 이건 그 값을 **실제로 입력**한다.
기본은 **드라이런**(계획만, 화면 안 건드림). 실제 입력은 `--live` 로만.

⚠️ 실제 입력은 반드시 **연습/더미 감정서**로 먼저 시험하세요. 텍스트·숫자·날짜칸만 자동
   입력하고, 선택형(물건종류 콤보·평가방법 라디오·점검항목)은 '수동'으로 남깁니다.

    (화면에 국민 담보폼 열어둔 상태)
    python tools/autofill_kb.py 01-2605-3-1638            # 드라이런(계획만)
    python tools/autofill_kb.py 01-2605-3-1638 --live     # 실제 입력(연습건에서만!)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bankon.config import load_config          # noqa: E402
from bankon.gam_bridge import process_gam       # noqa: E402
from bankon.mapping import kookmin              # noqa: E402
from bankon.ui import driver, form              # noqa: E402
import verify_form as vf                         # noqa: E402
import verify_fill_kb as VK                      # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

FORM_CLASS = "TBNKKBB24DAMB"
ORDER = {"거부": 0, "덮어씀": 1, "미발견": 2, "채움": 3, "수동(선택형)": 4, "일치": 5, "빈값": 6}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="autofill_kb")
    p.add_argument("doc_id")
    p.add_argument("--live", action="store_true", help="실제 입력(기본은 드라이런)")
    p.add_argument("--overwrite", action="store_true",
                   help="사람이 넣은 값도 덮어씀(기본은 빈칸만 채움)")
    p.add_argument("--seq", default=None, help="물건 일련번호(기본=화면 자동정합)")
    p.add_argument("--env", default=None)
    args = p.parse_args(argv)
    cfg = load_config(args.env)

    forms = [f for f in driver.find_windows(driver.FORM_CLASS_PREFIX) if f.class_name == FORM_CLASS]
    if not forms:
        print("국민 담보 화면(TBNKKBB24DAMB)이 안 열려 있습니다.", file=sys.stderr)
        return 1
    form_ref = forms[0]

    gam = process_gam(cfg.gamexport_exe, str(VK.fetch_gam_local(cfg, args.doc_id)),
                      str(Path("output") / args.doc_id))
    ctx = vf.build_context(cfg, args.doc_id, gam.tables, vf.sections_from_gam(gam))
    screen = vf.screen_values(form_ref)
    align = VK.seq_alignment(ctx, screen, args.seq)
    resolved = None if (align["resolved"] == "1" and align["total"] < 2) else align["resolved"]
    values = kookmin.build(ctx, resolved)

    mode = "🔴 실제입력(LIVE)" if args.live else "🟢 드라이런(계획만, 화면 안 건드림)"
    print(f"===== {args.doc_id} 자동입력 — {mode} =====")
    if align["total"] >= 2:                        # 다물건 — 순번 정합 표시
        flag = "✅정합" if align["safe"] else "⚠불명확"
        print(f"  📍다물건 {align['total']}건 · 화면 일련번호={align['screen_seq'] or '?'} "
              f"→ 채울 물건 순번={align['resolved']} ({align['by']}) {flag}")
    do_live = args.live and align["safe"]
    results = form.fill(form_ref, values, live=do_live, overwrite=args.overwrite)
    if args.live and not align["safe"]:
        print("  ⚠ 대상 물건 불명확 → 실입력 보류(계획만). 화면 물건 확인 후 --seq 로 지정하세요.")
    for r in sorted(results, key=lambda x: (ORDER.get(x.action.split("(")[0] if x.action.startswith("거부") else x.action, 9), x.label)):
        if r.action == "빈값":
            continue
        mark = "✍" + ("완료" if r.wrote else "") if r.action in ("채움", "덮어씀") else r.action
        print(f"  [{mark:9}] {r.label[:16]:18} 넣을값={r.ours[:24]:26} 현재={r.current[:20]}")

    done = sum(1 for r in results if r.wrote)
    plan = sum(1 for r in results if r.action in ("채움", "덮어씀"))
    same = sum(1 for r in results if r.action == "일치")
    manual = sum(1 for r in results if r.action == "수동(선택형)")
    miss = sum(1 for r in results if r.action == "미발견")
    if args.live:
        print(f"\n입력완료 {done} · 이미일치 {same} · 수동필요 {manual} · 칸못찾음 {miss}")
    else:
        print(f"\n채울계획 {plan} · 이미일치 {same} · 수동필요 {manual} · 칸못찾음 {miss}"
              f"\n(실제 입력하려면 --live, 반드시 연습건에서 먼저)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
