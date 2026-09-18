"""담보 폼에 매핑값을 입력한다 — 라벨로 칸을 찾아 값 주입 + 되읽기 검증.

`driver.find_by_label` 로 라벨 오른쪽/아래의 입력칸을 짚고 `driver.set_text` 로 넣는다
(메시지 기반이라 마우스·키보드를 뺏지 않는다). 값을 넣은 뒤 되읽어 다르면 즉시 멈춘다.

안전 원칙:
  - **기본은 드라이런**(live=False): 무엇을 어디에 넣을지 계획만 만들고 화면은 안 건드린다.
  - 선택형(콤보·라디오·체크)은 v1 에서 자동입력하지 않는다(잘못 고르면 위험) → '수동' 보고.
  - 빈 값(None/'')은 건너뛴다. 이미 같은 값이면 건너뛴다(일치).
  - 되읽기 불일치(ValueRejected)면 그 칸에서 멈추고 보고에 남긴다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import combos, driver

# 선택형 컨트롤 — 자동 텍스트 입력이 아니라 항목 선택이 필요하다.
SELECT_MARKERS = ("ComboBox", "RadioGroup", "CheckBox")

# 그중 **콤보만** 자동선택을 시도할 수 있다(`driver.select_item`). 라디오·체크는 화면마다
# 배치가 달라 아직 사람이 고른다.
SELECTABLE_MARKERS = ("ComboBox",)

# 화면이 스스로 관리하는 앵커(네비게이션) 필드 — 읽기만 하고 절대 쓰지 않는다.
# 일련번호는 '지금 보고 있는 물건 슬롯' 표시라, 쓰면 다물건에서 순번이 어긋난다.
ANCHOR_LABELS = ("일련번호",)


@dataclass(frozen=True)
class FillResult:
    label: str
    action: str          # 채움 | 덮어씀 | 일치 | 수동(선택형) | 미발견 | 빈값 | 거부
    ours: str
    current: str
    wrote: bool = False


def _norm(text: str) -> str:
    return (text or "").replace(",", "").strip()


def between_labels(form, above: str, below: str) -> list:
    """두 라벨 **사이**에 있는 입력칸들을 화면 순서(위→아래, 왼→오른쪽)로.

    라벨이 없거나 여러 칸이 같은 라벨을 나눠 쓰는 자리를 짚는 수단이다. 절대좌표가
    아니라 **위아래 라벨 사이의 순서**로 지정하므로 창 크기가 바뀌어도 견딘다.

    농협 담보 폼의 `물건기호`~`번지구분` 사이는 실측 14건에서 **항상 같은 7칸**이다:

        0 물건종류(콤보) · 1 부동산구분(콤보) · 2 우편번호 · 3 법정동코드
        4 소재지(짧은 표기) · 5 소재지(긴 표기) · 6 물건 표시
    """
    top = driver.find_by_label(form.handle, above)
    bottom = driver.find_by_label(form.handle, below)
    if top is None or bottom is None:
        return []
    try:
        upper, lower = top.rectangle().top, bottom.rectangle().top
    except Exception:
        return []
    found = []
    for control in driver.descendants(form.handle):
        try:
            name = control.element_info.class_name or ""
            rect = control.rectangle()
        except Exception:
            continue
        if not driver.is_input(name) or not (upper < rect.top < lower):
            continue
        found.append((rect.top, rect.left, control))
    return [control for _top, _left, control in sorted(found, key=lambda x: (x[0], x[1]))]


# 라벨이 없거나 겹치는 칸을 **위치**로 지정하는 표기.
#     `소재지@물건기호~번지구분[5]`     →  밴드에서 6번째 칸(0부터)
#     `소재지@일련번호~번지구분[왼쪽]`   →  밴드에서 **가장 왼쪽** 칸
# 앞부분(`소재지`)은 보고서에 쓰는 이름이고, 뒤가 위치 지정이다.
#
# 순번(숫자)은 밴드 구성이 문서마다 같을 때만 쓴다. 구성이 변형별로 달라지면(실측 기업:
# 소재지가 토지형 [2] · 집합건물형 [3]) 순번은 위험하고, 대신 `왼쪽`/`오른쪽` 처럼
# **구성이 바뀌어도 유지되는 성질**로 짚는다(기업 소재지는 35/35 에서 밴드 최좌측).
EDGES = ("왼쪽", "오른쪽")
# `위좌`/`위우` = 밴드 **최상단 행**(top 이 가장 작은 행, 오차 8px 이내로 같은 행)의 왼쪽/오른쪽
# 칸. 숫자 인덱스는 폼변형마다 밴드 구성이 달라지면 어긋나지만(실측 기업 소재지 토지형[2]·
# 집합건물형[3]), '최상단 행의 좌/우' 는 그 성질이 변형과 무관하게 유지된다(수협 법정동 2칸).
TOP_EDGES = ("위좌", "위우")
POSITIONAL = re.compile(
    r"^(?P<name>[^@]+)@(?P<above>[^~]+)~(?P<below>[^\[]+)\[(?P<index>\d+|왼쪽|오른쪽|위좌|위우)\]$")


def display_label(label: str) -> str:
    """보고서에 쓸 이름 — 위치 표기는 앞부분만 보여 준다."""
    spec = POSITIONAL.match(str(label))
    return spec.group("name") if spec else str(label)


def _payload_top(payload) -> int | None:
    """payload(컨트롤 또는 화면덤프 dict)의 top 좌표. 못 얻으면 None."""
    if isinstance(payload, dict):
        return payload.get("top")
    try:
        return payload.rectangle().top
    except Exception:
        return None


def pick_from(entries: list, token: str):
    """`(left, payload)` 목록에서 위치 토큰이 가리키는 payload(없으면 None).

    라이브(컨트롤)와 오프라인(화면 덤프)이 **같은 규칙**을 쓰도록 한 곳에 둔다.
    가장자리 지정(`왼쪽`/`오른쪽`)은 그 자리가 **유일할 때만** 짚는다 — 같은 x 에 두 칸이
    있으면 어느 쪽인지 못 가르므로 None 을 돌려 호출측이 '미발견'으로 남긴다.
    `위좌`/`위우` 는 밴드 **최상단 행**(top 최소, ±8px 동일행)의 왼쪽/오른쪽 칸 — 그 행에
    칸이 정확히 둘일 때만 짚는다(아니면 None → 안전하게 미발견).
    """
    if not entries:
        return None
    if token.isdigit():
        index = int(token)
        return entries[index][1] if index < len(entries) else None
    if token in TOP_EDGES:
        tops = [(_payload_top(p), left, p) for left, p in entries]
        if any(t is None for t, _l, _p in tops):
            return None                    # top 을 못 읽으면 짚지 않는다(안전)
        top_min = min(t for t, _l, _p in tops)
        # 최상단 행 = top 이 최소값과 3px 이내(같은 행). 아래 행(등기번호 top+5)이 섞이지
        # 않게 좁게 잡는다 — 수협 실측: 법정동 391 vs 등기번호 396.
        row = [(left, p) for t, left, p in tops if abs(t - top_min) <= 3]
        if len(row) != 2:                  # 최상단 행이 정확히 두 칸이 아니면 못 가른다(안전)
            return None
        row.sort(key=lambda x: x[0])       # 좌→우
        return row[0][1] if token == "위좌" else row[1][1]
    if token not in EDGES:
        return None
    lefts = [left for left, _payload in entries]
    edge = min(lefts) if token == "왼쪽" else max(lefts)
    if lefts.count(edge) != 1:
        return None
    return entries[lefts.index(edge)][1]


def resolve_control(form, label: str):
    """라벨 또는 위치 표기로 입력칸을 짚는다."""
    spec = POSITIONAL.match(str(label))
    if spec is None:
        return driver.find_by_label(form.handle, str(label))
    entries = []
    for control in between_labels(form, spec.group("above"), spec.group("below")):
        try:
            entries.append((control.rectangle().left, control))
        except Exception:
            return None                    # 좌표를 못 읽으면 짚지 않는다(안전)
    return pick_from(entries, spec.group("index"))


def read_field(form, label: str) -> str:
    """그 칸의 현재 화면값(못 짚으면 빈 문자열)."""
    control = resolve_control(form, label)
    return driver.read(driver.editable(control)) if control is not None else ""


def plan_field(form, label: str, value, *, select: bool = False) -> tuple[str, str, object]:
    """한 필드의 (action, current, control) 계산 — 아직 화면에 쓰지 않는다.

    `select=True` 면 **콤보도 채울 대상**으로 본다(`고름`). 기본은 예전대로 `수동(선택형)`.
    """
    if value in (None, ""):
        return "빈값", "", None
    control = resolve_control(form, label)
    if control is None:
        return "미발견", "", None
    try:
        cls = control.element_info.class_name or ""
    except Exception:
        cls = ""
    current = driver.read(driver.editable(control))
    if str(label) in ANCHOR_LABELS:
        return "순번(안건드림)", current, control
    if any(marker in cls for marker in SELECT_MARKERS):
        if not (select and any(m in cls for m in SELECTABLE_MARKERS)):
            return "수동(선택형)", current, control
        if driver.combo_text(current) == driver.combo_text(str(value)):
            return "일치", current, control
        return ("고름(덮어씀)" if current else "고름"), current, control
    if _norm(current) == _norm(str(value)):
        return "일치", current, control
    return ("덮어씀" if current else "채움"), current, control


def fill(form, values: dict, *, live: bool = False, overwrite: bool = False,
         select: bool = False) -> list[FillResult]:
    """매핑값을 폼에 채운다(기본 드라이런).

    live=True 면 텍스트/숫자/날짜칸을 실제 입력한다. **기본은 빈칸만 채운다**(안전) —
    사람이 이미 넣은 값은 건드리지 않는다(잡음 필드 오염 방지). overwrite=True 여야 덮어쓴다.

    select=True 면 **콤보도 자동선택**한다(`driver.select_item`). 목록에 없는 값이면
    ESC 로 취소하고 원래 값을 그대로 둔 채 `못찾음(목록)` 으로 남긴다 — 틀린 항목을
    고르는 일은 없다.
    """
    results: list[FillResult] = []
    for label, value in values.items():
        action, current, control = plan_field(form, label, value, select=select)
        wrote = False
        picking = action.startswith("고름")
        writable = (action == "채움" or picking or (action == "덮어씀" and overwrite))
        if picking and current and not overwrite:
            writable = False                       # 사람이 고른 값은 안 건드린다
        if live and writable and control is not None:
            try:
                if picking:
                    # 수집해 둔 선택지가 있으면 순번으로 건너뛴다(느린 훑기 대신).
                    wrote = driver.select_item(
                        control, str(value),
                        items=combos.items_for(form.class_name, display_label(label)))
                    if not wrote:
                        action = "못찾음(목록)"
                else:
                    driver.set_text(control, str(value))   # 되읽기 검증 포함
                    wrote = True
            except driver.ValueRejected as exc:
                action = f"거부({str(exc)[:30]})"
        results.append(FillResult(display_label(label), action,
                                  str(value) if value not in (None, "") else "",
                                  current, wrote))
    return results
