"""BANK24 화면 이동 — 실행 → 로그인 → 검색 → 작성 폼 열기.

실물 확인한 흐름:
    KadcLoader.exe Bank24 -e
      → TDXLoginDialog (라벨 없는 TEdit 2개: 위=아이디, 아래=비밀번호) → '확인'
      → TfrmMain [금융기관온라인 메인]  (MDI, 조회 화면 TBnkTop24Main)
      → 감정서조회 칸에 문서번호 → **'찾 기'**(조회가 아니다) → 그리드 1건으로 좁혀짐
      → 그리드 첫 행 좌클릭 → 우클릭 → 컨텍스트 메뉴(#32768) → '작 성(열람)' = 가속키 A
      → TBNK*B24DAMB (은행별 담보 입력 폼)

주의:
  - `조 회` 는 기간·업무구분 목록 조회고, 문서번호로 좁히는 건 `찾 기` 다.
  - 편집칸은 껍데기(TcxTextEdit)가 아니라 안쪽(TcxCustomInnerTextEdit)에 써야 한다.
  - 컨텍스트 메뉴는 표준 팝업(#32768)이라 컨트롤로 못 읽는다 → **가속키**로 고른다.
"""
from __future__ import annotations

import time
from pathlib import Path
from dataclasses import dataclass
from datetime import date

import pyperclip
from pywinauto.findwindows import find_elements
from pywinauto.keyboard import send_keys

from . import driver

SEARCH_LABEL = "감정서조회"
FIND_BUTTON = "찾 기"
QUERY_BUTTON = "조 회"
CONTEXT_MENU_CLASS = "#32768"

# 컨텍스트 메뉴 '작 성(열람)(A)' 의 가속키. 메뉴가 바뀌면 여기만 고친다.
WRITE_ACCELERATOR = "a"

# 그리드 첫 데이터 행을 찍을 상대 좌표(머리행 아래). 열 폭과 무관하게 안전한 지점.
FIRST_ROW_OFFSET = (200, 30)


class NavigationError(RuntimeError):
    """화면 이동이 예상대로 되지 않았다."""


@dataclass(frozen=True)
class Session:
    main: driver.WindowRef

    @property
    def pid(self) -> int:
        return self.main.pid


def open_app(loader_cmd: str, user: str, password: str, *, timeout: float = 90.0) -> Session:
    """실행 → 로그인 → 메인 창까지."""
    already = driver.find_windows(driver.MAIN_CLASS, title_any=driver.MAIN_TITLE_HINTS)
    if already:
        driver.bring_to_front(already[0].handle)
        return Session(already[0])

    driver.launch(loader_cmd, timeout=timeout)
    login = driver.wait_for_window(driver.LOGIN_CLASS, timeout=timeout)
    edits = driver.by_class(login.handle, "TEdit")
    if len(edits) < 2:
        raise NavigationError(f"로그인 입력칸을 찾지 못했습니다(TEdit {len(edits)}개).")

    # 라벨이 없어 위/아래 순서로 구분한다(by_class 가 화면 순서로 정렬해 준다).
    driver.set_text(edits[0], user)
    driver.set_text(edits[1], password, verify=False)  # 비밀번호는 되읽어도 마스킹된다

    confirm = driver.by_text(login.handle, "확인", "TButton")
    if confirm is None:
        raise NavigationError("로그인 '확인' 버튼을 찾지 못했습니다.")
    driver.click(confirm)

    main = driver.wait_for_window(
        driver.MAIN_CLASS, timeout=timeout, title_any=driver.MAIN_TITLE_HINTS)
    # 로그인 직후 메인 창이 GUI/콘솔 뒤로 숨는다(2026-08-27 실측) → 확실히 앞으로.
    time.sleep(1.0)
    driver.bring_to_front(main.handle)
    return Session(main)


# 상단 toolbar(TdxBarControl) 기준 탭 상대좌표 — Y_BankAuto 실측값 재사용.
# 작성 폼은 **작성 탭**에서만 열린다. 정찰/다른 작업이 미접수 탭으로 남겨둘 수 있어
# 문서를 열기 전에 명시적으로 골라야 한다(실측: 미접수 탭에선 '찾 기'가 0건).
TAB_COORDS = {"작성": (205, 29), "미접수": (147, 29), "발송완료": (329, 29)}   # 발송완료: 정찰 스크린샷 실측(2026-08-25)
TAB_ROW_MARKERS = {"작성": "접수완료", "발송완료": "발송완료"}   # 탭별 행 상태값(검증용, 실측 2026-08-26)


def select_tab(session: Session, tab: str = "작성") -> bool:
    """상단 toolbar에서 대상 탭을 클릭한다. 실패해도 예외 대신 False(진행은 가능)."""
    coords = TAB_COORDS.get(tab)
    if coords is None:
        return False
    win = driver.window(session.main.handle)
    bars = []
    for control in win.descendants():
        try:
            if control.element_info.class_name == "TdxBarControl":
                bars.append(control)
        except Exception:
            continue
    toolbar = next(
        (b for b in bars if (b.window_text() or "").strip() == "toolbar"), None)
    if toolbar is None and bars:
        toolbar = min(bars, key=lambda b: (b.rectangle().top, b.rectangle().left))
    if toolbar is None:
        return False
    # 다른 창(관리자 콘솔 등)이 덮고 있으면 좌표 클릭이 그 창에 떨어진다(2026-08-26 실측) → 먼저 앞으로.
    # 클릭이 안 먹는 경우가 간헐적으로 있어(통합 러너 2회 실측) 행 상태값으로 검증하고 재클릭한다.
    marker = TAB_ROW_MARKERS.get(tab)
    for attempt in range(3):
        try:
            driver.bring_to_front(session.main.handle)
            win.set_focus()
            time.sleep(0.4)
        except Exception:
            pass
        toolbar.click_input(coords=coords)
        time.sleep(1.2)
        if marker is None:
            return True
        try:
            text = focused_row_text(session)
        except Exception:
            text = ""
        if not text.strip() or marker in text:
            return True          # 행이 없으면 검증 불가 → 통과
        time.sleep(0.8)
    return False


def find_document(session: Session, doc_id: str, *, settle: float = 2.5) -> None:
    """감정서번호로 목록을 1건으로 좁힌다.

    `조 회` 가 아니라 `찾 기` 다 — `조 회` 는 기간 조회라 목록이 그대로 남는다.
    """
    edit = driver.find_by_label(session.main.handle, SEARCH_LABEL, "TcxTextEdit")
    if edit is None:
        raise NavigationError(f"'{SEARCH_LABEL}' 입력칸을 찾지 못했습니다.")
    driver.set_text(edit, doc_id)
    # DevExpress 검색칸은 set_edit_text 만으론 값 커밋/검색이벤트가 안 걸릴 수 있다.
    # 포커스된 칸에 Enter 를 보내 값을 확정(대개 이때 필터가 실행된다).
    send_keys("{ENTER}")
    time.sleep(0.4)

    button = driver.by_text(session.main.handle, FIND_BUTTON, "TcxButton")
    if button is None:
        raise NavigationError(f"'{FIND_BUTTON}' 버튼을 찾지 못했습니다.")
    driver.click(button)
    time.sleep(settle)


def _grid(session: Session):
    grids = driver.by_class(session.main.handle, "TcxGridSite")
    if not grids:
        raise NavigationError("결과 그리드를 찾지 못했습니다.")
    # 그리드가 여러 개면(검색결과 그리드 + 다른 그리드) 화면에서 가장 큰 것을 결과로 본다.
    def area(g):
        r = g.rectangle()
        return max(0, r.right - r.left) * max(0, r.bottom - r.top)
    return max(grids, key=area)


def open_forms(session: Session) -> tuple[driver.WindowRef, ...]:
    """이 BANK24 프로세스의 담보 폼만 돌려준다.

    pid 로 한정하지 않으면 다른 프로그램의 창(예: 다른 업무 앱의 '발송' 창)을
    우리 폼으로 오인할 수 있다 — 실제로 겪어서 막았다.
    """
    return driver.find_windows(driver.FORM_CLASS_PREFIX, pid=session.pid)


# 닫기 확인창("저장하시겠습니까?" 류)에서 누를 버튼 — 저장 안 함이 원칙.
DECLINE_TEXTS = ("아니오", "아니요", "No", "&No", "취소", "Cancel")
DIALOG_CLASSES = ("#32770", "TMessageForm", "TForm", "TdxMessageForm")


def _confirm_dialogs(session: Session) -> tuple[driver.WindowRef, ...]:
    """이 프로세스의 작은 확인창(담보 폼·메인 제외)."""
    return tuple(
        w for w in driver.find_windows(pid=session.pid)
        if w.class_name in DIALOG_CLASSES and w.handle != session.main.handle
    )


def decline_save_prompt(session: Session, *, wait: float = 3.0) -> str | None:
    """닫기 직후 뜨는 확인창이 있으면 '아니오'(저장 안 함)를 누른다. 누른 버튼 텍스트를 돌려준다.

    행 추가·값 입력 후 닫으면 저장 여부를 물을 수 있다(2단계 전 대비). 예/저장 쪽은 절대 안 누른다.
    """
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        for dialog in _confirm_dialogs(session):
            for text in DECLINE_TEXTS:
                button = driver.by_text(dialog.handle, text) or driver.by_text(dialog.handle, text, "TButton")
                if button is not None:
                    driver.click_message(button)
                    time.sleep(0.5)
                    return text
            # 버튼 텍스트를 못 읽는 창이면 위험하니 아무것도 안 누르고 남겨둔다(사람이 확인).
            return None
        time.sleep(driver.POLL_INTERVAL)
    return None


def close_forms(session: Session, *, timeout: float = 20.0) -> tuple[driver.WindowRef, ...]:
    """열려 있는 담보 폼을 모두 닫는다(다음 문서를 열기 전 정리). 저장 확인창은 '아니오'.

    **닫지 못한 폼을 돌려준다**(빈 튜플 = 전부 닫힘). 종전엔 조용히 넘어가서, 남은 폼을
    다음 문서가 자기 폼으로 읽는 사고가 났다(2026-09-15 오제외 3건 — open_write_form 주석 참조).
    """
    for form in open_forms(session):
        button = driver.by_text(form.handle, "닫 기", "TcxButton")
        if button is None:
            print(f"★닫기 버튼('닫 기')을 못 찾았습니다: {form.class_name} — 폼이 남습니다")
            continue
        driver.click(button)
        pressed = decline_save_prompt(session, wait=2.5)
        if pressed:
            print(f"닫기 확인창: '{pressed}' 선택(저장 안 함)")
        deadline = time.monotonic() + timeout
        reclick_at = time.monotonic() + 5.0
        while time.monotonic() < deadline and any(
            w.handle == form.handle for w in driver.find_windows(form.class_name, pid=session.pid)
        ):
            if decline_save_prompt(session, wait=0.2):
                print("닫기 확인창: 저장 안 함")
            if time.monotonic() >= reclick_at:      # 폼이 바빠 첫 클릭이 씹힌 경우(큰 PDF 뒤) 다시 누른다
                button = driver.by_text(form.handle, "닫 기", "TcxButton")
                if button is not None:
                    driver.click(button)
                    print("닫기 재클릭")
                reclick_at = time.monotonic() + 5.0
            time.sleep(driver.POLL_INTERVAL)
    remaining = open_forms(session)
    if remaining:
        print("★닫히지 않은 폼 " + ", ".join(f"{w.class_name}({w.handle})" for w in remaining))
    return remaining


# ── 작성 폼 왼쪽 '순번' 그리드(물건 목록) ─────────────────────────────────────
# Shift+F10 팝업(정찰 2026-08-25): 추가(마지막위치)(U) 추가(현재위치)(V) 추가(현재위치 복사)(W)
# 추가(마지막위치 복사)(X) 삭제(마지막위치)(Y) 삭제(현재위치)(Z)
OBJECT_MENU = {"append": "u", "insert": "v", "copy_here": "w", "copy_append": "x"}


def _object_grid(form: driver.WindowRef):
    grids = driver.by_class(form.handle, "TcxGridSite")
    if not grids:
        raise NavigationError("물건(순번) 그리드를 찾지 못했습니다.")
    return min(grids, key=lambda g: g.rectangle().left)    # 폼 왼쪽 세로 그리드


def current_object_seq(form: driver.WindowRef) -> int | None:
    """폼의 '물건순번' 칸(현재 선택된 물건의 순번)."""
    edit = driver.find_by_label(form.handle, "물건순번")
    if edit is None:
        return None
    text = driver.read(driver.editable(edit)).strip()
    return int(text) if text.isdigit() else None


def count_object_rows(form: driver.WindowRef) -> int:
    """순번 그리드 행 수 = Ctrl+End 후 물건순번. (포커스는 마지막 행에 남는다)"""
    grid = _object_grid(form)
    grid.set_focus()
    time.sleep(0.3)
    send_keys("^{END}")
    time.sleep(0.4)
    return current_object_seq(form) or 0


def select_object_row(form: driver.WindowRef, index: int) -> int:
    """순번 그리드에서 index(0부터)번째 행을 고르고 물건순번으로 확인한다(fail-closed)."""
    grid = _object_grid(form)
    grid.set_focus()
    time.sleep(0.3)
    send_keys("^{HOME}")
    time.sleep(0.3)
    for _ in range(index):
        send_keys("{DOWN}")
        time.sleep(0.15)
    time.sleep(0.3)
    seq = current_object_seq(form)
    if seq != index + 1:
        raise NavigationError(f"물건 {index + 1}행 선택 실패(화면 물건순번={seq}).")
    return seq


def add_object_row(form: driver.WindowRef, mode: str = "append", *, timeout: float = 5.0) -> int:
    """순번 그리드 팝업으로 물건 행을 추가한다. 추가 뒤 행 수를 돌려준다(폼 상태만 바뀜, 저장 아님)."""
    key = OBJECT_MENU[mode]
    grid = _object_grid(form)
    before_count = count_object_rows(form)
    grid.set_focus()
    time.sleep(0.3)
    before = _menu_handles()
    send_keys("+{F10}")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not (_menu_handles() - before):
        time.sleep(driver.POLL_INTERVAL)
    if not (_menu_handles() - before):
        raise NavigationError("물건 그리드 팝업 메뉴가 열리지 않았습니다.")
    send_keys(key)
    time.sleep(0.8)
    after_count = count_object_rows(form)
    if after_count != before_count + 1:
        raise NavigationError(f"물건 행 추가 실패(전 {before_count} → 후 {after_count}).")
    return after_count


def ensure_object_rows(form: driver.WindowRef, needed: int, *, mode: str = "append") -> int:
    """화면 행 수가 needed 보다 적으면 부족한 만큼 추가한다. 최종 행 수를 돌려준다."""
    count = count_object_rows(form)
    while count < needed:
        count = add_object_row(form, mode)
    return count


def _menu_handles() -> set[int]:
    return {
        int(e.handle) for e in find_elements(backend=driver.BACKEND)
        if (e.class_name or "") == CONTEXT_MENU_CLASS and e.handle
    }


def walk_rows(session: Session, *, max_rows: int = 400):
    """그리드 첫 행부터 Down 키로 내려가며 행 텍스트(Ctrl+C)를 차례로 낸다.

    정찰 때 Ctrl+A 복사가 포커스 행 1건만 돌려줬으므로, 행 단위로 읽는 것이
    유일하게 확인된 열거 방법이다. 마지막 행에서 더 못 내려가면(같은 텍스트 반복) 끝.
    읽기 전용 — 셀 값은 건드리지 않는다.
    """
    grid = _grid(session)
    grid.set_focus()
    time.sleep(0.4)
    send_keys("^{HOME}")
    time.sleep(0.3)
    prev = None
    same = 0
    row_no = 0
    for _ in range(max_rows * 2):
        pyperclip.copy("")
        send_keys("^c")
        time.sleep(0.25)
        text = pyperclip.paste() or ""
        if not text:                      # 클립보드 미갱신 — 한 번 더
            time.sleep(0.3)
            send_keys("^c")
            time.sleep(0.3)
            text = pyperclip.paste() or ""
        if text and text == prev and row_no > 0:
            same += 1
            if same >= 3:                 # 3회 연속 같으면 마지막 행(더 못 내려감)
                return
            time.sleep(0.3)               # 갱신 지연일 수 있어 다시 읽는다
            continue
        same = 0
        yield row_no, text
        row_no += 1
        if row_no >= max_rows:
            return
        prev = text
        send_keys("{DOWN}")
        time.sleep(0.12)


def list_rows(session: Session, *, max_rows: int = 400) -> list[str]:
    """조회 목록의 행 텍스트를 모두 모은다(포커스는 마지막 행에 남는다)."""
    return [text for _, text in walk_rows(session, max_rows=max_rows)]


def find_row_by_doc(session: Session, doc_id: str, *, max_rows: int = 400) -> bool:
    """목록을 행 단위로 훑어 감정서번호가 있는 행에 포커스를 둔다.

    '찾 기'는 전 기간 검색이라 오래 돈다(실측: 수 분). 조회기간을 좁혀 '조 회' 한
    목록에서 행별 Ctrl+C(클립보드)로 대조하는 편이 빠르고 확실하다(Y_BankAuto 방식).
    """
    for _, text in walk_rows(session, max_rows=max_rows):
        if doc_id in text:
            return True
    return False


def focus_row(session: Session, index: int, *, max_rows: int = 400) -> str:
    """조회 목록의 index(0부터)번째 행에 포커스를 두고 그 행 텍스트를 돌려준다."""
    if index < 0:
        raise NavigationError("행 번호는 1 이상이어야 합니다.")
    for i, text in walk_rows(session, max_rows=max_rows):
        if i == index:
            return text
    raise NavigationError(f"목록에 {index + 1}번째 행이 없습니다.")


def open_write_form(
    session: Session, *, timeout: float = 60.0, home: bool = True
) -> driver.WindowRef:
    """그리드 행을 골라 컨텍스트메뉴 → '작 성(열람)' → 은행별 담보 폼을 연다.

    마우스 좌표 클릭(click_input)은 권한·좌표에 취약해서(다중 그리드, SetCursorPos)
    **키보드**로 한다: 그리드 포커스 → Ctrl+Home(첫 행) → Shift+F10(컨텍스트메뉴)
    → 가속키 'a'(작성/열람). `home=False` 면 지금 포커스된 행을 그대로 쓴다
    (find_row_by_doc 로 찾아둔 행).

    ★앞 문서의 폼이 남아 있으면 먼저 닫고, 못 닫으면 **열지 않고 실패**한다(fail-closed).
    종전엔 `wait_for_window(TBNK*)` 가 남은 창을 그대로 돌려줘서 그 값을 자기 폼 값으로 읽었다
    (실증 2026-09-15: 우리 2869 제외 뒤 남은 우리 폼을 국민 2867·기업 2873·2836 이 읽어
     '사람 작성'으로 오제외 — 세 건 다 2869 의 감정수수료 27,811,300 을 봤다).
    그래서 여는 것도 **새로 생긴 창만** 채택한다(open_survey_form 과 같은 방식).
    """
    stale = open_forms(session)
    if stale:
        print("[navigate] 앞 문서 폼이 남아 있음 — 먼저 닫는다: "
              + ", ".join(w.class_name for w in stale))
        stale = close_forms(session)
        if stale:
            raise NavigationError(
                "앞 문서의 작성 폼이 닫히지 않았습니다("
                + ", ".join(f"{w.class_name}:{w.handle}" for w in stale)
                + ") — 그 폼을 읽으면 다른 건의 값을 자기 값으로 오인하므로 열지 않습니다.")

    opened = {w.handle for w in open_forms(session)}
    grid = _grid(session)
    grid.set_focus()
    time.sleep(0.4)
    if home:
        send_keys("^{HOME}")       # 첫(=유일) 행 선택
        time.sleep(0.4)

    before = _menu_handles()
    send_keys("+{F10}")            # Shift+F10 = 우클릭 컨텍스트 메뉴
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not (_menu_handles() - before):
        time.sleep(driver.POLL_INTERVAL)
    if not (_menu_handles() - before):
        raise NavigationError("컨텍스트 메뉴가 열리지 않았습니다.")

    # 표준 팝업 메뉴는 컨트롤로 못 읽으므로 가속키로 항목을 고른다.
    send_keys(WRITE_ACCELERATOR)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for form in open_forms(session):
            if form.handle not in opened:
                return form
        time.sleep(driver.POLL_INTERVAL)
    close_context_menu()
    raise NavigationError(f"작성 폼이 {timeout:.0f}초 안에 열리지 않았습니다.")


SURVEY_ACCELERATOR = "e"          # 컨텍스트 메뉴 '현장조사서 작성(E)'
SURVEY_CLASS_SUFFIX = "Hyun"      # TBNKSHG24Hyun(신한 담보 현장조사서, 정찰 2026-08-25)


def open_survey_form(session: Session, *, timeout: float = 30.0) -> driver.WindowRef:
    """포커스된 행에서 Shift+F10 → 'e' 로 현장조사서 폼을 연다(작성 폼과 같은 패턴)."""
    grid = _grid(session)
    grid.set_focus()
    time.sleep(0.4)
    before = {w.handle for w in driver.find_windows(pid=session.pid)}
    menus = _menu_handles()
    send_keys("+{F10}")
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not (_menu_handles() - menus):
        time.sleep(driver.POLL_INTERVAL)
    if not (_menu_handles() - menus):
        raise NavigationError("컨텍스트 메뉴가 열리지 않았습니다.")
    send_keys(SURVEY_ACCELERATOR)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for w in driver.find_windows(pid=session.pid):
            if w.handle not in before and w.class_name.endswith(SURVEY_CLASS_SUFFIX):
                return w
        time.sleep(driver.POLL_INTERVAL)
    close_context_menu()
    raise NavigationError("현장조사서 폼이 열리지 않았습니다.")


def survey_forms(session: Session) -> tuple[driver.WindowRef, ...]:
    return tuple(w for w in driver.find_windows(pid=session.pid)
                 if w.class_name.endswith(SURVEY_CLASS_SUFFIX))


def close_survey_forms(session: Session, *, timeout: float = 15.0) -> None:
    """현장조사서 폼을 '닫 기'로 닫는다(저장 확인창은 '아니오')."""
    for form in survey_forms(session):
        button = driver.by_text(form.handle, "닫 기", "TcxButton")
        if button is None:
            continue
        driver.click(button)
        if decline_save_prompt(session, wait=2.5):
            print("닫기 확인창: 저장 안 함")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and any(w.handle == form.handle for w in survey_forms(session)):
            if decline_save_prompt(session, wait=0.2):
                print("닫기 확인창: 저장 안 함")
            time.sleep(driver.POLL_INTERVAL)


# ── 포커스 행 확인(재순회는 필요할 때만 — 사용자 규칙 2026-08-25) ─────────────────
def focused_row_text(session: Session) -> str:
    """지금 포커스된 목록 행의 Ctrl+C 텍스트(행 이동 없음)."""
    grid = _grid(session)
    grid.set_focus()
    time.sleep(0.3)
    pyperclip.copy("")
    send_keys("^c")
    time.sleep(0.3)
    return pyperclip.paste() or ""


def focused_row_has(session: Session, doc_id: str) -> bool:
    return doc_id in focused_row_text(session)


def ensure_row(session: Session, doc_id: str, *, requery=None, attempts: int = 3) -> str:
    """포커스 행이 대상이면 그대로('focused'), 아니면 재순회('walked'), 그래도 없으면 requery()
    후 재순회. 어떤 경로였는지 문자열로 돌려준다."""
    if focused_row_has(session, doc_id):
        return "focused"
    for attempt in range(attempts):
        if attempt and requery is not None:
            requery()
        if find_row_by_doc(session, doc_id):
            return "walked" if attempt == 0 else f"requeried+walked({attempt + 1})"
    raise NavigationError(f"{doc_id} 행을 목록에서 찾지 못했습니다.")


# ── 저장(실서버 쓰기) — 저장 흐름에서만 쓴다 ─────────────────────────────────────
ACCEPT_TEXTS = ("예", "Yes", "&Yes", "확인", "OK", "&OK")
from .. import paths as _paths  # noqa: E402
_REPORTS = _paths.REPORTS_DIR


def _shot_window(handle: int, tag: str) -> str | None:
    """창 영역 스크린샷(다중 모니터 보정). TaskDialog 본문은 win32로 못 읽어 그림으로 남긴다."""
    try:
        import ctypes
        from PIL import ImageGrab
        import win32gui
        left, top, right, bottom = win32gui.GetWindowRect(handle)
        vx = ctypes.windll.user32.GetSystemMetrics(76)
        vy = ctypes.windll.user32.GetSystemMetrics(77)
        image = ImageGrab.grab(all_screens=True).crop((left - vx, top - vy, right - vx, bottom - vy))
        _REPORTS.mkdir(exist_ok=True)
        path = _REPORTS / f"prompt_{tag}_{time.strftime('%H%M%S')}.png"
        image.save(str(path))
        return path.name
    except Exception as error:  # noqa: BLE001
        return f"(스냅 실패 {error!r})"


def accept_prompt(session: Session, *, wait: float = 3.0, tag: str = "save") -> tuple[str, str | None] | None:
    """확인창이 뜨면 스크린샷을 남기고 예/확인/OK 를 누른다. (저장 흐름 전용)"""
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        for dialog in _confirm_dialogs(session):
            shot = _shot_window(dialog.handle, tag)
            for text in ACCEPT_TEXTS:
                button = driver.by_text(dialog.handle, text) or driver.by_text(dialog.handle, text, "TButton")
                if button is not None:
                    driver.click_message(button)
                    time.sleep(0.6)
                    return text, shot
            return "(버튼 못 읽음)", shot
        time.sleep(driver.POLL_INTERVAL)
    return None


def save_form(session: Session, form: driver.WindowRef, *, tag: str, settle: float = 12.0) -> list:
    """폼의 '저 장'을 누르고 뒤따르는 확인창을 처리한다(누른 버튼·스냅 목록 반환). 폼은 닫지 않는다."""
    button = driver.by_text(form.handle, "저 장", "TcxButton") or driver.by_text(form.handle, "저장", "TcxButton")
    if button is None:
        raise NavigationError("'저 장' 버튼을 찾지 못했습니다.")
    driver.click(button)
    pressed = []
    deadline = time.monotonic() + settle
    quiet = 0
    while time.monotonic() < deadline:
        got = accept_prompt(session, wait=1.0, tag=tag)
        if got:
            pressed.append(got)
            quiet = 0
        else:
            quiet += 1
            if quiet >= 3 and pressed:
                break
            if quiet >= 5:
                break
    return pressed


# ── PDF등록(감정평가서 PDF 첨부) — 실서버 쓰기, 정찰 2026-08-25 ───────────────────
PDF_WINDOW_CLASS = "TBnkTop24pdf"          # '감정평가서(PDF) 첨부'
PDF_DIALOG_TITLE = "첨부할 감정평가서 파일 선택"   # 표준 열기 대화상자(#32770)
# 국민 작성폼 PDF창 탭(TcxPageControl, 탭 텍스트는 컨트롤로 안 잡혀 창 기준 픽셀 클릭 — 정찰 2026-08-28 recon_pdf_tabs).
# 탭 시트(TcxTabSheet)는 처음 방문할 때 만들어지므로 클릭 뒤 같은 제목의 시트가 있는지로 전환을 확인한다.
# '파일선택'·'닫 기' 버튼은 탭 공통(하단 패널).
PDF_TABS = {"(원본)감정평가서": (60, 37), "평가전례 첨부용": (165, 37), "(관련)수수료 등": (265, 37), "관련서류": (345, 37)}


def _windows_of(session: Session) -> dict[int, tuple[str, str]]:
    return {w.handle: (w.class_name, w.title) for w in driver.find_windows(pid=session.pid)}


def _wait_new_window(session: Session, before: dict, *, class_name: str | None = None,
                     title: str | None = None, timeout: float = 20.0) -> driver.WindowRef | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for w in driver.find_windows(pid=session.pid):
            if w.handle in before:
                continue
            if class_name and w.class_name != class_name:
                continue
            if title and title not in w.title:
                continue
            return w
        time.sleep(driver.POLL_INTERVAL)
    return None


def open_pdf_window(session: Session, form: driver.WindowRef) -> driver.WindowRef:
    """작성 폼 'PDF등록' → 'TBnkTop24pdf 감정평가서(PDF) 첨부' 창."""
    button = driver.by_text(form.handle, "PDF등록", "TcxButton")
    if button is None:
        raise NavigationError("'PDF등록' 버튼을 찾지 못했습니다.")
    before = _windows_of(session)
    driver.click(button)
    win = _wait_new_window(session, before, class_name=PDF_WINDOW_CLASS)
    if win is None:
        raise NavigationError("PDF 첨부 창이 열리지 않았습니다.")
    time.sleep(0.8)
    return win


def pdf_tab_sheets(pdf_win: driver.WindowRef) -> list[str]:
    """PDF창 안에 만들어진 TcxTabSheet 제목들(방문한 탭만 생긴다)."""
    out = []
    for c in driver.descendants(pdf_win.handle):
        try:
            if c.element_info.class_name == "TcxTabSheet":
                out.append((c.window_text() or "").strip())
        except Exception:  # noqa: BLE001
            continue
    return out


def select_pdf_tab(pdf_win: driver.WindowRef, name: str, *, timeout: float = 5.0) -> None:
    """PDF창 탭 전환(픽셀 클릭). 시트가 생기지 않으면 NavigationError."""
    if name not in PDF_TABS:
        raise NavigationError(f"모르는 PDF 탭: {name!r}")
    from pywinauto import mouse
    x, y = PDF_TABS[name]
    w = driver.window(pdf_win.handle)
    w.set_focus()
    time.sleep(0.3)
    r = w.rectangle()
    for _ in range(3):
        mouse.click(coords=(r.left + x, r.top + y))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if name in pdf_tab_sheets(pdf_win):
                time.sleep(0.5)
                return
            time.sleep(driver.POLL_INTERVAL)
    raise NavigationError(f"PDF 탭 '{name}' 전환 실패(시트 미생성). 현재 시트={pdf_tab_sheets(pdf_win)}")


def pdf_windows(session: Session) -> tuple[driver.WindowRef, ...]:
    return tuple(w for w in driver.find_windows(pid=session.pid) if w.class_name == PDF_WINDOW_CLASS)


def _filename_edit(dialog_handle: int):
    """열기 대화상자의 '파일 이름' Edit — Edit 여러 개(주소창 등) 중 가장 아래 것."""
    edits = driver.by_class(dialog_handle, "Edit")
    if not edits:
        return None
    return max(edits, key=lambda e: e.rectangle().top)


def attach_pdf(session: Session, form: driver.WindowRef, pdf_path: str, *, on_prompt=None,
               settle: float = 90.0, tab: str | None = None, pdf_win: driver.WindowRef | None = None) -> dict:
    """PDF등록 창에서 '파일선택' → 열기 대화상자에 경로 입력 → '열기'. 이후 뜨는 확인창은 on_prompt(대화상자) 로
    처리(없으면 accept_prompt). 결과 dict(pdf_window, dialog_seen, prompts, elapsed).
    tab: 국민 작성폼 PDF창 탭(PDF_TABS). pdf_win 을 주면 이미 열린 창을 재사용(탭별 연속 첨부)."""
    if pdf_win is None:
        pdf_win = open_pdf_window(session, form)
    if tab:
        select_pdf_tab(pdf_win, tab)
    select = driver.by_text(pdf_win.handle, "파일선택", "TcxButton")
    if select is None:
        raise NavigationError("'파일선택' 버튼을 찾지 못했습니다.")
    before = _windows_of(session)
    driver.click(select)
    dialog = _wait_new_window(session, before, title=PDF_DIALOG_TITLE, timeout=8.0)
    if dialog is None:      # 현장조사서 PDF등록 등 제목이 다른 열기 대화상자 → 새 #32770 창으로 폴백
        dialog = _wait_new_window(session, before, class_name="#32770", timeout=12.0)
    if dialog is None:
        raise NavigationError("열기 대화상자가 뜨지 않았습니다.")
    dialog_title = dialog.title
    time.sleep(0.6)
    edit = _filename_edit(dialog.handle)
    if edit is None:
        raise NavigationError("열기 대화상자의 파일 이름 칸을 찾지 못했습니다.")
    edit.set_focus()
    edit.set_edit_text("")
    edit.set_edit_text(pdf_path)
    time.sleep(0.3)
    if (edit.window_text() or "") != pdf_path:
        raise driver.ValueRejected(f"파일 이름 칸 불일치: {edit.window_text()!r}")
    open_btn = driver.by_text(dialog.handle, "열기(&O)") or driver.by_text(dialog.handle, "열기")
    if open_btn is None:
        raise NavigationError("'열기' 버튼을 찾지 못했습니다.")
    driver.click_message(open_btn)
    started = time.monotonic()
    prompts = []
    # 대화상자가 닫히고, 업로드/확인창이 잦아들 때까지 지켜본다.
    deadline = started + settle
    quiet = 0
    while time.monotonic() < deadline:
        still_dialog = any(w.handle == dialog.handle or (dialog_title and w.title == dialog_title)
                           for w in driver.find_windows(pid=session.pid))
        got = (on_prompt or accept_prompt)(session, wait=1.0, tag="pdf")
        if got:
            prompts.append(got)
            quiet = 0
            continue
        if still_dialog:
            quiet = 0
            continue
        quiet += 1
        if quiet >= 4:
            break
    # 업로드가 끝나면 뷰어가 뜬다 — 뜰 때까지 기다린다(큰 파일 대비). 남은 시간 안에 못 뜨면 viewer=False 로 알린다.
    viewer = wait_pdf_viewer(pdf_win, timeout=max(5.0, deadline - time.monotonic()))
    return {"pdf_window": pdf_win, "prompts": prompts, "elapsed": round(time.monotonic() - started, 1),
            "viewer": viewer}


def pdf_viewer_ready(pdf_win: driver.WindowRef) -> bool:
    """PDF 창 안에 뷰어 컨트롤(AVL_/ATL 계열)이 만들어졌는지 — 큰 PDF는 업로드·렌더가 늦어 그 전에 닫으면
    폼이 바쁜 상태로 남아 '닫 기'가 안 먹는다(2026-08-27 22.6MB 실증)."""
    try:
        for c in driver.descendants(pdf_win.handle):
            try:
                name = c.element_info.class_name or ""
            except Exception:  # noqa: BLE001
                continue
            if "AVL" in name or "ATL" in name:
                return True
    except Exception:  # noqa: BLE001
        pass
    return False


def wait_pdf_viewer(pdf_win: driver.WindowRef, *, timeout: float = 90.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pdf_viewer_ready(pdf_win):
            return True
        time.sleep(0.5)
    return pdf_viewer_ready(pdf_win)


class PdfUploadPending(NavigationError):
    """업로드(프로그래스바)가 아직 도는 PDF 창 — 이때 '닫 기'를 누르면 폼이 바쁜 상태로 굳는다(2026-09-02 실증)."""


def ensure_pdf_uploaded(result: dict, *, extra: float = 300.0) -> None:
    """attach_pdf 뒤, 닫기 전에 호출: 뷰어가 아직이면 업로드 완료를 더 기다린다(대용량 PDF 는 settle 90초를 넘긴다).
    끝내 안 뜨면 PdfUploadPending — 러너는 '닫 기'를 누르지 말고 실패 처리해야 한다(창은 그대로 둔다)."""
    if result.get("viewer"):
        return
    print(f"[pdf] 뷰어 미표시 — 업로드 완료 추가 대기(최대 {extra:.0f}초)")
    if wait_pdf_viewer(result["pdf_window"], timeout=extra):
        print("[pdf] 업로드 완료(뷰어 표시)")
        return
    raise PdfUploadPending("PDF 업로드가 끝나지 않았습니다(뷰어 미표시) — '닫 기'를 누르지 않고 실패 처리합니다.")


def close_pdf_windows(session: Session, *, on_prompt=None) -> list:
    """PDF 첨부 창 '닫 기'. 뒤따르는 확인창은 on_prompt(기본 accept_prompt)로 처리."""
    pressed = []
    for win in pdf_windows(session):
        button = driver.by_text(win.handle, "닫 기", "TcxButton")
        if button is None:
            continue
        driver.click(button)
        for _ in range(6):
            got = (on_prompt or accept_prompt)(session, wait=1.0, tag="pdfclose")
            if got:
                pressed.append(got)
            elif not any(w.handle == win.handle for w in pdf_windows(session)):
                break
    return pressed


def set_date_range(session: Session, start: str) -> None:
    """조회시작일을 앞당겨 오래된 건도 목록에 나오게 한다(YYYY-MM-DD)."""
    edit = driver.find_by_label(session.main.handle, "조회시작일", "TcxDateEdit")
    if edit is None:
        raise NavigationError("'조회시작일' 칸을 찾지 못했습니다.")
    driver.set_text(edit, start, verify=False)
    button = driver.by_text(session.main.handle, QUERY_BUTTON, "TcxButton")
    if button is not None:
        driver.click(button)
        time.sleep(2.0)


def query_documents(
    session: Session,
    *,
    start: str,
    end: str,
    work_type: str = "담보",
    settle: float = 2.0,
) -> None:
    """문서번호 없이 업무구분·기간 조건으로 목록을 조회한다."""
    try:
        start_date = date.fromisoformat(start)
        end_date = date.fromisoformat(end)
    except ValueError as error:
        raise NavigationError("조회일은 YYYY-MM-DD 형식이어야 합니다.") from error
    if start_date > end_date:
        raise NavigationError("조회시작일은 조회종료일보다 늦을 수 없습니다.")

    work = driver.by_text(
        session.main.handle, work_type, "TcxCustomRadioGroupButton")
    if work is None:
        raise NavigationError(f"업무구분 '{work_type}' 항목을 찾지 못했습니다.")
    direct = driver.by_text(
        session.main.handle, "직접입력", "TcxCustomRadioGroupButton")
    if direct is None:
        raise NavigationError("기간검색 '직접입력' 항목을 찾지 못했습니다.")

    start_edit = driver.find_by_label(
        session.main.handle, "조회시작일", "TcxDateEdit")
    end_edit = driver.find_by_label(
        session.main.handle, "조회종료일", "TcxDateEdit")
    if start_edit is None or end_edit is None:
        raise NavigationError("조회 시작일/종료일 칸을 찾지 못했습니다.")

    # 라디오는 click_input 이 안 먹힌다(포커스만 바뀜) — BM_CLICK 메시지로.
    driver.click_message(work)
    driver.click_message(direct)
    driver.set_text(start_edit, start, verify=False)
    driver.set_text(end_edit, end, verify=False)

    # 이전 검색값이 화면에 남아 있어도 대상문서 없는 조회임을 명확히 한다.
    for label in (SEARCH_LABEL, "의뢰번호조회"):
        edit = driver.find_by_label(session.main.handle, label, "TcxTextEdit")
        if edit is not None:
            driver.set_text(edit, "", verify=False)

    button = driver.by_text(session.main.handle, QUERY_BUTTON, "TcxButton")
    if button is None:
        raise NavigationError(f"'{QUERY_BUTTON}' 버튼을 찾지 못했습니다.")
    driver.click(button)
    time.sleep(settle)


def close_context_menu() -> None:
    """열려 있는 팝업 메뉴를 닫는다(실패 복구용)."""
    if _menu_handles():
        send_keys("{ESC}")
        time.sleep(0.3)


def open_document(
    session: Session, doc_id: str, *, timeout: float = 60.0
) -> driver.WindowRef:
    """문서번호 하나를 작성 폼까지 열어 준다."""
    close_forms(session)      # 앞 문서 폼이 남아 있으면 그 값을 읽게 된다
    find_document(session, doc_id)
    try:
        return open_write_form(session, timeout=timeout)
    except Exception:
        close_context_menu()
        raise


# ── 국민 작성 폼(TBNKKBB24DAMB) 2단 구조 — 정찰 2026-08-26 ──────────────────
# 왼쪽 그리드=물건, 오른쪽 그리드=세부내역(종류 라디오 토지/건물/기계기구). 그리드 팝업 가속키는 신한과 다르다.
KB_MENU = {"append": "t", "insert": "u", "copy_here": "v", "copy_append": "w", "bulk": "z"}
KB_REGION_DETAIL = (615, 880)
KB_REGION_OBJECT = (170, 440)
KB_KIND_MARK = {"토지": "공부지목", "건물": "건물구조", "기계기구": "기계기구명"}   # 종류별로만 보이는 라벨


def _detail_grid(form: driver.WindowRef):
    grids = driver.by_class(form.handle, "TcxGridSite")
    if len(grids) < 2:
        raise NavigationError("세부내역 그리드를 찾지 못했습니다(그리드 2개 필요).")
    return max(grids, key=lambda g: g.rectangle().left)


def current_detail_seq(form: driver.WindowRef) -> int | None:
    edit = driver.find_by_label(form.handle, "일련번호", region=KB_REGION_DETAIL)
    if edit is None:
        return None
    text = driver.read(driver.editable(edit)).strip().replace(",", "")
    return int(text) if text.isdigit() else None


def count_detail_rows(form: driver.WindowRef) -> int:
    grid = _detail_grid(form)
    grid.set_focus()
    time.sleep(0.3)
    send_keys("^{END}")
    time.sleep(0.4)
    return current_detail_seq(form) or 0


def select_detail_row(form: driver.WindowRef, index: int) -> int:
    grid = _detail_grid(form)
    grid.set_focus()
    time.sleep(0.3)
    send_keys("^{HOME}")
    time.sleep(0.3)
    for _ in range(index):
        send_keys("{DOWN}")
        time.sleep(0.15)
    time.sleep(0.4)
    seq = current_detail_seq(form)
    if seq != index + 1:
        raise NavigationError(f"세부내역 {index + 1}행 선택 실패(화면 일련번호={seq}).")
    return seq


def add_detail_row(form: driver.WindowRef, *, timeout: float = 5.0) -> int:
    """세부내역 그리드 팝업 '추가(마지막위치)(T)'. 폼 상태만 바뀐다(저장 아님)."""
    grid = _detail_grid(form)
    before_count = count_detail_rows(form)
    grid.set_focus()
    time.sleep(0.3)
    before = _menu_handles()
    send_keys("+{F10}")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not (_menu_handles() - before):
        time.sleep(driver.POLL_INTERVAL)
    if not (_menu_handles() - before):
        raise NavigationError("세부내역 그리드 팝업 메뉴가 열리지 않았습니다.")
    send_keys(KB_MENU["append"])
    time.sleep(0.8)
    after_count = count_detail_rows(form)
    if after_count != before_count + 1:
        raise NavigationError(f"세부내역 행 추가 실패(전 {before_count} → 후 {after_count}).")
    return after_count


def detail_kind(form: driver.WindowRef) -> str | None:
    """현재 세부내역 행의 종류 — 라디오 상태는 못 읽으므로 종류별로만 보이는 라벨로 판정한다."""
    for kind, mark in KB_KIND_MARK.items():
        if driver.find_by_label(form.handle, mark, region=KB_REGION_DETAIL) is not None:
            return kind
    return None


def set_radio(form: driver.WindowRef, text: str, *, settle: float = 1.0) -> None:
    """DevExpress 라디오는 click_input 으로 안 바뀐다 → BM_CLICK(driver.click_message)."""
    btn = driver.by_text(form.handle, text, "TcxDBRadioGroupButton")
    if btn is None:
        raise NavigationError(f"라디오 '{text}' 를 찾지 못했습니다.")
    driver.click_message(btn)
    time.sleep(settle)


def set_detail_kind(form: driver.WindowRef, kind: str) -> str | None:
    """세부내역 종류 라디오를 고르고, 종류별 라벨이 보이는지로 확인한다(fail-closed)."""
    if detail_kind(form) == kind:
        return kind
    set_radio(form, kind)
    now = detail_kind(form)
    if now != kind:
        raise NavigationError(f"세부내역 종류 선택 실패: 원함={kind} 화면={now}")
    return now


# ── 국민 물건(왼쪽) 그리드 — 규칙 A(필지 1개=물건 1개, 2026-08-26 사용자 결정) ─────────
def kb_current_object_seq(form: driver.WindowRef) -> int | None:
    """물건 패널 '일련번호'(세부 패널에도 같은 라벨 → 구역으로 가른다)."""
    edit = driver.find_by_label(form.handle, "일련번호", region=KB_REGION_OBJECT)
    if edit is None:
        return None
    text = driver.read(driver.editable(edit)).strip().replace(",", "")
    return int(text) if text.isdigit() else None


def kb_count_object_rows(form: driver.WindowRef) -> int:
    grid = _object_grid(form)
    grid.set_focus()
    time.sleep(0.3)
    send_keys("^{END}")
    time.sleep(0.4)
    return kb_current_object_seq(form) or 0


def kb_select_object_row(form: driver.WindowRef, index: int) -> int:
    grid = _object_grid(form)
    grid.set_focus()
    time.sleep(0.3)
    send_keys("^{HOME}")
    time.sleep(0.3)
    for _ in range(index):
        send_keys("{DOWN}")
        time.sleep(0.15)
    time.sleep(0.5)
    seq = kb_current_object_seq(form)
    if seq != index + 1:
        raise NavigationError(f"물건 {index + 1}행 선택 실패(화면 일련번호={seq}).")
    return seq


def kb_add_object_row(form: driver.WindowRef, *, timeout: float = 5.0) -> int:
    """물건 그리드 팝업 '추가(마지막위치)(T)' — 국민은 가속키가 신한(U)과 다르다. 폼 상태만 바뀐다."""
    grid = _object_grid(form)
    before_count = kb_count_object_rows(form)
    grid.set_focus()
    time.sleep(0.3)
    before = _menu_handles()
    send_keys("+{F10}")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not (_menu_handles() - before):
        time.sleep(driver.POLL_INTERVAL)
    if not (_menu_handles() - before):
        raise NavigationError("물건 그리드 팝업 메뉴가 열리지 않았습니다.")
    send_keys(KB_MENU["append"])
    time.sleep(0.8)
    after_count = kb_count_object_rows(form)
    if after_count != before_count + 1:
        raise NavigationError(f"물건 행 추가 실패(전 {before_count} → 후 {after_count}).")
    return after_count


# ── 기업 물건(왼쪽) 그리드 — 정찰 2026-08-28(recon/fields_ibk_damb.md): 가속키는 신한과 같은 U~Z, 순번 칸은 국민처럼 '일련번호' ─
IBK_REGION_OBJECT = (190, 500)
IBK_REGION_TAB = (500, 810)
IBK_TAB_MARK = {"토지": "공부지목", "건물": "건물구조", "기계기구": "기계기구명"}   # 탭별로만 보이는 라벨(기계기구는 미정찰 추정)


def ibk_current_object_seq(form: driver.WindowRef) -> int | None:
    """물건 패널 '일련번호'(TcxDBCurrencyEdit @229,328)."""
    edit = driver.find_by_label(form.handle, "일련번호", region=IBK_REGION_OBJECT)
    if edit is None:
        return None
    text = driver.read(driver.editable(edit)).strip().replace(",", "")
    return int(text) if text.isdigit() else None


def ibk_count_object_rows(form: driver.WindowRef) -> int:
    grid = _object_grid(form)
    grid.set_focus()
    time.sleep(0.3)
    send_keys("^{END}")
    time.sleep(0.4)
    return ibk_current_object_seq(form) or 0


def ibk_select_object_row(form: driver.WindowRef, index: int) -> int:
    grid = _object_grid(form)
    grid.set_focus()
    time.sleep(0.3)
    send_keys("^{HOME}")
    time.sleep(0.3)
    for _ in range(index):
        send_keys("{DOWN}")
        time.sleep(0.15)
    time.sleep(0.5)
    seq = ibk_current_object_seq(form)
    if seq != index + 1:
        raise NavigationError(f"물건 {index + 1}행 선택 실패(화면 일련번호={seq}).")
    return seq


def ibk_add_object_row(form: driver.WindowRef, *, timeout: float = 5.0) -> int:
    """물건 그리드 팝업 '추가(마지막위치)(U)'(신한과 같은 가속키). 폼 상태만 바뀐다(저장 아님)."""
    grid = _object_grid(form)
    before_count = ibk_count_object_rows(form)
    grid.set_focus()
    time.sleep(0.3)
    before = _menu_handles()
    send_keys("+{F10}")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not (_menu_handles() - before):
        time.sleep(driver.POLL_INTERVAL)
    if not (_menu_handles() - before):
        raise NavigationError("물건 그리드 팝업 메뉴가 열리지 않았습니다.")
    send_keys(OBJECT_MENU["append"])
    time.sleep(0.8)
    after_count = ibk_count_object_rows(form)
    if after_count != before_count + 1:
        raise NavigationError(f"물건 행 추가 실패(전 {before_count} → 후 {after_count}).")
    return after_count


def ibk_tab_kind(form: driver.WindowRef) -> str | None:
    """오른쪽 탭이 지금 어느 종류인지 — 탭 시트가 같은 자리에 겹쳐 있어 **보이는** 라벨로 판정한다."""
    for kind, mark in IBK_TAB_MARK.items():
        if driver.find_by_label(form.handle, mark, region=IBK_REGION_TAB) is not None:
            return kind
    return None
