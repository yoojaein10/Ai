"""콤보 **자동선택이 실제로 되는지** 시험한다 — 값은 바뀌지 않는다.

콤보에 지금 들어 있는 값을 **목록에서 다시 찾아 고른다**(`select_item(force=True)`).
목표값 == 현재값이라 확정해도 화면 값이 그대로다. 그러면서도 실제 경로는 전부 돈다:

    F4 로 드롭다운 열기 → 맨 위로 → 하나씩 내리며 표시값 비교 → 맞으면 Enter → 되읽기 검증

즉 **위험 없이 Enter 확정까지 검증**한다. 끝나면 값이 처음과 같은지 한 번 더 확인한다.

    (관리자) python tools/check_combo_select.py --bank nh
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pywinauto.keyboard import send_keys            # noqa: E402

from bankon.config import load_config               # noqa: E402
from bankon.ui import combos as combo_lists         # noqa: E402
from bankon.ui import driver, navigate              # noqa: E402
from inspect_bankon import _connect, walk           # noqa: E402
from map_fields import collect                      # noqa: E402
from verify_grid_loop import BANKS                  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parent.parent


def _control_at(window, box):
    for child in window.descendants():
        try:
            rect = child.rectangle()
        except Exception:
            continue
        if (rect.left, rect.top) == (box.left, box.top):
            return child
    return None


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="check_combo_select")
    p.add_argument("--bank", choices=tuple(BANKS), required=True)
    p.add_argument("--doc", default=None, help="이 문서번호로 폼을 연다(그리드 훑기 대신)")
    p.add_argument("--log", default=None, help="출력을 이 파일에도 기록(관리자 실행용)")
    p.add_argument("--max", type=int, default=12, help="폼을 찾으려 훑을 그리드 행 수")
    p.add_argument("--skip", type=int, default=0,
                   help="조건에 맞는 폼을 이만큼 건너뛴다(다른 변형을 보고 싶을 때)")
    p.add_argument("--need", default=None,
                   help="이 라벨에 값이 있는 폼만 고른다(예: 심사자)")
    p.add_argument("--env", default=None)
    args = p.parse_args(argv)
    if args.log:
        sys.stdout = open(args.log, "w", encoding="utf-8", buffering=1)
        sys.stderr = sys.stdout
    load_config(args.env or str(ROOT / ".env"))

    driver.require_desktop()

    mains = [m for m in driver.find_windows(driver.MAIN_CLASS)
             if driver.by_class(m.handle, "TcxGridSite")]
    if not mains:
        print("그리드 있는 BANK24 메인창이 없습니다."); return 1
    session = navigate.Session(mains[0])
    navigate.close_forms(session)

    target = BANKS[args.bank]["cls"]
    form = None
    if args.doc:
        print(f"{args.doc} 여는 중 …")
        try:
            form = navigate.open_document(session, args.doc)
        except Exception as error:
            print(f"문서를 못 열었습니다: {type(error).__name__}: {error}"); return 1
        if form.class_name != target:
            print(f"열린 폼이 {form.class_name} 입니다 — {target} 이 아닙니다.")
            navigate.close_forms(session); return 1
        args.max = 0                       # 그리드 훑기는 건너뛴다

    grid = navigate._grid(session)
    if args.max:
        grid.set_focus(); time.sleep(0.4)
        send_keys("^{HOME}"); time.sleep(0.4)

    for index in range(args.max):
        before = navigate._menu_handles()
        send_keys("+{F10}")
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and not (navigate._menu_handles() - before):
            time.sleep(0.3)
        if not (navigate._menu_handles() - before):
            break
        send_keys("a")
        try:
            candidate = driver.wait_for_window(driver.FORM_CLASS_PREFIX,
                                               pid=session.pid, timeout=15)
        except Exception:
            navigate.close_context_menu(); candidate = None
        if candidate is not None and candidate.class_name == target:
            fits = True
            if args.need:
                value = driver.find_by_label(candidate.handle, args.need)
                fits = value is not None and bool(driver.read(driver.editable(value)))
            if fits and args.skip <= 0:
                form = candidate
                print(f"[{index}] {target} — 이 폼으로 시험")
                break
            args.skip -= 1 if fits else 0
            print(f"[{index}] {target} 건너뜀"
                  f"{'' if fits else f' ({args.need} 비어 있음)'}")
            navigate.close_forms(session)
            grid = navigate._grid(session)
            grid.set_focus(); time.sleep(0.3)
            send_keys("{DOWN}"); time.sleep(0.3)
            continue
        if candidate is not None:
            print(f"[{index}] {candidate.class_name} 건너뜀")
            navigate.close_forms(session)
        grid = navigate._grid(session)
        grid.set_focus(); time.sleep(0.3)
        send_keys("{DOWN}"); time.sleep(0.3)

    if form is None:
        print("해당 은행 폼을 못 찾았습니다."); return 1

    window = _connect(driver.BACKEND, title_re=None, pid=None, handle=form.handle)
    combos = [f for f in collect(walk(window))
              if "ComboBox" in f["class_name"] and str(f["value"]).strip()]
    print(f"\n값이 있는 콤보 {len(combos)}개 — 같은 값을 목록에서 다시 골라 본다"
          f"(값은 안 바뀐다)\n")

    ok = fail = 0
    for field in combos:
        control = _control_at(window, field["box"])
        if control is None:
            print(f"  [skip] {field['label']} — 컨트롤 못 찾음"); continue
        current = driver.read(driver.editable(control))
        started = time.monotonic()
        items = combo_lists.items_for(form.class_name, field["label"])
        try:
            picked = driver.select_item(control, current, force=True, items=items)
        except driver.ValueRejected as error:
            print(f"  ❌ {field['label'][:16]:18} {str(error)[:60]}"); fail += 1; continue
        except Exception as error:
            print(f"  ❌ {field['label'][:16]:18} {type(error).__name__}: {str(error)[:50]}")
            fail += 1; continue
        after = driver.read(driver.editable(control))
        same = driver.combo_text(after) == driver.combo_text(current)
        mark = "✅" if (picked and same) else "❌"
        ok, fail = (ok + 1, fail) if mark == "✅" else (ok, fail + 1)
        print(f"  {mark} {field['label'][:16]:18} {current[:22]:24} "
              f"{'고름' if picked else '못찾음'} · {time.monotonic() - started:5.1f}초"
              f" · 목록 {len(items) or '없음'}"
              f"{'' if same else '  ⚠값이 바뀜: ' + after}")

    print(f"\n[결과] 성공 {ok} / 실패 {fail}")
    print("폼은 열어 둡니다 — 값이 그대로인지 확인하고 '닫 기'(저장 안 함) 하세요.")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
