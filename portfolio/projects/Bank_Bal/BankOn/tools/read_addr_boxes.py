"""읽기전용: 발송완료/작성 탭에서 폼을 열어 물건 행마다 '동미만' 칸·읍면동 칸 전체 값을 읽는다(관리자).
    read_addr_boxes.py <from> <to> <doc> [탭]
"""
import io, os, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "src"))
FROM, TO, DOC = sys.argv[1:4]; TAB = sys.argv[4] if len(sys.argv) > 4 else "작성"
ts = time.strftime("%Y%m%d_%H%M%S")
log = open(ROOT / "reports" / f"addr_{ts}.log", "w", encoding="utf-8", errors="replace")
class Tee(io.TextIOBase):
    def write(self, s):
        for st in (sys.__stdout__, log): st.write(s); st.flush()
        return len(s)
sys.stdout = sys.stderr = Tee()
from bankon.config import load_config
from bankon.ui import driver, navigate
session = None
try:
    cfg = load_config(None)
    session = navigate.open_app(cfg.loader_cmd, cfg.bankon_user, cfg.bankon_password)
    navigate.select_tab(session, TAB)
    def requery():
        navigate.query_documents(session, start=FROM, end=TO, work_type="담보")
        navigate.close_forms(session)
    requery()
    print("행:", navigate.ensure_row(session, DOC, requery=requery))
    form = navigate.open_write_form(session, home=False)
    n = navigate.count_object_rows(form)
    print(f"{DOC} 탭={TAB} 물건행={n}")
    for r in range(n):
        navigate.select_object_row(form, r); time.sleep(0.4)
        vals = {}
        for name, dy in (("동미만", 127), ("읍면동", 176)):
            c = driver.find_by_offset(form.handle, "물건순번", -126, dy, "TcxDBTextEdit")
            vals[name] = driver.read(driver.editable(c)) if c is not None else "(미발견)"
        print(f"  행{r + 1}: 동미만={vals['동미만']!r}  읍면동={vals['읍면동']!r}")
except Exception as e:
    import traceback; traceback.print_exc()
finally:
    if session:
        navigate.close_forms(session)
