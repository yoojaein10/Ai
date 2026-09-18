# 2776 1건 LIVE 재실행 — 사용자가 Bank24 화면을 초기화한 뒤(2026-09-07 15:2x). 큐 워커 경유(이력 일관·이중 실행 방지). 관리자 권한으로 띄움.
# 종전 이력(Seq 28, 완료: 물건종류 '기타' 잔류·PDF 건너뜀)을 '실패'로 돌려야 워커가 '제외'하지 않는다.
import io, sys, pathlib, traceback
ROOT = pathlib.Path(r"D:\AI\Claude\Bank_Bal\BankOn")
sys.path.insert(0, str(ROOT / "tools")); sys.path.insert(0, str(ROOT / "src"))
out = open(ROOT / "reports" / "worker_2776_live.out", "w", encoding="utf-8", errors="replace", buffering=1)
sys.stdout = out; sys.stderr = out
try:
    import run_queue_worker as W
    from bankon.config import load_config
    from bankon.db import connect
    cfg = load_config(None)
    with connect(cfg.source_sql) as rw:
        cur = rw.cursor()
        cur.execute("SELECT Seq, Status FROM dbo.Apw_YJI_BankAuto WHERE Send_Seq = 12406")
        row = cur.fetchone()
        print(f"[wrapper] 기존 이력: {row}")
        if row and row[1] == "완료":
            W.finish(rw, int(row[0]), "실패", "사용자가 Bank24 화면 초기화 후 재실행(물건종류 '기타' 잔류 건, 2026-09-07)", None)
            print("[wrapper] Seq", row[0], "→ 실패로 전환(재실행 허용)")
    rc = W.main(["--live", "--once", "--seq", "12406", "--statuses", "진행"])
    print(f"[wrapper] worker exit={rc}")
except Exception:
    traceback.print_exc()
finally:
    out.close()
