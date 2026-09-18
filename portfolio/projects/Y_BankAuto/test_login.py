"""
로그인 직접 테스트 — _set_edit_text_direct / _click_login_ok_button 검증
"""
import sys, os, time
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

os.environ["BANK24_ID"] = "dbwodls00"
os.environ["BANK24_PW"] = 'REDACTED_CONFIGURE_LOCALLY'

sys.path.insert(0, r"D:\AI\Claude\Y_BankAuto")
from extract_shinhan import (
    kill_existing, launch_and_login, wait_main,
    safe_txt, log
)

uid = os.environ["BANK24_ID"]
pwd = os.environ["BANK24_PW"]

print(f"[TEST] 로그인 테스트 시작 — ID: {uid}")
kill_existing()
launch_and_login(uid, pwd)
main_win = wait_main()

if main_win:
    print(f"[TEST] ✅ 메인창 진입 성공: {safe_txt(main_win)!r}")
else:
    print("[TEST] ❌ 메인창 진입 실패")
