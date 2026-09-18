import sys, time
sys.path.insert(0, r"D:\AI\Claude\Bank_Bal\BankOn\src")
from bankon.ui import navigate, driver
out = open(r"D:\AI\Claude\Bank_Bal\BankOn\reports\probe_tab.log", "w", encoding="utf-8")
try:
    session = navigate.Session(driver.find_windows(driver.MAIN_CLASS, title_any=driver.MAIN_TITLE_HINTS)[0])
    import ctypes; print("admin", ctypes.windll.shell32.IsUserAnAdmin(), file=out)
    ok = navigate.select_tab(session, "발송완료"); time.sleep(1.5)
    driver.window(session.main.handle).capture_as_image().save(r"D:\AI\Claude\Bank_Bal\BankOn\reports\probe_tab.png")
    print("select_tab ->", ok, file=out)
except Exception as e:
    import traceback; traceback.print_exc(file=out)
out.close()
