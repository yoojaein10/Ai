"""
Bank24 자동화 툴
Target: C:\KADC\X11\bank24.exe (Delphi 기반)
"""
import os
import sys
import json
import time
import logging
import traceback
from datetime import datetime
from pathlib import Path

import pandas as pd
import pyodbc
import pyautogui
import pyperclip

try:
    from pywinauto import Application, Desktop
    from pywinauto.keyboard import send_keys
    PYWINAUTO_OK = True
except Exception:
    PYWINAUTO_OK = False

from bank_parser import parse_pdf
from db_writer import get_connection, upsert
import pdf_exporter

# ─── 로깅 설정 ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bank24_auto.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.3


# ─── 설정 로드 ────────────────────────────────────────────────────────────────
def load_config(path: str = "config.json") -> dict:
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    # 날짜 기본값: 오늘
    today = datetime.today().strftime("%Y%m%d")
    if not cfg["search"]["date_from"]:
        cfg["search"]["date_from"] = today
    if not cfg["search"]["date_to"]:
        cfg["search"]["date_to"] = today
    return cfg


# ─── 앱 실행 / 연결 ──────────────────────────────────────────────────────────
class Bank24App:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.app = None
        self.main_win = None

    def launch(self):
        """기존 프로세스 종료 후 재시작 → 로그인"""
        import subprocess
        app_path = self.cfg["app_path"]
        exe_name = Path(app_path).name  # bank24.exe

        # 실행 중이면 종료
        result = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {exe_name}"],
                                capture_output=True, text=True)
        if exe_name.lower() in result.stdout.lower():
            subprocess.run(["taskkill", "/F", "/IM", exe_name], capture_output=True)
            log.info(f"{exe_name} 기존 프로세스 종료")
            time.sleep(2)

        log.info(f"앱 실행: {app_path}")
        proc = subprocess.Popen(app_path)
        self._pid = proc.pid
        time.sleep(4)
        self._login_autogui()
        time.sleep(5)  # 메인 창 완전히 로드될 때까지 대기
        self._connect_main_win()

    def _connect_main_win(self):
        """로그인 완료 후 Desktop 스캔으로 TfrmMain 창 핸들 확보"""
        if not PYWINAUTO_OK:
            return
        # 최대 15초간 재시도 (창이 완전히 로드될 때까지)
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                wins = Desktop(backend="win32").windows()
                for w in wins:
                    try:
                        if w.class_name() == "TfrmMain":
                            self.main_win = w
                            log.info(f"메인 창 연결 성공: title={w.window_text()!r}")
                            return
                    except Exception:
                        pass
            except Exception as e:
                log.debug(f"Desktop 스캔 오류: {e}")
            time.sleep(0.5)
        log.warning("메인 창 연결 실패 (15초) — pyautogui 전용 모드로 계속")

    def _login_uia(self):
        """pywinauto UIA 방식 로그인"""
        log.info("UIA 로그인 시도")
        dlg = self.app.window(class_name="TDXLoginDialog")
        dlg.wait("visible", timeout=10)

        id_ctrl = dlg.child_window(auto_id="402020", control_type="Edit")
        pw_ctrl = dlg.child_window(auto_id="1122982", control_type="Edit")
        ok_btn  = dlg.child_window(auto_id="1122960", title="확인")

        id_ctrl.set_edit_text(self.cfg["login"]["id"])
        time.sleep(0.3)
        pw_ctrl.set_edit_text(self.cfg["login"]["pw"])
        time.sleep(0.3)
        ok_btn.click()
        log.info("로그인 완료 (UIA)")
        time.sleep(3)

        self.main_win = self.app.top_window()

    def _login_autogui(self):
        """pyautogui 좌표 방식 로그인 (보안 모듈 간섭 시)"""
        log.info("pyautogui 로그인 시도")
        # ID 필드 (997, 538)
        pyautogui.click(997, 538)
        time.sleep(0.5)
        pyautogui.hotkey("ctrl", "a")
        pyautogui.typewrite(self.cfg["login"]["id"], interval=0.1)

        # PW 필드 (997, 563)
        pyautogui.click(997, 563)
        time.sleep(0.5)
        pyautogui.hotkey("ctrl", "a")
        # 비밀번호는 typewrite 대신 클립보드 방식 (특수문자 대응)
        pyperclip.copy(self.cfg["login"]["pw"])
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.3)

        # 확인 버튼: Tab으로 이동 후 Enter (좌표 찾기 실패 대비)
        pyautogui.press("enter")
        log.info("로그인 완료 (pyautogui)")


# ─── 검색 필터 설정 ───────────────────────────────────────────────────────────
class SearchFilter:
    def __init__(self, app_obj: Bank24App):
        self.app = app_obj
        self.cfg = app_obj.cfg["search"]

    # 라디오 인덱스 매핑 (win32 controls.txt 기준 순서: 공동주택자문,동산담보,탁상,담보,전체)
    RADIO_IDX = {"공동주택자문": 0, "동산담보": 1, "탁상": 2, "담보": 3, "전체": 4}

    def apply(self):
        """라디오 버튼 + 날짜 설정 + 조회 버튼 클릭"""
        log.info(f"검색 필터 적용: type={self.cfg['type']}, "
                 f"{self.cfg['date_from']} ~ {self.cfg['date_to']}")
        self._set_radio()
        self._set_dates()
        self._click_search()

    def _set_radio(self):
        """업무구분 라디오 버튼"""
        if not PYWINAUTO_OK or not self.app.main_win:
            log.warning("라디오 설정 skip — main_win 없음 (pywinauto 연결 실패)")
            return
        target = self.cfg["type"]
        idx = self.RADIO_IDX.get(target, 3)
        log.info(f"라디오 설정 시도: {target} (index={idx})")
        try:
            radios = _timed_descendants(self.app.main_win, "TcxCustomRadioGroupButton", timeout=8.0)
            if len(radios) > idx:
                radios[idx].click_input()
                log.info(f"라디오 선택 완료: {target}")
                time.sleep(0.3)
            else:
                log.warning(f"라디오 버튼 없음({len(radios)}개) — 건너뜀")
        except Exception as e:
            log.warning(f"라디오 버튼 설정 실패: {e} — 건너뜀")

    def _set_dates(self):
        """날짜 설정 — TcxDateEdit"""
        if not PYWINAUTO_OK or not self.app.main_win:
            log.warning("날짜 설정 skip — main_win 없음 (pywinauto 연결 실패)")
            return
        date_from = self.cfg["date_from"]
        date_to   = self.cfg["date_to"]
        fmt_from  = f"{date_from[:4]}-{date_from[4:6]}-{date_from[6:]}"
        fmt_to    = f"{date_to[:4]}-{date_to[4:6]}-{date_to[6:]}"
        log.info(f"날짜 설정 시도: {fmt_from} ~ {fmt_to}")
        try:
            inner_edits = _timed_descendants(self.app.main_win, "TcxCustomDropDownInnerEdit", timeout=8.0)
            if len(inner_edits) >= 2:
                for edit, val, label in [
                    (inner_edits[1], fmt_from, "시작일"),
                    (inner_edits[0], fmt_to,   "종료일"),
                ]:
                    edit.click_input()
                    time.sleep(0.2)
                    edit.type_keys("^a", with_spaces=True)
                    edit.type_keys(val, with_spaces=True)
                    edit.type_keys("{TAB}", with_spaces=True)
                    time.sleep(0.2)
                    log.info(f"{label} 설정: {val}")
            else:
                log.warning(f"TcxCustomDropDownInnerEdit 없음({len(inner_edits)}개) — 건너뜀")
        except Exception as e:
            log.warning(f"날짜 설정 실패: {e} — 건너뜀")

    def _click_search(self):
        """조회 버튼 클릭 — TcxButton"""
        if not PYWINAUTO_OK or not self.app.main_win:
            log.warning("조회 버튼 skip — main_win 없음 (pywinauto 연결 실패)")
            return
        log.info("조회 버튼 클릭 시도")
        try:
            btns = _timed_descendants(self.app.main_win, "TcxButton", timeout=8.0)
            if len(btns) >= 4:
                btns[3].click_input()
                log.info("조회 버튼 클릭 완료")
                time.sleep(3)
            else:
                log.warning(f"TcxButton 없음({len(btns)}개) — 건너뜀")
        except Exception as e:
            log.warning(f"조회 버튼 클릭 실패: {e} — 건너뜀")


# ─── 데이터 수집 ──────────────────────────────────────────────────────────────
def _timed_descendants(win, class_names, timeout: float = 8.0) -> list:
    """descendants() 를 별도 스레드에서 실행 — hang 방지용 타임아웃 래퍼"""
    import threading
    if isinstance(class_names, str):
        class_names = (class_names,)
    result = []

    def _do():
        try:
            result.extend([c for c in win.descendants() if c.class_name() in class_names])
        except Exception as e:
            log.debug(f"_timed_descendants 실패: {e}")

    t = threading.Thread(target=_do, daemon=True)
    t.start()
    t.join(timeout=timeout)
    if t.is_alive():
        log.warning(f"_timed_descendants 타임아웃({timeout}s) — 빈 목록 반환")
    return result


class DataCollector:
    def __init__(self, app_obj: Bank24App, cfg: dict):
        self.app = app_obj
        self.cfg = cfg
        self.excel_path: str | None = None
        self.df_main: pd.DataFrame | None = None
        self.df_detail: pd.DataFrame | None = None

    # ── 그리드 클립보드 복사 → DataFrame ────────────────────────────────────
    def export_excel(self):
        """그리드 전체 선택 → Ctrl+C → 클립보드로 DataFrame 읽기"""
        log.info("그리드 데이터 클립보드 복사 시작")

        # 그리드 클릭 — 가장 큰 그리드(메인 데이터 그리드) 선택
        clicked = False
        grid_r = None
        try:
            if self.app.main_win:
                grids = _timed_descendants(
                    self.app.main_win,
                    ("TcxGrid", "TDBGrid", "TStringGrid"),
                    timeout=8.0,
                )
                if grids:
                    best = max(grids, key=lambda g: (
                        g.rectangle().width() * g.rectangle().height()
                    ))
                    grid_r = best.rectangle()
                    log.info(f"그리드 발견 (pywinauto): ({grid_r.left},{grid_r.top},{grid_r.right},{grid_r.bottom}) size={grid_r.width()}x{grid_r.height()}")
                    clicked = True
                else:
                    log.warning("_timed_descendants: 그리드 없음 — pyautogui fallback")
        except Exception as e:
            log.warning(f"그리드 pywinauto 탐색 실패: {e}")

        if not clicked:
            try:
                if self.app.main_win:
                    wr = self.app.main_win.rectangle()
                    log.info(f"그리드 fallback: 메인 창 rect 사용 ({wr.left},{wr.top},{wr.right},{wr.bottom})")
                    # 창 내 추정 그리드 영역 (상단 필터 ~130px, 하단 ~80px 제외)
                    class _R:
                        left = wr.left + 5
                        top = wr.top + 130
                        right = wr.right - 5
                        bottom = wr.bottom - 80
                    grid_r = _R()
                    clicked = True
            except Exception as e:
                log.warning(f"메인 창 rect 실패: {e}")

        if not clicked or grid_r is None:
            log.error("그리드 위치 파악 불가 — 클립보드 복사 건너뜀")
            return

        # 헤더 2행 건너뛰고 첫 데이터 행 클릭 (TcxGrid 병합헤더 ~55px)
        HEADER_PX  = 55
        cx         = (grid_r.left + grid_r.right) // 2
        first_y    = grid_r.top + HEADER_PX + 10
        last_y     = grid_r.bottom - 20   # 마지막 데이터 행 추정

        # 첫 행 클릭
        log.info(f"첫 행 클릭: ({cx}, {first_y})")
        pyautogui.click(cx, first_y)
        time.sleep(0.3)

        # Shift+클릭으로 마지막 행까지 범위 선택
        log.info(f"마지막 행 Shift+클릭: ({cx}, {last_y})")
        pyautogui.keyDown("shift")
        pyautogui.click(cx, last_y)
        pyautogui.keyUp("shift")
        time.sleep(0.3)

        pyautogui.hotkey("ctrl", "c")
        time.sleep(1.5)

        try:
            self.df_main = pd.read_clipboard(dtype=str)
            self.df_main = self._fix_merged_headers(self.df_main)
            log.info(f"클립보드 읽기 완료: {len(self.df_main)}행, {len(self.df_main.columns)}열")
        except Exception as e:
            log.error(f"클립보드 읽기 실패: {e}")

    def _fix_merged_headers(self, df: pd.DataFrame) -> pd.DataFrame:
        """병합셀로 쪼개진 컬럼명 복원 (예: '은'+'행' → '은행', '상'+'태' → '상태')"""
        # 실제 앱 컬럼 순서 (2.png 기준)
        EXPECTED_COLS = [
            "은행", "의뢰영업점", "의뢰번호", "법인명", "지사명",
            "업무구분", "업무실적", "매칭", "열람허용", "상태",
            "현장조사서", "감정서번호", "의뢰일자", "접수일자",
            "발송일자", "조사서발송일", "지급여부", "보실행여부",
            "계산서발행", "취소일자", "서명요청", "서명완료", "본발송일자",
        ]
        cols = list(df.columns)

        # 단일 글자 컬럼이 연속으로 있으면 병합
        merged = []
        i = 0
        while i < len(cols):
            if len(cols[i].strip()) == 1 and i + 1 < len(cols) and len(cols[i+1].strip()) == 1:
                merged.append(cols[i].strip() + cols[i+1].strip())
                i += 2
            else:
                merged.append(cols[i].strip())
                i += 1

        if len(merged) == len(EXPECTED_COLS):
            df.columns = EXPECTED_COLS
            log.info("컬럼명 복원 완료 (EXPECTED 매핑)")
        elif len(merged) == len(cols):
            df.columns = merged
            log.info(f"컬럼명 병합 완료: {merged}")
        else:
            log.warning(f"컬럼 수 불일치 — 원본 유지 ({len(cols)}열)")
        return df


    # ── 상세 창 주소 수집 ────────────────────────────────────────────────────
    def collect_details(self):
        """그리드 키보드 내비게이션 → Shift+F10 메뉴 → 주소 추출 → df_main에 직접 기록"""
        if self.df_main is None:
            return

        row_count = len(self.df_main) - 1  # 마지막 행 제외 (합계 행)
        if row_count <= 0:
            log.info("수집할 데이터 없음")
            return

        log.info(f"상세 주소 수집 시작: {row_count}행")

        # 그리드에 포커스
        grid_focused = False
        if PYWINAUTO_OK and self.app.main_win:
            try:
                grids = _timed_descendants(
                    self.app.main_win,
                    ("TcxGrid", "TDBGrid", "TStringGrid"),
                    timeout=8.0,
                )
                if grids:
                    grids[0].click_input()
                    grid_focused = True
                    log.info(f"그리드 포커스 완료 ({grids[0].class_name()})")
            except Exception as e:
                log.warning(f"그리드 포커스 실패: {e}")

        if not grid_focused:
            grid_rect = self._get_grid_rect()
            if grid_rect:
                cx = (grid_rect[0] + grid_rect[2]) // 2
                cy = (grid_rect[1] + grid_rect[3]) // 2
                pyautogui.click(cx, cy)
                grid_focused = True
            else:
                log.error("그리드 포커스 불가 — 상세 수집 건너뜀")
                self.df_main["주소"] = ""
                return

        time.sleep(0.3)
        # 첫 행으로 이동
        send_keys("^{HOME}")
        time.sleep(0.5)

        # 그리드 rect (우클릭 좌표용)
        grid_rect = self._get_grid_rect()
        if not grid_rect:
            log.error("그리드 rect 파악 실패")
            self.df_main["주소"] = ""
            return
        cx = (grid_rect[0] + grid_rect[2]) // 2
        click_y = grid_rect[1] + 35  # 헤더 아래 첫 행

        addresses = []
        for i in range(row_count):
            req_no = str(self.df_main.iloc[i]["의뢰번호"]) if "의뢰번호" in self.df_main.columns else ""
            try:
                address = self._open_detail_get_address(cx, click_y)
                addresses.append(address)
                log.info(f"  [{i+1}/{row_count}] 의뢰번호={req_no}, 주소={address[:40] if address else '(없음)'}")
            except Exception as e:
                log.warning(f"  [{i+1}] 상세 수집 실패: {e}")
                addresses.append("")

            # 다음 행으로 이동 (마지막 행 제외)
            if i < row_count - 1:
                send_keys("{DOWN}")
                time.sleep(0.3)

        self.df_main = self.df_main.iloc[:row_count].reset_index(drop=True)
        self.df_main["주소"] = addresses
        log.info(f"상세 주소 수집 완료: {row_count}건")

    def _get_grid_rect(self):
        """TcxGrid 화면 위치 반환 — 면적이 가장 큰 그리드(메인 데이터 그리드) 선택"""
        if PYWINAUTO_OK and self.app.main_win:
            try:
                grids = _timed_descendants(
                    self.app.main_win,
                    ("TcxGrid", "TDBGrid", "TStringGrid"),
                    timeout=8.0,
                )
                if grids:
                    # 면적 기준으로 가장 큰 그리드 선택
                    best = max(grids, key=lambda g: (
                        g.rectangle().width() * g.rectangle().height()
                    ))
                    r = best.rectangle()
                    log.info(f"그리드 rect: ({r.left},{r.top},{r.right},{r.bottom}) "
                             f"size={r.width()}x{r.height()}")
                    return (r.left, r.top, r.right, r.bottom)
            except Exception as e:
                log.warning(f"그리드 rect win32 실패: {e}")

        # pywinauto 실패 시 메인 창 기준 추정값
        if self.app.main_win:
            try:
                wr = self.app.main_win.rectangle()
                # 창 상단 필터 영역(약 130px) 제외, 하단 상태바(약 30px) 제외
                left   = wr.left + 5
                top    = wr.top + 130
                right  = wr.right - 5
                bottom = wr.bottom - 80
                log.info(f"그리드 rect 추정값: ({left},{top},{right},{bottom})")
                return (left, top, right, bottom)
            except Exception as e:
                log.warning(f"그리드 rect 추정 실패: {e}")
        return None

    def _open_detail_get_address(self, click_x: int, click_y: int) -> str:
        """그리드 행 우클릭 → '0' 단축키(접수(열람)) → 주소 추출 → 창 닫기"""
        if self.app.main_win:
            self.app.main_win.set_focus()
        time.sleep(0.2)
        pyautogui.rightClick(click_x, click_y)
        time.sleep(1.0)
        pyautogui.press("0")
        time.sleep(2.5)

        # 종합접수 창에서 주소 추출
        address = self._extract_address_from_detail()

        # 창 닫기 (클래스명으로 연결 — 타이틀보다 안정적)
        if PYWINAUTO_OK:
            try:
                from pywinauto import Application as App32
                dapp = App32(backend="win32").connect(class_name="TBnkTop24Rcp", timeout=3)
                dwin = dapp.top_window()
                dwin.set_focus()
                dwin.close()
                time.sleep(0.5)
            except Exception as e:
                log.warning(f"종합접수 창 닫기 실패: {e}")
                try:
                    if self.app.main_win:
                        self.app.main_win.set_focus()
                except Exception:
                    pass

        return address

    def _extract_address_from_detail(self) -> str:
        """종합접수 창 내부 주소 그리드(Grid 0) 첫 번째 행 주소 셀 클립보드 추출"""
        if not PYWINAUTO_OK:
            return ""
        try:
            from pywinauto import Application as App32
            import pyperclip
            dapp = App32(backend="win32").connect(class_name="TBnkTop24Rcp", timeout=8)
            detail_win = dapp.top_window()

            # 종합접수 창 내부 그리드 목록 (면적 큰 순 정렬 → 주소 그리드가 가장 큼)
            inner_grids = _timed_descendants(detail_win, "TcxGrid", timeout=8.0)
            if not inner_grids:
                log.warning("종합접수 내부 그리드 없음")
                return ""

            # 가장 큰 그리드 = 주소 그리드
            addr_grid = max(inner_grids, key=lambda g: (
                g.rectangle().width() * g.rectangle().height()
            ))
            r = addr_grid.rectangle()
            log.info(f"주소 그리드 rect: {r.left},{r.top},{r.right},{r.bottom}")

            # 첫 번째 데이터 행의 주소 컬럼 클릭
            # 주소 컬럼은 2번째 컬럼 → x를 오른쪽 60% 지점으로
            cell_x = r.left + int((r.right - r.left) * 0.6)
            cell_y = r.top + 35  # 헤더(~25px) + 첫 행 중앙
            pyautogui.click(cell_x, cell_y)
            time.sleep(0.3)

            # 클립보드로 복사
            pyperclip.copy("")
            pyautogui.hotkey("ctrl", "c")
            time.sleep(0.5)
            val = pyperclip.paste().strip()

            if val:
                log.info(f"주소 그리드 클립보드: {val[:60]}")
                return val

            log.warning("주소 그리드 클립보드 빈값")
        except Exception as e:
            log.warning(f"종합접수 주소 추출 실패: {e}")
        return ""

    # ── PDF 자동 저장 → 파싱 → MSSQL UPSERT ────────────────────────────────
    def collect_and_upsert_pdfs(self):
        """그리드 각 행: 우클릭→C(미리보기)→PDF저장→파싱→MSSQL upsert
        행 수를 미리 파악하지 않고, 미리보기 열기 실패 시 종료"""
        grid_rect = self._get_grid_rect()
        if not grid_rect:
            log.error("그리드 rect 파악 실패 — PDF 수집 건너뜀")
            return
        grid_cx = (grid_rect[0] + grid_rect[2]) // 2
        grid_cy = grid_rect[1] + 35  # 헤더 아래 첫 행 중앙

        # 그리드 포커스 + 첫 행으로 이동
        pyautogui.click(grid_cx, grid_cy)
        time.sleep(0.3)
        send_keys("^{HOME}")
        time.sleep(0.5)

        # MSSQL 연결
        conn = None
        try:
            conn = get_connection(self.cfg["mssql"])
            cursor = conn.cursor()
        except Exception as e:
            log.error(f"MSSQL 연결 실패: {e}")

        out_dir = Path(self.cfg["output_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)

        ok_cnt = fail_cnt = 0
        # df_main 행 수로 제한 (없으면 500)
        # open_preview_for_row()가 False 반환 시 자동 종료 — df_main 행 수 불필요
        MAX_ROWS = 2  # TODO: 테스트 완료 후 200으로 변경
        log.info(f"PDF 수집 시작 (최대 {MAX_ROWS}건, 미리보기 없으면 자동 종료)")

        for i in range(MAX_ROWS):
            pdf_path = str(out_dir / f"row_{i}.pdf")
            log.info(f"  [{i+1}] 미리보기 열기 시도")

            try:
                # 미리보기 열기 — 실패하면 더 이상 행 없음
                opened = pdf_exporter.open_preview_for_row(grid_cx, grid_cy, wait_sec=5.0)
                if not opened:
                    log.info(f"  [{i+1}] 미리보기 열리지 않음 — 수집 종료")
                    break

                # PDF 저장
                saved = pdf_exporter.save_preview_as_pdf(pdf_path, pdf_wait=8.0)
                if not saved:
                    raise RuntimeError("PDF 저장 실패")

                # 미리보기 닫기
                pdf_exporter.close_preview()
                time.sleep(0.5)

                # 파싱
                data = parse_pdf(pdf_path)
                log.info(f"    파싱: Docid={data.get('Docid')} CustNm={data.get('CustNm')}")

                # MSSQL upsert
                if conn:
                    result = upsert(cursor, data)
                    conn.commit()
                    log.info(f"    DB: {result}")

                # PDF 삭제
                try:
                    os.remove(pdf_path)
                except Exception:
                    pass

                ok_cnt += 1

            except Exception as e:
                log.warning(f"    실패: {e}")
                fail_cnt += 1
                try:
                    pdf_exporter.close_preview()
                except Exception:
                    pass

            # 다음 행으로 이동
            send_keys("{DOWN}")
            time.sleep(0.4)

        if conn:
            conn.close()

        log.info(f"PDF 수집 완료: 성공 {ok_cnt}건 / 실패 {fail_cnt}건")

    # ── 컬럼 재정렬 ──────────────────────────────────────────────────────────
    def merge(self) -> pd.DataFrame:
        """주소 컬럼을 의뢰영업점 바로 오른쪽으로 이동"""
        df = self.df_main.copy()

        if "주소" not in df.columns:
            df["주소"] = ""

        cols = list(df.columns)
        cols.remove("주소")
        if "의뢰영업점" in cols:
            idx = cols.index("의뢰영업점") + 1
        else:
            idx = len(cols)
        cols.insert(idx, "주소")

        df = df[cols]
        log.info(f"컬럼 재정렬 완료: 주소 → 의뢰영업점 다음 ({len(df)}행)")
        return df


# ─── 데이터 저장 ──────────────────────────────────────────────────────────────
class DataSink:
    def __init__(self, cfg: dict):
        self.cfg = cfg

    def save_excel(self, df: pd.DataFrame, path: str = None):
        if not path:
            today = datetime.today().strftime("%Y%m%d")
            path = str(Path(self.cfg["output_dir"]) / f"result_{today}.xls")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        if path.endswith(".xls"):
            try:
                df.to_excel(path, index=False, engine="xlwt")
            except Exception:
                path = path + "x"  # .xlsx 로 폴백
                df.to_excel(path, index=False)
                log.warning(f"xlwt 미설치 — .xlsx 로 저장: {path}")
        else:
            df.to_excel(path, index=False)
        log.info(f"Excel 저장 완료: {path}")

    def save_mssql(self, df: pd.DataFrame):
        mc = self.cfg["mssql"]
        conn_str = (
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={mc['server']};"
            f"DATABASE={mc['database']};"
            f"UID={mc['username']};"
            f"PWD={mc['password']};"
        )
        try:
            conn = pyodbc.connect(conn_str, timeout=10)
            cursor = conn.cursor()
            table = mc["table"]
            cols = list(df.columns)
            placeholders = ", ".join(["?" for _ in cols])
            col_str = ", ".join([f"[{c}]" for c in cols])

            inserted = updated = 0
            for _, row in df.iterrows():
                vals = [None if pd.isna(v) else str(v) for v in row]
                try:
                    cursor.execute(
                        f"INSERT INTO [{table}] ({col_str}) VALUES ({placeholders})",
                        vals,
                    )
                    inserted += 1
                except pyodbc.IntegrityError:
                    # PK 중복 시 UPDATE (의뢰번호 기준)
                    set_clause = ", ".join(
                        [f"[{c}]=?" for c in cols if c != "의뢰번호"]
                    )
                    upd_vals = [str(row[c]) for c in cols if c != "의뢰번호"]
                    upd_vals.append(str(row["의뢰번호"]))
                    cursor.execute(
                        f"UPDATE [{table}] SET {set_clause} WHERE [의뢰번호]=?",
                        upd_vals,
                    )
                    updated += 1

            conn.commit()
            conn.close()
            log.info(f"MSSQL 저장 완료: INSERT {inserted}건, UPDATE {updated}건")
        except Exception as e:
            log.error(f"MSSQL 저장 실패: {e}")


# ─── 메인 ─────────────────────────────────────────────────────────────────────
def main():
    log.info("=" * 60)
    log.info("Bank24 자동화 시작")
    log.info("=" * 60)

    try:
        cfg = load_config("config.json")
    except FileNotFoundError:
        log.error("config.json 없음")
        sys.exit(1)

    app_obj = Bank24App(cfg)
    try:
        app_obj.launch()
    except Exception as e:
        log.error(f"앱 실행/로그인 실패: {e}\n{traceback.format_exc()}")
        sys.exit(1)

    # 검색 필터 적용
    try:
        SearchFilter(app_obj).apply()
        time.sleep(1)
    except Exception as e:
        log.warning(f"필터 적용 중 오류 (계속 진행): {e}")

    # 데이터 수집
    collector = DataCollector(app_obj, cfg)
    try:
        collector.export_excel()
    except Exception as e:
        log.error(f"데이터 수집 실패: {e}\n{traceback.format_exc()}")
        sys.exit(1)

    if collector.df_main is None or len(collector.df_main) == 0:
        log.error("그리드 데이터 없음 — 종료")
        sys.exit(1)

    log.info("=" * 40)
    log.info(f"  수집 대상: 총 {len(collector.df_main)}건")
    log.info("=" * 40)

    # PDF 자동 저장 → 파싱 → MSSQL upsert
    try:
        collector.collect_and_upsert_pdfs()
    except Exception as e:
        log.error(f"PDF 수집/upsert 실패: {e}\n{traceback.format_exc()}")

    log.info("=" * 60)
    log.info("Bank24 자동화 완료")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
