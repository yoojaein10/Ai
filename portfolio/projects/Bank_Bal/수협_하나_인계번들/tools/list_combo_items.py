"""LookupComboBox 선택지 수집기 (정찰 3단계).

은행 폼의 콤보는 그 은행이 정한 코드 목록이다. `.gam` 값(예: '철근콘크리트구조')을
그 코드로 바꾸려면 선택지 목록이 필요하다.

수집 순서 — 덜 위험한 것부터:
  1) item_texts()  : 조작 없음. 표준 콤보면 이걸로 끝
  2) 드롭다운 열기  : F4 로 열고 팝업 창의 텍스트를 읽은 뒤 **ESC 로 취소**

안전장치: 각 콤보마다 **작업 전후 값을 비교**해서 하나라도 바뀌면 즉시 중단한다.
ESC 는 선택을 취소하므로 값이 바뀌지 않아야 정상이다.

사용법:
    python tools/list_combo_items.py --handle 0x000F2172 [--only 담보종류,지목] [--probe]
    (--probe 없으면 1)만 시도하고 끝낸다 — 완전 무해)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from inspect_bankon import BACKENDS, _connect, walk  # noqa: E402
from map_fields import collect  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

POPUP_WAIT = 0.4


class ValueChanged(RuntimeError):
    """콤보 값이 바뀌었다 — 즉시 중단한다."""


def _find_control(window, box):
    """좌표로 컨트롤을 되찾는다(수집 대상 지정용)."""
    for child in window.descendants():
        try:
            rect = child.rectangle()
        except Exception:
            continue
        if (rect.left, rect.top) == (box.left, box.top):
            return child
    return None


def _read(control) -> str:
    for attr in ("get_value", "window_text"):
        try:
            value = getattr(control, attr)()
            if value:
                return str(value).strip()
        except Exception:
            continue
    return ""


def try_item_texts(control) -> list[str]:
    """조작 없이 목록을 읽어본다."""
    try:
        items = control.item_texts()
    except Exception:
        return []
    return [str(i).strip() for i in items if str(i).strip()]


def probe_dropdown(control, max_items: int = 400) -> list[str]:
    """F4 로 드롭다운을 열고 방향키로 훑으며 표시값을 모은 뒤 ESC 로 되돌린다.

    DevExpress 드롭다운(TcxCustomLookupDBGrid)은 항목이 그려진 픽셀이라
    win32/UIA 어느 쪽으로도 텍스트를 읽을 수 없다(확인함). 대신 항목을 하나씩
    이동하면 편집칸 표시값이 바뀌므로 그걸 읽는다. ESC 는 선택을 취소하므로
    원래 값이 그대로 남는다 — 함수 끝에서 반드시 검증한다.
    """
    import time

    before = _read(control)
    items: list[str] = []
    try:
        control.set_focus()
        control.type_keys("{F4}")
        time.sleep(POPUP_WAIT)
        # {HOME} 은 그리드가 아니라 편집칸 커서에 먹혀서 맨 위로 가지 않는다.
        # 위로 끝까지 올린 뒤(값이 더 안 바뀔 때까지) 아래로 훑어야 전체가 나온다.
        top, up_stall = None, 0
        for _ in range(max_items):
            current = _read(control)
            if current != top:
                top, up_stall = current, 0
            else:
                up_stall += 1
                if up_stall >= 3:
                    break
            control.type_keys("{UP}")
            time.sleep(0.08)

        last, stall = None, 0
        for _ in range(max_items):
            value = _read(control)
            if value and value != last:
                items.append(value)
                last, stall = value, 0
            else:
                stall += 1
                if stall >= 3:
                    break
            control.type_keys("{DOWN}")
            time.sleep(0.08)
    finally:
        try:
            control.type_keys("{ESC}")
            time.sleep(0.25)
        except Exception:
            pass

    after = _read(control)
    if after != before:
        raise ValueChanged(f"값이 {before!r} → {after!r} 로 바뀜")
    return items


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="list_combo_items")
    parser.add_argument("--handle", type=lambda s: int(s, 0), required=True)
    parser.add_argument("--backend", choices=BACKENDS, default="win32")
    parser.add_argument("--only", default=None, help="콤마로 구분한 항목명(부분일치)")
    parser.add_argument("--probe", action="store_true", help="드롭다운을 열어 수집(ESC 로 복원)")
    parser.add_argument("--out", default="combo_items.md")
    args = parser.parse_args(argv)

    from pywinauto import Desktop

    window = _connect(args.backend, title_re=None, pid=None, handle=args.handle)
    fields = [f for f in collect(walk(window)) if "ComboBox" in f["class_name"]]
    if args.only:
        wanted = [w.strip() for w in args.only.split(",") if w.strip()]
        fields = [f for f in fields if any(w in f["label"] for w in wanted)]

    desktop = Desktop(backend=args.backend)
    lines = ["# 콤보 선택지", ""]
    print(f"대상 콤보 {len(fields)}개 (probe={'ON' if args.probe else 'OFF'})\n")

    for field in fields:
        control = _find_control(window, field["box"])
        if control is None:
            print(f"  [skip] {field['label']} — 컨트롤 못 찾음")
            continue
        items = try_item_texts(control)
        how = "item_texts"
        if not items and args.probe:
            try:
                if not control.is_enabled():
                    how = "비활성-건너뜀"
                else:
                    items = probe_dropdown(control)
                    how = "dropdown"
            except ValueChanged as error:
                # 값이 실제로 바뀐 경우에만 중단한다 — 데이터 훼손 위험.
                print(f"\n[중단] {field['label']}: {error}")
                print("값이 변경되었습니다. 수동으로 확인·복구하세요.")
                return 2
            except Exception as error:  # 개별 콤보 실패는 건너뛴다
                how = f"실패({type(error).__name__})"
        label = field["label"][:34]
        print(f"  {label:36} {len(items):3}개 ({how})")
        lines.append(f"## {field['label']}  ({field['class_name']}, 현재값={field['value']!r})")
        lines += [f"- {i}" for i in items] or ["- (수집 실패)"]
        lines.append("")

    Path(args.out).write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[저장] {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
