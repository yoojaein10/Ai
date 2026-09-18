"""기업 담보 폼 자동입력 — 2단 구조(헤더 + 물건 → 오른쪽 탭 토지/건물/기계기구). 세부내역 그리드 없음.

기본은 **드라이런**(계획만). 실제 입력은 `--live` 로만. 저장은 여기서 하지 않는다.
드라이런도 물건 행 추가·물건종류 콤보(탭 전환)는 실행한다(폼 상태만 바뀌고 닫으면 사라짐 — 신한·국민과 같은 원칙).
    (화면에 기업 담보폼 열어둔 상태)
    python tools/autofill_ibk.py 01-2608-3-2704            # 드라이런
    python tools/autofill_ibk.py 01-2608-3-2704 --live     # 실제 입력(연습건에서만!)
    --no-touch   드라이런에서 행 추가·콤보도 안 건드림(읽기만)
    --dump       화면 값 읽기만(물건 행 전부) — 실물 대조용
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bankon import paths as _paths               # noqa: E402
from bankon.config import load_config          # noqa: E402
from bankon.db import connect                  # noqa: E402
from bankon.gam_bridge import process_gam       # noqa: E402
from bankon.mapping import ibk, survey          # noqa: E402
from bankon.ui import driver, form, navigate    # noqa: E402
import verify_form as vf                         # noqa: E402
import verify_fill_kb as VK                      # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

FORM_CLASS = ibk.FORM_CLASS
ORDER = {"거부": 0, "덮어씀": 1, "선택(덮어씀)": 1, "미발견": 2, "채움": 3, "선택": 3, "수동(선택형)": 4, "일치": 5, "빈값": 6}
_COMBO_PATH = _paths.RECON_DIR / "combo_ibk.md"
COMBO_LISTS = form.load_combo_lists(_COMBO_PATH) if _COMBO_PATH.exists() else {}   # 콤보 목록 미수집(2026-08-31) — 있으면 씀

DUMP_HEADER = ["평가사명", "헤더:물건종류", "기준시점", "감정수수료", "순수수료", "실 비", "특별용역비", "부가세"]
DUMP_OBJECT = ["물건:" + k for k in ("일련번호", "법정동코드", "소재지", "번지구분", "본번지", "부번지", "물건종류", "총감정평가액",
                                    "토지평가금액", "건물평가금액", "기계기구평가금액", "기타평가금액", "부동산구분", "등기소기준 고유번호")]
DUMP_TAB = ["탭:" + k for k in ("공부지목", "용도지역", "공부면적", "건물구조", "준공일자", "내용년수", "잔존년수", "공부면적(전용면적)",
                              "사정면적", "평가단가", "감정평가액", "비 고")]


def _report(results, totals):
    for r in sorted(results, key=lambda x: (ORDER.get(x.action.split("(")[0] if x.action.startswith("거부") else x.action, 9), x.label)):
        if r.action == "빈값":
            continue
        mark = "✍" + ("완료" if r.wrote else "") if r.action in ("채움", "덮어씀", "선택", "선택(덮어씀)") else r.action
        print(f"  [{mark:9}] {r.label[:18]:20} 넣을값={r.ours[:24]:26} 현재={r.current[:20]}")
    totals["채움"] += sum(1 for x in results if x.action in ("채움", "덮어씀", "선택", "선택(덮어씀)"))
    totals["일치"] += sum(1 for x in results if x.action == "일치")
    totals["수동"] += sum(1 for x in results if x.action == "수동(선택형)")
    totals["미발견"] += sum(1 for x in results if x.action == "미발견")
    totals["거부"] += sum(1 for x in results if x.action.startswith("거부"))
    totals["완료"] += sum(1 for x in results if x.wrote)


def _read_labels(form_ref, labels) -> None:
    for label in labels:
        action, current, control = form.plan_field(form_ref, label, "?")
        if action == "미발견":
            continue
        print(f"    {label:22} = {current!r}")


def dump_screen(form_ref) -> int:
    """실물 화면 읽기(변경 없음): 헤더 → 물건 행마다 패널 + 보이는 탭."""
    print("----- 헤더 -----")
    _read_labels(form_ref, DUMP_HEADER)
    n_obj = navigate.ibk_count_object_rows(form_ref)
    print(f"----- 물건 {n_obj}개 -----")
    for oi in range(n_obj):
        navigate.ibk_select_object_row(form_ref, oi)
        print(f"=== 물건 {oi + 1} [탭 {navigate.ibk_tab_kind(form_ref) or '?'}] ===")
        _read_labels(form_ref, DUMP_OBJECT)
        _read_labels(form_ref, DUMP_TAB)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="autofill_ibk")
    p.add_argument("doc_id")
    p.add_argument("--live", action="store_true")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--no-touch", action="store_true", help="드라이런에서 행 추가·콤보도 안 건드림")
    p.add_argument("--dump", action="store_true", help="화면 값 읽기만(물건 행 전부) — 실물 대조용")
    p.add_argument("--env", default=None)
    args = p.parse_args(argv)
    cfg = load_config(args.env)
    form.use_layout(ibk.POSITIONAL, ibk.REGIONS)

    forms = [f for f in driver.find_windows(driver.FORM_CLASS_PREFIX) if f.class_name == FORM_CLASS]
    if not forms:
        print(f"기업 담보 화면({FORM_CLASS})이 안 열려 있습니다.", file=sys.stderr)
        return 1
    form_ref = forms[0]
    touch = args.live or not args.no_touch
    if args.dump:
        return dump_screen(form_ref)

    gam = process_gam(cfg.gamexport_exe, str(VK.fetch_gam_local(cfg, args.doc_id)),
                      str(Path("output") / args.doc_id))
    ctx = vf.build_context(cfg, args.doc_id, gam.tables, vf.sections_from_gam(gam))
    with connect(cfg.source_sql, readonly=True) as conn:
        costs = survey.fetch_costs(conn.cursor(), args.doc_id)
    header, objects = ibk.build_ibk(ctx, costs)

    mode = "🔴 실제입력(LIVE)" if args.live else "🟢 드라이런(계획만)"
    print(f"===== {args.doc_id} 기업 자동입력 — {mode} · 물건 {len(objects)}개 =====")
    totals = {"채움": 0, "일치": 0, "수동": 0, "미발견": 0, "거부": 0, "완료": 0}

    print("----- 헤더 -----")
    results = form.fill(form_ref, header, live=args.live, overwrite=args.overwrite,
                        combo_lists=COMBO_LISTS, force_labels=ibk.ALWAYS_OVERWRITE)
    _report(results, totals)

    obj_count = navigate.ibk_count_object_rows(form_ref)
    print(f"----- 물건: 문서 {len(objects)}개 / 화면 {obj_count}개 -----")
    for oi, obj in enumerate(objects):
        kind = obj.get("_kind")
        panel = {k: v for k, v in obj.items() if k.startswith("물건:")}
        tab = {k: v for k, v in obj.items() if k.startswith("탭:")}
        if oi >= obj_count:
            if not touch:
                print(f"  물건 {oi + 1}: 화면에 없음(추가 필요, --no-touch) → 건너뜀")
                continue
            obj_count = navigate.ibk_add_object_row(form_ref)
        navigate.ibk_select_object_row(form_ref, oi)
        print(f"=== 물건 {oi + 1} [{kind}/{panel.get('물건:물건종류') or '?'}] "
              f"{panel.get('물건:본번지') or ''}-{panel.get('물건:부번지') or ''} ===")
        # 물건종류 콤보를 먼저 골라야 오른쪽 탭이 그 종류로 바뀐다(토지/건물 탭이 같은 자리에 겹침).
        first = {k: panel.pop(k) for k in ("물건:물건종류",) if k in panel}
        results = form.fill(form_ref, first, live=touch, overwrite=args.overwrite,
                            combo_lists=COMBO_LISTS, force_labels=ibk.ALWAYS_OVERWRITE)
        _report(results, totals)
        results = form.fill(form_ref, panel, live=args.live, overwrite=args.overwrite,
                            combo_lists=COMBO_LISTS, force_labels=ibk.ALWAYS_OVERWRITE)
        _report(results, totals)
        now = navigate.ibk_tab_kind(form_ref)
        if tab and now != kind:
            print(f"  탭: 화면 종류={now} ≠ 문서 {kind} → 탭 값 {len(tab)}칸 건너뜀(물건종류 콤보 확인)")
            totals["미발견"] += sum(1 for v in tab.values() if not form.is_blank(v))
            continue
        if tab:
            print(f"  --- 탭 [{now}] ---")
            results = form.fill(form_ref, tab, live=args.live, overwrite=args.overwrite,
                                combo_lists=COMBO_LISTS, force_labels=ibk.ALWAYS_OVERWRITE)
            _report(results, totals)

    label = "입력완료" if args.live else "채울계획"
    print(f"\n[전체] {label} {totals['완료'] if args.live else totals['채움']} · 일치 {totals['일치']} · "
          f"수동 {totals['수동']} · 칸못찾음 {totals['미발견']} · 거부 {totals['거부']}")
    return 1 if totals["거부"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
