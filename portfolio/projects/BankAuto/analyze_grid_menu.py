import pywinauto
from pywinauto import Application
import os

def analyze_grid_and_menu():
    print("--- 1. Analyzing Main Grid Control ---")
    output = os.popen('tasklist /FI "IMAGENAME eq bank24.exe" /FO CSV /NH').read()
    if 'Bank24.exe' not in output:
        print("Bank24.exe is not running.")
        return
    
    import csv
    from io import StringIO
    f = StringIO(output)
    reader = csv.reader(f)
    pids = [int(row[1]) for row in reader if row]
    pid = pids[-1]

    try:
        app = Application(backend="uia").connect(process=pid)
        win = app.window(title_re=".*BANK ONLINE.*")
        
        # 첫 화면의 모든 'Pane'이나 'List'성 컨트롤 검색
        # 보통 델파이 그리드는 Pane 하위에 배치되거나 특정 속성을 가짐
        print("\n--- Listing All Main Window Descendants to find Grid ---")
        grid_candidates = win.descendants(control_type="Pane") + win.descendants(control_type="List") + win.descendants(control_type="Table")
        
        for idx, ctrl in enumerate(grid_candidates):
            try:
                text = ctrl.window_text()
                if text:
                    print(f"Candidate {idx}: Text='{text}', Class={ctrl.element_info.class_name}, Rect={ctrl.rectangle()}")
            except:
                pass

        print("\n--- 2. Simulating Right-Click to Test Menu Visibility ---")
        # 임의의 좌표 (그리드 근처) 우클릭 테스트
        win.set_focus()
        import pyautogui
        # 화면 중앙 부근 우클릭 시뮬레이션
        rect = win.rectangle()
        target_x = rect.left + 300
        target_y = rect.top + 250
        print(f"Right-clicking at ({target_x}, {target_y}) to see if menu appears...")
        pyautogui.right_click(target_x, target_y)
        
        import time
        time.sleep(1)
        
        # 팝업 메뉴 탐색 (보통 Menu 또는 Window 타입으로 뜸)
        desktop = pywinauto.Desktop(backend="uia")
        menus = [w for w in desktop.windows() if w.element_info.class_name == '#32768' or w.element_info.control_type == 'Menu']
        print(f"Found {len(menus)} potential popup menus.")
        for m in menus:
            print(f"Menu Title: '{m.window_text()}', Class: {m.element_info.class_name}")

    except Exception as e:
        print(f"Research error: {e}")

if __name__ == "__main__":
    analyze_grid_and_menu()
