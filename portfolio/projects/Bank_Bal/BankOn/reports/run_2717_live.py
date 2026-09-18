# 2717(신한) 1건 LIVE — 이 PC 에서 큐 워커 경유(이력 일관·배포 PC 워커와 이중 실행 방지). 관리자 권한으로 띄움.
# Send#12425 Status '진행'(배포 ini 는 '대기'만 보므로 배포 PC 워커는 안 집어감). 이력 없음. 전례 PDF 없음 → PDF 등록 건너뜀.
import io, sys, pathlib, traceback
ROOT = pathlib.Path(r"D:\AI\Claude\Bank_Bal\BankOn")
sys.path.insert(0, str(ROOT / "tools")); sys.path.insert(0, str(ROOT / "src"))
out = open(ROOT / "reports" / "worker_2717_live.out", "w", encoding="utf-8", errors="replace", buffering=1)
sys.stdout = out; sys.stderr = out
try:
    import run_queue_worker as W
    from bankon.config import load_config
    from bankon.db import connect
    cfg = load_config(None)
    with connect(cfg.source_sql) as rw:
        cur = rw.cursor()
        cur.execute("SELECT Seq, Status, Msg FROM dbo.Apw_YJI_BankAuto WHERE Send_Seq = 12425")
        row = cur.fetchone()
        print(f"[wrapper] 기존 이력: {row}")
        if row and row[1] in ("완료", "처리중"):
            W.finish(rw, int(row[0]), "실패", "이 PC 에서 재실행 전 전환(2026-09-08)", None)
            print("[wrapper] Seq", row[0], "→ 실패로 전환(재실행 허용)")
    rc = W.main(["--live", "--once", "--seq", "12425", "--statuses", "진행,대기"])
    print(f"[wrapper] worker exit={rc}")
except Exception:
    traceback.print_exc()
finally:
    out.close()
