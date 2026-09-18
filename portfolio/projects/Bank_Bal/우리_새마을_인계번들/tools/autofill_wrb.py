"""우리은행 담보 폼 자동입력 — 물건 하나 또는 **다물건 순번순회(--all)**.

하나판(autofill_hnb)의 우리판. 화면에 물건 하나씩 보이고 순번(일련번호)으로 넘긴다.
`--all` 은 물건 selector 그리드를 Ctrl+Home→DOWN 반복하며, 각 행의 **번지로 소스물건
매칭**해 채운다(대형 다물건 21개도 전부).

⚠️ 반드시 **연습/더미건**으로 먼저. 기본 드라이런. --live 는 승격(관리자)에서만.
   --all --live(순회)·--select(콤보)는 감사 P0 로 **봉인**(--i-understand-experimental 로만).

    python tools/autofill_wrb.py 01-2608-3-2668            # 단일 드라이런
    python tools/autofill_wrb.py 01-2608-3-2668 --all      # 전물건 드라이런
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bankon.config import load_config          # noqa: E402
from bankon.gam_bridge import process_gam       # noqa: E402
from bankon.mapping import wrb                  # noqa: E402
from bankon.parse import detail                 # noqa: E402
from bankon.ui import driver                    # noqa: E402
from pywinauto.keyboard import send_keys        # noqa: E402
import verify_form as vf                         # noqa: E402
import verify_fill_kb as VK                      # noqa: E402
import verify_fill_wrb as VW                     # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

FORM_CLASS = "TBNKWRB24DAMB"
# 우리 물건종류 콤보에서 부동산 계열(자동입력 대상). 선박·어업권·차량·기계 등은 보류.
KNOWN_REALTY = {"단독주택", "다가구주택", "아파트", "연립주택", "다세대주택", "근린주택",
                "근린상가", "상가", "상가(아파트형)", "건물", "오피스텔", "사무실",
                "공장(공장재단포함)", "창고", "나대지", "대형상업시설", "주유소(충전소)",
                "전", "답", "과수원", "임야", "잡종지"}


def _row_key(form):
    """현재 폼이 보는 물건 행의 식별키 — 본번-부번+감정평가액. 행 이동 감지용."""
    sc = vf.screen_values(form)
    bun = f"{sc.get('본번지') or ''}-{sc.get('부번지') or ''}"
    return (VW._banji(bun), VW.norm(sc.get("감정평가액", "")),
            (sc.get("건물명") or "").strip())


def _property_grid(form):
    """물건 **행**을 바꾸는 그리드 — DOWN 이 행 식별키를 바꾸는 쪽. 못 찾으면 None."""
    grids = [c for c in driver.descendants(form.handle)
             if c.element_info.class_name == "TcxGridSite"]
    for g in grids:
        try:
            g.set_focus(); time.sleep(0.2)
            send_keys("^{HOME}"); time.sleep(0.3)
            k1 = _row_key(form)
            send_keys("{DOWN}"); time.sleep(0.35)
            k2 = _row_key(form)
            send_keys("^{HOME}"); time.sleep(0.3)
            if k1 != k2 and any(k2):
                return g
        except Exception:
            continue
    return None


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="autofill_wrb")
    p.add_argument("doc_id")
    p.add_argument("--all", action="store_true", help="다물건 전부 순회하며 채움")
    p.add_argument("--live", action="store_true", help="실제 입력(승격 세션에서만)")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--select", action="store_true", help="콤보도 자동선택")
    p.add_argument("--seq", default=None)
    p.add_argument("--i-understand-experimental", action="store_true",
                   help="실험 경로(--all --live · --select) 봉인 해제. 감사 P0 미해결이라 기본 봉인.")
    p.add_argument("--env", default=None)
    args = p.parse_args(argv)
    cfg = load_config(args.env)

    # 감사(하나 P0-C/D 동형): --all --live·--select 는 비가역·오행 위험 → 봉인.
    if args.live and not args.i_understand_experimental:
        if args.all:
            print("⛔ --all --live(다물건 순회)는 감사 P0(틀린행 write 위험)로 봉인됨. "
                  "단일물건은 --all 없이. (정말 필요하면 --i-understand-experimental)", file=sys.stderr)
            return 2
        if args.select:
            print("⛔ --select(콤보 자동선택)는 감사 P0(닫힌 드롭다운 ENTER→저장 커밋)로 봉인됨. "
                  "콤보는 사람이 선택. (--i-understand-experimental)", file=sys.stderr)
            return 2

    forms = [f for f in driver.find_windows(driver.FORM_CLASS_PREFIX) if f.class_name == FORM_CLASS]
    if not forms:
        print("우리 담보 화면(TBNKWRB24DAMB)이 안 열려 있습니다.", file=sys.stderr)
        return 1
    form_ref = forms[0]

    gam = process_gam(cfg.gamexport_exe, str(VK.fetch_gam_local(cfg, args.doc_id)),
                      str(Path("output") / args.doc_id))
    ctx = vf.build_context(cfg, args.doc_id, gam.tables, vf.sections_from_gam(gam))
    anchors = [r for r in ctx.details if (r.is_land or r.is_building) and r.amount is not None]
    total = len(anchors)
    mode = "🔴 실입력(LIVE)" if args.live else "🟢 드라이런(계획만)"
    from bankon.ui import form as form_mod

    if not args.all:
        screen = vf.screen_values(form_ref)
        seq = args.seq or VW._screen_seq(screen)
        align = VW.seq_alignment(ctx, screen, seq)
        values = wrb.build(ctx, str(seq))
        supported = (values.get("물건종류") in KNOWN_REALTY) or (values.get("세부물건종류")
                     in ("대지", "건물"))
        print(f"===== {args.doc_id} 우리 자동입력 순번{seq} — {mode} =====")
        if total >= 2:
            print(f"  📍다물건 {total}건 · 화면순번={align['screen_seq']} → 채울물건={align['resolved']} "
                  f"({align['by']}) {'✅정합' if align['safe'] else '⚠불명확'}")
        if not supported:
            print(f"  ⚠ 물건종류={values.get('물건종류')!r} — 부동산 아님(선박·어업권 등) → 실입력 보류.")
        results = form_mod.fill(form_ref, values,
                                live=args.live and align["safe"] and supported,
                                overwrite=args.overwrite, select=args.select)
        _report(results, args.live)
        return 0

    # --- 다물건 순회 ---
    print(f"===== {args.doc_id} 우리 자동입력 전물건({total}) 순회 — {mode} =====")
    if not args.live:
        for i in range(1, total + 1):
            v = wrb.build(ctx, str(i))
            plan = sum(1 for r in form_mod.fill(form_ref, v, live=False,
                       overwrite=args.overwrite, select=args.select)
                       if r.action in ("채움", "덮어씀"))
            print(f"  소스물건{i}/{total} · 본번={v.get('본번지')}-{v.get('부번지')} "
                  f"감정평가액={v.get('감정평가액')} · 계획{plan}")
        print("\n(드라이런 — 실입력하려면 --all --live --i-understand-experimental, 승격·연습건 먼저)")
        return 0

    driver.require_desktop()
    grid = _property_grid(form_ref)
    if grid is None:
        print("  ⚠ 물건 행 그리드를 못 찾음(단일행이거나 폼 상태 다름) — 순회 보류.")
        return 1
    done_total, seen = 0, set()
    for step in range(total + 2):
        grid.set_focus(); time.sleep(0.15)
        if step > 0:
            send_keys("{DOWN}"); time.sleep(0.35)
        key = _row_key(form_ref)
        if key in seen:
            break
        seen.add(key)
        screen = vf.screen_values(form_ref)
        # 화면 순번(일련번호)의 소스물건을 채운다 — 실측 화면순번=소스순번. 화면에 감정평가액이
        # 있으면(완료건 재확인) 그 순번 소스물건 금액과 **교차검증**해 틀린 행이면 보류.
        cur_seq = VW._screen_seq(screen)
        values = wrb.build(ctx, cur_seq)
        scr_amt = VW.norm(screen.get("감정평가액", ""))
        our_amt = VW.norm(values.get("감정평가액", ""))
        amt_ok = (not scr_amt) or (scr_amt == our_amt)      # 빈폼이면 순번 신뢰, 값있으면 대조
        supported = (values.get("물건종류") in KNOWN_REALTY) or (values.get("세부물건종류")
                     in ("대지", "건물"))
        do = amt_ok and supported
        results = form_mod.fill(form_ref, values, live=do,
                                overwrite=args.overwrite, select=args.select)
        wrote = sum(1 for r in results if r.wrote)
        done_total += wrote
        tag = f"✅입력{wrote}" if do else (
            "⚠금액불일치→보류" if not amt_ok else "⚠미지원→보류")
        print(f"  행{step+1} · 화면순번={cur_seq} 금액={scr_amt or '(빈)'} → 소스물건{cur_seq} · {tag}")
    print(f"\n총 입력완료 {done_total}칸 · 저장은 사람이 (도구는 저장 안 함)")
    return 0


def _report(results, live):
    done = sum(1 for r in results if r.wrote)
    plan = sum(1 for r in results if r.action in ("채움", "덮어씀"))
    same = sum(1 for r in results if r.action == "일치")
    manual = sum(1 for r in results if r.action == "수동(선택형)")
    miss = sum(1 for r in results if r.action == "미발견")
    for r in sorted(results, key=lambda x: x.action):
        if r.action in ("빈값", "일치"):
            continue
        mark = ("✍완료" if r.wrote else "✍") if r.action in ("채움", "덮어씀") else r.action
        print(f"  [{mark:8}] {r.label[:16]:18} 넣을값={r.ours[:22]:24} 현재={r.current[:18]}")
    tag = f"입력완료 {done}" if live else f"채울계획 {plan}"
    print(f"\n{tag} · 이미일치 {same} · 수동필요 {manual} · 칸못찾음 {miss}")


if __name__ == "__main__":
    raise SystemExit(main())
