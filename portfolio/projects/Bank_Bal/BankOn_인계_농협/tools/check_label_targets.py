"""매핑이 내는 라벨이 **어느 칸을 짚는지** 실폼에서 확인한다 — 쓰기 전 안전 관문. 읽기 전용.

`driver.find_by_label` 은 같은 글자의 라벨이 여러 개면 **먼저 나온 것**을 쓴다. 그래서
한 폼에 같은 라벨이 두 번 붙어 있으면(실측 기업: `물건종류` 가 텍스트칸과 콤보 둘 다에
붙어 있다) 우리 값이 엉뚱한 칸으로 갈 수 있다.

이 도구는 값을 **읽기만** 한다. 매핑 라벨마다:
  · 그 글자의 라벨 컨트롤이 몇 개인지(2개 이상이면 ⚠ 모호)
  · `find_by_label` 이 실제로 짚는 칸의 클래스·좌표·현재값
  · 콤보면 수집된 목록에 우리 값이 있는지
를 보여 준다.

    (관리자) python tools/check_label_targets.py --bank ibk --doc 01-2608-3-2683
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bankon.config import load_config              # noqa: E402
from bankon.gam_bridge import load_extracted       # noqa: E402
from bankon.mapping import ibk, kookmin, nh        # noqa: E402
from bankon.ui import combos, driver, navigate     # noqa: E402
from bankon.ui import form as form_mod             # noqa: E402
import verify_form as vf                           # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parent.parent
MAPPINGS = {"kb": kookmin, "ibk": ibk, "nh": nh}
FORM_CLASS = {"kb": "TBNKKBB24DAMB", "ibk": "TBNKKIB24DAMB", "nh": "TBNKNHB24DAMB"}


def label_controls(handle: int, text: str) -> list:
    """그 글자를 가진 **라벨 컨트롤**들 — 2개 이상이면 find_by_label 이 모호해진다."""
    target = text.replace(" ", "")
    found = []
    for control in driver.descendants(handle):
        try:
            if control.element_info.class_name not in driver.LABEL_CLASSES:
                continue
            if (control.window_text() or "").replace(" ", "") == target:
                found.append(control)
        except Exception:
            continue
    return found


def describe(control) -> str:
    if control is None:
        return "(못 짚음)"
    try:
        rect = control.rectangle()
        cls = control.element_info.class_name or ""
    except Exception:
        return "(읽기 실패)"
    value = driver.read(driver.editable(control))
    return f"{cls[:26]:28} ({rect.left:5},{rect.top:4}) = {str(value)[:26]!r}"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="check_label_targets")
    p.add_argument("--bank", choices=tuple(MAPPINGS), required=True)
    p.add_argument("--doc", required=True)
    p.add_argument("--log", default=None, help="출력을 이 파일에도 기록(관리자 실행용)")
    p.add_argument("--keep", action="store_true", help="끝나고 폼을 닫지 않는다")
    p.add_argument("--env", default=None)
    args = p.parse_args(argv)
    if args.log:
        sys.stdout = open(args.log, "w", encoding="utf-8", buffering=1)
        sys.stderr = sys.stdout
    cfg = load_config(args.env or str(ROOT / ".env"))

    driver.require_desktop()
    mapping = MAPPINGS[args.bank]

    gam = load_extracted(str(ROOT / "output" / args.doc))
    context = vf.build_context(cfg, args.doc, gam.tables, vf.sections_from_gam(gam))
    values = mapping.build(context)

    mains = [m for m in driver.find_windows(driver.MAIN_CLASS)
             if driver.by_class(m.handle, "TcxGridSite")]
    if not mains:
        print("그리드 있는 BANK24 메인창이 없습니다."); return 1
    session = navigate.Session(mains[0])
    print(f"{args.doc} 여는 중 …")
    try:
        form = navigate.open_document(session, args.doc)
    except Exception as error:
        print(f"문서를 못 열었습니다: {type(error).__name__}: {error}"); return 1
    if form.class_name != FORM_CLASS[args.bank]:
        print(f"열린 폼이 {form.class_name} — {FORM_CLASS[args.bank]} 가 아닙니다.")
        navigate.close_forms(session); return 1

    table = combos.for_form(form.class_name)
    print(f"\n{form.class_name} — 매핑이 내는 라벨 {len(values)}개\n")
    print(f"{'라벨':20} {'라벨수':5} {'짚은 칸'}")
    ambiguous, wrong_kind, missing = [], [], []

    for key, value in values.items():
        name = form_mod.display_label(key)
        positional = form_mod.POSITIONAL.match(str(key)) is not None
        control = form_mod.resolve_control(form, key)
        count = 0 if positional else len(label_controls(form.handle, name))
        mark = " "
        if positional:
            mark = "위"                              # 위치 표기 — 라벨 모호성과 무관
        elif count == 0:
            mark = "✗"; missing.append(name)
        elif count > 1:
            mark = "⚠"; ambiguous.append(f"{name}×{count}")
        note = ""
        if control is not None and value not in (None, ""):
            try:
                cls = control.element_info.class_name or ""
            except Exception:
                cls = ""
            if "ComboBox" in cls:
                items = table.get(name, ())
                if items:
                    hit = any(driver.combo_text(i) == driver.combo_text(str(value))
                              for i in items)
                    note = f"  [콤보 목록 {len(items)}개 — 우리값 {'있음' if hit else '없음'}]"
                    if not hit:
                        wrong_kind.append(f"{name}={value}")
                else:
                    note = "  [콤보 — 수집된 목록 없음]"
        print(f"{mark} {name[:18]:20} {count:5} {describe(control)}{note}")
        if value not in (None, ""):
            print(f"{'':26} 우리값 = {str(value)[:40]!r}")

    print("\n=== 요약 ===")
    print(f"  ⚠ 라벨이 여러 개(짚는 칸이 흔들릴 수 있다): "
          f"{' · '.join(ambiguous) if ambiguous else '없음'}")
    print(f"  ✗ 라벨을 못 찾음: {' · '.join(missing) if missing else '없음'}")
    print(f"  콤보인데 우리값이 목록에 없음: "
          f"{' · '.join(wrong_kind) if wrong_kind else '없음'}")

    if not args.keep:
        navigate.close_forms(session)
        print("\n폼 닫음(저장 안 함).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
