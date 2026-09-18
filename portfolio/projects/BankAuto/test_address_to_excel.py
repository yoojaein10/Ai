"""
주소 수집 → xlsx 저장 테스트
- bank24.exe 실행 중 + 조회 결과 그리드가 보이는 상태에서 실행
- xls 로드 → 행별 우클릭+'0' → 주소 추출 → 의뢰영업점 옆에 삽입 → 저장
"""
import time
import pyautogui
import pandas as pd
from pathlib import Path
from pywinauto import Application, Desktop
from pywinauto.keyboard import send_keys

XLS_PATH = r"D:\AI\Claude\BankAuto\output\20260403_2.xls"

def connect_bank24():
    app = Application(backend="win32").connect(
        class_name="TfrmMain", title_re=".*BANK24.*"
    )
    return app, app.top_window()

def get_grid(main_win):
    for cls in ("TcxGrid", "TDBGrid", "TStringGrid"):
        grids = [c for c in main_win.descendants() if c.class_name() == cls]
        if grids:
            return grids[0]
    return None

def extract_address() -> str:
    """TBnkTop24Rcp 창 내부 주소 그리드(가장 큰 TcxGrid) 첫 행 클립보드 추출"""
    import pyperclip
    try:
        dapp = Application(backend="win32").connect(class_name="TBnkTop24Rcp", timeout=8)
        detail_win = dapp.top_window()

        inner_grids = [c for c in detail_win.descendants() if c.class_name() == "TcxGrid"]
        if not inner_grids:
            print("    주소 그리드 없음")
            return ""

        # 가장 큰 그리드 = 주소 그리드
        addr_grid = max(inner_grids, key=lambda g: g.rectangle().width() * g.rectangle().height())
        r = addr_grid.rectangle()
        print(f"    주소 그리드 rect: {r.left},{r.top},{r.right},{r.bottom}")

        # 주소 컬럼(2번째) 첫 행 클릭
        cell_x = r.left + int((r.right - r.left) * 0.6)
        cell_y = r.top + 35
        pyautogui.click(cell_x, cell_y)
        time.sleep(0.3)

        pyperclip.copy("")
        pyautogui.hotkey("ctrl", "c")
        time.sleep(0.5)
        val = pyperclip.paste().strip()
        return val

    except Exception as e:
        print(f"    주소 추출 실패: {e}")
    return ""

def main():
    # xls 로드
    print(f"[1] xls 로드: {XLS_PATH}")
    df = pd.read_excel(XLS_PATH, dtype=str, skiprows=1, header=0)
    df = df.dropna(how='all').reset_index(drop=True)
    print(f"    {len(df)}행, 컬럼: {list(df.columns)}")

    # bank24 연결
    print("[2] bank24 연결...")
    app, main_win = connect_bank24()
    print(f"    OK: {main_win.window_text()}")

    # 그리드 포커스
    print("[3] 그리드 포커스 + Ctrl+Home")
    main_win.set_focus()
    time.sleep(0.3)
    grid = get_grid(main_win)
    if not grid:
        print("    FAIL: 그리드 못 찾음")
        return
    grid.click_input()
    time.sleep(0.3)
    send_keys("^{HOME}")
    time.sleep(0.5)

    # 그리드 rect
    r = grid.rectangle()
    cx = (r.left + r.right) // 2
    first_row_y = r.top + 35
    print(f"    그리드 rect: {r.left},{r.top},{r.right},{r.bottom} → 우클릭 Y={first_row_y}")

    # 행별 주소 수집 (마지막 행 제외 — 합계 행)
    row_count = len(df) - 1
    print(f"[4] 주소 수집 시작 ({row_count}행)")
    addresses = []

    for i in range(row_count):
        req_no = str(df.iloc[i].get("의뢰번호", "")) if "의뢰번호" in df.columns else ""

        # 우클릭 → 컨텍스트 메뉴 → '0' 단축키
        main_win.set_focus()
        time.sleep(0.2)
        row_y = first_row_y if i == 0 else r.top + 35  # 항상 선택된 행이 보임
        pyautogui.rightClick(cx, row_y)
        time.sleep(1.0)
        pyautogui.press("0")
        time.sleep(2.5)

        address = extract_address()
        addresses.append(address)
        print(f"    [{i+1}/{row_count}] 의뢰번호={req_no} → {address[:50] if address else '(없음)'}")

        # 종합접수 창 닫기
        try:
            dapp = Application(backend="win32").connect(class_name="TBnkTop24Rcp", timeout=3)
            dapp.top_window().close()
            time.sleep(0.5)
        except Exception:
            pass

        # 다음 행으로
        if i < row_count - 1:
            main_win.set_focus()
            time.sleep(0.2)
            grid.click_input()
            time.sleep(0.2)
            send_keys("{DOWN}")
            time.sleep(0.3)

    # 마지막 행(합계) 제거 후 주소 컬럼 삽입
    print("[5] 주소 컬럼 삽입 → xlsx 저장")
    df = df.iloc[:row_count].reset_index(drop=True)
    df["주소"] = addresses
    cols = list(df.columns)
    cols.remove("주소")
    if "의뢰영업점" in cols:
        cols.insert(cols.index("의뢰영업점") + 1, "주소")
    else:
        cols.append("주소")
    df = df[cols]

    out_path = XLS_PATH.replace(".xls", ".xlsx")
    df.to_excel(out_path, index=False)
    print(f"    저장 완료: {out_path}")
    print(f"    주소 수집: {sum(1 for a in addresses if a)}건 / {row_count}건")

if __name__ == "__main__":
    main()
