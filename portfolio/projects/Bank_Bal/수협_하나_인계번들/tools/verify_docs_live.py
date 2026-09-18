r"""문서번호를 지정해 BANK24 폼을 **자동으로 열고** 채울값↔화면을 대조한다 (수협·하나, 읽기 전용).

verify_fill_ssb/hnb 는 "사람이 폼을 열어 둔 상태"를 전제하지만, 이 도구는 BANK24 실행·로그인 →
탭 전환 → 조회 → '찾 기' → 작성(열람) 폼 열기 → 대조 → 닫기 를 문서마다 반복한다.
화면엔 쓰지 않는다(작성/열람 폼 읽기만).

    (관리자) python tools\verify_docs_live.py --bank ssb 01-2609-3-2785 01-2609-3-2759
    (관리자) python tools\verify_docs_live.py --bank hnb --recent 5        # DB에서 실사완료 최근 5건
    (관리자) python tools\verify_docs_live.py --bank ssb --recent 5 --log reports\ssb_live.log

⭐ 관리자 권한 필요(BANK24 가 requireAdministrator 라 키 주입이 UIPI 에 막힌다). 승격 cmd 에서 실행하거나
   `powershell -File tools\elevated_verify.ps1 -Bank ssb -Recent 5` 로.

실측으로 굳힌 규칙(2026-09-08, 수협 5건·하나 4건 전건 불일치 0):
  · 실사완료(=작성·발송 끝난) 건은 **발송완료 탭**(또는 전체)에 있다 — 작성 탭엔 미발송 건만.
    탭은 상단 toolbar(TdxBarControl 'toolbar') 상대좌표 click_input, 라디오는 BM_CLICK, '조 회'는 click_input.
  · 캡션 '국민은행 현장재조사 미발송 건 (최근 6개월)' 은 stale 표시 — 무시하고 그리드 행으로 판단한다.
  · **'찾 기' 결과 그리드에 대상 행이 있을 때만** Shift+F10/가속키를 보낸다. 빈 그리드에 키를 보내면 다른
    앱으로 샌다(실측: Excel 찾기창이 떴다). 행 확인은 그리드 Ctrl+C 텍스트에 문서번호 포함 여부.
  · 아직 작성 전인 문서는 BANK24 에 감정서번호가 없어 '찾 기'로 안 잡힌다 → 건너뛴다(정상).
"""
from __future__ import annotations

import argparse
import ctypes
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pyperclip                                # noqa: E402
from pywinauto import Desktop                   # noqa: E402
from pywinauto.keyboard import send_keys        # noqa: E402
from bankon.config import load_config          # noqa: E402
from bankon.db import connect                   # noqa: E402
from bankon.ui import driver, navigate          # noqa: E402
import verify_fill_ssb as VF_SSB                # noqa: E402
import verify_fill_hnb as VF_HNB                # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parent.parent

BANKS = {
    "ssb": {"name": "수협", "cls": "TBNKSSB24DAMB", "build": VF_SSB.build_fill_ssb, "cust_like": "%수%협%"},
    "hnb": {"name": "하나", "cls": "TBNKHNB24DAMB", "build": VF_HNB.build_fill_hnb, "cust_like": "%하나은행%"},
}
ORDER = {"❌불일치": 0, "🖊우리채움": 1, "📄화면만": 2, "✅일치": 3}
# 상단 toolbar('toolbar' TdxBarControl) 상대좌표 — BankOn navigate.TAB_COORDS 실측값(2026-08-25).
TAB_COORDS = {"전체": (36, 28), "작성": (205, 29), "발송완료": (329, 29)}
TAB_ORDER = ("발송완료", "작성", "전체")
BM_CLICK = 0x00F5
GRID_HEADER_PREFIX = "은  행"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def pick_recent(cfg, bank: str, limit: int) -> list[str]:
    """의뢰처가 그 은행인 **실사완료** 담보 문서를 최근 순으로(fetch_docs.pick_docs 와 같은 기준)."""
    with connect(cfg.source_sql, readonly=True) as s:
        c = s.cursor()
        c.execute(
            """SELECT TOP (?) DocID FROM apw_masterex
               WHERE LWorkinfo=N'담보' AND CustName LIKE ?
                 AND DocID LIKE '01-2[56]%-3-%' AND ConductDate IS NOT NULL
               ORDER BY DocID DESC""", limit, BANKS[bank]["cust_like"])
        return [r[0] for r in c.fetchall()]


# ── 메인 목록 조작 ─────────────────────────────────────────────────────────────

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
    """BM_CLICK — DevExpress 라디오는 click_input 이 포커스만 옮기고 선택을 못 바꾼다(BankOn 실측)."""
    ctypes.windll.user32.SendMessageW(int(control.handle), BM_CLICK, 0, 0)


def focus_main(session) -> None:
    try:
        driver.window(session.main.handle).set_focus()
        time.sleep(0.4)
    except Exception:
        pass


def grid_rows(session) -> list[str]:
    """결과 그리드 Ctrl+C 텍스트의 데이터 행(헤더 제외). 행 이동 없음."""
    grids = driver.by_class(session.main.handle, "TcxGridSite")
    if not grids:
        return []
    grid = max(grids, key=lambda g: (g.rectangle().right - g.rectangle().left)
               * (g.rectangle().bottom - g.rectangle().top))
    focus_main(session)
    grid.set_focus()
    time.sleep(0.3)
    pyperclip.copy("")
    send_keys("^c")
    time.sleep(0.4)
    text = pyperclip.paste() or ""
    return [ln for ln in text.splitlines() if ln.strip() and not ln.startswith(GRID_HEADER_PREFIX)]


def _top_toolbar(main_handle: int, *, timeout: float = 15.0):
    """상단 toolbar(TdxBarControl 'toolbar'). 로그인 직후엔 아직 없을 수 있어 잠시 기다리고,
    이름이 안 맞으면 가장 위·왼쪽 TdxBarControl 로 대신한다(BankOn select_tab 과 같은 폴백)."""
    deadline = time.monotonic() + timeout
    while True:
        bar = _desc(main_handle, "TdxBarControl", "toolbar")
        if bar is not None:
            return bar
        w = Desktop(backend="win32").window(handle=main_handle)
        bars = []
        for c in w.descendants():
            try:
                if c.class_name() == "TdxBarControl":
                    bars.append(c)
            except Exception:
                continue
        if bars:
            return min(bars, key=lambda b: (b.rectangle().top, b.rectangle().left))
        if time.monotonic() > deadline:
            return None
        time.sleep(0.5)


def click_tab(session, tab: str) -> None:
    bar = _top_toolbar(session.main.handle)
    if bar is None:
        raise navigate.NavigationError(
            f"상단 toolbar(TdxBarControl) 를 찾지 못했습니다 — 잡힌 창: {session.main.title!r}")
    focus_main(session)
    bar.click_input(coords=TAB_COORDS[tab])
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
        raise navigate.NavigationError("'조 회' 버튼을 찾지 못했습니다.")
    focus_main(session)
    button.click_input()             # BM_CLICK 은 이 버튼에 안 먹는 PC 가 있었다(실측 2026-09-08)
    time.sleep(4.0)


class Browser:
    """탭·조회 상태를 기억하며 문서 행을 찾아 주는 작은 상태기계."""

    def __init__(self, session, span: tuple[str, str]):
        self.session = session
        self.span = span
        self.tab: str | None = None

    def goto(self, tab: str) -> None:
        if self.tab == tab:
            return
        click_tab(self.session, tab)
        set_conditions(self.session, *self.span)
        press_query(self.session)
        rows = grid_rows(self.session)
        self.tab = tab
        log(f"탭 '{tab}' 조회 {self.span}: {len(rows)}행")

    def locate(self, doc: str) -> str | None:
        """탭을 돌며 '찾 기'로 대상 행을 잡는다. 잡힌 탭 이름, 없으면 None. (키 주입 없음)"""
        tab, _row = self.locate_row(doc)
        return tab

    def locate_row(self, doc: str) -> tuple[str | None, str]:
        """(잡힌 탭, 그 행의 전체 텍스트). 없으면 (None, '')."""
        order = ([t for t in TAB_ORDER if t == self.tab] + [t for t in TAB_ORDER if t != self.tab])
        for tab in order:
            self.goto(tab)
            focus_main(self.session)
            navigate.find_document(self.session, doc)
            rows = grid_rows(self.session)
            hit = [r for r in rows if doc in r]
            log(f"  찾기 {doc} @ {tab}: {len(rows)}행, 대상행 {'있음' if hit else '없음'}")
            if hit:
                return tab, hit[0]
        return None, ""


GRID_COLUMNS = ("은행", "의뢰영업점", "의뢰번호", "법인명", "지사명", "업무구분", "업무실적매칭", "열람허용",
                "상태", "현장조사서", "감정서번호", "의뢰일자", "접수일자", "발송일자", "현장조사서발송일자")


def describe_row(row: str) -> str:
    """그리드 행 텍스트(탭 구분)를 '열=값' 로 풀어 쓴다(빈 열 생략)."""
    cells = row.split("\t")
    parts = [f"{name}={cells[i].strip()}" for i, name in enumerate(GRID_COLUMNS)
             if i < len(cells) and cells[i].strip()]
    return " · ".join(parts)


# ── 대조 ───────────────────────────────────────────────────────────────────────

def compare_doc(cfg, browser: Browser, bank: str, doc: str) -> tuple[str, list]:
    spec = BANKS[bank]
    tab = browser.locate(doc)
    if tab is None:
        return "목록에 없음(미작성 건이면 정상) — 건너뜀", []
    focus_main(browser.session)
    form = navigate.open_write_form(browser.session)
    try:
        if form.class_name != spec["cls"]:
            return f"열린 폼 클래스 {form.class_name} ≠ {spec['cls']} — 건너뜀", []
        rows = spec["build"](cfg, doc, form)
    finally:
        navigate.close_forms(browser.session)
    cnt = {m: sum(1 for r in rows if r[0] == m) for m in ORDER}
    return " ".join(f"{m}{n}" for m, n in cnt.items()) + f"  [{tab}]", rows


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="verify_docs_live", description=__doc__.split("\n\n")[0])
    p.add_argument("doc_id", nargs="*")
    p.add_argument("--bank", choices=tuple(BANKS), default=None, help="ssb=수협 hnb=하나 (--locate-only 면 생략 가능)")
    p.add_argument("--recent", type=int, default=0, help="DB에서 실사완료 최근 N건을 골라 추가")
    p.add_argument("--env", default=None)
    p.add_argument("--log", default=None, help="결과를 이 파일에도 기록(UTF-8)")
    p.add_argument("--quiet", action="store_true", help="필드별 행은 생략하고 문서별 합계만")
    p.add_argument("--locate-only", action="store_true",
                   help="폼은 열지 않고 문서가 어느 탭에 어떤 행(의뢰일자·접수일자·상태)으로 있는지만 확인 — 은행 무관")
    args = p.parse_args(argv)
    if not args.locate_only and not args.bank:
        p.error("--bank 가 필요합니다(--locate-only 가 아니면).")
    if args.recent and not args.bank:
        p.error("--recent 는 --bank 와 함께 써야 합니다.")

    cfg = load_config(args.env or str(ROOT / ".env"))
    docs = list(args.doc_id)
    if args.recent:
        docs += [d for d in pick_recent(cfg, args.bank, args.recent) if d not in docs]
    if not docs:
        p.error("문서번호나 --recent 중 하나가 필요합니다.")
    if not (cfg.loader_cmd and cfg.bankon_user and cfg.bankon_password):
        p.error("BANKON_LOADER_CMD / BANKON_USER / BANKON_PASSWORD 가 .env 에 있어야 합니다.")

    out = open(args.log, "a", encoding="utf-8") if args.log else None

    def emit(line: str) -> None:
        print(line, flush=True)
        if out:
            out.write(line + "\n")
            out.flush()

    driver.require_desktop()
    session = navigate.open_app(cfg.loader_cmd, cfg.bankon_user, cfg.bankon_password)
    if driver.MAIN_TITLE not in (session.main.title or ""):
        raise SystemExit(f"잡힌 메인 창이 BANK24 가 아닙니다: {session.main.title!r} — 중단(다른 프로그램 조작 방지)")
    log(f"BANK24 main handle={session.main.handle} pid={session.pid} title={session.main.title!r}")
    navigate.close_forms(session)
    navigate.close_context_menu()
    span = navigate.range_for(docs[0]) or navigate.range_for(docs[-1])
    browser = Browser(session, span)

    summary = []
    for doc in docs:
        t0 = time.time()
        emit(f"\n===== {BANKS[args.bank]['name'] if args.bank else '위치확인'} {doc} =====")
        try:
            if args.locate_only:
                tab, row = browser.locate_row(doc)
                line = (f"[{tab}] {describe_row(row)}" if tab
                        else "어느 탭에도 없음(미작성이면 감정서번호 미부여, 또는 조회기간 밖)")
                emit(f"  -- {line} ({time.time() - t0:.0f}s)")
                summary.append((doc, line))
                continue
            line, rows = compare_doc(cfg, browser, args.bank, doc)
            if not args.quiet:
                for mark, label, ours, theirs in sorted(rows, key=lambda r: (ORDER[r[0]], r[1])):
                    emit(f"  [{mark:6}] {label[:18]:20} 채울값={ours[:28]:30} 화면={theirs[:26]}")
            emit(f"  -- {line} ({time.time() - t0:.0f}s)")
            summary.append((doc, line))
        except Exception as e:  # noqa: BLE001
            emit(f"  ✖ 오류: {e!r}")
            traceback.print_exc()
            summary.append((doc, f"오류 {type(e).__name__}: {str(e)[:60]}"))
            try:
                navigate.close_context_menu()
                navigate.close_forms(session)
            except Exception:
                pass
    emit("\n===== SUMMARY =====")
    for doc, line in summary:
        emit(f"  {doc}: {line}")
    if out:
        out.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
