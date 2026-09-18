import sys, time
sys.path.insert(0, 'Y:\\PUBLIC_SOURCE\\tools'); sys.path.insert(0, 'Y:\\PUBLIC_SOURCE\\src')
out=open('Y:\\PUBLIC_SOURCE\\scratch_rowtest3.log',"w",encoding="utf-8")
def w(*a): print(*a,file=out); out.flush()
from bankon.ui import driver, navigate
from pywinauto.keyboard import send_keys
session=navigate.Session(driver.find_windows(driver.MAIN_CLASS)[0])
def soin(form):
    from inspect_bankon import _connect, walk
    from map_fields import collect
    bun=addr=appr=None
    for f in collect(walk(_connect(driver.BACKEND, title_re=None, pid=None, handle=form.handle))):
        if f["label"]=="본번지": bun=f["value"]
        if f["label"]=="평가사명1" and f["value"]: appr=f["value"]
        if not f["label"] and len(f["value"])>6 and not addr: addr=f["value"]
    return f"{addr} / 본번{bun} / {appr}"
grid=navigate._grid(session)
grid.set_focus(); time.sleep(0.3)
send_keys("^{HOME}"); time.sleep(0.3)   # 맨 위 행
for i in range(3):
    send_keys("+{F10}"); time.sleep(0.7)   # 컨텍스트 메뉴
    send_keys("a")
    try:
        form=driver.wait_for_window(driver.FORM_CLASS_PREFIX, pid=session.pid, timeout=15)
        w(f"행{i}: {soin(form)}")
        btn=driver.by_text(form.handle,"닫 기","TcxButton")
        if btn: driver.click(btn)
        time.sleep(1.2)
    except Exception as e:
        w(f"행{i}: 폼안열림 {str(e)[:50]}"); break
    # 다음 행으로
    grid.set_focus(); time.sleep(0.3)
    send_keys("{DOWN}"); time.sleep(0.3)
out.close()
