"""pdf_exporter.py — TfrxPreviewForm → Microsoft Print to PDF 자동화

흐름:
  1. 그리드 행 우클릭 → 'C' → TfrxPreviewForm 열림
  2. Ctrl+P → TfrxPrintDialog (Microsoft Print to PDF)
  3. OK → Windows 저장 다이얼로그 (#32770)
  4. 경로 클립보드 붙여넣기 → 저장(S)
  5. PDF 파일 생성 확인
"""
import os
import subprocess
import time
import logging
import pyautogui
import pyperclip
from pywinauto import Desktop

log = logging.getLogger(__name__)

_PREVIEW_CLASS = "TfrxPreviewForm"
_PRINT_DLG_CLASS = "TfrxPrintDialog"
_PDF_PRINTER = "Microsoft Print to PDF"


def _set_default_printer(printer_name: str):
    """PowerShell로 기본 프린터 변경"""
    try:
        subprocess.run(
            ["powershell", "-Command",
             f'(New-Object -ComObject WScript.Network).SetDefaultPrinter("{printer_name}")'],
            capture_output=True, timeout=5
        )
        log.info(f"기본 프린터 설정: {printer_name}")
    except Exception as e:
        log.warning(f"기본 프린터 설정 실패: {e}")


def _get_default_printer() -> str:
    """현재 기본 프린터명 반환"""
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             "(Get-WmiObject -Query 'SELECT * FROM Win32_Printer WHERE Default=$true').Name"],
            capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip()
    except Exception:
        return ""


def _get_preview_win():
    wins = Desktop(backend="win32").windows(class_name=_PREVIEW_CLASS)
    return wins[0] if wins else None


def open_preview_for_row(row_screen_x: int, row_screen_y: int,
                         wait_sec: float = 3.0) -> bool:
    """그리드 행 좌표에서 우클릭 → 의뢰서 출력(C) → TfrxPreviewForm 열림 대기"""
    pyautogui.rightClick(row_screen_x, row_screen_y)
    time.sleep(0.5)
    pyautogui.press('c')          # 의뢰서 출력(C)
    deadline = time.time() + wait_sec
    while time.time() < deadline:
        if _get_preview_win():
            log.info("TfrxPreviewForm 열림 확인")
            time.sleep(0.5)
            return True
        time.sleep(0.3)
    log.warning("TfrxPreviewForm 열림 대기 시간 초과")
    return False


def save_preview_as_pdf(output_path: str,
                        print_wait: float = 2.0,
                        pdf_wait: float = 5.0) -> bool:
    """TfrxPreviewForm이 열린 상태에서 PDF 저장.

    Parameters
    ----------
    output_path : 저장할 PDF 파일 전체 경로 (확장자 .pdf 포함)
    print_wait  : 인쇄 다이얼로그 열릴 때까지 대기(초)
    pdf_wait    : PDF 파일 생성 대기(초)

    Returns
    -------
    True if PDF was created successfully
    """
    win = _get_preview_win()
    if not win:
        log.error("TfrxPreviewForm 없음")
        return False

    # 기본 프린터를 Microsoft Print to PDF로 전환
    prev_printer = _get_default_printer()
    if prev_printer != _PDF_PRINTER:
        _set_default_printer(_PDF_PRINTER)
        time.sleep(0.5)

    win.set_focus()
    time.sleep(0.3)

    # ── Step 1: Ctrl+P → TfrxPrintDialog ─────────────────────────────────────
    pyautogui.hotkey('ctrl', 'p')
    deadline = time.time() + print_wait + 2
    print_dlg = None
    while time.time() < deadline:
        wins = Desktop(backend="win32").windows(class_name=_PRINT_DLG_CLASS)
        if wins:
            print_dlg = wins[0]
            break
        time.sleep(0.3)
    if not print_dlg:
        log.error("TfrxPrintDialog 열림 실패")
        return False

    # ── Step 2: Microsoft Print to PDF 선택 ──────────────────────────────────
    time.sleep(0.5)  # 다이얼로그 컨트롤 로딩 대기
    for ctrl in print_dlg.descendants():
        try:
            cls = ctrl.class_name()
            if cls in ('TcxComboBox', 'TComboBox', 'ComboBox'):
                items = ctrl.item_texts() if hasattr(ctrl, 'item_texts') else []
                # 1순위: 정확히 일치
                matched_idx = None
                for idx, text in enumerate(items):
                    if text.strip() == _PDF_PRINTER:
                        matched_idx = idx
                        break
                # 2순위: Microsoft + PDF 둘 다 포함
                if matched_idx is None:
                    for idx, text in enumerate(items):
                        if 'MICROSOFT' in text.upper() and 'PDF' in text.upper():
                            matched_idx = idx
                            break
                if matched_idx is not None:
                    ctrl.select(matched_idx)
                    log.info(f"프린터 선택: {items[matched_idx]}")
                    time.sleep(0.3)
                    break
        except Exception:
            pass

    ok_clicked = False
    for ctrl in print_dlg.descendants():
        try:
            if ctrl.class_name() == 'TButton' and 'OK' in ctrl.window_text():
                r = ctrl.rectangle()
                pyautogui.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)
                ok_clicked = True
                log.info("TfrxPrintDialog OK 클릭")
                break
        except Exception:
            pass
    if not ok_clicked:
        log.error("OK 버튼을 찾지 못함")
        return False

    # ── Step 3: Windows 저장 다이얼로그 대기 ─────────────────────────────────
    time.sleep(1.5)
    save_dlg = _find_save_dialog(timeout=5)
    if not save_dlg:
        log.error("PDF 저장 다이얼로그 열림 실패")
        return False

    # 저장 다이얼로그 컨트롤 구조 덤프 (디버그용)
    try:
        for ctrl in save_dlg.descendants():
            try:
                r2 = ctrl.rectangle()
                log.debug(f"  CTRL cls={ctrl.class_name()} txt={repr(ctrl.window_text()[:30])} "
                          f"w={r2.width()} h={r2.height()} parent={ctrl.parent().class_name()}")
            except Exception:
                pass
    except Exception:
        pass

    # ── Step 4: 파일명 입력 ───────────────────────────────────────────────────
    save_dlg.set_focus()
    time.sleep(0.3)

    edit_ctrl = _find_filename_edit(save_dlg)
    if edit_ctrl:
        # Edit 컨트롤 직접 클릭 후 텍스트 입력
        try:
            edit_ctrl.click_input()
            time.sleep(0.2)
            edit_ctrl.type_keys('^a', with_spaces=True)
            time.sleep(0.1)
            pyperclip.copy(output_path)
            pyautogui.hotkey('ctrl', 'v')
            time.sleep(0.4)
            log.info(f"파일명 입력 (Edit 컨트롤): {output_path}")
        except Exception as e:
            log.warning(f"Edit 컨트롤 입력 실패, 좌표 폴백: {e}")
            dr = save_dlg.rectangle()
            pyautogui.click((dr.left + dr.right) // 2, dr.bottom - 65)
            time.sleep(0.3)
            pyautogui.hotkey('ctrl', 'a')
            time.sleep(0.1)
            pyperclip.copy(output_path)
            pyautogui.hotkey('ctrl', 'v')
            time.sleep(0.4)
            log.info(f"파일명 입력 (좌표 폴백): {output_path}")
    else:
        # 폴백: 좌표 기반
        log.warning("파일명 Edit 컨트롤 못 찾음, 좌표 폴백 사용")
        dr = save_dlg.rectangle()
        pyautogui.click((dr.left + dr.right) // 2, dr.bottom - 65)
        time.sleep(0.3)
        pyautogui.hotkey('ctrl', 'a')
        time.sleep(0.1)
        pyperclip.copy(output_path)
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(0.4)
        log.info(f"파일명 입력 (좌표 폴백): {output_path}")

    # ── Step 5: Enter로 저장 ─────────────────────────────────────────────────
    pyautogui.press('enter')
    time.sleep(0.3)
    log.info("Enter로 저장 완료")

    # ── Step 6: PDF 생성 확인 ─────────────────────────────────────────────────
    deadline = time.time() + pdf_wait
    while time.time() < deadline:
        if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
            log.info(f"PDF 저장 완료: {output_path} ({os.path.getsize(output_path)} bytes)")
            return True
        time.sleep(0.5)

    log.warning(f"PDF 생성 대기 시간 초과: {output_path}")
    return False


def close_preview():
    """TfrxPreviewForm '닫기' 버튼 클릭 (ESC는 사용하지 않음)"""
    win = _get_preview_win()
    if not win:
        return
    # 툴바에서 '닫기' 버튼 찾기
    for ctrl in win.descendants():
        try:
            t = ctrl.window_text().strip()
            if t in ('닫기', '&Close', 'Close'):
                ctrl.click()
                log.info("닫기 버튼 클릭")
                time.sleep(0.5)
                return
        except Exception:
            pass
    # fallback: Alt+F4
    win.set_focus()
    pyautogui.hotkey('alt', 'f4')
    log.info("닫기 Alt+F4 사용")
    time.sleep(0.5)


# ─── 내부 헬퍼 ───────────────────────────────────────────────────────────────

def _find_save_dialog(timeout: float = 8.0):
    """Windows 파일 저장 다이얼로그 (#32770) 탐색
    - '저장(&S)' 버튼이 있는 창을 기준으로 특정 (알약 등 다른 #32770 팝업 제외)
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        wins = Desktop(backend="win32").windows(class_name="#32770")
        for w in wins:
            try:
                r = w.rectangle()
                if r.width() < 400 or r.height() < 200:
                    continue
                # '저장(&S)' 버튼이 있는 창만 선택
                for ctrl in w.children():
                    try:
                        if ctrl.class_name() == 'Button' and '저장' in ctrl.window_text():
                            return w
                    except Exception:
                        pass
            except Exception:
                pass
        time.sleep(0.3)
    return None


def _find_filename_edit(save_dlg):
    """파일명 입력 Edit 컨트롤"""
    edits = []
    for ctrl in save_dlg.descendants():
        try:
            if ctrl.class_name() == 'Edit':
                r = ctrl.rectangle()
                if r.width() > 100 and r.height() < 50:
                    edits.append((r.width(), ctrl))
        except Exception:
            pass
    if not edits:
        return None
    # 가장 넓은 Edit = 파일명 입력란
    edits.sort(key=lambda x: x[0], reverse=True)
    return edits[0][1]
