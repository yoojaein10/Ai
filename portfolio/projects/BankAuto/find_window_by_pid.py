import pywinauto
from pywinauto import Desktop, Application
import os

def find_by_pid():
    # bank24.exe의 PID 찾기
    pid = None
    output = os.popen('tasklist /FI "IMAGENAME eq bank24.exe" /FO CSV /NH').read()
    if 'Bank24.exe' in output:
        # 가장 큰 메모리를 사용하는 PID 선택 (보통 메인 창)
        try:
            import csv
            from io import StringIO
            f = StringIO(output)
            reader = csv.reader(f)
            pids = []
            for row in reader:
                if row:
                    pids.append(int(row[1]))
            pid = pids[-1] # 마지막으로 뜬 프로세스 선택
            print(f"Target PID: {pid}")
        except:
            pass

    if pid:
        try:
            print(f"\n--- Connecting to Process {pid} ---")
            app = Application(backend="uia").connect(process=pid)
            main_window = app.top_window()
            print(f"Main Window Text: '{main_window.window_text()}'")
            print(f"Main Window Class: {main_window.element_info.class_name}")
            print(f"Main Window Rect: {main_window.rectangle()}")
            
            print("\n--- Printing Control Identifiers (UI Tree) ---")
            main_window.print_control_identifiers()
        except Exception as e:
            print(f"Error connecting to PID {pid}: {e}")
            print("Trying backend='win32'...")
            try:
                app = Application(backend="win32").connect(process=pid)
                main_window = app.top_window()
                main_window.print_control_identifiers()
            except Exception as e2:
                print(f"Error connecting with win32: {e2}")

if __name__ == "__main__":
    find_by_pid()
