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
from dataclasses import dataclass

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
    already = driver.find_windows(driver.MAIN_CLASS)
    if already:
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

    main = driver.wait_for_window(driver.MAIN_CLASS, timeout=timeout)
    return Session(main)


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


def close_forms(session: Session, *, timeout: float = 20.0) -> None:
    """열려 있는 담보 폼을 모두 닫는다(다음 문서를 열기 전 정리)."""
    for form in open_forms(session):
        button = driver.by_text(form.handle, "닫 기", "TcxButton")
        if button is None:
            continue
        driver.click(button)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and driver.find_windows(
            form.class_name, pid=session.pid
        ):
            time.sleep(driver.POLL_INTERVAL)


def _menu_handles() -> set[int]:
    return {
        int(e.handle) for e in find_elements(backend=driver.BACKEND)
        if (e.class_name or "") == CONTEXT_MENU_CLASS and e.handle
    }


def open_write_form(session: Session, *, timeout: float = 60.0) -> driver.WindowRef:
    """그리드 첫 행을 골라 컨텍스트메뉴 → '작 성(열람)' → 은행별 담보 폼을 연다.

    마우스 좌표 클릭(click_input)은 권한·좌표에 취약해서(다중 그리드, SetCursorPos)
    **키보드**로 한다: 그리드 포커스 → Ctrl+Home(첫 행) → Shift+F10(컨텍스트메뉴)
    → 가속키 'a'(작성/열람). 검색으로 1건만 남긴 상태에서 첫 행이 곧 대상이다.
    """
    grid = _grid(session)
    grid.set_focus()
    time.sleep(0.4)
    send_keys("^{HOME}")           # 첫(=유일) 행 선택
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
    return driver.wait_for_window(driver.FORM_CLASS_PREFIX, pid=session.pid, timeout=timeout)


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
