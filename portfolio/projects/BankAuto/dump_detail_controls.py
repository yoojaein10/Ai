"""
TBnkTop24Rcp (종합접수) 창 컨트롤 전체 덤프
- bank24에서 종합접수 창을 열어둔 상태에서 실행
"""
from pywinauto import Application

app = Application(backend="win32").connect(class_name="TBnkTop24Rcp")
win = app.top_window()

print(f"창 타이틀: {win.window_text()}")
print(f"창 클래스: {win.element_info.class_name}")
print("=" * 70)

edit_classes = ("TEdit", "TcxEdit", "TcxCustomInnerTextEdit", "TcxTextEdit", "TMemo", "TcxMemo")
label_classes = ("TLabel", "TcxLabel", "TStaticText")

all_ctrls = list(win.descendants())
for i, ctrl in enumerate(all_ctrls):
    try:
        cls = ctrl.class_name()
        txt = ctrl.window_text().strip()
        if cls in edit_classes and txt:
            print(f"[{i:03d}] EDIT  cls={cls:<35} val='{txt}'")
        elif cls in label_classes and txt:
            print(f"[{i:03d}] LABEL cls={cls:<35} txt='{txt}'")
    except Exception:
        continue
