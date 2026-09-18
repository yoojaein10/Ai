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

from dataclasses import dataclass

from . import driver

# 선택형 컨트롤 — 자동 텍스트 입력이 아니라 항목 선택이 필요해 v1 에선 수동으로 남긴다.
SELECT_MARKERS = ("ComboBox", "RadioGroup", "CheckBox")

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


def plan_field(form, label: str, value) -> tuple[str, str, object]:
    """한 필드의 (action, current, control) 계산 — 아직 화면에 쓰지 않는다."""
    if value in (None, ""):
        return "빈값", "", None
    control = driver.find_by_label(form.handle, str(label))
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
        return "수동(선택형)", current, control
    if _norm(current) == _norm(str(value)):
        return "일치", current, control
    return ("덮어씀" if current else "채움"), current, control


def fill(form, values: dict, *, live: bool = False, overwrite: bool = False) -> list[FillResult]:
    """매핑값을 폼에 채운다(기본 드라이런).

    live=True 면 텍스트/숫자/날짜칸을 실제 입력한다. **기본은 빈칸만 채운다**(안전) —
    사람이 이미 넣은 값은 건드리지 않는다(잡음 필드 오염 방지). overwrite=True 여야 덮어쓴다.
    """
    results: list[FillResult] = []
    for label, value in values.items():
        action, current, control = plan_field(form, label, value)
        wrote = False
        writable = action == "채움" or (action == "덮어씀" and overwrite)
        if live and writable and control is not None:
            try:
                driver.set_text(control, str(value))   # 되읽기 검증 포함
                wrote = True
            except driver.ValueRejected as exc:
                action = f"거부({str(exc)[:30]})"
        results.append(FillResult(str(label), action, str(value) if value not in (None, "") else "",
                                  current, wrote))
    return results
