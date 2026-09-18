"""콤보를 **다른 값으로 바꿨다가 되돌린다** — 자동선택이 진짜 쓰는지 확인하는 시험.

`check_combo_select.py` 는 *같은 값*을 다시 골라 경로만 돌린다(값이 안 바뀐다).
이건 한 걸음 더 간다 — 실제로 **다른 항목을 골라 값이 바뀌는 걸 확인**하고, 곧바로
**원래 값으로 되돌린 뒤 되읽어 확인**한다. 실전에서 우리가 쓰는 경로 그대로다.

    원래값 기억 → 목록에서 다른 항목 고름 → 화면값이 그 항목인지 확인
                → 원래값으로 다시 고름 → 화면값이 원래대로인지 확인

안전:
  - **저장하지 않는다.** 폼도 우리가 안 닫는다 — 끝나면 사람이 `닫 기`(저장 안 함) 한다.
    저장 전이므로 DB 는 건드려지지 않는다.
  - 되돌리기에 실패하면 **거기서 즉시 멈추고** 무엇이 어떻게 남았는지 크게 알린다.
  - 원래 값이 비어 있는 콤보는 건너뛴다(되돌릴 기준이 없다).
  - `--labels` 로 시험할 칸을 좁힐 수 있다. 기본은 목록을 아는 콤보만 한 칸씩.

    (관리자) python tools/check_combo_change.py --bank nh --limit 3
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


def _other_item(items, current: str) -> str | None:
    """현재값이 아닌 항목 하나 — 목록 앞쪽에서 고른다(멀리 갈수록 느리다)."""
    now = driver.combo_text(current)
    for item in items:
        if item and driver.combo_text(item) != now:
            return item
    return None


def open_form(session, target: str, *, max_rows: int, need: str | None):
    """그리드를 훑어 그 은행 폼을 연다(`찾 기` 를 안 써 안전하다)."""
    grid = navigate._grid(session)
    grid.set_focus(); time.sleep(0.4)
    send_keys("^{HOME}"); time.sleep(0.4)
    for index in range(max_rows):
        before = navigate._menu_handles()
        send_keys("+{F10}")
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and not (navigate._menu_handles() - before):
            time.sleep(0.3)
        if not (navigate._menu_handles() - before):
            print(f"  [{index}] 메뉴 안 열림 — 종료"); return None
        send_keys("a")
        try:
            form = driver.wait_for_window(driver.FORM_CLASS_PREFIX,
                                          pid=session.pid, timeout=15)
        except Exception:
            navigate.close_context_menu(); form = None
        if form is not None and form.class_name == target:
            fits = True
            if need:
                control = driver.find_by_label(form.handle, need)
                fits = control is not None and bool(driver.read(driver.editable(control)))
            if fits:
                print(f"  [{index}] {target} — 이 폼으로 시험")
                return form
            print(f"  [{index}] {target} 건너뜀({need} 비어 있음)")
        elif form is not None:
            print(f"  [{index}] {form.class_name} 건너뜀")
        if form is not None:
            navigate.close_forms(session)
        grid = navigate._grid(session)
        grid.set_focus(); time.sleep(0.3)
        send_keys("{DOWN}"); time.sleep(0.3)
    return None


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="check_combo_change")
    p.add_argument("--bank", choices=tuple(BANKS), required=True)
    p.add_argument("--doc", default=None, help="이 문서번호로 폼을 연다(그리드 훑기 대신)")
    p.add_argument("--max", type=int, default=12, help="폼을 찾으려 훑을 그리드 행 수")
    p.add_argument("--limit", type=int, default=3, help="시험할 콤보 수")
    p.add_argument("--labels", default=None, help="이 라벨들만(콤마 구분)")
    p.add_argument("--need", default=None, help="이 라벨에 값이 있는 폼만 고른다")
    p.add_argument("--log", default=None, help="출력을 이 파일에도 기록(관리자 실행용)")
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
    if args.doc:
        print(f"{args.doc} 여는 중 …")
        try:
            form = navigate.open_document(session, args.doc)
        except Exception as error:
            print(f"문서를 못 열었습니다: {type(error).__name__}: {error}"); return 1
        if form.class_name != target:
            print(f"열린 폼이 {form.class_name} 입니다 — {target} 이 아닙니다.")
            navigate.close_forms(session); return 1
    else:
        print(f"{BANKS[args.bank]['name']} 폼({target}) 찾는 중 …")
        form = open_form(session, target, max_rows=args.max, need=args.need)
    if form is None:
        print("해당 은행 폼을 못 찾았습니다."); return 1

    only = {s.strip() for s in args.labels.split(",")} if args.labels else None
    window = _connect(driver.BACKEND, title_re=None, pid=None, handle=form.handle)
    fields = [f for f in collect(walk(window))
              if "ComboBox" in f["class_name"] and str(f["value"]).strip()
              and (only is None or f["label"] in only)]

    print(f"\n값이 있는 콤보 {len(fields)}개 중 최대 {args.limit}개를 시험한다.")
    print("  다른 값으로 바꿨다가 → 원래 값으로 되돌린다. **저장하지 않는다.**\n")

    ok = fail = skipped = 0
    for field in fields:
        if ok + fail >= args.limit:
            break
        label = field["label"] or "(라벨없음)"
        control = _control_at(window, field["box"])
        if control is None:
            print(f"  [skip] {label} — 컨트롤 못 찾음"); skipped += 1; continue
        items = combo_lists.items_for(form.class_name, label)
        if not items:
            print(f"  [skip] {label} — 수집된 목록 없음(되돌릴 기준이 약해 건너뜀)")
            skipped += 1; continue
        original = driver.read(driver.editable(control))
        other = _other_item(items, original)
        if other is None:
            print(f"  [skip] {label} — 목록에 다른 항목이 없다"); skipped += 1; continue

        started = time.monotonic()
        # 1) 다른 값으로 바꾼다
        try:
            changed = driver.select_item(control, other, items=items)
        except Exception as error:
            print(f"  ❌ {label[:14]:16} 바꾸기 실패 {type(error).__name__}: {str(error)[:50]}")
            fail += 1; continue
        now = driver.read(driver.editable(control))
        if not (changed and driver.combo_text(now) == driver.combo_text(other)):
            print(f"  ❌ {label[:14]:16} 안 바뀜 — {original!r} → {now!r} (목표 {other!r})")
            fail += 1
            if driver.combo_text(now) != driver.combo_text(original):
                print("     ⛔ 원래 값도 아니다 — 여기서 멈춘다. 화면을 확인하세요.")
                break
            continue

        # 2) 원래 값으로 되돌린다 — 여기서 실패하면 즉시 멈춘다
        try:
            back = driver.select_item(control, original, items=items)
        except Exception as error:
            print(f"  ⛔ {label[:14]:16} **되돌리기 실패** {type(error).__name__}: {str(error)[:50]}")
            print(f"     화면에 {now!r} 가 남아 있습니다. 원래 값은 {original!r} 입니다.")
            print("     ★ 저장하지 말고 '닫 기' 하세요 — 저장 전이라 DB 는 그대로입니다.")
            fail += 1; break
        restored = driver.read(driver.editable(control))
        same = driver.combo_text(restored) == driver.combo_text(original)
        if not (back and same):
            print(f"  ⛔ {label[:14]:16} **되돌리기 확인 실패** — 지금 {restored!r} / 원래 {original!r}")
            print("     ★ 저장하지 말고 '닫 기' 하세요.")
            fail += 1; break

        ok += 1
        print(f"  ✅ {label[:14]:16} {original[:16]:18} → {other[:16]:18} → 원복 "
              f"· {time.monotonic() - started:5.1f}초 · 목록 {len(items)}개")

    print(f"\n[결과] 성공 {ok} / 실패 {fail} / 건너뜀 {skipped}")
    print("폼은 열어 둡니다 — 값이 처음과 같은지 눈으로 확인하고 "
          "**'닫 기'(저장 안 함)** 하세요.")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
