"""국민 담보 폼 자동입력 — 2단 구조(헤더+물건 → 세부내역 행별 토지/건물/기계기구).

기본은 **드라이런**(계획만). 실제 입력은 `--live` 로만. 저장은 여기서 하지 않는다.
드라이런도 세부내역 행 추가·종류 라디오는 실행한다(폼 상태만 바뀌고 닫으면 사라짐 — 신한과 같은 원칙).
    (화면에 국민 담보폼 열어둔 상태)
    python tools/autofill_kb.py 01-2608-3-2647            # 드라이런
    python tools/autofill_kb.py 01-2608-3-2647 --live     # 실제 입력(연습건에서만!)
    --no-touch   드라이런에서 행 추가·라디오도 안 건드림(읽기만)
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
from bankon.ui import driver, form, navigate    # noqa: E402
import verify_form as vf                         # noqa: E402
import verify_fill_kb as VK                      # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

FORM_CLASS = "TBNKKBB24DAMB"
ORDER = {"거부": 0, "덮어씀": 1, "선택(덮어씀)": 1, "미발견": 2, "채움": 3, "선택": 3, "수동(선택형)": 4, "일치": 5, "빈값": 6}
from bankon import paths as _paths               # noqa: E402
COMBO_LISTS = form.load_combo_lists(_paths.RECON_DIR / "combo_kb.md")


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


def _fill_checklist(form_ref, ctx, totals, *, live: bool) -> None:
    """오른쪽 점검항목 20콤보 — .gam KB_Summary_Chk 값이 있을 때만, 기본값과 다른 것만 고른다(항상 덮어씀)."""
    if not ctx.kb_checks:
        print("  [점검항목  ] KB_Summary_Chk 없음 → 안 건드림")
        return
    answers = kookmin.checklist_answers(ctx)
    combos = [c for c in driver.by_class(form_ref.handle, kookmin.CHECKLIST_CONTROL_CLASS)
              if driver._visible(c) and driver._in_region(form_ref.handle, c, kookmin.CHECKLIST_REGION)]
    currents = [driver.read(driver.editable(c)) for c in combos]
    plan = kookmin.plan_checklist(currents, answers)
    if not plan:
        print(f"  [점검항목  ] 콤보 {len(combos)}개 ≠ {len(answers)} → 안 건드림")
        return
    results = []
    for i, action, ans, cur in plan:
        wrote = False
        if live and action != "일치":
            try:
                form.select_combo(combos[i], ans, ["예", "아니오"])
                wrote = True
            except driver.ValueRejected as exc:
                action = f"거부({str(exc)[:70]})"
        results.append(form.FillResult(f"점검항목{i + 1:02}", action, ans, cur, wrote))
    _report([r for r in results if r.action != "일치"], totals)
    totals["일치"] += sum(1 for r in results if r.action == "일치")
    print(f"  [점검항목  ] {len(results)}칸 중 기본값과 다른 것 {sum(1 for r in results if r.action != '일치')}칸")


DUMP_HEADER = ["대표,지사장", "평가사명1", "평가사명2", "심사자", "감정평가(순)수수료", "(순)수수료-부가가치세", "감정평가(순)수수료 총액",
               "실비-총액", "수수료할증적용", "사업등록번호", "現 기준시점", "감정평가액 결정의견"]
DUMP_OBJECT = ["물건:" + k for k in ("일련번호", "물건종류", "법정동코드", "번지구분", "본번지", "부번지", "소재지", "건물명", "동",
                                    "건물 층수", "호", "표준지소재지", "표준지공시지가", "공시기준일", "총층수/층수", "총층수/층수@2",
                                    "총세대수", "비   고")]
DUMP_DETAIL = ["세부:" + k for k in ("일련번호", "법정동코드", "소재지", "번지구분", "본번지", "부번지", "공부지목", "용도지역", "공부면적", "사정면적",
                                    "평가단가", "감정평가액", "등기번호", "건물구조", "준공일자", "내용년수", "잔존년수", "공부면적(전용면적)",
                                    "기계기구명")]


def _read_labels(form_ref, labels) -> None:
    for label in labels:
        action, current, control = form.plan_field(form_ref, label, "?")
        if action == "미발견":
            continue
        print(f"    {label:22} = {current!r}")


def dump_screen(form_ref) -> int:
    """실물 화면 읽기(변경 없음): 헤더 → 물건 행마다 필드 + 세부 행마다 종류·필드."""
    print("----- 헤더 -----")
    _read_labels(form_ref, DUMP_HEADER)
    n_obj = navigate.kb_count_object_rows(form_ref)
    print(f"----- 물건 {n_obj}개 -----")
    for oi in range(n_obj):
        navigate.kb_select_object_row(form_ref, oi)
        print(f"=== 물건 {oi + 1} ===")
        _read_labels(form_ref, DUMP_OBJECT)
        n_det = navigate.count_detail_rows(form_ref)
        print(f"  ----- 세부내역 {n_det}행 -----")
        for i in range(n_det):
            navigate.select_detail_row(form_ref, i)
            print(f"  --- 행 {i + 1} [{navigate.detail_kind(form_ref)}] ---")
            _read_labels(form_ref, DUMP_DETAIL)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="autofill_kb")
    p.add_argument("doc_id")
    p.add_argument("--live", action="store_true")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--no-touch", action="store_true", help="드라이런에서 행 추가·라디오도 안 건드림")
    p.add_argument("--dump", action="store_true", help="화면 값 읽기만(물건·세부 행 전부) — 실물 대조용")
    p.add_argument("--env", default=None)
    args = p.parse_args(argv)
    cfg = load_config(args.env)
    form.use_layout(kookmin.POSITIONAL, kookmin.REGIONS)

    forms = [f for f in driver.find_windows(driver.FORM_CLASS_PREFIX) if f.class_name == FORM_CLASS]
    if not forms:
        print("국민 담보 화면(TBNKKBB24DAMB)이 안 열려 있습니다.", file=sys.stderr)
        return 1
    form_ref = forms[0]
    touch = args.live or not args.no_touch

    gam = process_gam(cfg.gamexport_exe, str(VK.fetch_gam_local(cfg, args.doc_id)),
                      str(Path("output") / args.doc_id))
    ctx = vf.build_context(cfg, args.doc_id, gam.tables, vf.sections_from_gam(gam))
    if args.dump:
        return dump_screen(form_ref)
    header, objects = kookmin.build_kb(ctx)
    n_details = sum(len(o["_details"]) for o in objects)

    mode = "🔴 실제입력(LIVE)" if args.live else "🟢 드라이런(계획만)"
    print(f"===== {args.doc_id} 국민 자동입력 — {mode} · 물건 {len(objects)}개 · 세부내역 {n_details}행 =====")
    totals = {"채움": 0, "일치": 0, "수동": 0, "미발견": 0, "거부": 0, "완료": 0}

    # ── 헤더 ──
    method = header.pop("평가방법", None)
    print("----- 헤더 -----")
    results = form.fill(form_ref, header, live=args.live, overwrite=args.overwrite,
                        combo_lists=COMBO_LISTS, force_labels=kookmin.ALWAYS_OVERWRITE)
    _report(results, totals)
    # 평가방법 라디오는 **물건 패널**에 있어 물건마다 따로 눌러야 한다 — 종전엔 여기서 한 번만 눌러 2번째 물건부터
    # 아무것도 안 찍혀 있었다(2822 담당자 제보 2026-09-14). 아래 물건 루프에서 `_method` 로 누른다.
    del method
    _fill_checklist(form_ref, ctx, totals, live=args.live)

    # ── 물건(규칙 A: 필지 1개 = 물건 1개) → 각 물건의 세부내역 ──
    obj_count = navigate.kb_count_object_rows(form_ref)
    print(f"----- 물건: 문서 {len(objects)}개 / 화면 {obj_count}개 -----")
    for oi, obj in enumerate(objects):
        details = obj["_details"]
        values = {k: v for k, v in obj.items() if not k.startswith("_")}
        if oi >= obj_count:
            if not touch:
                print(f"  물건 {oi + 1}: 화면에 없음(추가 필요, --no-touch) → 건너뜀")
                continue
            obj_count = navigate.kb_add_object_row(form_ref)
        navigate.kb_select_object_row(form_ref, oi)
        print(f"=== 물건 {oi + 1} [{values.get('물건:물건종류') or '?'}] "
              f"{values.get('물건:본번지') or ''}-{values.get('물건:부번지') or ''} · 세부 {len(details)}행 ===")
        results = form.fill(form_ref, values, live=args.live, overwrite=args.overwrite,
                            combo_lists=COMBO_LISTS, force_labels=kookmin.ALWAYS_OVERWRITE)
        _report(results, totals)
        method = obj.get("_method")
        if method:
            if touch:
                navigate.set_radio(form_ref, method)
                print(f"  [라디오    ] 평가방법             → {method}")
            else:
                print(f"  [수동(선택형)] 평가방법             넣을값={method}")
        if obj.get("_clear"):
            _report(form.clear_fields(form_ref, obj["_clear"], live=args.live), totals)

        existing = navigate.count_detail_rows(form_ref)
        print(f"  ----- 세부내역: 문서 {len(details)}행 / 화면 {existing}행 -----")
        for i, det in enumerate(details):
            kind = det.get("_kind")
            dvals = {k: v for k, v in det.items() if not k.startswith("_")}
            if i >= existing:
                if not touch:
                    print(f"  행 {i + 1}: 화면에 없음(추가 필요, --no-touch) → 건너뜀")
                    continue
                existing = navigate.add_detail_row(form_ref)
            navigate.select_detail_row(form_ref, i)
            now = navigate.detail_kind(form_ref)
            if now != kind:
                if not touch:
                    print(f"  행 {i + 1}: 화면 종류={now} ≠ 문서 {kind} (--no-touch) → 건너뜀")
                    continue
                navigate.set_detail_kind(form_ref, kind)
            print(f"  --- 행 {i + 1} [{kind}] {dvals.get('세부:본번지') or ''}-{dvals.get('세부:부번지') or ''} ---")
            results = form.fill(form_ref, dvals, live=args.live, overwrite=args.overwrite,
                                combo_lists=COMBO_LISTS, force_labels=kookmin.ALWAYS_OVERWRITE)
            _report(results, totals)

    label = "입력완료" if args.live else "채울계획"
    print(f"\n[전체] {label} {totals['완료'] if args.live else totals['채움']} · 일치 {totals['일치']} · "
          f"수동 {totals['수동']} · 칸못찾음 {totals['미발견']} · 거부 {totals['거부']}")
    return 1 if totals["거부"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
