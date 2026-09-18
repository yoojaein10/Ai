"""신한 현장조사서 자동입력 — APW_Bill 실비 → 화면. 기본 드라이런, --live 로 입력(저장은 안 누름).

    (현장조사서 폼 열어둔 상태)
    python tools/autofill_survey.py 01-2608-3-2552          # 드라이런
    python tools/autofill_survey.py 01-2608-3-2552 --live   # 실제 입력(저장 없음)
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bankon.config import load_config          # noqa: E402
from bankon.db import connect                  # noqa: E402
from bankon.gam_bridge import process_gam       # noqa: E402
from bankon.mapping import survey, survey_ibk, survey_kb    # noqa: E402
from bankon.ui import driver, form, navigate    # noqa: E402
import verify_form as vf                         # noqa: E402
import verify_fill as VS                         # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

ORDER = {"거부": 0, "덮어씀": 1, "선택(덮어씀)": 1, "미발견": 2, "채움": 3, "선택": 3,
         "수동(선택형)": 4, "일치": 5, "빈값": 6}
WRITE_ACTIONS = ("채움", "덮어씀", "선택", "선택(덮어씀)")


def _auto_calc_buttons(form_ref) -> list:
    """기업 현장조사서의 '자동계산' TcxButton 전부(화면 순서: 여 비 → 물건조사비 → 공부발급비 → 기타실비)."""
    found = []
    for c in driver.descendants(form_ref.handle):
        try:
            if c.element_info.class_name == "TcxButton" and (c.window_text() or "").replace(" ", "") == "자동계산":
                found.append(c)
        except Exception:  # noqa: BLE001
            continue

    def pos(c):
        r = c.rectangle()
        return (r.top, r.left)
    return sorted(found, key=pos)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="autofill_survey")
    p.add_argument("doc_id")
    p.add_argument("--live", action="store_true", help="실제 입력(기본은 드라이런)")
    p.add_argument("--overwrite", action="store_true", help="사람이 넣은 값도 덮어씀")
    p.add_argument("--env", default=None)
    args = p.parse_args(argv)
    cfg = load_config(args.env)

    forms = [w for w in driver.find_windows(driver.FORM_CLASS_PREFIX)
             if w.class_name.endswith(navigate.SURVEY_CLASS_SUFFIX)]
    if not forms:
        print("현장조사서 화면(TBNK*Hyun)이 안 열려 있습니다.", file=sys.stderr)
        return 1
    form_ref = forms[0]

    with connect(cfg.source_sql, readonly=True) as conn:
        costs = survey.fetch_costs(conn.cursor(), args.doc_id)
    gam = process_gam(cfg.gamexport_exe, str(VS.fetch_gam_local(cfg, args.doc_id)),
                      str(Path("output") / args.doc_id))
    ctx = vf.build_context(cfg, args.doc_id, gam.tables, vf.sections_from_gam(gam))
    is_kb = form_ref.class_name.startswith("TBNKKBB")
    is_ibk = form_ref.class_name.startswith("TBNKKIB")     # 기업 TBNKKIB24Hyun — 실비 세분 항목(survey_ibk)
    if is_kb:
        form.use_layout(survey_kb.POSITIONAL)
        values = survey_kb.build(costs, ctx)
    elif is_ibk:
        values = survey_ibk.build(costs, ctx)
    else:
        values = survey.build(costs, ctx.survey_date)

    mode = "🔴 실제입력(LIVE)" if args.live else "🟢 드라이런"
    bank = "국민" if is_kb else "기업" if is_ibk else "신한"
    print(f"===== {args.doc_id} 현장조사서({bank}) — {mode} =====")
    auto = {}
    if is_ibk and args.live:
        # 소계 4칸(여 비·물건조사비·공부발급비·기타실비)은 읽기전용이고 칸 옆 '자동계산' 버튼 4개가 채운다(2706 LIVE 실측 2026-09-01:
        # 버튼을 안 누르면 저장 뒤에도 빈칸이고 작성 폼 헤더 '실 비'가 0 으로 바뀜). 값 입력 뒤 버튼을 모두 누르고 기대값과 대조 —
        # 하나라도 다르면 '거부'(금액이라 fail-closed, 러너가 저장하지 않는다).
        auto = {k: values.pop(k) for k in list(values) if k in survey_ibk.AUTO_FIELDS}
    results = form.fill(form_ref, values, live=args.live, overwrite=args.overwrite)
    if auto:
        buttons = _auto_calc_buttons(form_ref)
        print(f"  자동계산 버튼 {len(buttons)}개 클릭")
        for b in buttons:
            driver.click(b)
            time.sleep(0.4)
        time.sleep(0.6)
        for r in form.fill(form_ref, auto, live=False):
            # 기대값이 비어 있으면(항목 없음 → 소계 0) 화면도 빈칸/0 이어야 한다. '빈값' 은 fill 이 우리 값이 빈칸이라 비교를 건너뛴 표시.
            ok = r.action == "일치" or (r.action == "빈값" and form.is_blank(r.current))
            results.append(form.FillResult(r.label, "일치" if ok else f"거부(자동계산 결과 다름: {r.action})", r.ours, r.current))
    for r in sorted(results, key=lambda x: (ORDER.get(x.action.split("(")[0], 9), x.label)):
        if r.action == "빈값":
            continue
        mark = "✍" + ("완료" if r.wrote else "") if r.action in WRITE_ACTIONS else r.action
        print(f"  [{mark:9}] {r.label[:16]:18} 넣을값={r.ours[:16]:18} 현재={r.current[:16]}")
    rejected = sum(1 for r in results if r.action.startswith("거부"))
    done = sum(1 for r in results if r.wrote)
    same = sum(1 for r in results if r.action == "일치")
    plan = sum(1 for r in results if r.action in WRITE_ACTIONS)
    missing = sum(1 for r in results if r.action == "미발견")
    head = f"입력완료 {done}" if args.live else f"채울계획 {plan}"
    print(f"\n{head} · 일치 {same} · 거부 {rejected} · 칸못찾음 {missing}")
    return 1 if rejected else 0


if __name__ == "__main__":
    raise SystemExit(main())
