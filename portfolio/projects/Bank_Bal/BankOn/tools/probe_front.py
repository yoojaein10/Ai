"""로그인 뒤 메인 창이 앞으로 오는지 확인 — 관리자로 실행. 읽기 전용."""
import ctypes, os, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; os.chdir(ROOT); sys.path.insert(0, str(ROOT / "src"))
from bankon.config import load_config
from bankon.ui import driver, navigate
out = ROOT / "reports" / "probe_front.log"
def log(m):
    with open(out, "a", encoding="utf-8") as f: f.write(f"{time.strftime('%H:%M:%S')} {m}\n")
cfg = load_config()
try:
    s = navigate.open_app(cfg.loader_cmd, cfg.bankon_user, cfg.bankon_password)
    u32 = ctypes.windll.user32
    fg = u32.GetForegroundWindow()
    log(f"main={s.main.handle} fg={fg} front={fg == s.main.handle} iconic={bool(u32.IsIconic(s.main.handle))}")
    ok = driver.bring_to_front(s.main.handle)
    log(f"bring_to_front again -> {ok} fg={u32.GetForegroundWindow()}")
except Exception as e:
    log(f"ERR {e!r}")
