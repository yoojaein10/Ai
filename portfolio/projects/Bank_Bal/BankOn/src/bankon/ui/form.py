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
import time
from dataclasses import dataclass

from pywinauto.keyboard import send_keys

from . import driver

# 라벨 없는 칸 — 기준 라벨 입력칸에서의 상대 위치(dx, dy)로 짚는다(신한 폼 정찰표 실측).
# 은행별 항목은 autofill_* 가 mapping.<bank>.POSITIONAL / REGIONS 로 덧붙인다(use_layout).
POSITIONAL = {
    "법정동_시군구": ("물건순번", 0, 153, "TcxDBTextEdit"),
    "법정동_읍면동": ("물건순번", 55, 153, "TcxDBTextEdit"),
    # 소재지 = '※아래 칸은 동미만 주소만' 바로 아래 칸(y+127). 그 아래 주소검색 밑 칸(y+176)은 시군구·읍면동
    # 은행 선입력 칸이라 건드리지 않는다(2026-08-27: 2673·2695 에서 아래 칸에 넣었다가 사용자가 되돌림).
    "소재지": ("물건순번", -126, 127, "TcxDBTextEdit"),
    # 우편번호 = 첫 "주소검색" 버튼 오른쪽 칸(물건순번 칸 바로 아래, 2819 실측 y+68). 은행이 1행에만 선입력한다 —
    # 매핑값은 없고(소스에 우편번호 없음) 행 복사 추가로 넘겨받는다. 보정 도구가 읽고 쓸 때만 짚는다(2026-09-14).
    "우편번호": ("물건순번", 0, 68, "TcxDBTextEdit"),
}
# 라벨 접두 '구역:' → 창 왼쪽 기준 x 범위. 같은 라벨이 패널마다 있는 폼(국민 물건/세부내역)용.
REGIONS: dict[str, tuple[int, int]] = {}


def use_layout(positional: dict | None = None, regions: dict | None = None) -> None:
    """은행별 상대좌표·구역 정의를 등록한다(autofill_* 시작 시 1회)."""
    if positional:
        POSITIONAL.update(positional)
    if regions:
        REGIONS.update(regions)


def split_label(label: str) -> tuple[str, str, int, tuple[int, int] | None]:
    """'구역:라벨@N' → (원문 키, 라벨, index, region)."""
    text = str(label)
    region = None
    if ":" in text:
        head, _, rest = text.partition(":")
        if head in REGIONS:
            region, text = REGIONS[head], rest
    name, _, nth = text.partition("@")
    return str(label), name, (int(nth) - 1 if nth.isdigit() else 0), region

# 선택형 컨트롤. 콤보(TcxDBLookupComboBox·TcxComboBox)는 "포커스→타이핑→Enter"로 고를 수 있음을
# 실증(diag_combo 2026-08-25). 라디오·체크박스는 아직 수동.
SELECT_MARKERS = ("ComboBox", "RadioGroup", "CheckBox")
COMBO_MARKERS = ("ComboBox",)
_CODE_SUFFIX = re.compile(r"\((\d+)\)\s*$")     # '김치암(4189)' 의 코드 접미
_KEY_SPECIALS = set("+^%~(){}")


def _combo_norm(text: str) -> str:
    return _norm(_CODE_SUFFIX.sub("", text or ""))


def _keys(text: str) -> str:
    """send_keys 특수문자(+ ^ % ~ ( ) { })를 {..}로 감싼다 — '상가(중/소형)' 같은 값 보호."""
    return "".join("{" + c + "}" if c in _KEY_SPECIALS else c for c in text)


def load_combo_lists(path) -> dict[str, list[str]]:
    """recon/combo_*.md 의 '## 라벨' 섹션별 '- 항목' 을 **순서대로** 읽는다(콤보 훑기 거리 계산용)."""
    lists: dict[str, list[str]] = {}
    current = None
    for line in open(path, encoding="utf-8"):
        if line.startswith("## "):
            current = line[3:].split("  (")[0].strip()   # '## 용도지역구분(신)  (TcxDBLookupComboBox, …)'
            lists[current] = []
        elif current and line.startswith("- "):
            lists[current].append(line[2:].strip())
    return lists


def _index_in(items: list[str], text: str) -> int | None:
    want = _combo_norm(text)
    for k, item in enumerate(items):
        if _combo_norm(item) == want:
            return k
    return None


def _confirm(inner, want: str, value: str) -> str:
    send_keys("{ENTER}")
    time.sleep(0.3)
    send_keys("{TAB}")
    time.sleep(0.25)
    final = driver.read(inner)
    if _combo_norm(final) != want:
        raise driver.ValueRejected(f"콤보 확정 후 불일치: {value!r} / {final!r}")
    return final


def select_combo(control, value: str, items: list[str] | None = None, *, max_steps: int = 40) -> str:
    """룩업콤보에 값을 고른다.

    ① 안쪽 에디트에 타이핑(접두 검색)→되읽기. 정확히 맞으면 Enter+Tab 확정.
    ② 다른 항목이 잡히면(접두 겹침: '공장'→'공장용지', '농림지역'→'농림지역미분류'):
       - 목록(items, recon 순서)을 알면 현재 항목→목표 항목 거리만큼 F4 열고 ↓/↑ 후 Enter.
       - 모르면 F4+↓+Enter 로 한 칸씩 최대 max_steps 훑는다(닫힌 상태 ↓는 안 움직임 — 실측).
    ③ 못 찾으면 원래 값으로 되돌리고 ValueRejected(②의 훑기는 항목마다 Enter 로 확정되므로 Esc 만으론 안 돌아옴 —
       2754 실측 '마지막 읽힘 자연환경'. 거부 칸은 비운 채 저장하는 정책(2026-09-03)이라 엉뚱한 항목이 남으면 안 된다)."""
    inner = driver.editable(control)
    original = driver.read(inner)
    if items and _index_in(items, value) is None:
        # 목록에 없는 값은 **타이핑 전에** 거른다 — 접두 검색이 엉뚱한 항목을 골라 놓는다
        # (2776 실측 2026-09-07: '기계기구' 를 치자 '기' 접두로 '기타' 가 잡혔고, ESC 로는 안 돌아와 '기타' 로 저장됨).
        raise driver.ValueRejected(f"콤보 목록에 없는 값: {value!r} (원래 {original!r} 유지)")
    inner.set_focus()
    time.sleep(0.2)
    send_keys("^a{BACKSPACE}")
    time.sleep(0.15)
    send_keys(_keys(value), with_spaces=True, pause=0.04)
    time.sleep(0.45)
    want = _combo_norm(value)
    got = driver.read(inner)
    if _combo_norm(got) == want:
        return _confirm(inner, want, value)

    if items:
        target = _index_in(items, value)
        here = _index_in(items, got)
        if target is None:                       # (위에서 걸러지므로 목록이 낡아 못 찾은 경우) — 되돌리고 거부
            send_keys("{ESC}")
            time.sleep(0.2)
            now = _restore_combo(inner, original)
            raise driver.ValueRejected(f"콤보 목록에 없는 값: {value!r} (되돌림 {now!r}, 원래 {original!r})")
        if here is not None:
            delta = target - here
            key = "{DOWN}" if delta > 0 else "{UP}"
            inner.set_focus()
            send_keys("{F4}")
            time.sleep(0.35)
            for _ in range(abs(delta)):
                send_keys(key)
                time.sleep(0.05)
            send_keys("{ENTER}")
            time.sleep(0.35)
            got = driver.read(inner)
            if _combo_norm(got) == want:
                return _confirm(inner, want, value)

    last = got
    for _ in range(max_steps):
        inner.set_focus()
        send_keys("{F4}")
        time.sleep(0.3)
        send_keys("{DOWN}{ENTER}")
        time.sleep(0.3)
        got = driver.read(inner)
        if _combo_norm(got) == want:
            return _confirm(inner, want, value)
        if got == last:            # 끝까지 갔다
            break
        last = got
    send_keys("{ESC}")
    time.sleep(0.2)
    now = _restore_combo(inner, original)
    raise driver.ValueRejected(f"콤보 항목 없음: {value!r} (되돌림 {now!r}, 원래 {original!r})")


def _restore_combo(inner, original: str) -> str:
    """거부된 콤보를 원래 값으로 되돌린다(최선). 원래 빈값이면 비운다. 되돌린 뒤 실제 읽힌 값을 돌려준다."""
    try:
        inner.set_focus()
        time.sleep(0.15)
        send_keys("^a{BACKSPACE}")
        time.sleep(0.15)
        if original:
            send_keys(_keys(original), with_spaces=True, pause=0.04)
            time.sleep(0.45)
            send_keys("{ENTER}")
            time.sleep(0.3)
        send_keys("{TAB}")
        time.sleep(0.25)
    except Exception:  # noqa: BLE001
        pass
    return driver.read(inner)


@dataclass(frozen=True)
class FillResult:
    label: str
    action: str          # 채움 | 덮어씀 | 선택 | 선택(덮어씀) | 일치 | 수동(선택형) | 미발견 | 빈값 | 거부
    ours: str
    current: str
    wrote: bool = False


def _norm(text: str) -> str:
    """비교용 정규화: 천단위 콤마 제거, 숫자는 0패딩·소수 끝 0 무시(0356==356, 4227.40==4227.4)."""
    t = re.sub(r"\s+", "", (text or "").replace(",", "")).strip()   # 공백 무시(은행 '김포시  감정동', '프리케스트 콘크리트구조')
    if t and t.replace(".", "", 1).isdigit():
        if "." in t:
            t = t.rstrip("0").rstrip(".")
        t = t.lstrip("0") or "0"
    return t


def is_blank(value) -> bool:
    """None/''/공백, 그리고 숫자 0(0, 0.00, '0')은 '값 없음'으로 본다 — 빈 골격 .gam이
    총감정가액=0 을 채우려던 사고(2026-08-25) 방지. 0을 실제로 넣어야 하는 칸은 없다."""
    if value is None:
        return True
    text = str(value).replace(",", "").strip()
    if not text:
        return True
    try:
        return float(text) == 0.0
    except ValueError:
        return False


# 0 을 실제로 넣어야 하는 칸(0가드 예외). 평가단가는 건물 물건에 0 을 넣는다(업무팀 확정 2026-08-26).
ZERO_ALLOWED = frozenset({"평가단가"})
ZERO_ALLOWED_FULL = frozenset({"세부:감정평가액", "탭:감정평가액", "특별용역비", "탭:내용년수", "탭:잔존년수"})   # 기업 구분건물 건물 탭 0(2026-09-07)   # 국민 세부·기업 탭 토지행: 도로 등 감정평가외 필지 = 단가 1·금액 0


# ── 라벨 사이 위치 표기(농협 이식 2026-09-07): `소재지@물건기호~번지구분[5]` = 두 라벨 사이 6번째 입력칸.
# 좌표 상대표기(POSITIONAL dict)와 별개로, 라벨이 아예 없거나 여러 칸이 한 라벨을 나눠 쓰는 자리를 짚는다.

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
# `위좌`/`위우` = 밴드 **최상단 행**(top 이 가장 작은 행)의 왼쪽/오른쪽 칸. 숫자 인덱스는 폼변형마다
# 밴드 구성이 달라지면 어긋나지만, '최상단 행의 좌/우' 는 그 성질이 변형과 무관하게 유지된다
# (수협 법정동코드 시군구/읍면동 2칸 — 인계본 감사 P0-2, 이식 2026-09-10).
TOP_EDGES = ("위좌", "위우")
BAND_SPEC = re.compile(
    r"^(?P<name>[^@]+)@(?P<above>[^~]+)~(?P<below>[^\[]+)\[(?P<index>\d+|왼쪽|오른쪽|위좌|위우)\]$")


def display_label(label: str) -> str:
    """보고서에 쓸 이름 — 위치 표기는 앞부분만 보여 준다."""
    spec = BAND_SPEC.match(str(label))
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
    `위좌`/`위우` 는 밴드 **최상단 행**(top 최소, ±3px 동일행)의 왼쪽/오른쪽 칸 — 그 행에
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
    spec = BAND_SPEC.match(str(label))
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
    """그 칸의 현재 화면값(못 짚으면 빈 문자열) — 위치 표기 칸을 대조 도구가 직접 읽을 때 쓴다."""
    control = resolve_control(form, label)
    return driver.read(driver.editable(control)) if control is not None else ""


def plan_field(form, label: str, value) -> tuple[str, str, object]:
    """한 필드의 (action, current, control) 계산 — 아직 화면에 쓰지 않는다."""
    zero_ok = ((split_label(label)[1] in ZERO_ALLOWED or label in ZERO_ALLOWED_FULL)
               and value is not None and str(value).strip() != "")
    if is_blank(value) and not zero_ok:
        return "빈값", "", None
    # '라벨@N' = 같은 줄 오른쪽 N번째 컨트롤(1부터). 예: 평가사명1@2 → 오른쪽 이름 콤보.
    # '구역:라벨' = REGIONS 로 패널을 가른다(국민). POSITIONAL 은 원문 키('세부:법정동코드') 우선, 라벨명 폴백.
    band = BAND_SPEC.match(str(label))
    if band:                                   # 라벨 사이 위치 표기(농협)
        control = resolve_control(form, label)
    else:
        key, name, index, region = split_label(label)
        spec = POSITIONAL.get(key) or (POSITIONAL.get(name) if region is None else None)
        if spec:
            anchor, dx, dy, cls = spec
            control = driver.find_by_offset(form.handle, anchor, dx, dy, cls, region=region)
        else:
            control = driver.find_by_label(form.handle, name, index=index, region=region)
    if control is None:
        return "미발견", "", None
    try:
        cls = control.element_info.class_name or ""
    except Exception:
        cls = ""
    current = driver.read(driver.editable(control))
    if any(marker in cls for marker in COMBO_MARKERS):
        if _combo_norm(current) == _combo_norm(str(value)):
            return "일치", current, control
        return ("선택(덮어씀)" if current else "선택"), current, control
    if any(marker in cls for marker in SELECT_MARKERS):
        return "수동(선택형)", current, control
    if _norm(current) == _norm(str(value)):
        return "일치", current, control
    # 은행 폼이 숫자칸에 미리 넣어 두는 '0'/'0.00'(국민 수수료·면적·감정평가액 등)은 '값 없음' — 사람이 넣은 값이
    # 아니므로 '채움'으로 본다. 종전엔 '덮어씀'으로 분류돼 기본(빈칸만) 모드에서 미기록됐다(2703·2715 LIVE, 2026-08-31).
    return ("채움" if is_blank(current) else "덮어씀"), current, control


def clear_fields(form, refs: dict[str, str | None], *, live: bool = False) -> list[FillResult]:
    """은행이 선입력한 값을 **지운다** — refs = {라벨: 기준문자열}.

    현재값이 비어 있으면 '일치'. 기준문자열이 있고 현재값이 그 안에 들어 있지 않으면(사람이 넣은 실제 값으로 봄)
    '유지' — 손대지 않는다. 그 밖(기준문자열의 조각, 예: 건물명 '두산더랜드파크' 가 잘린 '두산더랜드파')이면 '지움'.
    fill() 은 None 값을 '빈값'으로 건너뛰므로 지우기는 이 함수로만 한다(2715 동 칸, 2026-08-31).
    """
    results: list[FillResult] = []
    for label, ref in refs.items():
        action, current, control = plan_field(form, label, "?")
        if action == "미발견":
            results.append(FillResult(str(label), "미발견", "", "", False))
            continue
        cur = (current or "").strip()
        if not cur:
            results.append(FillResult(str(label), "일치", "", current, False))
            continue
        if ref is not None and _norm(cur) not in _norm(str(ref)):
            results.append(FillResult(str(label), "유지", "", current, False))
            continue
        wrote = False
        action = "지움"
        if live and control is not None:
            try:
                driver.set_text(control, "")
                wrote = True
            except driver.ValueRejected as exc:
                action = f"거부({str(exc)[:70]})"
        results.append(FillResult(str(label), action, "", current, wrote))
    return results


def fill(form, values: dict, *, live: bool = False, overwrite: bool = False,
         combo_lists: dict[str, list[str]] | None = None,
         force_labels: set[str] | frozenset[str] | None = None) -> list[FillResult]:
    """매핑값을 폼에 채운다(기본 드라이런).

    live=True 면 텍스트/숫자/날짜칸을 실제 입력한다. **기본은 빈칸만 채운다**(안전) —
    사람이 이미 넣은 값은 건드리지 않는다(잡음 필드 오염 방지). overwrite=True 여야 덮어쓴다.
    force_labels 에 든 라벨은 overwrite 와 무관하게 항상 덮어쓴다 — 은행 폼이 미리 넣어두는
    기본값(물건특성 '아니오'/'해당없음', 의뢰 소재지)을 문서 값으로 바꿔야 하는 칸(2026-08-26 업무팀 대조).
    """
    forced = set(force_labels or ())
    results: list[FillResult] = []
    for label, value in values.items():
        action, current, control = plan_field(form, label, value)
        wrote = False
        may_overwrite = overwrite or str(label) in forced
        writable = action in ("채움", "선택") or (action in ("덮어씀", "선택(덮어씀)") and may_overwrite)
        if live and writable and control is not None:
            try:
                if action.startswith("선택"):
                    name = display_label(label) if BAND_SPEC.match(str(label)) else split_label(label)[1]
                    select_combo(control, str(value), (combo_lists or {}).get(name))   # 되읽기 검증 포함
                else:
                    driver.set_text(control, str(value))   # 되읽기 검증 포함
                wrote = True
            except driver.ValueRejected as exc:
                action = f"거부({str(exc)[:70]})"
        results.append(FillResult(str(label), action, "" if action == "빈값" else str(value),
                                  current, wrote))
    return results
