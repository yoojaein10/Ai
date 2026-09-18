"""수협·하나 인계번들 라이브 검증 — BANK24 를 열어 문서 5건씩 폼을 열고 채울값↔화면 대조.

읽기 전용(작성/열람 폼을 열어 읽기만, 값 변경 없음). 번들 도구(build_fill_ssb/hnb)를 그대로 사용.
안전규칙: '찾 기' 결과 그리드에 **대상 문서 행이 실제로 있을 때만** Shift+F10/가속키를 보낸다
(빈 그리드에 키를 보내면 다른 앱으로 새는 것을 실측 — Excel 찾기창이 떴다).
탭은 발송완료 → 작성 → 전체 순으로 찾는다(실사완료 건은 대개 발송완료 탭).
"""
import ctypes, os, subprocess, sys, time, traceback
from pathlib import Path

BUNDLE = Path(r"D:\AI\Claude\Bank_Bal\수협_하나_인계번들")
HERE = Path(__file__).resolve().parent
os.chdir(HERE)                       # work/ · output/ 는 스크래치에 생성(번들 오염 방지)
sys.path.insert(0, str(BUNDLE / "src"))
sys.path.insert(0, str(BUNDLE / "tools"))
os.environ.setdefault("PYTHONUTF8", "1")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import pyperclip                                # noqa: E402
from PIL import ImageGrab                       # noqa: E402
from pywinauto import Desktop                   # noqa: E402
from pywinauto.keyboard import send_keys        # noqa: E402
from bankon.config import load_config          # noqa: E402
from bankon.ui import driver, navigate          # noqa: E402
import verify_fill_ssb as VF_SSB                # noqa: E402
import verify_fill_hnb as VF_HNB                # noqa: E402

PLAN = [
    ("수협", "TBNKSSB24DAMB", VF_SSB.build_fill_ssb,
     ["01-2609-3-2785", "01-2609-3-2759", "01-2608-3-2740", "01-2608-3-2694", "01-2608-3-2660"]),
    ("하나", "TBNKHNB24DAMB", VF_HNB.build_fill_hnb,
     ["01-2609-3-2777", "01-2609-3-2751", "01-2608-3-2746", "01-2608-3-2729", "01-2608-3-2722"]),
]
ORDER = {"❌불일치": 0, "🖊우리채움": 1, "📄화면만": 2, "✅일치": 3}
# 상단 toolbar(TdxBarControl 'toolbar') 상대좌표 — BankOn navigate.TAB_COORDS 실측값.
TOP = {"전체": (36, 28), "작성": (205, 29), "발송완료": (329, 29)}
TAB_ORDER = ("발송완료", "작성", "전체")
BM_CLICK = 0x00F5
_STATE = {"tab": None}


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def kill_stale(pids: list[int]) -> None:
    for pid in pids:
        if pid == os.getpid():
            continue
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True).stdout or b""
        if b"python" in out.lower():
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
            log(f"stale python {pid} killed")
        else:
            log(f"pid {pid}: python 아님/없음 — 건너뜀")


def shot(tag: str) -> None:
    try:
        ImageGrab.grab().save(str(HERE / f"diag_{tag}.png"))
        log(f"screenshot diag_{tag}.png")
    except Exception as e:  # noqa: BLE001
        log(f"screenshot 실패 {e!r}")


def _desc(main_handle: int, cls: str, text: str | None = None):
    w = Desktop(backend="win32").window(handle=main_handle)
    for c in w.descendants():
        try:
            if c.class_name() == cls and (text is None or c.window_text().strip() == text):
                return c
        except Exception:
            continue
    return None


def click_message(control) -> None:
    ctypes.windll.user32.SendMessageW(int(control.handle), BM_CLICK, 0, 0)


def focus_main(session) -> None:
    try:
        driver.window(session.main.handle).set_focus()
        time.sleep(0.4)
    except Exception:
        pass


def grid_rows(session) -> list[str]:
    """포커스 그리드 Ctrl+C 텍스트에서 데이터 행(헤더 제외)."""
    grids = driver.by_class(session.main.handle, "TcxGridSite")
    if not grids:
        return []
    grid = max(grids, key=lambda g: (g.rectangle().right - g.rectangle().left) * (g.rectangle().bottom - g.rectangle().top))
    focus_main(session)
    grid.set_focus()
    time.sleep(0.3)
    pyperclip.copy("")
    send_keys("^c")
    time.sleep(0.4)
    text = pyperclip.paste() or ""
    return [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("은  행")]


def click_top(session, name: str) -> None:
    bar = _desc(session.main.handle, "TdxBarControl", "toolbar")
    if bar is None:
        log("toolbar 못 찾음")
        return
    focus_main(session)
    bar.click_input(coords=TOP[name])
    log(f"상단 '{name}' 클릭 {TOP[name]}")
    time.sleep(1.5)


def set_conditions(session, start: str, end: str) -> None:
    main = session.main.handle
    for name in ("담 보", "직접입력"):
        r = _desc(main, "TcxCustomRadioGroupButton", name)
        if r is not None:
            click_message(r)
            time.sleep(0.3)
    for label, value in (("조회시작일", start), ("조회종료일", end)):
        edit = driver.find_by_label(main, label, "TcxDateEdit")
        if edit is not None:
            driver.set_text(edit, value, verify=False)
    for label in (navigate.SEARCH_LABEL, "의뢰번호조회"):
        edit = driver.find_by_label(main, label, "TcxTextEdit")
        if edit is not None:
            driver.set_text(edit, "", verify=False)


def press_query(session) -> None:
    button = driver.by_text(session.main.handle, navigate.QUERY_BUTTON, "TcxButton")
    if button is None:
        raise navigate.NavigationError("'조 회' 버튼 못 찾음")
    focus_main(session)
    button.click_input()
    time.sleep(4.0)


def goto_tab(session, tab: str, span) -> int:
    if _STATE["tab"] == tab:
        return -1
    click_top(session, tab)
    set_conditions(session, *span)
    press_query(session)
    rows = grid_rows(session)
    _STATE["tab"] = tab
    log(f"탭 '{tab}' 조회 {span}: {len(rows)}행 (첫 행 {rows[0][:70]!r})" if rows else f"탭 '{tab}' 조회 {span}: 0행")
    return len(rows)


def locate_doc(session, doc: str, span) -> str | None:
    """탭을 돌며 '찾 기'로 대상 행을 잡는다. 잡힌 탭 이름, 없으면 None. (키 주입 없음)"""
    order = [t for t in TAB_ORDER if t == _STATE["tab"]] + [t for t in TAB_ORDER if t != _STATE["tab"]]
    for tab in order:
        goto_tab(session, tab, span)
        focus_main(session)
        navigate.find_document(session, doc)
        rows = grid_rows(session)
        hit = [r for r in rows if doc in r]
        log(f"  찾기 {doc} @ {tab}: {len(rows)}행, 대상행 {'있음' if hit else '없음'}"
            + (f" → {hit[0][:80]!r}" if hit else ""))
        if hit:
            return tab
    return None


def main() -> int:
    log(f"start pid={os.getpid()} argv={sys.argv[1:]}")
    kill_stale([int(a) for a in sys.argv[1:] if a.isdigit()])
    cfg = load_config(r"D:\AI\Claude\Bank_Bal\BankOn\.env")
    session = navigate.open_app(cfg.loader_cmd, cfg.bankon_user, cfg.bankon_password)
    log(f"BANK24 main handle={session.main.handle} pid={session.pid}")
    navigate.close_forms(session)
    navigate.close_context_menu()
    span = navigate.range_for(PLAN[0][3][0])
    shot("0_start")
    summary = []
    for bank, cls, build, docs in PLAN:
        for doc in docs:
            t0 = time.time()
            print(f"\n===== {bank} {doc} =====", flush=True)
            try:
                tab = locate_doc(session, doc, span)
                if tab is None:
                    print("  ⚠ 어느 탭에서도 대상 행 없음 — 건너뜀(키 주입 안 함)", flush=True)
                    summary.append((bank, doc, "목록에 없음(건너뜀)"))
                    continue
                focus_main(session)
                form = navigate.open_write_form(session)
                if form.class_name != cls:
                    print(f"  ⚠ 열린 폼 클래스={form.class_name} (기대 {cls}) — 건너뜀", flush=True)
                    summary.append((bank, doc, "폼클래스 불일치 " + form.class_name))
                    continue
                rows = build(cfg, doc, form)
                for mark, label, ours, theirs in sorted(rows, key=lambda r: (ORDER[r[0]], r[1])):
                    print(f"  [{mark:6}] {label[:18]:20} 채울값={ours[:28]:30} 화면={theirs[:26]}", flush=True)
                cnt = {m: sum(1 for r in rows if r[0] == m) for m in ORDER}
                line = " ".join(f"{m}{n}" for m, n in cnt.items())
                print(f"  -- {line}  [{tab}] ({time.time() - t0:.0f}s)", flush=True)
                summary.append((bank, doc, line))
            except Exception as e:  # noqa: BLE001
                print(f"  ✖ 오류: {e!r}", flush=True)
                traceback.print_exc()
                summary.append((bank, doc, f"오류 {type(e).__name__}: {str(e)[:60]}"))
                shot(f"err_{doc}")
                try:
                    navigate.close_context_menu()
                except Exception:
                    pass
            finally:
                try:
                    navigate.close_forms(session)
                except Exception as e:  # noqa: BLE001
                    print(f"  (close_forms 실패: {e!r})", flush=True)
    print("\n===== SUMMARY =====", flush=True)
    for bank, doc, line in summary:
        print(f"  {bank} {doc}: {line}", flush=True)
    log("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
