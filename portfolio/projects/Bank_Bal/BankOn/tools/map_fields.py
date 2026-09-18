"""컨트롤 트리 → "항목 목록" 추출기 (정찰 2단계).

Delphi/VCL 폼은 라벨(TcxLabel)과 입력칸(TcxDBTextEdit 등)이 서로 모르는
별개 컨트롤이다. 연결 정보가 없으므로 **화면 좌표**로 짝짓는다.

  규칙 1) 같은 가로줄(세로 중심이 겹침) + 라벨이 입력칸 왼쪽 → 가장 가까운 것
  규칙 2) 1)이 없으면 바로 위쪽에 있고 가로로 겹치는 라벨

사용법:
    python tools/map_fields.py --handle 0x001A1E4C [--backend win32] [--out fields.md]
    python tools/map_fields.py --title-re "국민은행 담보"

읽기 전용이다 — 클릭·입력·창 조작을 하지 않는다.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from inspect_bankon import BACKENDS, _connect, walk  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

LABEL_CLASSES = ("TcxLabel", "TLabel", "TStaticText")

# 값을 넣을 수 있는 컨트롤. Inner* 는 바깥 컨트롤의 내부 구현이라 제외한다.
INPUT_MARKERS = (
    "TextEdit", "CurrencyEdit", "DateEdit", "ComboBox", "MaskEdit",
    "SpinEdit", "CheckBox", "RadioGroup", "Memo", "TimeEdit",
)
INNER_MARKERS = ("Inner",)

# 라벨을 찾는 최대 거리(px). 이보다 멀면 짝이 아니라고 본다.
MAX_LEFT_GAP = 260
MAX_ABOVE_GAP = 30


@dataclass(frozen=True)
class Box:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def cy(self) -> float:
        return (self.top + self.bottom) / 2

    @property
    def cx(self) -> float:
        return (self.left + self.right) / 2


def _box(node: dict) -> Box:
    return Box(node["left"], node["top"], node["right"], node["bottom"])


def is_label(node: dict) -> bool:
    return node["class_name"] in LABEL_CLASSES


def is_input(node: dict) -> bool:
    name = node["class_name"]
    if any(marker in name for marker in INNER_MARKERS):
        return False
    return any(marker in name for marker in INPUT_MARKERS)


def _row_overlaps(a: Box, b: Box) -> bool:
    """두 컨트롤이 같은 가로줄에 있는가(세로 구간이 겹치는가)."""
    return a.top < b.bottom and b.top < a.bottom


def _pool_for(target: dict, labels: list[dict]) -> tuple[list[dict], str]:
    """같은 부모 컨테이너의 라벨만 후보로 본다(다른 패널 라벨 가로채기 방지)."""
    siblings = [label for label in labels if label["parent"] == target["parent"]]
    if siblings:
        return siblings, ""
    return labels, "*"  # * = 부모 밖에서 찾음(신뢰도 낮음)


def find_label_primary(target: dict, labels: list[dict]) -> tuple[dict | None, str]:
    """1차: 라벨은 보통 입력칸 **왼쪽**(없으면 바로 위)에 놓인다."""
    if "RadioGroup" in target["class_name"] and target["title"].strip():
        return target, "자체"

    box = _box(target)
    pool, scope = _pool_for(target, labels)

    left_side = [
        label for label in pool
        if _row_overlaps(box, _box(label))
        and _box(label).right <= box.left + 4
        and box.left - _box(label).right <= MAX_LEFT_GAP
    ]
    if left_side:
        # 세로 중심이 가장 가까운 라벨(같은 줄에 라벨이 2개 걸칠 때 오매칭 방지),
        # 동률이면 더 오른쪽(=더 가까운) 라벨.
        return min(left_side,
                   key=lambda label: (abs(_box(label).cy - box.cy), -_box(label).right)), "왼쪽" + scope

    above = [
        label for label in pool
        if _box(label).bottom <= box.top + 2
        and box.top - _box(label).bottom <= MAX_ABOVE_GAP
        and _box(label).left < box.right and box.left < _box(label).right
    ]
    if above:
        return max(above, key=lambda label: _box(label).bottom), "위쪽" + scope

    return None, "미매칭"


def find_label_right(target: dict, labels: list[dict]) -> tuple[dict | None, str]:
    """2차: 점검항목처럼 콤보가 왼쪽·설명이 오른쪽에 오는 배치.

    1차에서 이미 쓰인 라벨은 후보에서 빠진 상태로 들어온다. 그래서 라벨 없는
    주소칸이 옆 열의 라벨을 가로채는 일이 생기지 않는다.
    """
    box = _box(target)
    pool, scope = _pool_for(target, labels)
    right_side = [
        label for label in pool
        if _row_overlaps(box, _box(label))
        and _box(label).left >= box.right - 4
        and _box(label).left - box.right <= MAX_LEFT_GAP
    ]
    if right_side:
        return min(right_side,
                   key=lambda label: (abs(_box(label).cy - box.cy), _box(label).left)), "오른쪽" + scope
    return None, "미매칭"


def _kind(class_name: str) -> str:
    """컨트롤 클래스 → 사람이 읽는 입력 종류."""
    table = {
        "CurrencyEdit": "숫자/금액",
        "DateEdit": "날짜",
        "ComboBox": "목록선택",
        "RadioGroup": "라디오",
        "CheckBox": "체크",
        "Memo": "여러줄",
        "TextEdit": "텍스트",
    }
    for marker, label in table.items():
        if marker in class_name:
            return label
    return "기타"


def _is_db_bound(class_name: str) -> bool:
    """TcxDB* = 데이터셋에 묶인 컨트롤(저장 대상 필드일 가능성 높음)."""
    return class_name.startswith("TcxDB")


def collect(nodes: list[dict]) -> list[dict]:
    labels = [node for node in nodes if is_label(node) and node["title"].strip()]
    inputs = [node for node in nodes if is_input(node)]

    # 1차(왼쪽/위쪽)로 짝지어 라벨을 선점하고, 남은 라벨로만 2차(오른쪽)를 돌린다.
    matched: dict[int, tuple[dict, str]] = {}
    used: set[int] = set()
    for index, node in enumerate(inputs):
        label, how = find_label_primary(node, labels)
        if label is not None:
            matched[index] = (label, how)
            if how != "자체":
                used.add(label["handle"])

    free = [label for label in labels if label["handle"] not in used]
    for index, node in enumerate(inputs):
        if index in matched:
            continue
        label, how = find_label_right(node, free)
        if label is not None:
            matched[index] = (label, how)
            used.add(label["handle"])
            free = [lb for lb in free if lb["handle"] != label["handle"]]

    fields = []
    for index, node in enumerate(inputs):
        label, how = matched.get(index, (None, "미매칭"))
        fields.append({
            "label": label["title"].strip() if label else "",
            "match": how,
            "kind": _kind(node["class_name"]),
            "class_name": node["class_name"],
            "db_bound": _is_db_bound(node["class_name"]),
            "value": node["value"] or "",
            "box": _box(node),
        })
    # 화면 읽는 순서(위→아래, 왼→오른쪽)로 정렬한다.
    return sorted(fields, key=lambda f: (f["box"].top, f["box"].left))


def render(fields: list[dict], title: str) -> str:
    matched = [f for f in fields if f["label"]]
    unmatched = [f for f in fields if not f["label"]]
    bound = [f for f in matched if f["db_bound"]]

    lines = [
        f"# {title} — 입력 항목",
        "",
        f"- 입력 컨트롤 {len(fields)}개 (라벨 매칭 {len(matched)} / 미매칭 {len(unmatched)})",
        f"- DB 바인딩(TcxDB*) {len(bound)}개 ← 실제 저장되는 필드",
        "",
        "| # | 항목 | 종류 | 현재값 | DB | 매칭 | 컨트롤 | 좌표(L,T) |",
        "|---|------|------|--------|----|------|--------|-----------|",
    ]
    for index, field in enumerate(matched, start=1):
        value = field["value"].replace("|", "\\|")[:40]
        lines.append(
            f"| {index} | {field['label']} | {field['kind']} | {value} | "
            f"{'O' if field['db_bound'] else ''} | {field['match']} | {field['class_name']} | "
            f"{field['box'].left},{field['box'].top} |"
        )

    if unmatched:
        lines += ["", "## 라벨 미매칭 (수동 확인 필요)", "",
                  "| # | 종류 | 현재값 | 컨트롤 | 좌표(L,T) |",
                  "|---|------|--------|--------|-----------|"]
        for index, field in enumerate(unmatched, start=1):
            value = field["value"].replace("|", "\\|")[:40]
            lines.append(
                f"| {index} | {field['kind']} | {value} | {field['class_name']} | "
                f"{field['box'].left},{field['box'].top} |"
            )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="map_fields")
    parser.add_argument("--title-re", default=None)
    parser.add_argument("--handle", type=lambda s: int(s, 0), default=None)
    parser.add_argument("--pid", type=int, default=None)
    parser.add_argument("--backend", choices=BACKENDS, default="win32")
    parser.add_argument("--out", default="fields.md")
    args = parser.parse_args(argv)

    if not (args.title_re or args.handle or args.pid):
        parser.error("--title-re / --handle / --pid 중 하나가 필요합니다.")

    window = _connect(args.backend, title_re=args.title_re, pid=args.pid, handle=args.handle)
    nodes = walk(window)
    if not nodes:
        print("컨트롤을 찾지 못했습니다.", file=sys.stderr)
        return 1

    text = render(collect(nodes), nodes[0]["title"] or nodes[0]["class_name"])
    Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    print(f"\n[저장] {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
