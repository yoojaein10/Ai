import pywinauto
from pywinauto import Application
import pyautogui
import time
import os

def robust_test_input():
    print("--- 1. Locating Window and PID ---")
    output = os.popen('tasklist /FI "IMAGENAME eq bank24.exe" /FO CSV /NH').read()
    if 'Bank24.exe' not in output:
        print("Bank24.exe is not running.")
        return
        
    pids = [int(row.split(',')[1].strip('"')) for row in output.strip().split('\n') if row]
    pid = pids[-1]
    print(f"Target PID: {pid}")

    try:
        print("\n--- 2. Method 1: Pywinauto Direct Input ---")
        app = Application(backend="uia").connect(process=pid)
        win = app.top_window()
        print(f"Connected to: {win.window_text()}")
        
        # 이전 조사에서 확보한 Edit 필드 (좌표: 997, 538)
        id_field = win.child_window(auto_id="1122982", control_type="Edit") or win.child_window(auto_id="402020", control_type="Edit")
        if id_field.exists():
            print("Edit field found via UIA. Typing...")
            win.set_focus()
            id_field.set_focus()
            id_field.type_keys("TEST_ID_UIA", with_spaces=True)
            print("UIA Input Successful.")
        else:
            print("UIA Edit field not found. Trying generic Edit...")
            win.child_window(control_type="Edit").type_keys("TEST_ID_GENERIC")

    except Exception as e:
        print(f"Pywinauto failed: {e}")

    try:
        print("\n--- 3. Method 2: PyAutoGUI Coordinate Input ---")
        # 조사된 좌표 (997, 538) 중앙 지점
        target_x, target_y = 1084, 547 
        print(f"Clicking at Absolute Screen Coord: {target_x}, {target_y}")
        pyautogui.click(target_x, target_y)
        time.sleep(0.5)
        pyautogui.write("TEST_ID_COORD")
        print("Coordinate Input Successful.")
    except Exception as e:
        print(f"PyAutoGUI failed: {e}")

if __name__ == "__main__":
    robust_test_input()
