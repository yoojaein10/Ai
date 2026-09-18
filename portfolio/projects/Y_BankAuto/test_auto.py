#!/usr/bin/env python3
"""
Bank24 TBnkTop24Rcp pywinauto 읽기 테스트 — 완전 자동 실행
- 자격증명: 기존 BankAuto config.json 에서 런타임 로드 (새로 저장 안 함)
- Bank24 데이터 파일 생성·수정·삭제 없음
"""
import sys, time, subprocess, json
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try: sys.stdout.reconfigure(encoding="utf-8")
    except: pass

MISSING = []
try:
    from pywinauto import Application, Desktop
    from pywinauto.keyboard import send_keys
except ImportError:
    MISSING.append("pywinauto")
try:
    import pyautogui
    pyautogui.FAILSAFE = False
    pyautogui.PAUSE = 0.2
except ImportError:
    MISSING.append("pyautogui")
try:
    import pyperclip
except ImportError:
    MISSING.append("pyperclip")

if MISSING:
    print(f"[ERROR] 미설치: {', '.join(MISSING)}")
    sys.exit(1)

APP_PATH   = r"C:\KADC\X11\Bank24.exe"
EXE_NAME   = "bank24.exe"
MAIN_CLS   = "TfrmMain"
DETAIL_CLS = "TBnkTop24Rcp"
CFG_PATH   = r"D:\AI\Claude\BankAuto\config.json"

TARGET_FIELDS = [
    "감정서번호", "의뢰번호", "영업점", "담당자",
    "담당자 연락처", "채무자", "소유자", "안심번호", "비고",
]
SEP = "─" * 64


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────
def hdr(t): print(f"\n{SEP}\n  {t}\n{SEP}")

def safe_cls(c):
    try:    return c.class_name()
    except: return "?"

def safe_txt(c):
    try:    return c.window_text()
    except: return ""

def safe_rect(c):
    try:
        r = c.rectangle()
        return r.left, r.top, r.right, r.bottom
    except:
        return 0, 0, 0, 0

def tasklist_has(exe: str) -> bool:
    r = subprocess.run(
        ["tasklist", "/FI", f"IMAGENAME eq {exe}"],
        capture_output=True, text=True, encoding="cp949", errors="replace",
    )
    return exe.lower() in r.stdout.lower()

def _timed_descendants(win, cls_filter, timeout=6.0):
    import threading
    result = []
    if isinstance(cls_filter, str):
        cls_filter = (cls_filter,)
    def _do():
        try:
            result.extend(c for c in win.descendants() if safe_cls(c) in cls_filter)
        except Exception as e:
            print(f"    [descendants 오류] {e}")
    t = threading.Thread(target=_do, daemon=True)
    t.start(); t.join(timeout=timeout)
    if t.is_alive():
        print(f"    [WARN] descendants 타임아웃({timeout}s)")
    return result


# ══════════════════════════════════════════════════════════════════════════════
# Step 0. 자격증명 로드
# ══════════════════════════════════════════════════════════════════════════════
def step0_load_creds():
    hdr("Step 0. 자격증명 로드 (기존 config.json)")
    p = Path(CFG_PATH)
    if not p.exists():
        print(f"  [ERROR] {CFG_PATH} 없음")
        sys.exit(1)
    with open(p, encoding="utf-8") as f:
        cfg = json.load(f)
    uid = cfg["login"]["id"]
    pwd = cfg["login"]["pw"]
    print(f"  → ID hint: {uid[:2]}*** (새로 저장 안 함)")
    return uid, pwd


# ══════════════════════════════════════════════════════════════════════════════
# Step 1. 실행 중인 Bank24 정리
# ══════════════════════════════════════════════════════════════════════════════
def step1_check_running():
    hdr("Step 1. Bank24.exe 실행 여부 확인")
    if not tasklist_has(EXE_NAME):
        print("  → 실행 중 아님")
        return
    print("  → 실행 감지. 정상 종료 시도…")
    try:
        app = Application(backend="win32").connect(class_name=MAIN_CLS, timeout=4)
        app.top_window().close()
        time.sleep(3)
        if not tasklist_has(EXE_NAME):
            print("  → 정상 종료 완료")
            return
    except Exception as e:
        print(f"  → 정상 종료 실패: {e}")
    print("  → taskkill /F 진행")
    subprocess.run(["taskkill", "/F", "/IM", EXE_NAME], capture_output=True)
    time.sleep(2)
    print("  → 강제 종료 완료")


# ══════════════════════════════════════════════════════════════════════════════
# Step 2. 실행 + 로그인
# ══════════════════════════════════════════════════════════════════════════════
def _snapshot_hwnd_set() -> set:
    """현재 열린 모든 top-level 창 hwnd 집합 반환"""
    s = set()
    try:
        for w in Desktop(backend="win32").windows():
            try: s.add(w.handle)
            except: pass
    except: pass
    return s

def _find_bank24_login_win(before: set):
    """Bank24 실행 이후 새로 생긴 창 중 로그인 후보 반환"""
    # Bank24 로그인 다이얼로그 후보 클래스명 패턴
    KNOWN_LOGIN_CLS = {
        "TDXLoginDialog", "TfrmLogin", "TfrmLoginDlg",
        "TLoginForm", "TApplication",
    }
    # 제외할 비-Bank24 클래스
    SKIP_CLS = {
        "Chrome_WidgetWin_1", "Chrome_WidgetWin_0",
        "MozillaWindowClass", "IEFrame", "CabinetWClass",
        "Shell_TrayWnd", "Progman", "WorkerW",
    }

    try:
        all_wins = Desktop(backend="win32").windows()
    except:
        return None, []

    candidates = []
    for w in all_wins:
        try:
            hwnd = w.handle
            if hwnd in before:
                continue                       # 기존 창 제외
            cls = safe_cls(w)
            if cls in SKIP_CLS:
                continue
            ttl = safe_txt(w)
            # 직접 매칭
            if cls in KNOWN_LOGIN_CLS:
                return w, f"클래스 직접 매칭: {cls!r}"
            # Bank24 관련 힌트
            if any(k in cls for k in ("TBnk", "TDX", "TForm", "TfrLogin")):
                candidates.append((w, cls, ttl))
            elif any(k in ttl for k in ("BANK", "Bank", "bank", "로그인", "Login")):
                candidates.append((w, cls, ttl))
        except:
            pass

    # Edit 컨트롤이 있는 창 우선
    for w, cls, ttl in candidates:
        try:
            eds = [c for c in w.descendants()
                   if safe_cls(c) in ("Edit", "TEdit", "TMaskEdit",
                                      "TcxCustomDropDownInnerEdit")]
            if len(eds) >= 2:
                return w, f"Edit 2개 이상 포함: class={cls!r} title={ttl!r}"
        except:
            pass

    # 그냥 신규 창 목록 반환 (첫 번째)
    if candidates:
        w, cls, ttl = candidates[0]
        return w, f"후보(Edit 불명): class={cls!r} title={ttl!r}"

    return None, "신규 창 없음"


def step2_launch_login(uid: str, pwd: str):
    hdr("Step 2. Bank24.exe 실행 및 로그인")

    # 실행 전 창 목록 스냅샷
    before = _snapshot_hwnd_set()
    print(f"  실행 전 창 개수: {len(before)}")

    print(f"  실행: {APP_PATH}")
    subprocess.Popen(APP_PATH)
    print("  → 6초 대기…"); time.sleep(6)

    # 새로 생긴 창 진단
    after = _snapshot_hwnd_set()
    new_handles = after - before
    print(f"  신규 창 {len(new_handles)}개:")
    new_wins = []
    for w in Desktop(backend="win32").windows():
        try:
            if w.handle in new_handles:
                cls = safe_cls(w); ttl = safe_txt(w)
                r = safe_rect(w)
                print(f"    hwnd={w.handle:#010x}  class={cls!r:<35} title={ttl!r}  rect={r}")
                new_wins.append(w)
        except:
            pass

    login_ok = False

    # 시도 1: pywinauto win32 — 신규 창에서 로그인 창 탐색
    print("\n  [시도 1] pywinauto win32 — 신규 창에서 Edit 컨트롤 탐색")
    login_win, reason = _find_bank24_login_win(before)
    if login_win:
        print(f"    로그인 창 선택: {reason}")
        try:
            edits = [c for c in login_win.descendants()
                     if safe_cls(c) in ("Edit", "TEdit", "TMaskEdit",
                                        "TcxCustomDropDownInnerEdit")]
            print(f"    Edit 컨트롤 {len(edits)}개")
            # y좌표 오름차순 정렬: 위(작은 y) = ID, 아래(큰 y) = PW
            edits.sort(key=lambda c: safe_rect(c)[1])
            for i, e in enumerate(edits):
                print(f"      [{i}] class={safe_cls(e)!r}  rect={safe_rect(e)}")

            if len(edits) >= 2:
                id_ctrl, pw_ctrl = edits[0], edits[1]
                id_ctrl.click_input();  time.sleep(0.2)
                id_ctrl.type_keys("^a", with_spaces=True)
                id_ctrl.type_keys(uid,  with_spaces=True)
                pyperclip.copy(pwd)
                pw_ctrl.click_input();  time.sleep(0.2)
                pw_ctrl.type_keys("^a", with_spaces=True)
                pw_ctrl.type_keys("^v", with_spaces=True)
                time.sleep(0.2)
                pw_ctrl.type_keys("{ENTER}", with_spaces=True)
                login_ok = True
                print("    → pywinauto 로그인 전송 완료")
            else:
                print("    → Edit 부족 — 다음 방법으로 진행")
        except Exception as e:
            print(f"    → 실패: {e}")
        finally:
            pyperclip.copy("")
    else:
        print(f"    → {reason}")

    # 시도 2: 신규 창 중 가장 작은 창의 중앙 좌표 기반 입력
    if not login_ok and new_wins:
        print("\n  [시도 2] 신규 창 상대좌표 방식")
        # 가장 작은 창 = 로그인 다이얼로그 추정
        dlg = min(new_wins, key=lambda w: (safe_rect(w)[2]-safe_rect(w)[0])*(safe_rect(w)[3]-safe_rect(w)[1]))
        l, t, r, b = safe_rect(dlg)
        w_width  = r - l
        w_height = b - t
        print(f"    대상 창: class={safe_cls(dlg)!r}  rect=({l},{t},{r},{b})  {w_width}x{w_height}")
        try:
            dlg.set_focus(); time.sleep(0.3)
            # ID 필드: 창 중앙 상단 1/3 지점
            id_x = l + w_width  // 2
            id_y = t + w_height // 3
            # PW 필드: ID 아래 약 25px
            pw_x = id_x
            pw_y = id_y + 25
            print(f"    ID 클릭: ({id_x},{id_y})  PW 클릭: ({pw_x},{pw_y})")
            pyautogui.click(id_x, id_y); time.sleep(0.4)
            pyautogui.hotkey("ctrl", "a")
            pyautogui.typewrite(uid, interval=0.08)

            pyperclip.copy(pwd)
            pyautogui.click(pw_x, pw_y); time.sleep(0.3)
            pyautogui.hotkey("ctrl", "a")
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.3)
            pyautogui.press("enter")
            login_ok = True
            print("    → 상대좌표 로그인 전송 완료")
        except Exception as e:
            print(f"    → 실패: {e}")
        finally:
            pyperclip.copy("")

    del pwd, uid
    if not login_ok:
        print("  [ERROR] 로그인 전송 실패")
        sys.exit(1)


# ══════════════════════════════════════════════════════════════════════════════
# Step 3. 메인 창 대기
# ══════════════════════════════════════════════════════════════════════════════
def step3_wait_main():
    hdr("Step 3. 메인 창 대기 (최대 20초)")
    deadline = time.time() + 20
    while time.time() < deadline:
        for w in Desktop(backend="win32").windows():
            if safe_cls(w) == MAIN_CLS:
                print(f"\n  → 메인 창: {w.window_text()!r}")
                return w
        sys.stdout.write("."); sys.stdout.flush()
        time.sleep(1)
    print("\n  [ERROR] 메인 창 대기 초과")
    return None


# ══════════════════════════════════════════════════════════════════════════════
# Step 3-B. 검색 필터 적용 (그리드 데이터 확보)
# ══════════════════════════════════════════════════════════════════════════════
def step3b_apply_filter(main_win):
    hdr("Step 3-B. 검색 필터 적용 (담보 / 최근 30일)")
    if not main_win:
        print("  → skip (메인 창 없음)")
        return

    from datetime import datetime, timedelta
    today = datetime.today()
    d_to   = today.strftime("%Y-%m-%d")
    d_from = (today - timedelta(days=30)).strftime("%Y-%m-%d")
    print(f"  날짜 범위: {d_from} ~ {d_to}")

    try:
        # 라디오: 담보(index=3)
        radios = _timed_descendants(main_win, "TcxCustomRadioGroupButton")
        print(f"  라디오 버튼: {len(radios)}개")
        if len(radios) > 3:
            radios[3].click_input()
            print("  → 담보 선택")
            time.sleep(0.3)
        else:
            print("  → 라디오 인덱스 부족 — 건너뜀")
    except Exception as e:
        print(f"  → 라디오 실패: {e}")

    try:
        # 날짜 편집
        inner = _timed_descendants(main_win, "TcxCustomDropDownInnerEdit")
        print(f"  TcxCustomDropDownInnerEdit: {len(inner)}개")
        if len(inner) >= 2:
            for ctrl, val, label in [(inner[1], d_from, "시작일"), (inner[0], d_to, "종료일")]:
                ctrl.click_input(); time.sleep(0.2)
                ctrl.type_keys("^a", with_spaces=True)
                ctrl.type_keys(val,  with_spaces=True)
                ctrl.type_keys("{TAB}", with_spaces=True)
                print(f"  → {label}: {val}")
                time.sleep(0.2)
    except Exception as e:
        print(f"  → 날짜 설정 실패: {e}")

    try:
        # 조회 버튼(TcxButton index=3)
        btns = _timed_descendants(main_win, "TcxButton")
        print(f"  TcxButton: {len(btns)}개")
        if len(btns) >= 4:
            btns[3].click_input()
            print("  → 조회 버튼 클릭")
            time.sleep(3)
        else:
            print("  → 조회 버튼 인덱스 부족")
    except Exception as e:
        print(f"  → 조회 버튼 실패: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# Step 4. 종합접수 창 열기
# ══════════════════════════════════════════════════════════════════════════════
def step4_open_detail(main_win):
    hdr("Step 4. 종합접수(TBnkTop24Rcp) 창 열기")

    def find_detail():
        for w in Desktop(backend="win32").windows():
            if safe_cls(w) == DETAIL_CLS:
                return w
        return None

    existing = find_detail()
    if existing:
        print(f"  → 이미 열려있음: {existing.window_text()!r}")
        return existing

    if main_win:
        try:
            grids = _timed_descendants(main_win, ("TcxGrid", "TDBGrid", "TStringGrid"))
            print(f"  그리드: {len(grids)}개")
            if grids:
                best = max(grids, key=lambda g: g.rectangle().width() * g.rectangle().height())
                r   = best.rectangle()
                cx  = (r.left + r.right) // 2
                cy  = r.top + 60
                print(f"  → 그리드 rect: ({r.left},{r.top},{r.right},{r.bottom})")
                print(f"  → 우클릭: ({cx},{cy})")
                main_win.set_focus(); time.sleep(0.3)
                pyautogui.rightClick(cx, cy); time.sleep(1.2)
                pyautogui.press("0");         time.sleep(3.0)
            else:
                print("  → 그리드 없음 (조회 결과 0건 또는 로드 중)")
        except Exception as e:
            print(f"  → 자동 열기 실패: {e}")

    print("  → TBnkTop24Rcp 폴링 (최대 15초)…")
    deadline = time.time() + 15
    while time.time() < deadline:
        w = find_detail()
        if w:
            print(f"\n  → 발견: {w.window_text()!r}")
            return w
        sys.stdout.write("."); sys.stdout.flush()
        time.sleep(0.5)

    print("\n  [WARN] 종합접수 창 미발견. 현재 열린 창:")
    for w in Desktop(backend="win32").windows():
        try:
            print(f"    class={safe_cls(w)!r:<40} title={safe_txt(w)!r}")
        except:
            pass
    return None


# ══════════════════════════════════════════════════════════════════════════════
# Step 5-A. win32 컨트롤 트리 덤프
# ══════════════════════════════════════════════════════════════════════════════
def step5a_dump_win32(detail_win):
    hdr("Step 5-A. 컨트롤 트리 [win32 backend]")
    try:
        app  = Application(backend="win32").connect(handle=detail_win.handle)
        win  = app.top_window()
        descs = win.descendants()
        print(f"  descendants: {len(descs)}개\n")
        print(f"  {'클래스명':<38} {'텍스트':<35} rect")
        print(f"  {'─'*38} {'─'*35} {'─'*28}")
        for c in descs:
            try:
                cls = safe_cls(c)
                txt = repr(safe_txt(c))[:33]
                l, t, r, b = safe_rect(c)
                print(f"  {cls:<38} {txt:<35} ({l},{t},{r},{b})")
            except:
                pass
        return win, descs
    except Exception as e:
        print(f"  [ERROR] {e}")
        return None, []


# ══════════════════════════════════════════════════════════════════════════════
# Step 5-B. UIA 컨트롤 트리 덤프
# ══════════════════════════════════════════════════════════════════════════════
def step5b_dump_uia(detail_win):
    hdr("Step 5-B. 컨트롤 트리 [UIA backend]")
    try:
        app  = Application(backend="uia").connect(handle=detail_win.handle)
        win  = app.top_window()
        descs = win.descendants()
        print(f"  descendants: {len(descs)}개\n")
        print(f"  {'클래스명':<32} {'control_type':<22} {'name':<30} value")
        print(f"  {'─'*32} {'─'*22} {'─'*30} {'─'*25}")
        for c in descs:
            try:
                cls   = safe_cls(c)
                ctype = str(c.element_info.control_type)[:20]
                name  = repr(safe_txt(c))[:28]
                val   = ""
                try: val = repr(str(c.get_value()))[:23]
                except: pass
                if safe_txt(c) or val:
                    print(f"  {cls:<32} {ctype:<22} {name:<30} {val}")
            except:
                pass
        return win, descs
    except Exception as e:
        print(f"  [ERROR] {e}")
        return None, []


# ══════════════════════════════════════════════════════════════════════════════
# Step 6. 대상 필드 직접 읽기
# ══════════════════════════════════════════════════════════════════════════════
def step6_read_fields(w32_win, descs_w32):
    hdr("Step 6. 대상 필드 직접 읽기")

    LABEL_CLS = ("TLabel", "Static", "TStaticText", "Label")
    EDIT_CLS  = (
        "Edit", "TEdit", "TcxTextEdit", "TcxCustomDropDownInnerEdit",
        "TMemo", "RichEdit", "TMaskEdit", "TcxMemo", "TDBEdit", "TDBMemo",
    )

    labels = [(c, safe_txt(c).strip(), safe_rect(c))
              for c in descs_w32
              if safe_cls(c) in LABEL_CLS and safe_txt(c).strip()]
    edits  = [(c, safe_cls(c), safe_rect(c))
              for c in descs_w32
              if safe_cls(c) in EDIT_CLS]

    print(f"  라벨 {len(labels)}개 / 편집 {len(edits)}개\n")

    def nearest_edit(lL, lT, lR, lB):
        best, best_d = None, 9999
        for ec, ec_cls, (eL, eT, eR, eB) in edits:
            if abs(eT - lT) <= 15 and eL > lL:
                d = eL - lR
                if 0 <= d < best_d:
                    best_d, best = d, (ec, ec_cls)
        return best

    print(f"  {'라벨 텍스트':<22} {'편집 클래스':<32} 값")
    print(f"  {'─'*22} {'─'*32} {'─'*30}")
    label_map: dict[str, str] = {}
    for ctrl, ltxt, (lL, lT, lR, lB) in labels:
        pair = nearest_edit(lL, lT, lR, lB)
        if pair:
            ec, ec_cls = pair
            val = safe_txt(ec).strip()
            print(f"  {ltxt:<22} {ec_cls:<32} {val!r}")
            label_map[ltxt] = val
        else:
            print(f"  {ltxt:<22} (편집 없음)")

    print(f"\n  {'='*62}")
    print(f"  TARGET_FIELDS 읽기 결과")
    print(f"  {'='*62}")

    read_ok:   dict[str, str] = {}
    read_fail: list[str]      = []

    for field in TARGET_FIELDS:
        if field in label_map:
            read_ok[field] = label_map[field]
        else:
            partial = [(k, v) for k, v in label_map.items()
                       if field in k or k in field]
            if partial:
                read_ok[field] = partial[0][1]
                print(f"  [OK partial] {field:<20} ~= {partial[0][0]!r} = {partial[0][1]!r}")
            else:
                read_fail.append(field)

    for f, v in read_ok.items():
        print(f"  [OK  ] {f:<20} = {v!r}")
    for f in read_fail:
        print(f"  [FAIL] {f}")

    if read_fail:
        print("\n  FAIL 필드 대체 방법 후보:")
        for a in [
            "① 클릭 → Ctrl+A Ctrl+C → pyperclip.paste()",
            "② UIA: ctrl.get_value() / ValuePattern",
            "③ pywin32 SendMessage(WM_GETTEXT, handle, ...)",
            "④ pyautogui 좌표 클릭 후 클립보드 복사",
            "⑤ pytesseract OCR",
        ]:
            print(f"    {a}")

    return read_ok, read_fail


# ══════════════════════════════════════════════════════════════════════════════
# Step 7. TcxGrid 주소 목록 읽기
# ══════════════════════════════════════════════════════════════════════════════
def step7_read_grid(detail_win, descs_w32):
    hdr("Step 7. TcxGrid 주소 목록 읽기")

    GRID_CLS = (
        "TcxGrid", "TDBGrid", "TStringGrid", "TcxGridSite",
        "TcxGridTableView", "TcxGridDBTableView",
    )
    grids = [(c, safe_cls(c), safe_rect(c))
             for c in descs_w32 if safe_cls(c) in GRID_CLS]

    print(f"  그리드 컨트롤: {len(grids)}개")
    for i, (c, cls, rect) in enumerate(grids):
        w = rect[2] - rect[0]; h = rect[3] - rect[1]
        print(f"    [{i}] {cls:<32} rect={rect}  {w}x{h}")

    if not grids:
        print("\n  → 그리드 없음. 대체 방법:")
        print("    ① Ctrl+A Ctrl+C → pandas.read_clipboard()")
        print("    ② WM_GETTEXT / SendMessage (pywin32)")
        print("    ③ OCR")
        return

    # 가장 큰 그리드 클립보드 테스트
    largest = max(grids, key=lambda x: (x[2][2]-x[2][0]) * (x[2][3]-x[2][1]))
    _, cls, (l, t, r, b) = largest
    cx = (l + r) // 2
    cy = t + 35

    print(f"\n  클립보드 복사 테스트: {cls} → click({cx},{cy})")
    try:
        detail_win.set_focus(); time.sleep(0.3)
        pyautogui.click(cx, cy); time.sleep(0.4)
        pyperclip.copy("")
        pyautogui.hotkey("ctrl", "c"); time.sleep(0.6)
        val = pyperclip.paste()
        if val:
            print(f"  → 클립보드 값: {val[:200]!r}")
        else:
            print("  → 빈값 (셀 미선택 또는 Ctrl+C 미지원)")
    except Exception as e:
        print(f"  → 실패: {e}")

    print("\n  TcxGrid 읽기 대체 방법 후보:")
    for a in [
        "① 전체 Ctrl+A Ctrl+C → pandas.read_clipboard()",
        "② 행 단위 Down+Ctrl+C 반복",
        "③ pywin32 SendMessage(LVM_GETITEMTEXT)",
        "④ pytesseract OCR",
    ]:
        print(f"    {a}")


# ══════════════════════════════════════════════════════════════════════════════
# Step 8. 결과 요약
# ══════════════════════════════════════════════════════════════════════════════
def step8_summary(read_ok, read_fail):
    hdr("Step 8. 결과 요약 및 다음 단계 추천")
    total = len(TARGET_FIELDS)
    print(f"  대상 {total}개  /  성공 {len(read_ok)}개  /  실패 {len(read_fail)}개\n")

    if read_ok:
        print("  읽기 성공:")
        for f, v in read_ok.items():
            print(f"    {f:<20} = {v!r}")

    if read_fail:
        print("\n  읽기 실패 (대체 방법 필요):")
        for f in read_fail:
            print(f"    {f}")

    print("\n  다음 단계 추천:")
    for s in [
        "1. FAIL 필드: 클립보드/UIA 방식 개별 검증 후 DataReader 확정",
        "2. TcxGrid 주소: Ctrl+A Ctrl+C → pandas.read_clipboard() 검증",
        "3. 종합접수 자동 열기(우클릭 '0') 재현 여부 확인",
        "4. win32/UIA 결과 기반 Y_BankAuto DataReader 클래스 설계",
        "5. 전체 플로우(조회→읽기→DB) 재설계 착수",
    ]:
        print(f"    {s}")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
def main():
    print("=" * 64)
    print("  Bank24 TBnkTop24Rcp 읽기 테스트 (자동 실행)")
    print("  읽기 전용 — 파일/DB 수정 없음")
    print("=" * 64)

    uid, pwd = step0_load_creds()
    step1_check_running()
    step2_launch_login(uid, pwd)

    main_win = step3_wait_main()
    if main_win is None:
        print("[ABORT] 메인 창 미발견")
        sys.exit(1)

    time.sleep(2)
    step3b_apply_filter(main_win)

    detail_win = step4_open_detail(main_win)
    if detail_win is None:
        print("[ABORT] 종합접수 창 없음 — 그리드 데이터 확인 필요")
        sys.exit(1)

    time.sleep(1)

    w32_win, descs_w32 = step5a_dump_win32(detail_win)
    step5b_dump_uia(detail_win)

    if w32_win is None:
        print("[ABORT] win32 연결 실패")
        sys.exit(1)

    read_ok, read_fail = step6_read_fields(w32_win, descs_w32)
    step7_read_grid(detail_win, descs_w32)
    step8_summary(read_ok, read_fail)

    print(f"\n{'='*64}\n  테스트 완료\n{'='*64}")


if __name__ == "__main__":
    main()
