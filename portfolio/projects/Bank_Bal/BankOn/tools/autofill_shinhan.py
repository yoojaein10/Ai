"""신한 담보 폼 자동입력 — 매핑값을 화면에 채운다(되읽기 검증).

verify_fill 이 "채울 값 ↔ 화면"을 보여주는 검증이라면, 이건 그 값을 **실제로 입력**한다.
기본은 **드라이런**(계획만, 화면 안 건드림). 실제 입력은 `--live` 로만.

⚠️ 실제 입력은 반드시 **연습/더미 감정서**로 먼저 시험하세요. 텍스트·숫자·날짜칸만 자동
   입력하고, 선택형(콤보·점검항목)은 '수동'으로 남깁니다(v1 — autofill_kb 와 동일 원칙).

    (화면에 신한 담보폼 열어둔 상태)
    python tools/autofill_shinhan.py 01-2608-3-2615            # 드라이런(계획만)
    python tools/autofill_shinhan.py 01-2608-3-2615 --live     # 실제 입력(연습건에서만!)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bankon.config import load_config          # noqa: E402
from bankon.gam_bridge import process_gam       # noqa: E402
from bankon.mapping import shinhan              # noqa: E402
from bankon.ui import driver, form              # noqa: E402
import verify_form as vf                         # noqa: E402
import verify_fill as VS                         # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

FORM_CLASS = "TBNKSHG24DAMB"
ORDER = {"거부": 0, "덮어씀": 1, "선택(덮어씀)": 1, "미발견": 2, "채움": 3, "선택": 3, "수동(선택형)": 4, "일치": 5, "빈값": 6}


def _jibun_key(values: dict) -> tuple[str, str]:
    return (VS.digs0(VS.norm(values.get("본번지") or "")), VS.digs0(VS.norm(values.get("부번지") or "")))


def _match_object(built, screen: dict, used: set[int]) -> int | None:
    """화면 행(본번지·부번지·담보세부종류)에 맞는 물건 인덱스. 없으면 None."""
    key = (VS.digs0(VS.norm(screen.get("본번지", ""))), VS.digs0(VS.norm(screen.get("부번지", ""))))
    if not key[0]:
        return None
    hits = [i for i, v in enumerate(built) if i not in used and _jibun_key(v) == key]
    kind = VS.norm(screen.get("담보세부종류", ""))
    if len(hits) > 1 and kind:
        narrowed = [i for i in hits if VS.norm(built[i].get("담보세부종류") or "") == kind]
        hits = narrowed or hits
    return hits[0] if hits else None


# 폼 하단(문서 단위) 칸 — 물건마다 반복 입력할 필요 없어 첫 행에서만 채운다.
HEADER_KEYS = ("총감정가액", "기준시점", "현장답사일", "순수수료", "실   비", "감정평가료",
               "대표,지사장", "심사자", "평가사명1@2", "평가사명2@2", "평가사명3@2")


from bankon import paths as _paths               # noqa: E402
COMBO_LISTS = form.load_combo_lists(_paths.RECON_DIR / "combo_shinhan.md")


def run_all_objects(form_ref, built, *, live: bool, overwrite: bool) -> int:
    """물건 전체 처리: ① 기존 행은 본번지·부번지로 물건 매칭 ② 남는 물건은 행 추가(U) 후 순서대로.
    행 추가·입력은 폼 상태만 바꾸고 '저 장'은 누르지 않는다(닫으면 저장 확인창 → 아니오)."""
    from bankon.ui import navigate
    existing = navigate.count_object_rows(form_ref)
    print(f"물건: 감정서 {len(built)}개 / 화면 {existing}행")
    assign: dict[int, int] = {}      # row index -> object index
    used: set[int] = set()
    for r in range(existing):
        navigate.select_object_row(form_ref, r)
        screen = vf.screen_values(form_ref)
        hit = _match_object(built, screen, used)
        if hit is None:
            print(f"  행 {r + 1}: 본번지 {screen.get('본번지', '')}-{screen.get('부번지', '')} → 매칭 물건 없음(건너뜀)")
            continue
        assign[r] = hit
        used.add(hit)
        print(f"  행 {r + 1}: 본번지 {screen.get('본번지', '')}-{screen.get('부번지', '')} → 물건 {hit + 1}")
    leftover = [i for i in range(len(built)) if i not in used]
    if leftover:
        # 행 추가는 드라이런에서도 수행(저장 안 하므로 닫으면 사라짐) — 행 추가 동작 검증 목적
        if True:
            # 복사 추가(X) — 빈 행(U)은 은행이 1행에 선입력한 우편번호가 안 넘어와 2행부터 비었다(2819, 2026-09-14).
            # 담당자도 '현재위치 복사(W)' 로 늘린다. 새 폼(지표 칸 비어 있음 가드)이라 복사되는 건 은행 선입력값뿐이고, 매핑 칸은 뒤에서 덮는다.
            total = navigate.ensure_object_rows(form_ref, existing + len(leftover), mode="copy_append")
            print(f"  행 추가: {existing} → {total} (물건 {[i + 1 for i in leftover]} 배정)")
        for k, obj in enumerate(leftover):
            assign[existing + k] = obj
    totals = {"채움": 0, "일치": 0, "수동": 0, "미발견": 0, "거부": 0, "완료": 0}
    first = True
    for r in sorted(assign):
        obj = assign[r]
        navigate.select_object_row(form_ref, r)
        values = built[obj] if first else {k: v for k, v in built[obj].items() if k not in HEADER_KEYS}
        first = False
        print(chr(10) + f"----- 행 {r + 1} ← 물건 {obj + 1}/{len(built)} "
              f"({values.get('담보세부종류')} {values.get('본번지')}-{values.get('부번지')}) -----")
        results = form.fill(form_ref, values, live=live, overwrite=overwrite, combo_lists=COMBO_LISTS,
                            force_labels=shinhan.ALWAYS_OVERWRITE)
        for x in sorted(results, key=lambda x: (ORDER.get(x.action.split("(")[0] if x.action.startswith("거부") else x.action, 9), x.label)):
            if x.action == "빈값":
                continue
            mark = "✍" + ("완료" if x.wrote else "") if x.action in ("채움", "덮어씀", "선택", "선택(덮어씀)") else x.action
            print(f"  [{mark:9}] {x.label[:16]:18} 넣을값={x.ours[:24]:26} 현재={x.current[:20]}")
        totals["채움"] += sum(1 for x in results if x.action in ("채움", "덮어씀", "선택", "선택(덮어씀)"))
        totals["일치"] += sum(1 for x in results if x.action == "일치")
        totals["수동"] += sum(1 for x in results if x.action == "수동(선택형)")
        totals["미발견"] += sum(1 for x in results if x.action == "미발견")
        totals["거부"] += sum(1 for x in results if x.action.startswith("거부"))
        totals["완료"] += sum(1 for x in results if x.wrote)
    mode = "LIVE 입력완료" if live else "드라이런 채울계획"
    print(chr(10) + f"[전체] {mode} {totals['완료'] if live else totals['채움']} · 일치 {totals['일치']} · "
          f"수동 {totals['수동']} · 칸못찾음 {totals['미발견']} · 거부 {totals['거부']}")
    return 1 if totals["거부"] else 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="autofill_shinhan")
    p.add_argument("doc_id")
    p.add_argument("--live", action="store_true", help="실제 입력(기본은 드라이런)")
    p.add_argument("--overwrite", action="store_true",
                   help="사람이 넣은 값도 덮어씀(기본은 빈칸만 채움)")
    p.add_argument("--seq", type=int, default=None, help="물건 일련번호(기본=화면 물건순번)")
    p.add_argument("--force", action="store_true",
                   help="화면 본번지 ≠ 문서 본번지여도 진행(기본은 중단)")
    p.add_argument("--all-objects", action="store_true",
                   help="물건 전체: 화면 행이 모자라면 추가(U)하고 행마다 본번지·부번지로 매칭해 입력")
    p.add_argument("--env", default=None)
    args = p.parse_args(argv)
    cfg = load_config(args.env)

    forms = [f for f in driver.find_windows(driver.FORM_CLASS_PREFIX)
             if f.class_name == FORM_CLASS]
    if not forms:
        print("신한 담보 화면(TBNKSHG24DAMB)이 안 열려 있습니다.", file=sys.stderr)
        return 1
    form_ref = forms[0]

    gam = process_gam(cfg.gamexport_exe, str(VS.fetch_gam_local(cfg, args.doc_id)),
                      str(Path("output") / args.doc_id))
    ctx = vf.build_context(cfg, args.doc_id, gam.tables, vf.sections_from_gam(gam))
    combos = vf.load_combos(
        _paths.RECON_DIR / "combo_shinhan.md")
    built = shinhan.build(ctx, combos)
    screen = vf.screen_values(form_ref)

    if args.all_objects:
        return run_all_objects(form_ref, built, live=args.live, overwrite=args.overwrite)

    screen_bun = VS.digs0(VS.norm(screen.get("본번지", "")))
    screen_bu = VS.digs0(VS.norm(screen.get("부번지", "")))
    if args.seq is not None:
        idx = min(max(args.seq - 1, 0), len(built) - 1)
        how = f"--seq {args.seq}"
    else:
        # 물건 매칭은 순번이 아니라 본번지·부번지(사용자 확정 2026-08-25). 화면 순번은 폴백.
        hits = [i for i, v in enumerate(built)
                if VS.digs0(VS.norm(v.get("본번지") or "")) == screen_bun
                and VS.digs0(VS.norm(v.get("부번지") or "")) == screen_bu]
        screen_kind = VS.norm(screen.get("담보세부종류", ""))
        if len(hits) > 1 and screen_kind:
            # 같은 지번에 토지·건물·기계기구가 겹치면 화면 담보세부종류로 가른다.
            narrowed = [i for i in hits if VS.norm(built[i].get("담보세부종류") or "") == screen_kind]
            if narrowed:
                hits = narrowed
        if len(hits) == 1:
            idx, how = hits[0], f"본번지·부번지 {screen_bun}-{screen_bu} 일치"
        elif len(hits) > 1:
            kinds = "/".join(str(built[i].get("담보세부종류") or "?") for i in hits)
            idx, how = hits[0], (f"본번지·부번지 {screen_bun}-{screen_bu} 후보 {len(hits)}건({kinds}) "
                                 f"중 첫째 — 화면 담보세부종류 비어 있어 확인 필요")
        else:
            scr = VS.norm(screen.get("물건순번", ""))
            seq = int(scr) if scr.isdigit() else 1
            idx, how = min(max(seq - 1, 0), len(built) - 1), f"본번지 매칭 실패 → 순번 {seq} 폴백"
    values = built[idx]
    print(f"물건 선택: {idx + 1}/{len(built)} ({how})")

    # 다른 문서/물건이 열려 있는데 입력하는 사고 방지 — 본번지 대조(fail-closed)
    mine_bun = VS.digs0(VS.norm(values.get("본번지") or ""))
    if screen_bun and mine_bun and screen_bun != mine_bun:
        print(f"⚠️  화면 본번지({screen_bun}) ≠ 문서 본번지({mine_bun}) — 다른 문서/물건일 수 있음")
        if not args.force:
            print("중단합니다. 확인 후 진행하려면 --force.", file=sys.stderr)
            return 1

    mode = "🔴 실제입력(LIVE)" if args.live else "🟢 드라이런(계획만, 화면 안 건드림)"
    print(f"===== {args.doc_id} (물건 {idx + 1}/{len(built)}) 자동입력 — {mode} =====")
    results = form.fill(form_ref, values, live=args.live, overwrite=args.overwrite, combo_lists=COMBO_LISTS,
                        force_labels=shinhan.ALWAYS_OVERWRITE)
    for r in sorted(results, key=lambda x: (ORDER.get(x.action.split("(")[0] if x.action.startswith("거부") else x.action, 9), x.label)):
        if r.action == "빈값":
            continue
        mark = "✍" + ("완료" if r.wrote else "") if r.action in ("채움", "덮어씀", "선택", "선택(덮어씀)") else r.action
        print(f"  [{mark:9}] {r.label[:16]:18} 넣을값={r.ours[:24]:26} 현재={r.current[:20]}")

    done = sum(1 for r in results if r.wrote)
    plan = sum(1 for r in results if r.action in ("채움", "덮어씀", "선택", "선택(덮어씀)"))
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
