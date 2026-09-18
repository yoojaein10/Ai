"""TfrxPreviewForm 컨트롤 구조 덤프"""
from pywinauto import Application

try:
    app = Application(backend="win32").connect(class_name="TfrxPreviewForm", timeout=5)
    win = app.top_window()
    print(f"창 제목: {win.window_text()}")
    print(f"창 크기: {win.rectangle()}\n")

    print("=== 전체 자식 컨트롤 ===")
    for i, ctrl in enumerate(win.descendants()):
        try:
            txt  = ctrl.window_text().strip()
            cls  = ctrl.class_name()
            rect = ctrl.rectangle()
            if rect.width() > 0 and rect.height() > 0:
                print(f"[{i:3d}] cls={cls:35s} txt={txt!r:30s} rect=({rect.left},{rect.top},{rect.right},{rect.bottom})")
        except Exception:
            pass

except Exception as e:
    print(f"연결 실패: {e}")
    print("TfrxPreviewForm 창이 열려 있는지 확인해주세요.")
