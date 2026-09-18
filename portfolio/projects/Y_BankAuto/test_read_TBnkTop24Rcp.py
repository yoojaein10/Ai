#!/usr/bin/env python3
"""
Bank24 종합접수(TBnkTop24Rcp) pywinauto 읽기 테스트
- 읽기 전용: Bank24 데이터 파일·DB 수정 없음
- 자격증명: 코드·로그·파일에 저장 안 함
"""
import sys
import time
import getpass
import subprocess

# Windows 터미널 UTF-8 출력 (특수문자 깨짐 방지)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ── 의존성 체크 ────────────────────────────────────────────────────────────────
MISSING = []
try:
    from pywinauto import Application, Desktop
    from pywinauto.keyboard import send_keys
except ImportError:
    MISSING.append("pywinauto")
try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.2
except ImportError:
    MISSING.append("pyautogui")
try:
    import pyperclip
except ImportError:
    MISSING.append("pyperclip")

if MISSING:
    print(f"[ERROR] 미설치 패키지: {', '.join(MISSING)}")
    print(f"       pip install {' '.join(MISSING)}")
    sys.exit(1)

# ── 상수 ───────────────────────────────────────────────────────────────────────
APP_PATH   = r"C:\KADC\X11\Bank24.exe"
EXE_NAME   = "bank24.exe"
MAIN_CLS   = "TfrmMain"
DETAIL_CLS = "TBnkTop24Rcp"

TARGET_FIELDS = [
    "감정서번호", "의뢰번호", "영업점", "담당자",
    "담당자 연락처", "채무자", "소유자", "안심번호", "비고",
]

# 로그인 좌표 폴백 (이전 BankAuto 검증값, 해상도 고정 시 유효)
LOGIN_ID_XY = (997, 538)
LOGIN_PW_XY = (997, 563)

SEP = "─" * 64

# ── 헬퍼 ───────────────────────────────────────────────────────────────────────
def hdr(title: str):
    print(f"\n{SEP}\n  {title}\n{SEP}")

def safe_cls(c):
    try:    return c.class_name()
    except: return "?"

def safe_txt(c):
    try:    return c.window_text()
    except: return ""

def safe_rect(c):
    try:
        r = c.rectangle()
        return (r.left, r.top, r.right, r.bottom)
    except:
        return (0, 0, 0, 0)

def tasklist_has(exe: str) -> bool:
    r = subprocess.run(
        ["tasklist", "/FI", f"IMAGENAME eq {exe}"],
        capture_output=True, text=True, encoding="cp949", errors="replace"
    )
    return exe.lower() in r.stdout.lower()


# ══════════════════════════════════════════════════════════════════════════════
# Step 1. 실행 중인 Bank24.exe 정리
# ══════════════════════════════════════════════════════════════════════════════
def step1_check_running():
    hdr("Step 1. Bank24.exe 실행 여부 확인")

    if not tasklist_has(EXE_NAME):
        print("  → 실행 중 아님 ✓")
        return

    print("  → 실행 감지: 정상 종료 시도 (창 닫기)…")
    try:
        app = Application(backend="win32").connect(class_name=MAIN_CLS, timeout=4)
        app.top_window().close()
        time.sleep(3)
        if not tasklist_has(EXE_NAME):
            print("  → 정상 종료 완료 ✓")
            return
        print("  → 창 닫기 후에도 프로세스 잔류")
    except Exception as e:
        print(f"  → 정상 종료 실패: {e}")

    print()
    print("  !! 정상 종료 불가 상태입니다.")
    print("  !! 강제 종료(taskkill /F) 없이는 안전한 재시작이 어렵습니다.")
    ans = input("  강제 종료 후 계속 진행하시겠습니까? (y/n): ").strip().lower()
    if ans == "y":
        subprocess.run(["taskkill", "/F", "/IM", EXE_NAME], capture_output=True)
        time.sleep(2)
        print("  → 강제 종료 완료")
    else:
        print("  → 사용자 취소. 종료합니다.")
        sys.exit(0)


# ══════════════════════════════════════════════════════════════════════════════
# Step 2. 실행 + 로그인
# ══════════════════════════════════════════════════════════════════════════════
def step2_launch_login():
    hdr("Step 2. Bank24.exe 실행 및 로그인")

    print("  [로그인 정보 입력 — 파일·로그·메모리에 저장되지 않음]")
    uid = input("  ID: ").strip()
    pwd = getpass.getpass("  PW (입력 내용 화면 미표시): ")

    print(f"\n  실행: {APP_PATH}")
    subprocess.Popen(APP_PATH)
    print("  → 4초 대기…")
    time.sleep(4)

    login_ok = False

    # ── 시도 1: pywinauto win32 ──────────────────────────────────────────────
    print("  [시도 1] pywinauto win32 로그인 창 탐색")
    try:
        login_win = None
        deadline = time.time() + 8
        while time.time() < deadline and not login_win:
            for w in Desktop(backend="win32").windows():
                cls = safe_cls(w)
                ttl = safe_txt(w)
                if any(k in cls.lower() for k in ("login", "dx")) or \
                   any(k in ttl     for k in ("로그인", "Login")):
                    login_win = w
                    print(f"    로그인 창: class={cls!r}, title={ttl!r}")
                    break
            if not login_win:
                time.sleep(0.5)

        if login_win:
            edits = [c for c in login_win.descendants()
                     if safe_cls(c) in ("Edit", "TEdit", "TMaskEdit",
                                        "TcxCustomDropDownInnerEdit")]
            print(f"    Edit 컨트롤 {len(edits)}개")
            if len(edits) >= 2:
                edits[0].click_input(); time.sleep(0.2)
                edits[0].type_keys("^a", with_spaces=True)
                edits[0].type_keys(uid,  with_spaces=True)
                pyperclip.copy(pwd)
                edits[1].click_input(); time.sleep(0.2)
                edits[1].type_keys("^a", with_spaces=True)
                edits[1].type_keys("^v", with_spaces=True)
                time.sleep(0.2)
                edits[1].type_keys("{ENTER}", with_spaces=True)
                login_ok = True
                print("    → pywinauto 로그인 전송 완료")
        else:
            print("    → 로그인 창 미발견 (보안 모듈 간섭 추정)")
    except Exception as e:
        print(f"    → 실패: {e}")
    finally:
        pyperclip.copy("")  # 클립보드 즉시 클리어

    # ── 시도 2: pyautogui 좌표 폴백 ─────────────────────────────────────────
    if not login_ok:
        print(f"  [시도 2] pyautogui 좌표 폴백 ({LOGIN_ID_XY}, {LOGIN_PW_XY})")
        try:
            pyautogui.click(*LOGIN_ID_XY); time.sleep(0.4)
            pyautogui.hotkey("ctrl", "a")
            pyautogui.typewrite(uid, interval=0.08)

            pyperclip.copy(pwd)
            pyautogui.click(*LOGIN_PW_XY); time.sleep(0.3)
            pyautogui.hotkey("ctrl", "a")
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.3)
            pyautogui.press("enter")
            login_ok = True
            print("    → pyautogui 로그인 전송 완료")
        except Exception as e:
            print(f"    → 실패: {e}")
        finally:
            pyperclip.copy("")

    # 자격증명 메모리 해제
    uid_hint = uid[:2] + "***" if len(uid) > 2 else "***"
    del pwd, uid

    if not login_ok:
        print(f"  [ERROR] 로그인 전송 실패 (ID hint: {uid_hint})")
        sys.exit(1)

    print(f"  → 로그인 전송 완료 (ID hint: {uid_hint})")


# ══════════════════════════════════════════════════════════════════════════════
# Step 3. 메인 창 대기
# ══════════════════════════════════════════════════════════════════════════════
def step3_wait_main():
    hdr("Step 3. 메인 창 대기 (최대 20초)")

    deadline = time.time() + 20
    while time.time() < deadline:
        for w in Desktop(backend="win32").windows():
            if safe_cls(w) == MAIN_CLS:
                print(f"  → 메인 창: {w.window_text()!r}")
                return w
        sys.stdout.write("."); sys.stdout.flush()
        time.sleep(1)

    print("\n  [ERROR] 메인 창 대기 시간 초과")
    return None


# ══════════════════════════════════════════════════════════════════════════════
# Step 4. 종합접수 창 열기 또는 대기
# ══════════════════════════════════════════════════════════════════════════════
def step4_open_detail(main_win):
    hdr("Step 4. 종합접수(TBnkTop24Rcp) 창 열기")

    auto_tried = False
    if main_win:
        try:
            grids = [c for c in main_win.descendants()
                     if safe_cls(c) in ("TcxGrid", "TDBGrid", "TStringGrid")]
            if grids:
                best = max(grids, key=lambda g: (
                    g.rectangle().width() * g.rectangle().height()
                ))
                r   = best.rectangle()
                cx  = (r.left + r.right) // 2
                cy  = r.top + 60
                print(f"  → 그리드: ({r.left},{r.top},{r.right},{r.bottom}) size={r.width()}x{r.height()}")
                print(f"  → 우클릭 + '0' 단축키 시도: ({cx},{cy})")
                main_win.set_focus(); time.sleep(0.3)
                pyautogui.rightClick(cx, cy); time.sleep(1.2)
                pyautogui.press("0");         time.sleep(2.5)
                auto_tried = True
            else:
                print("  → 그리드 미발견 (조회 결과 없음 또는 아직 조회 전)")
        except Exception as e:
            print(f"  → 자동 열기 실패: {e}")

    if not auto_tried:
        print()
        print("  !! 종합접수 창을 직접 열어주세요.")

    input("\n  → 종합접수 창이 열렸으면 Enter를 눌러 계속하세요: ")

    # 창 탐색
    for _ in range(12):
        for w in Desktop(backend="win32").windows():
            if safe_cls(w) == DETAIL_CLS:
                print(f"  → {DETAIL_CLS} 발견: {w.window_text()!r}")
                return w
        time.sleep(0.5)

    print(f"\n  [WARN] {DETAIL_CLS} 창을 찾지 못했습니다.")
    print("  현재 열린 창 목록:")
    for w in Desktop(backend="win32").windows():
        try:
            print(f"    class={safe_cls(w)!r:<40} title={safe_txt(w)!r}")
        except:
            pass
    return None


# ══════════════════════════════════════════════════════════════════════════════
# Step 5-A. 컨트롤 트리 덤프 — win32
# ══════════════════════════════════════════════════════════════════════════════
def step5a_dump_win32(detail_win):
    hdr("Step 5-A. 컨트롤 트리 [win32 backend]")
    try:
        app = Application(backend="win32").connect(handle=detail_win.handle)
        win = app.top_window()
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
# Step 5-B. 컨트롤 트리 덤프 — UIA
# ══════════════════════════════════════════════════════════════════════════════
def step5b_dump_uia(detail_win):
    hdr("Step 5-B. 컨트롤 트리 [UIA backend]")
    try:
        app = Application(backend="uia").connect(handle=detail_win.handle)
        win = app.top_window()
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
# Step 6. 대상 필드 읽기
# ══════════════════════════════════════════════════════════════════════════════
def step6_read_fields(w32_win, descs_w32):
    hdr("Step 6. 대상 필드 직접 읽기")

    LABEL_CLS = ("TLabel", "Static", "TStaticText", "Label")
    EDIT_CLS  = ("Edit", "TEdit", "TcxTextEdit", "TcxCustomDropDownInnerEdit",
                 "TMemo", "RichEdit", "TMaskEdit", "TcxMemo", "TDBEdit", "TDBMemo")

    labels = [(c, safe_txt(c).strip(), safe_rect(c))
              for c in descs_w32 if safe_cls(c) in LABEL_CLS and safe_txt(c).strip()]
    edits  = [(c, safe_cls(c), safe_rect(c))
              for c in descs_w32 if safe_cls(c) in EDIT_CLS]

    print(f"  라벨 {len(labels)}개 / 편집 컨트롤 {len(edits)}개\n")

    def nearest_edit(lL, lT, lR, lB):
        best, best_d = None, 9999
        for ec, ec_cls, (eL, eT, eR, eB) in edits:
            # 수직 겹침 허용 ±15px
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

    # TARGET_FIELDS 매핑
    print(f"\n  {'═'*62}")
    print(f"  대상 필드 읽기 결과")
    print(f"  {'═'*62}")

    read_ok: dict[str, str] = {}
    read_fail: list[str]    = []

    for field in TARGET_FIELDS:
        if field in label_map:
            read_ok[field] = label_map[field]
        else:
            partial = [(k, v) for k, v in label_map.items()
                       if field in k or k in field]
            if partial:
                read_ok[field] = partial[0][1]
                print(f"  [OK  partial] {field:<20} ≈ '{partial[0][0]}' = {partial[0][1]!r}")
            else:
                read_fail.append(field)

    for f, v in read_ok.items():
        print(f"  [OK  ] {f:<20} = {v!r}")
    for f in read_fail:
        print(f"  [FAIL] {f}")

    if read_fail:
        print(f"\n  [FAIL 필드 대체 방법 후보]")
        alts = [
            "① 해당 컨트롤 클릭 → Ctrl+A Ctrl+C → pyperclip.paste()",
            "② UIA ValuePattern: ctrl.get_value()",
            "③ SendMessage(WM_GETTEXT) via pywin32 win32gui",
            "④ pyautogui 좌표 클릭 후 클립보드 복사",
            "⑤ 스크린샷 + OCR (pytesseract)",
        ]
        for a in alts:
            print(f"    {a}")

    return read_ok, read_fail


# ══════════════════════════════════════════════════════════════════════════════
# Step 7. TcxGrid 주소 목록 읽기
# ══════════════════════════════════════════════════════════════════════════════
def step7_read_grid(detail_win, descs_w32):
    hdr("Step 7. TcxGrid 주소 목록 읽기")

    GRID_CLS = ("TcxGrid", "TDBGrid", "TStringGrid", "TcxGridSite",
                "TcxGridTableView", "TcxGridDBTableView")
    grids = [(c, safe_cls(c), safe_rect(c))
             for c in descs_w32 if safe_cls(c) in GRID_CLS]

    print(f"  그리드 컨트롤: {len(grids)}개")
    for i, (c, cls, rect) in enumerate(grids):
        print(f"    Grid[{i}]: {cls:<30} rect={rect}  size={rect[2]-rect[0]}x{rect[3]-rect[1]}")

    if not grids:
        print("\n  그리드 컨트롤 없음 — 대체 방법 후보:")
        print("    ① 그리드 클릭 → Ctrl+A Ctrl+C → pandas.read_clipboard()")
        print("    ② WM_GETTEXT / 커스텀 메시지 (pywin32)")
        print("    ③ 스크린샷 + OCR")
        return

    # 가장 큰 그리드: 클립보드 복사 테스트
    largest = max(grids, key=lambda x: (x[2][2]-x[2][0]) * (x[2][3]-x[2][1]))
    _, cls, (l, t, r, b) = largest
    cx = (l + r) // 2
    cy = t + 35  # 헤더 아래 첫 행 추정

    print(f"\n  클립보드 복사 테스트: 가장 큰 그리드({cls}) → ({cx},{cy})")
    try:
        detail_win.set_focus(); time.sleep(0.3)
        pyautogui.click(cx, cy); time.sleep(0.4)
        pyperclip.copy("")
        pyautogui.hotkey("ctrl", "c"); time.sleep(0.6)
        val = pyperclip.paste()
        if val:
            print(f"  → 클립보드: {val[:120]!r}")
        else:
            print("  → 클립보드 빈값 (셀 선택 실패 또는 Ctrl+C 미지원)")
    except Exception as e:
        print(f"  → 클립보드 테스트 실패: {e}")

    print()
    print("  TcxGrid 셀 직접 읽기 방법 후보:")
    print("    ① 전체 선택(Ctrl+A) → Ctrl+C → pandas.read_clipboard()")
    print("    ② 행 단위 Down+Ctrl+C 반복")
    print("    ③ pywin32 SendMessage(LVM_GETITEMTEXT)")
    print("    ④ 스크린샷 + pytesseract OCR")


# ══════════════════════════════════════════════════════════════════════════════
# Step 8. 결과 요약
# ══════════════════════════════════════════════════════════════════════════════
def step8_summary(read_ok: dict, read_fail: list):
    hdr("Step 8. 결과 요약 및 다음 단계 추천")

    total = len(TARGET_FIELDS)
    print(f"  대상 {total}개  /  성공 {len(read_ok)}개  /  실패 {len(read_fail)}개\n")

    if read_ok:
        print("  ✓ 읽기 성공:")
        for f, v in read_ok.items():
            print(f"    {f:<20} = {v!r}")

    if read_fail:
        print("\n  ✗ 읽기 실패 (대체 방법 필요):")
        for f in read_fail:
            print(f"    {f}")

    print("\n  [다음 단계 추천]")
    steps = [
        "1. FAIL 필드: 클립보드 복사(Ctrl+C) 개별 검증 → DataReader 확정",
        "2. TcxGrid 주소: Ctrl+A Ctrl+C → pandas.read_clipboard() 검증",
        "3. 종합접수 창 자동 열기(우클릭 메뉴 '0') 재현 여부 확인",
        "4. win32/UIA 결과 기반으로 Y_BankAuto DataReader 클래스 설계",
        "5. 전체 플로우(조회→PDF저장→파싱→DB) 재설계 착수",
    ]
    for s in steps:
        print(f"    {s}")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
def main():
    print("=" * 64)
    print("  Bank24 종합접수(TBnkTop24Rcp) pywinauto 읽기 테스트")
    print("  읽기 전용 — 파일/DB 수정 없음")
    print("=" * 64)

    step1_check_running()
    step2_launch_login()

    main_win = step3_wait_main()
    if main_win is None:
        print("[ABORT] 메인 창 미발견")
        sys.exit(1)

    time.sleep(2)  # 메인 창 완전 로드 대기

    detail_win = step4_open_detail(main_win)
    if detail_win is None:
        print("[ABORT] 종합접수 창 미발견")
        sys.exit(1)

    w32_win, descs_w32 = step5a_dump_win32(detail_win)
    _,       _         = step5b_dump_uia(detail_win)

    if w32_win is None:
        print("[ABORT] win32 연결 실패")
        sys.exit(1)

    read_ok, read_fail = step6_read_fields(w32_win, descs_w32)
    step7_read_grid(detail_win, descs_w32)
    step8_summary(read_ok, read_fail)

    print(f"\n{'='*64}")
    print("  테스트 완료")
    print(f"{'='*64}")


if __name__ == "__main__":
    main()
