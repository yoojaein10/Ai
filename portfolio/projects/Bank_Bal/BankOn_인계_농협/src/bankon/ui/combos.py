"""수집해 둔 콤보 선택지 — 자동선택을 **빠르게** 하기 위한 목록.

`tools/recon_combos.py` 가 `recon/combo_<폼클래스>.md` 에 모아 둔 목록을 읽는다.

목록이 있으면 목표 항목이 **몇 번째인지** 알 수 있어, 드롭다운을 한 칸씩 훑는 대신
`{UP n}` 으로 맨 위에 붙였다가 `{DOWN i}` 로 한 번에 건너뛴다(77개짜리 심사자 콤보가
22초 → 1초대). 목록이 없거나 순서가 어긋나면 훑기로 물러선다 — **Enter 전에 표시값을
반드시 확인**하므로 목록이 낡아도 틀린 항목을 고르지는 않는다.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]     # src/bankon/ui/combos.py → 저장소 루트
RECON = ROOT / "recon"

_HEAD = re.compile(r"^##\s+(?P<label>.+?)\s{2}\(")

_cache: dict[str, dict[str, tuple[str, ...]]] = {}


def _parse(text: str) -> dict[str, tuple[str, ...]]:
    """`## 라벨  (…)` + `- 항목` 형식을 {라벨: 항목들} 로.

    같은 라벨이 여러 칸일 수 있어(`물건종류` 가 물건종류·부동산구분 두 곳) **먼저 나온 것**을
    쓴다 — `driver.find_by_label` 도 첫 라벨을 집으므로 규칙이 같다.
    """
    table: dict[str, tuple[str, ...]] = {}
    label: str | None = None
    items: list[str] = []

    def flush() -> None:
        if label and items:
            table.setdefault(label, tuple(items))

    for line in text.splitlines():
        head = _HEAD.match(line)
        if head:
            flush()
            label, items = head.group("label").strip(), []
            continue
        if line.startswith("- ") and label is not None:
            value = line[2:].strip()
            if value and value != "(수집 실패)":
                items.append(value)
    flush()
    return table


def for_form(form_class: str) -> dict[str, tuple[str, ...]]:
    """폼 클래스의 콤보 목록(없으면 빈 dict)."""
    if form_class in _cache:
        return _cache[form_class]
    path = RECON / f"combo_{form_class}.md"
    table: dict[str, tuple[str, ...]] = {}
    if path.exists():
        try:
            table = _parse(path.read_text(encoding="utf-8"))
        except OSError:
            table = {}
    _cache[form_class] = table
    return table


def items_for(form_class: str, label: str) -> tuple[str, ...]:
    return for_form(form_class).get(str(label), ())
