"""수협 담보 폼 자동입력 — 매핑값을 화면에 채운다(되읽기 검증, 순번 정합).

verify_fill_ssb 가 "채울값 ↔ 화면" 검증이라면, 이건 그 값을 **실제로 입력**한다.
기본은 **드라이런**(계획만). 실제 입력은 `--live` 로만.

⚠️ 실제 입력은 반드시 **연습/더미 감정서**로 먼저 시험하세요. 텍스트·숫자·날짜칸만 자동
   입력하고, 선택형(콤보)은 `--select` 없으면 '수동'으로 남깁니다. 다물건은 화면 기호·감정
   평가액으로 순번을 정합해 채우며, 어느 물건인지 불명확하면 실입력을 보류합니다.

⚠️ **선박·어업권·대형 일단지·일반건물(집계형)은 미지원** — 부동산 단순건(토지·집합물건)만
   안전합니다. 물건구분코드가 예상 밖이거나 순번이 불명확하면 실입력이 보류됩니다.

    (화면에 수협 담보폼 열어둔 상태)
    python tools/autofill_ssb.py 01-2608-3-2609            # 드라이런(계획만)
    python tools/autofill_ssb.py 01-2608-3-2609 --live     # 실제 입력(연습건에서만!)
    # --select(콤보 자동선택)는 감사 P0-D 로 봉인됨 — 콤보는 사람이 선택.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bankon.config import load_config          # noqa: E402
from bankon.gam_bridge import process_gam       # noqa: E402
from bankon.mapping import ssb                  # noqa: E402
from bankon.parse import detail                 # noqa: E402
from bankon.ui import driver, form              # noqa: E402
import verify_form as vf                         # noqa: E402
import verify_fill_kb as VK                      # noqa: E402
import verify_fill_ssb as VS                     # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

FORM_CLASS = "TBNKSSB24DAMB"
ORDER = {"거부": 0, "덮어씀": 1, "미발견": 2, "채움": 3, "수동(선택형)": 4,
         "순번(안건드림)": 5, "일치": 6, "빈값": 7}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="autofill_ssb")
    p.add_argument("doc_id")
    p.add_argument("--live", action="store_true", help="실제 입력(기본은 드라이런)")
    p.add_argument("--overwrite", action="store_true", help="사람이 넣은 값도 덮어씀(기본 빈칸만)")
    p.add_argument("--seq", default=None, help="물건 순번(기본=화면 자동정합)")
    p.add_argument("--select", action="store_true",
                   help="콤보도 자동선택. 목록에 없으면 ESC 로 취소하고 원래 값을 둔다")
    p.add_argument("--i-understand-experimental", action="store_true",
                   help="실험 경로(--select) 봉인 해제. 감사 P0-D 미해결이라 기본 봉인.")
    p.add_argument("--env", default=None)
    args = p.parse_args(argv)
    cfg = load_config(args.env)

    # 감사(P0-D): --select(콤보 자동선택)는 닫힌 드롭다운에 ENTER 가 가면 폼 기본버튼(저장)이
    # 눌려 비가역 커밋될 위험이 확인됐다(수협 콤보 목록 공백으로 느린 훑기 강제라 더 위험).
    # 명시 플래그 없이는 봉인. 드라이런(--live 없음)은 항상 허용.
    if args.live and args.select and not args.i_understand_experimental:
        print("⛔ --select(콤보 자동선택)는 감사 P0-D(닫힌 드롭다운 ENTER→폼 저장 커밋 위험)로 "
              "봉인됨. 콤보는 사람이 선택하세요. (정말 필요하면 --i-understand-experimental)",
              file=sys.stderr)
        return 2

    forms = [f for f in driver.find_windows(driver.FORM_CLASS_PREFIX) if f.class_name == FORM_CLASS]
    if not forms:
        print("수협 담보 화면(TBNKSSB24DAMB)이 안 열려 있습니다.", file=sys.stderr)
        return 1
    form_ref = forms[0]

    gam = process_gam(cfg.gamexport_exe, str(VK.fetch_gam_local(cfg, args.doc_id)),
                      str(Path("output") / args.doc_id))
    ctx = vf.build_context(cfg, args.doc_id, gam.tables, vf.sections_from_gam(gam))
    screen = vf.screen_values(form_ref)
    align = VS.seq_alignment(ctx, screen, args.seq)
    resolved = None if (align["resolved"] == "1" and align["total"] < 2) else align["resolved"]
    values = ssb.build(ctx, resolved)

    mode = "🔴 실제입력(LIVE)" if args.live else "🟢 드라이런(계획만, 화면 안 건드림)"
    print(f"===== {args.doc_id} 수협 자동입력 — {mode} =====")
    if align["total"] >= 2:                         # 다물건 순번 정합 표시
        flag = "✅정합" if align["safe"] else "⚠불명확"
        print(f"  📍다물건 {align['total']}건 · 화면 기호={align['screen_seq'] or '?'} "
              f"→ 채울 순번={align['resolved']} ({align['by']}) {flag}")

    # 미지원 유형 가드 — 물건구분코드가 부동산 3종이 아니면 실입력 보류(선박·어업권 등)
    kind = values.get("물건구분코드")
    KNOWN = {"토지", "집합물건(건물)", "건물"}
    supported = kind in KNOWN
    if not supported:
        print(f"  ⚠ 물건구분코드={kind!r} — 부동산(토지·집합물건·건물)이 아님. "
              f"선박·어업권 등 미지원 → 실입력 보류(계획만).")

    # 감사 P0-3: 집계형(rollup)·일단지(묶음머리) 다물건은 소스로 면적·금액 결정이 불가하거나
    # 규칙 미확정이라(2660·1158·1932 등) 틀린 값 실입력 위험 → 실입력 보류. 사람이 확인.
    rows = ctx.details
    is_rollup = detail.is_rollup_only(rows)
    picked = detail.for_sequence(tuple(r for r in rows if r.is_land or r.is_building), resolved)
    is_group = bool(picked and getattr(picked, "group_head", False))
    if is_rollup or is_group:
        why = "집계형(rollup)" if is_rollup else "일단지(묶음머리)"
        print(f"  ⚠ {why} — 소스로 면적·금액 결정 불가/규칙 미확정 → 실입력 보류(계획만). 사람 확인.")

    do_live = args.live and align["safe"] and supported and not (is_rollup or is_group)
    results = form.fill(form_ref, values, live=do_live, overwrite=args.overwrite,
                        select=args.select)
    if args.live and not align["safe"]:
        print("  ⚠ 대상 물건 불명확 → 실입력 보류(계획만). 화면 물건 확인 후 --seq 로 지정하세요.")

    for r in sorted(results, key=lambda x: (ORDER.get(x.action if not x.action.startswith("거부")
                                                       else "거부", 9), x.label)):
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
