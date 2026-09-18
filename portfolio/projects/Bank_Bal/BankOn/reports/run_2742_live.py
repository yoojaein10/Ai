# 2742 1건 LIVE — 큐 워커 경유(처리중/완료 이력이 남아 배포 PC 워커와 이중 실행 방지). 관리자 권한으로 띄움.
import io, sys, pathlib, traceback
ROOT = pathlib.Path(r"D:\AI\Claude\Bank_Bal\BankOn")
sys.path.insert(0, str(ROOT / "tools")); sys.path.insert(0, str(ROOT / "src"))
out = open(ROOT / "reports" / "worker_2742_live.out", "w", encoding="utf-8", errors="replace", buffering=1)
sys.stdout = out; sys.stderr = out
try:
    import run_queue_worker as W
    rc = W.main(["--live", "--once", "--seq", "12346", "--statuses", "진행"])
    print(f"[wrapper] worker exit={rc}")
except Exception:
    traceback.print_exc()
finally:
    out.close()
