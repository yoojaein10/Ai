import sys, time, ctypes
sys.path.insert(0, 'Y:\\PUBLIC_SOURCE\\tools'); sys.path.insert(0, 'Y:\\PUBLIC_SOURCE\\src')
out=open('Y:\\PUBLIC_SOURCE\\scratch_rowtest.log',"w",encoding="utf-8")
def w(*a): print(*a,file=out); out.flush()
from bankon.ui import driver, navigate
from pywinauto.keyboard import send_keys
from pywinauto.findwindows import find_elements
try:
    session=navigate.Session(driver.find_windows(driver.MAIN_CLASS)[0])
    grid=navigate._grid(session)
    r=grid.rectangle(); w("결과그리드:",hex(int(grid.handle)),f"({r.left},{r.top},{r.right},{r.bottom})")
    grid.set_focus(); time.sleep(0.4)
    before={int(e.handle) for e in find_elements(backend="win32") if (e.class_name or"")=="#32768" and e.handle}
    # 행 선택 시도: Down 한 번
    send_keys("{DOWN}"); time.sleep(0.4)
    # 컨텍스트 메뉴(키보드)
    send_keys("+{F10}"); time.sleep(0.8)
    menus={int(e.handle) for e in find_elements(backend="win32") if (e.class_name or"")=="#32768" and e.handle}
    w("Shift+F10 후 컨텍스트메뉴 새로뜸:", len(menus-before))
    # 작성 가속키
    send_keys("a"); 
    try:
        form=driver.wait_for_window(driver.FORM_CLASS_PREFIX, pid=session.pid, timeout=20)
        w("★ 폼 열림:", form.class_name, hex(form.handle))
        # 본번지 읽기
        sys.path.insert(0,'Y:\\PUBLIC_SOURCE\\tools')
        from inspect_bankon import _connect, walk
        from map_fields import collect
        for f in collect(walk(_connect(driver.BACKEND, title_re=None, pid=None, handle=form.handle))):
            if f["label"]=="본번지": w("  본번지=",f["value"])
            if not f["label"] and len(f["value"])>6: w("  소재지=",f["value"]); break
        # 닫기
        btn=driver.by_text(form.handle,"닫 기","TcxButton")
        w("닫기버튼:", "있음" if btn else "없음")
        if btn:
            driver.click(btn); time.sleep(1.5)
            w("닫은 뒤 폼 남음:", [f.class_name for f in driver.find_windows(driver.FORM_CLASS_PREFIX)] or "없음(닫힘✓)")
    except Exception as e:
        w("폼 안 열림:", str(e)[:80])
except Exception as e:
    import traceback; w("에러:", traceback.format_exc()[:500])
out.close()
