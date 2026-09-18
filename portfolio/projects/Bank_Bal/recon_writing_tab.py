# -*- coding: utf-8 -*-
r"""
Bank_Bal 정찰 (읽기전용)

작성 탭에서:
  1. 그리드 헤더·행수 덤프
  2. 첫 행 우클릭 컨텍스트 메뉴 항목 덤프 (열어서 읽고 ESC — 클릭 없음)
미접수 탭에서:
  3. 그리드 헤더 덤프 → 작성 탭과 컬럼 비교

부작용 없음: DB 접근·발송·저장 없음. 클릭은 탭/필터/조회 버튼뿐.
결과: Bank_Bal\reports\recon_<TS>.txt (+ 메뉴 스크린샷 png)

실행: python recon_writing_tab.py [--from YYYY-MM-DD] [--to YYYY-MM-DD]
      기본 기간은 오늘-3일 ~ 오늘. 계정은 C:\Bank24Extractor\settings.ini 사용.
"""
import argparse
import configparser
import datetime
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
YBANK_DIR = os.path.join(os.path.dirname(HERE), "Y_BankAuto")
sys.path.insert(0, YBANK_DIR)

SETTINGS_INI = r"C:\Bank24Extractor\settings.ini"
REPORT_DIR = os.path.join(HERE, "reports")

import extract_shinhan as es  # noqa: E402  (Y_BankAuto 원본 재사용)
from pywinauto import Desktop  # noqa: E402
from pywinauto.keyboard import send_keys  # noqa: E402

TS = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
_report_lines = []
_log_file = None


def log(msg):
    line = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    if _log_file:
        _log_file.write(line + "\n")
        _log_file.flush()


def rpt(msg):
    """보고서 본문 + 콘솔 둘 다."""
    _report_lines.append(msg)
    log(msg)


def load_credentials():
    cfg = configparser.ConfigParser()
    cfg.read(SETTINGS_INI, encoding="utf-8")
    uid = cfg.get("login", "bank24_id", fallback="")
    pwd = cfg.get("login", 'REDACTED_CONFIGURE_LOCALLY', fallback="")
    if not uid or not pwd:
        raise RuntimeError(f"Bank24 계정 미설정: {SETTINGS_INI} [login] bank24_id/bank24_pw")
    return uid, pwd


def attach_or_login(uid, pwd):
    """실행 중인 Bank24 메인창이 있으면 붙고, 없으면 로그인."""
    existing = None
    try:
        for w in Desktop(backend="win32").windows():
            if es.safe_cls(w) == es.MAIN_CLS and any(
                    h in es.safe_txt(w) for h in es._BANK24_TITLE_HINTS):
                existing = w
                break
    except Exception:
        pass
    if existing is not None:
        log("기존 Bank24 메인 창 재사용")
        es.force_foreground(existing.handle, "기존 메인창")
        time.sleep(1)
    else:
        log("실행 중인 Bank24 미발견 — 새로 실행·로그인")
        es.kill_existing()
        es.launch_and_login(uid, pwd)
    main_win = es.wait_main()
    if main_win is None:
        raise RuntimeError("Bank24 메인 창을 찾을 수 없습니다.")
    time.sleep(2)
    return main_win


def dump_tab_grid(main_win, tab_name):
    """탭 전환 → 필터·조회 → 헤더/행수 반환."""
    rpt(f"\n{'=' * 60}\n[{tab_name} 탭] 그리드 덤프\n{'=' * 60}")
    if not es.select_bank24_source_tab(main_win, tab_name):
        rpt(f"[{tab_name}] 탭 전환 실패 — 이 탭 덤프 생략")
        return None, []
    time.sleep(1.0)
    es.apply_filter(main_win)
    headers, rows = es.read_main_grid_rows(main_win)
    rpt(f"[{tab_name}] 헤더 {len(headers)}개: {headers}")
    rpt(f"[{tab_name}] 데이터 행수: {len(rows)}")
    if rows:
        # PII 값은 남기지 않고, 첫 행에서 어떤 컬럼이 채워져 있는지만 기록
        first = rows[0]
        filled = [k for k, v in first.items() if str(v).strip()]
        rpt(f"[{tab_name}] 첫 행 값 있는 컬럼: {filled}")
    return headers, rows


def _snapshot_visible_handles():
    handles = set()
    try:
        for w in Desktop(backend="win32").windows():
            handles.add(w.handle)
    except Exception:
        pass
    return handles


def dump_context_menu(main_win, tab_name):
    """첫 행 포커스 → {APPS} 로 컨텍스트 메뉴 열기 → 항목 덤프 → ESC. 클릭 없음."""
    rpt(f"\n{'=' * 60}\n[{tab_name} 탭] 우클릭 컨텍스트 메뉴 덤프\n{'=' * 60}")

    if not es.navigate_to_row(main_win, 0):
        rpt("[메뉴] 첫 행 포커스 실패 — 메뉴 덤프 생략")
        return

    before = _snapshot_visible_handles()
    try:
        send_keys("{VK_APPS}")
    except Exception:
        send_keys("+{F10}")  # fallback: Shift+F10
    time.sleep(1.2)

    new_wins = []
    try:
        for w in Desktop(backend="win32").windows():
            if w.handle not in before and w.is_visible():
                new_wins.append(w)
    except Exception as e:
        rpt(f"[메뉴] 새 창 열거 실패: {type(e).__name__}: {e}")

    if not new_wins:
        rpt("[메뉴][WARN] 새 팝업 창 미발견 — 스크린샷만 저장")
    for w in new_wins:
        r = es.safe_rect(w)
        rpt(f"[메뉴] 팝업: class={es.safe_cls(w)!r} title={es.safe_txt(w)!r} rect={r}")
        # win32 자식 컨트롤 텍스트
        try:
            for c in w.descendants():
                t = es.safe_txt(c).strip()
                if t:
                    rpt(f"    (win32) class={es.safe_cls(c)!r} text={t!r}")
        except Exception as e:
            rpt(f"    (win32) descendants 실패: {e}")
        # UIA로 메뉴 항목 읽기 (DevExpress 메뉴는 UIA가 더 잘 읽는 경우가 많음)
        try:
            uw = Desktop(backend="uia").window(handle=w.handle)
            for item in uw.descendants():
                try:
                    ct = item.element_info.control_type
                    name = (item.element_info.name or "").strip()
                    if name and ct in ("MenuItem", "Button", "ListItem", "Text"):
                        rpt(f"    (uia)   {ct}: {name!r}")
                except Exception:
                    pass
        except Exception as e:
            rpt(f"    (uia) 읽기 실패: {e}")

    # 스크린샷 (메뉴가 native #32768 이라 창 열거에 안 잡혀도 화면엔 보임)
    try:
        import pyautogui
        shot = os.path.join(REPORT_DIR, f"menu_{tab_name}_{TS}.png")
        pyautogui.screenshot().save(shot)
        rpt(f"[메뉴] 스크린샷 저장: {shot}  (그리드 실데이터 포함 — 외부 공유 금지)")
    except Exception as e:
        rpt(f"[메뉴] 스크린샷 실패: {e}")

    # 메뉴 닫기 — 클릭 없이 ESC 두 번
    send_keys("{ESC}")
    time.sleep(0.3)
    send_keys("{ESC}")
    time.sleep(0.3)
    rpt("[메뉴] ESC로 닫음 (항목 클릭 없음)")


def main():
    global _log_file

    ap = argparse.ArgumentParser()
    today = datetime.date.today()
    ap.add_argument("--from", dest="date_from",
                    default=(today - datetime.timedelta(days=3)).isoformat())
    ap.add_argument("--to", dest="date_to", default=today.isoformat())
    args = ap.parse_args()

    os.makedirs(REPORT_DIR, exist_ok=True)
    log_path = os.path.join(REPORT_DIR, f"recon_{TS}.log")
    _log_file = open(log_path, "w", encoding="utf-8")
    es._log_callback = log  # Y_BankAuto 내부 log()를 이쪽으로 수신

    es.DATE_FROM = args.date_from
    es.DATE_TO = args.date_to

    rpt(f"Bank_Bal 정찰 시작  기간: {es.DATE_FROM} ~ {es.DATE_TO}")
    rpt("모드: 읽기전용 (DB·발송·저장 없음)")

    try:
        uid, pwd = load_credentials()
        main_win = attach_or_login(uid, pwd)

        # 1) 작성 탭: 그리드 + 컨텍스트 메뉴
        h_write, rows_write = dump_tab_grid(main_win, "작성")
        if rows_write:
            dump_context_menu(main_win, "작성")
        else:
            rpt("[작성] 행이 없어 컨텍스트 메뉴 덤프 생략 — 기간을 넓혀 재실행 필요")

        # 2) 미접수 탭: 그리드 (비교용)
        h_recv, _rows_recv = dump_tab_grid(main_win, "미접수")

        # 3) 헤더 비교
        rpt(f"\n{'=' * 60}\n헤더 비교 (작성 vs 미접수)\n{'=' * 60}")
        if h_write is not None and h_recv is not None:
            if h_write == h_recv:
                rpt("결과: 완전 동일 (순서까지 일치)")
            else:
                only_w = [c for c in h_write if c not in h_recv]
                only_r = [c for c in h_recv if c not in h_write]
                rpt(f"작성에만 있는 컬럼: {only_w}")
                rpt(f"미접수에만 있는 컬럼: {only_r}")
                if not only_w and not only_r:
                    rpt("컬럼 구성 동일, 순서만 다름")
        else:
            rpt("어느 한쪽 탭 덤프 실패로 비교 불가")

    except Exception as exc:
        rpt(f"[FATAL] {type(exc).__name__}: {exc}")
        rpt(traceback.format_exc())
    finally:
        es._log_callback = None
        report_path = os.path.join(REPORT_DIR, f"recon_{TS}.txt")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(_report_lines) + "\n")
        log(f"\n보고서: {report_path}")
        log(f"전체 로그: {log_path}")
        _log_file.close()


if __name__ == "__main__":
    main()
