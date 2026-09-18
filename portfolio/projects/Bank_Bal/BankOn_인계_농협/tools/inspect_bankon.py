"""뱅크온라인 화면 정찰기 — 입력 필드가 무엇인지 알아내는 1단계 도구.

UI 자동입력은 "어떤 컨트롤에 무엇을 넣을지"를 알아야 시작할 수 있다.
이 스크립트는 실행 중인 창의 컨트롤 트리를 덤프해서 그 목록을 만든다.

사용법:
    python tools/inspect_bankon.py list
        현재 떠 있는 최상위 창 목록(제목/클래스/PID)을 보여준다.

    python tools/inspect_bankon.py dump --title-re "뱅크" [--backend uia|win32]
        해당 창의 컨트롤 트리를 덤프한다. --backend 미지정 시 둘 다 시도해
        더 많은 컨트롤을 찾은 쪽을 쓴다(Delphi VCL=win32, .NET/WPF=uia).

    python tools/inspect_bankon.py dump --pid 1234 --out dump.txt

출력은 항상 UTF-8 파일로도 남긴다(콘솔 CP949 깨짐 대비).
읽기 전용이다 — 클릭·입력·창 조작을 일절 하지 않는다.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# 콘솔 한글 깨짐 방지(가능한 환경에서만).
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover - 구형 콘솔
    pass

try:
    from pywinauto import Desktop
    from pywinauto.findwindows import find_elements
except ImportError as error:  # pragma: no cover - 설치 안내
    raise SystemExit(
        "pywinauto 가 필요합니다: pip install pywinauto\n"
        f"(원인: {error})"
    ) from error

BACKENDS = ("win32", "uia")
MAX_DEPTH = 12
MAX_NODES = 4000


@dataclass(frozen=True)
class WindowInfo:
    title: str
    class_name: str
    pid: int
    handle: int
    backend: str


def list_windows() -> tuple[WindowInfo, ...]:
    """보이는 최상위 창을 백엔드별로 모아 반환한다."""
    found: dict[tuple[int, str], WindowInfo] = {}
    for backend in BACKENDS:
        try:
            elements = find_elements(backend=backend, top_level_only=True, visible_only=True)
        except Exception as error:
            print(f"[warn] {backend} 열거 실패: {error}", file=sys.stderr)
            continue
        for element in elements:
            title = (element.name or "").strip()
            handle = int(element.handle or 0)
            if not title or not handle:
                continue
            found.setdefault(
                (handle, backend),
                WindowInfo(
                    title=title,
                    class_name=element.class_name or "",
                    pid=int(element.process_id or 0),
                    handle=handle,
                    backend=backend,
                ),
            )
    return tuple(sorted(found.values(), key=lambda w: (w.pid, w.backend, w.title)))


def _framework_hint(class_name: str) -> str:
    """창 클래스명으로 UI 프레임워크를 추정한다(백엔드 선택 근거)."""
    name = class_name or ""
    if name.startswith("TApplication") or name.startswith("TForm") or name.startswith("Tfrm"):
        return "Delphi VCL → win32 백엔드"
    if name.startswith("WindowsForms"):
        return ".NET WinForms → uia(또는 win32) 백엔드"
    if name == "HwndWrapper" or name.startswith("HwndWrapper"):
        return "WPF → uia 백엔드"
    if name in ("Chrome_WidgetWin_1", "MozillaWindowClass"):
        return "브라우저(Chromium/Gecko) → 웹 자동화 검토"
    if name.startswith("SunAwt"):
        return "Java Swing → uia 제한적"
    return "미상"


def _node_line(depth: int, info: dict) -> str:
    pad = "  " * depth
    parts = [f"{pad}{info['control_type']}"]
    if info["title"]:
        parts.append(f'"{info["title"]}"')
    if info["auto_id"]:
        parts.append(f"auto_id={info['auto_id']}")
    parts.append(f"class={info['class_name']}")
    parts.append(f"rect=({info['left']},{info['top']},{info['right']},{info['bottom']})")
    if info["value"] is not None:
        parts.append(f"value={info['value']!r}")
    if not info["enabled"]:
        parts.append("DISABLED")
    return " ".join(parts)


def _read_value(element) -> str | None:
    """편집 가능한 컨트롤이면 현재 값을 읽는다(읽기 전용)."""
    for attr in ("get_value", "window_text", "texts"):
        try:
            getter = getattr(element, attr, None)
            if getter is None:
                continue
            value = getter()
            if isinstance(value, list):
                value = " | ".join(str(v) for v in value if str(v).strip())
            value = str(value).strip()
            if value:
                return value[:200]
        except Exception:
            continue
    return None


def _describe(element, depth: int, parent: int = 0) -> dict:
    def safe(fn, default=""):
        try:
            return fn()
        except Exception:
            return default

    rect = safe(element.rectangle, None)
    control_type = safe(lambda: element.element_info.control_type, "") or safe(
        lambda: type(element).__name__, "?"
    )
    return {
        "depth": depth,
        "handle": _handle_of(element),
        "parent": parent,
        "control_type": control_type,
        "title": safe(element.window_text, "")[:120],
        "auto_id": safe(lambda: element.element_info.automation_id, ""),
        "class_name": safe(lambda: element.element_info.class_name, ""),
        "enabled": safe(element.is_enabled, True),
        "left": getattr(rect, "left", 0),
        "top": getattr(rect, "top", 0),
        "right": getattr(rect, "right", 0),
        "bottom": getattr(rect, "bottom", 0),
        "value": _read_value(element),
    }


def _handle_of(element) -> int:
    try:
        return int(element.element_info.handle or 0)
    except Exception:
        return 0


def walk(
    element,
    depth: int = 0,
    budget: list[int] | None = None,
    seen: set[int] | None = None,
    parent: int = 0,
) -> list[dict]:
    """컨트롤 트리를 깊이우선으로 순회한다(깊이·노드 수 상한 있음).

    VCL 은 children() 이 직계 자식과 후손을 함께 돌려주는 경우가 있어 같은
    컨트롤이 여러 번 나온다. HWND 로 중복을 걸러 트리를 한 번만 찍는다.
    """
    if budget is None:
        budget = [MAX_NODES]
    if seen is None:
        seen = set()
    if depth > MAX_DEPTH or budget[0] <= 0:
        return []

    handle = _handle_of(element)
    if handle:
        if handle in seen:
            return []
        seen.add(handle)

    budget[0] -= 1
    nodes = [_describe(element, depth, parent)]
    try:
        children = element.children()
    except Exception:
        children = []
    for child in children:
        nodes.extend(walk(child, depth + 1, budget, seen, handle))
    return nodes


def _connect(backend: str, *, title_re: str | None, pid: int | None, handle: int | None):
    desktop = Desktop(backend=backend)
    if handle:
        return desktop.window(handle=handle)
    if pid:
        return desktop.window(process=pid)
    return desktop.window(title_re=title_re)


def dump(
    *,
    title_re: str | None,
    pid: int | None,
    handle: int | None,
    backend: str | None,
    out_path: Path,
) -> int:
    candidates = (backend,) if backend else BACKENDS
    best: tuple[str, list[dict]] | None = None
    for name in candidates:
        try:
            window = _connect(name, title_re=title_re, pid=pid, handle=handle)
            nodes = walk(window)
        except Exception as error:
            print(f"[warn] {name} 백엔드 실패: {error}", file=sys.stderr)
            continue
        print(f"[info] {name} 백엔드: 컨트롤 {len(nodes)}개")
        if best is None or len(nodes) > len(best[1]):
            best = (name, nodes)

    if best is None:
        print("창을 찾지 못했습니다. `list` 로 제목을 먼저 확인하세요.", file=sys.stderr)
        return 1

    used_backend, nodes = best
    root_class = nodes[0]["class_name"] if nodes else ""
    header = [
        f"# 백엔드: {used_backend}",
        f"# 루트 클래스: {root_class}",
        f"# 프레임워크 추정: {_framework_hint(root_class)}",
        f"# 컨트롤 수: {len(nodes)}",
        "",
    ]
    body = [_node_line(node["depth"], node) for node in nodes]
    text = "\n".join(header + body)

    out_path.write_text(text, encoding="utf-8")
    print(text)
    print(f"\n[저장] {out_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="inspect_bankon")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="최상위 창 목록")

    p_dump = sub.add_parser("dump", help="컨트롤 트리 덤프")
    p_dump.add_argument("--title-re", default=None, help="창 제목 정규식")
    p_dump.add_argument("--pid", type=int, default=None)
    p_dump.add_argument("--handle", type=lambda s: int(s, 0), default=None)
    p_dump.add_argument("--backend", choices=BACKENDS, default=None)
    p_dump.add_argument("--out", default="bankon_dump.txt")

    args = parser.parse_args(argv)

    if args.cmd == "list":
        windows = list_windows()
        if not windows:
            print("보이는 창이 없습니다.")
            return 1
        for window in windows:
            print(
                f"[{window.backend:5}] pid={window.pid:<6} hwnd=0x{window.handle:08X} "
                f"class={window.class_name:<28} {window.title}"
            )
            hint = _framework_hint(window.class_name)
            if hint != "미상":
                print(f"{'':>8}└ {hint}")
        return 0

    if not (args.title_re or args.pid or args.handle):
        parser.error("dump 는 --title-re / --pid / --handle 중 하나가 필요합니다.")
    return dump(
        title_re=args.title_re,
        pid=args.pid,
        handle=args.handle,
        backend=args.backend,
        out_path=Path(args.out),
    )


if __name__ == "__main__":
    raise SystemExit(main())
