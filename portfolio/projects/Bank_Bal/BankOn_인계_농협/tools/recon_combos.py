"""은행 담보 폼의 **콤보 선택지**를 모은다 — 자동선택(v2)을 켜기 전 필수 확인.

우리가 만든 값이 콤보 목록에 **실제로 있는지** 알아야 자동선택을 켤 수 있다. 없으면
아무리 값이 맞아도 못 고른다(예: 우리 `대` / 목록엔 `대지`).

그리드를 훑어 그 은행 폼을 하나 열고, 콤보마다 목록을 수집한 뒤 폼을 닫는다.
수집은 `list_combo_items.probe_dropdown` 방식 — **F4 로 열고 방향키로 훑은 뒤 ESC 로 취소**
하므로 값이 바뀌지 않는다(바뀌면 즉시 중단).

    (관리자) python tools/recon_combos.py --bank nh --max 20
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pywinauto import Desktop                       # noqa: E402
from pywinauto.keyboard import send_keys            # noqa: E402

from bankon.config import load_config               # noqa: E402
from bankon.ui import driver, navigate              # noqa: E402
from inspect_bankon import _connect, walk           # noqa: E402
from map_fields import collect                      # noqa: E402
from list_combo_items import ValueChanged, probe_dropdown, try_item_texts  # noqa: E402
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


def open_bank_form(session, target_class: str, *, max_rows: int) -> driver.WindowRef | None:
    """그리드를 훑어 그 은행 폼이 나올 때까지 연다(`찾 기` 를 안 써 안전하다)."""
    grid = navigate._grid(session)
    grid.set_focus()
    time.sleep(0.4)
    send_keys("^{HOME}")
    time.sleep(0.4)
    for index in range(max_rows):
        before = navigate._menu_handles()
        send_keys("+{F10}")
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and not (navigate._menu_handles() - before):
            time.sleep(0.3)
        if not (navigate._menu_handles() - before):
            print(f"  [{index}] 메뉴 안 열림 — 종료")
            return None
        send_keys("a")
        try:
            form = driver.wait_for_window(driver.FORM_CLASS_PREFIX, pid=session.pid, timeout=15)
        except Exception:
            navigate.close_context_menu()
            form = None
        if form is not None:
            if form.class_name == target_class:
                print(f"  [{index}] {form.class_name} — 이 폼으로 수집")
                return form
            print(f"  [{index}] {form.class_name} 건너뜀")
            navigate.close_forms(session)
        grid = navigate._grid(session)
        grid.set_focus()
        time.sleep(0.3)
        send_keys("{DOWN}")
        time.sleep(0.3)
    return None


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="recon_combos")
    p.add_argument("--bank", choices=tuple(BANKS), required=True)
    p.add_argument("--doc", default=None,
                   help="이 문서번호로 폼을 연다(그리드 훑기 대신). 목록에 그 은행 건이 "
                        "없을 때 확실하다 — '찾 기' + 접수달로 기간 이동")
    p.add_argument("--max", type=int, default=25, help="폼을 찾으려 훑을 그리드 행 수")
    p.add_argument("--out", default=None)
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
        print(f"  {form.class_name} — 이 폼으로 수집")
    else:
        print(f"{BANKS[args.bank]['name']} 폼({target}) 찾는 중 …")
        form = open_bank_form(session, target, max_rows=args.max)
    if form is None:
        print("해당 은행 폼을 못 찾았습니다."); return 1

    window = _connect(driver.BACKEND, title_re=None, pid=None, handle=form.handle)
    fields = [f for f in collect(walk(window)) if "ComboBox" in f["class_name"]]
    print(f"콤보 {len(fields)}개 수집 시작 (ESC 로 원복, 값이 바뀌면 즉시 중단)\n")

    out = Path(args.out) if args.out else ROOT / "recon" / f"combo_{form.class_name}.md"
    lines = [f"# {BANKS[args.bank]['name']} 담보 콤보 선택지 ({form.class_name})", ""]
    status = 0
    for field in fields:
        control = _control_at(window, field["box"])
        if control is None:
            print(f"  [skip] {field['label']} — 컨트롤 못 찾음")
            continue
        items, how = try_item_texts(control), "item_texts"
        if not items:
            try:
                items = probe_dropdown(control) if control.is_enabled() else []
                how = "dropdown" if items else "비활성"
            except ValueChanged as error:
                print(f"\n[중단] {field['label']}: {error}")
                print("값이 바뀌었습니다 — 화면을 확인하고 되돌리세요.")
                status = 2
                break
            except Exception as error:
                how = f"실패({type(error).__name__})"
        print(f"  {field['label'][:24]:26} {len(items):3}개 ({how})  현재={field['value'][:20]!r}")
        lines.append(f"## {field['label']}  ({field['class_name']}, "
                     f"현재값={field['value']!r}, 좌표={field['box'].left},{field['box'].top})")
        lines += [f"- {i}" for i in items] or ["- (수집 실패)"]
        lines.append("")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[저장] {out}")
    navigate.close_forms(session)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
