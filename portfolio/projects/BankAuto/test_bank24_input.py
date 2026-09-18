from pywinauto import Application, Desktop
import time
import os

def test_input():
    print("--- 1. Connecting to Bank24 Window ---")
    try:
        # 이미 실행 중인 bank24.exe에 연결 (PID 기반이 가장 확실함)
        output = os.popen('tasklist /FI "IMAGENAME eq bank24.exe" /FO CSV /NH').read()
        if 'Bank24.exe' not in output:
            print("Bank24.exe is not running. Please run the program first.")
            return
            
        import csv
        from io import StringIO
        f = StringIO(output)
        reader = csv.reader(f)
        pids = [int(row[1]) for row in reader if row]
        pid = pids[-1]
        
        app = Application(backend="uia").connect(process=pid)
        win = app.window(class_name="TDXLoginDialog")
        
        if not win.exists():
            print("Login Dialog not found. Trying top_window()...")
            win = app.top_window()
            
        print(f"Window Connected: '{win.window_text()}'")
        win.set_focus()
        time.sleep(1)
        
        print("\n--- 2. Attempting ID Input (Edit2) ---")
        # Edit2는 조사에서 식별된 아이디 입력칸
        id_field = win.child_window(auto_id="402020", control_type="Edit")
        
        print("Typing 'TEST_ID'...")
        id_field.set_focus()
        id_field.type_keys("TEST_ID", with_spaces=True)
        
        print("\nSUCCESS: Input sent. Please check the Bank24 login window.")
        
    except Exception as e:
        print(f"ERROR during input test: {e}")

if __name__ == "__main__":
    test_input()
