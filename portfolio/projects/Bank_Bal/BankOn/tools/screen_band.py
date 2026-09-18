"""화면 덤프(`recon/<은행>_screen.json`)에서 **위치 표기**를 푸는 오프라인 판.

라이브는 `ui.form.between_labels` + `ui.form.pick_from` 으로 칸을 짚는다. 오프라인 검사도
**정확히 같은 규칙**이어야 결과가 갈리지 않으므로, 순번·가장자리 고르기는 `form.pick_from`
을 그대로 불러 쓰고 여기서는 밴드를 만드는 일만 한다.

라이브와 다른 점 하나: 라이브는 `driver.is_input()` 으로 컨테이너·라벨을 거르지만, 덤프에는
**입력칸만 기록돼 있어** 거를 것이 없다(`recon_form` 이 이미 걸렀다). 그래서 결과가 같다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bankon.ui import form as form_mod          # noqa: E402


def band(record: dict, above: str, below: str) -> list[dict]:
    """두 라벨 **사이**의 칸들 — 화면 순서(위→아래, 왼→오른쪽)."""
    fields = record["fields"]
    top = next((f for f in fields if f["label"] == above), None)
    bottom = next((f for f in fields if f["label"] == below), None)
    if top is None or bottom is None:
        return []
    return sorted((f for f in fields if top["top"] < f["top"] < bottom["top"]),
                  key=lambda f: (f["top"], f["left"]))


def resolve(record: dict, label: str) -> dict | None:
    """위치 표기가 가리키는 필드 레코드(못 짚으면 None)."""
    spec = form_mod.BAND_SPEC.match(str(label))
    if spec is None:
        return None
    rows = band(record, spec.group("above"), spec.group("below"))
    return form_mod.pick_from([(f["left"], f) for f in rows], spec.group("index"))


def value_of(record: dict, label: str) -> str:
    field = resolve(record, label)
    if field is None:
        return ""
    return str(field["value"] if field["value"] is not None else "").strip()


def add_positional(screen: dict, record: dict, labels) -> None:
    """라벨이 없어 라벨맵이 못 담은 칸을 **위치 표기**로 채워 넣는다.

    같은 이름의 평범한 라벨 항목이 이미 있으면 **지운다** — 위치 표기를 쓴다는 건 그 라벨이
    엉뚱한 칸을 짚는다는 뜻이라(실측 기업 `물건종류`: 텍스트칸/콤보 둘에 붙어 있다),
    두 줄이 같이 뜨면 대조표가 헷갈린다. 위치 쪽이 정답이다.
    """
    for label in labels:
        if form_mod.BAND_SPEC.match(str(label)):
            screen[label] = value_of(record, label)
            screen.pop(form_mod.display_label(label), None)
