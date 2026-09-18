"""저장 다이얼로그 컨트롤 구조 덤프 - 실행 전 저장 다이얼로그를 열어두세요"""
import time
from pywinauto import Desktop

print("3초 후 #32770 다이얼로그 탐색 시작...")
time.sleep(3)

wins = Desktop(backend="win32").windows(class_name="#32770")
print(f"#32770 창 수: {len(wins)}")

for i, w in enumerate(wins):
    try:
        r = w.rectangle()
        print(f"\n[창 {i}] txt={repr(w.window_text())} w={r.width()} h={r.height()}")
        if r.width() < 200:
            continue
        print("  자식 컨트롤:")
        for ctrl in w.descendants():
            try:
                cr = ctrl.rectangle()
                txt = ctrl.window_text()[:40]
                cls = ctrl.class_name()
                parent_cls = ctrl.parent().class_name() if ctrl.parent() else "?"
                print(f"    cls={cls:25s} txt={repr(txt):35s} w={cr.width():4d} h={cr.height():3d} parent={parent_cls}")
            except Exception as e:
                print(f"    [err] {e}")
    except Exception as e:
        print(f"  [창 err] {e}")
