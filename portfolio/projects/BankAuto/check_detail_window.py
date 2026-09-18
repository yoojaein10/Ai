"""
종합접수 창 타이틀/클래스명 확인 스크립트
bank24.exe 실행 후 종합접수 창을 열어둔 상태에서 실행하세요.
"""
from pywinauto import Desktop, Application

def check_all_windows():
    print("=" * 60)
    print("현재 열려있는 모든 창 목록 (win32)")
    print("=" * 60)
    desktop = Desktop(backend="win32")
    for w in desktop.windows():
        title = w.window_text().strip()
        cls = w.element_info.class_name
        if title:
            print(f"  타이틀: '{title}'  /  클래스: '{cls}'")

def check_bank24_children():
    print()
    print("=" * 60)
    print("bank24.exe 프로세스의 모든 창 (자식 포함)")
    print("=" * 60)
    try:
        app = Application(backend="win32").connect(
            class_name="TfrmMain", title_re=".*BANK24.*"
        )
        main = app.top_window()
        print(f"메인 창: '{main.window_text()}'  /  클래스: '{main.element_info.class_name}'")
    except Exception as e:
        print(f"메인 창 연결 실패: {e}")

    # 현재 프로세스의 모든 top-level 창
    try:
        import psutil, os
        for proc in psutil.process_iter(['name', 'pid']):
            if proc.info['name'] and 'bank24' in proc.info['name'].lower():
                pid = proc.info['pid']
                print(f"\nbank24 PID: {pid}")
                app2 = Application(backend="win32").connect(process=pid)
                for win in app2.windows():
                    t = win.window_text().strip()
                    c = win.element_info.class_name
                    if t:
                        print(f"  창 타이틀: '{t}'  /  클래스: '{c}'")
    except ImportError:
        print("(psutil 없음 — 위 목록에서 확인하세요)")
    except Exception as e:
        print(f"PID 기반 탐색 오류: {e}")

if __name__ == "__main__":
    check_all_windows()
    check_bank24_children()
    print()
    print("종합접수 창이 목록에 있으면 타이틀/클래스명을 알려주세요.")
