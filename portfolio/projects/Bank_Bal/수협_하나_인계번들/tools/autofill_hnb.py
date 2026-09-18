"""하나은행 담보 폼 자동입력 — 물건 하나 또는 **다물건 순번순회(--all)**.

하나는 화면에 물건 하나씩 보이고 순번(일련번호)으로 넘긴다. `--all` 은 물건그리드를
Ctrl+Home 으로 맨 위(순번1)로 보낸 뒤, 물건마다 [순번·감정평가액 확인 → 채움 → DOWN]
을 반복해 **모든 물건**을 채운다.

⚠️ 반드시 **연습/더미건**으로 먼저. 기본 드라이런. --live 는 승격(관리자) 세션에서만
   쓰기가 된다. 순번이 화면과 안 맞으면(감정평가액 불일치) 그 물건 실입력을 건너뛴다.

    (화면에 하나 담보폼 열어둔 상태)
    python tools/autofill_hnb.py 01-2609-3-2751            # 현재 물건 드라이런
    python tools/autofill_hnb.py 01-2609-3-2751 --all      # 전물건 드라이런
    python tools/autofill_hnb.py 01-2609-3-2751 --all --live   # 전물건 실입력(승격에서!)
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
from bankon.mapping import hnb                  # noqa: E402
from bankon.parse import detail                 # noqa: E402
from bankon.ui import driver, form              # noqa: E402
from pywinauto.keyboard import send_keys        # noqa: E402
import verify_form as vf                         # noqa: E402
import verify_fill_kb as VK                      # noqa: E402
import verify_fill_hnb as VH                     # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

FORM_CLASS = "TBNKHNB24DAMB"


def _row_key(form):
    """현재 폼이 보는 물건 행의 식별키 — 번지+등기(둘 중 있는 것). 행 이동 감지용."""
    sc = vf.screen_values(form)
    return (VH._banji(sc.get("번지", "")), (sc.get("등기부고유번호") or "").strip(),
            (sc.get("건물명") or "").strip())


def _property_grid(form):
    """물건 **행**을 바꾸는 그리드 — DOWN 이 행 식별키(번지/등기/건물명)를 바꾸는 쪽.

    실측: 완료건은 오른쪽 그리드가 순번을, 미입력 다행건은 왼쪽 그리드가 번지를 바꾼다.
    폼/상태마다 다르므로 **키가 실제로 바뀌는 그리드**를 시험으로 고른다(순번·번지 무관).
    못 찾으면 None. 시험 후 반드시 Ctrl+Home 으로 맨 위로 복원한다.
    """
    grids = [c for c in driver.descendants(form.handle)
             if c.element_info.class_name == "TcxGridSite"]
    for g in grids:
        try:
            g.set_focus(); time.sleep(0.2)
            send_keys("^{HOME}"); time.sleep(0.3)
            k1 = _row_key(form)
            send_keys("{DOWN}"); time.sleep(0.35)
            k2 = _row_key(form)
            send_keys("^{HOME}"); time.sleep(0.3)               # 맨 위로 복원
            if k1 != k2 and any(k2):                            # 행이 바뀌었다
                return g
        except Exception:
            continue
    return None


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="autofill_hnb")
    p.add_argument("doc_id")
    p.add_argument("--all", action="store_true", help="다물건 전부 순번순회하며 채움")
    p.add_argument("--live", action="store_true", help="실제 입력(승격 세션에서만)")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--select", action="store_true", help="콤보도 자동선택")
    p.add_argument("--seq", default=None)
    p.add_argument("--env", default=None)
    p.add_argument("--i-understand-experimental", action="store_true",
                   help="실험 경로(--all --live · --select) 봉인 해제. 감사 P0 미해결이라 기본 봉인.")
    args = p.parse_args(argv)
    cfg = load_config(args.env)

    # 감사(P0-C/D)에서 --all --live(다물건 순회)와 --select(콤보 커밋)는 비가역·오행 위험이
    # 확인됐다. 명시 플래그 없이는 실입력을 봉인한다. 드라이런(--live 없음)은 항상 허용.
    if args.live and not args.i_understand_experimental:
        if args.all:
            print("⛔ --all --live(다물건 순회)는 감사 P0-C(틀린행 write 위험)로 봉인됨. "
                  "단일물건은 --all 없이 실입력하세요. (정말 필요하면 --i-understand-experimental)",
                  file=sys.stderr)
            return 2
        if args.select:
            print("⛔ --select(콤보 자동선택)는 감사 P0-D(닫힌 드롭다운 ENTER→폼 저장 커밋 위험)로 "
                  "봉인됨. 콤보는 사람이 선택하세요. (정말 필요하면 --i-understand-experimental)",
                  file=sys.stderr)
            return 2

    forms = [f for f in driver.find_windows(driver.FORM_CLASS_PREFIX) if f.class_name == FORM_CLASS]
    if not forms:
        print("하나 담보 화면(TBNKHNB24DAMB)이 안 열려 있습니다.", file=sys.stderr)
        return 1
    form_ref = forms[0]

    gam = process_gam(cfg.gamexport_exe, str(VK.fetch_gam_local(cfg, args.doc_id)),
                      str(Path("output") / args.doc_id))
    ctx = vf.build_context(cfg, args.doc_id, gam.tables, vf.sections_from_gam(gam))
    anchors = [r for r in ctx.details if (r.is_land or r.is_building) and r.amount is not None]
    total = len(anchors)
    mode = "🔴 실입력(LIVE)" if args.live else "🟢 드라이런(계획만)"
    from bankon.ui import form as form_mod

    KNOWN = {"토지", "건물"}     # 하나 물건종류 콤보(부동산). 선박·어업권·기계는 미지원.

    if not args.all:
        screen = vf.screen_values(form_ref)
        seq = args.seq or VH._screen_seq(screen)
        align = VH.seq_alignment(ctx, screen, seq)
        values = hnb.build(ctx, str(seq))
        # 미지원 유형 가드(감사 P0-A) — 물건종류가 부동산이 아니면(선박·어업권 등) 실입력 보류.
        supported = values.get("물건종류") in KNOWN
        print(f"===== {args.doc_id} 하나 자동입력 순번{seq} — {mode} =====")
        if total >= 2:
            print(f"  📍다물건 {total}건 · 화면순번={align['screen_seq']} "
                  f"→ 채울물건={align['resolved']} ({align['by']}) "
                  f"{'✅정합' if align['safe'] else '⚠불명확'}")
        if not supported:
            print(f"  ⚠ 물건종류={values.get('물건종류')!r} — 부동산(토지·건물) 아님. "
                  f"선박·어업권 등 미지원 → 실입력 보류(계획만).")
        results = form_mod.fill(form_ref, values,
                                live=args.live and align["safe"] and supported,
                                overwrite=args.overwrite, select=args.select)
        _report(results, args.live)
        return 0

    # --- 다물건 순회 (행마다 번지로 소스물건 매칭해 채움) ---
    print(f"===== {args.doc_id} 하나 자동입력 전물건({total}) 순회 — {mode} =====")
    if not args.live:
        # 드라이런: 폼 행을 못 넘기니 소스 물건별 계획만 보여준다.
        for i in range(1, total + 1):
            v = hnb.build(ctx, str(i))
            plan = sum(1 for r in form_mod.fill(form_ref, v, live=False,
                       overwrite=args.overwrite, select=args.select)
                       if r.action in ("채움", "덮어씀"))
            print(f"  소스물건{i}/{total} · 번지={v.get('번지')} 감정평가액={v.get('감정평가액')} · 계획{plan}")
        print("\n(드라이런 — 실입력하려면 --all --live, 승격 세션에서 연습건 먼저)")
        return 0

    driver.require_desktop()          # 순회 중 화면 잠기면 키 주입이 엉뚱한 창으로 간다
    grid = _property_grid(form_ref)
    if grid is None:
        print("  ⚠ 물건 행을 넘기는 그리드를 못 찾음(단일행이거나 폼 상태 다름) — 순회 보류.")
        return 1
    done_total = 0
    seen_keys = set()
    for step in range(total + 2):                      # 행 수만큼(+여유) 순회
        grid.set_focus(); time.sleep(0.15)
        if step > 0:
            send_keys("{DOWN}"); time.sleep(0.35)
        key = _row_key(form_ref)
        if key in seen_keys:                           # 더 내려갈 행이 없다(끝)
            break
        seen_keys.add(key)
        screen = vf.screen_values(form_ref)
        # 화면 **번지**로 소스 물건을 찾는다(빈 폼도 번지는 auto-generated 로 차 있다).
        seq, how = VH.match_seq_by_banji(ctx, screen)
        scr_banji = VH._banji(screen.get("번지", ""))
        values = hnb.build(ctx, str(seq))
        our_banji = VH._banji(values.get("번지", ""))
        matched = bool(scr_banji and our_banji == scr_banji)
        results = form_mod.fill(form_ref, values, live=matched,
                                overwrite=args.overwrite, select=args.select)
        wrote = sum(1 for r in results if r.wrote)
        done_total += wrote
        tag = f"✅입력{wrote}" if matched else "⚠번지불일치→보류"
        print(f"  행{step+1} · 화면번지={scr_banji or '?'} → 소스물건{seq}({how}) · {tag}")
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
