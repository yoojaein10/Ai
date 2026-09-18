"""
batch_load_test.py — PDF → 테스트DB 직접 적재 (exe GUI 대체)
- pdf_parser.parse_bank24_pdf() + db_writer.insert_apw_master_expand() 직접 호출
- 수정 금지 파일(db_writer.py / pdf_parser.py) 수정 없음
- 실서버 INSERT 금지: C:\Bank24Extractor\settings.ini database=apworksdw 에만 INSERT
"""
import configparser
import glob
import json
import os
import sys
from pathlib import Path

# 소스 모듈 경로
BASE = Path(r"D:\AI\Claude\Y_BankAuto")
sys.path.insert(0, str(BASE))

import pdf_parser as pp
import db_writer as dw

# ── 설정 로드 ──────────────────────────────────────────────────────
SETTINGS = Path(r"C:\Bank24Extractor\settings.ini")
cfg = configparser.ConfigParser()
cfg.read(SETTINGS, encoding="utf-8")
db_sec = cfg["database"]

DB_CONFIG = {
    "driver":                   db_sec.get("driver", "ODBC Driver 17 for SQL Server"),
    "server":                   db_sec.get("server"),
    "port":                     db_sec.get("port", "1433"),
    "database":                 db_sec.get("database"),          # apworksdw
    "username":                 db_sec.get("username"),
    "password":                 db_sec.get("password"),
    "trust_server_certificate": db_sec.get("trust_server_certificate", "true"),
    "reg_lookup_database":      db_sec.get("reg_lookup_database", "apworksdw"),
    "reg_lookup_table":         db_sec.get("reg_lookup_table",    "APW_RegHist"),
}

BANK_DIRS = [
    "신한은행", "기업은행", "우리은행", "주택도시보증공사",
    "국민은행", "새마을금고", "하나은행", "농협은행", "농협중앙회", "수협은행",
]

ROLLBACK_TEST = False  # 실제 INSERT

# ── PDF 파싱 ──────────────────────────────────────────────────────
log_lines = []
def log(msg):
    print(msg)
    log_lines.append(msg)

items = []
parse_skip = []

for bank_dir in BANK_DIRS:
    pdf_paths = sorted(glob.glob(str(BASE / bank_dir / "*.pdf")))
    for pdf_path in pdf_paths:
        try:
            parsed = pp.parse_bank24_pdf(pdf_path)
            if not isinstance(parsed, dict):
                parse_skip.append({"path": pdf_path, "reason": "parse 반환값 비정상"})
                log(f"  SKIP(parse) {os.path.relpath(pdf_path, BASE)}")
                continue

            # 소재지 확인
            addr_candidates = [
                (parsed.get("pdf_소재지") or "").strip(),
                *[(a.strip()) for a in (parsed.get("addresses") or [])],
                (parsed.get("주소") or "").strip(),
            ]
            has_addr = any(addr_candidates)
            if not has_addr:
                parse_skip.append({"path": pdf_path, "reason": "소재지 없음"})
                log(f"  SKIP(addr) {os.path.relpath(pdf_path, BASE)}")
                continue

            item = dict(parsed)
            item["처리상태"] = "성공"
            # 상세창 의뢰번호 fallback
            if not item.get("상세창 의뢰번호"):
                item["상세창 의뢰번호"] = item.get("의뢰번호", "")
            items.append(item)
            log(f"  PARSED {os.path.relpath(pdf_path, BASE)} | 은행={item.get('은행','')} | 의뢰={item.get('의뢰번호','')}")
        except Exception as e:
            parse_skip.append({"path": pdf_path, "reason": f"{type(e).__name__}: {e}"})
            log(f"  ERROR(parse) {os.path.relpath(pdf_path, BASE)}: {e}")

log(f"\n파싱 완료: 성공={len(items)} / SKIP={len(parse_skip)}")
if parse_skip:
    for s in parse_skip:
        log(f"  SKIP: {s['path']} → {s['reason']}")

# ── DB INSERT ─────────────────────────────────────────────────────
if not items:
    log("INSERT 대상 없음 — 중단")
    sys.exit(1)

log(f"\n=== DB INSERT 시작 (rollback_test={ROLLBACK_TEST}) ===")
result = dw.insert_apw_master_expand(
    items,
    DB_CONFIG,
    log=log,
    rollback_test=ROLLBACK_TEST,
)

log(f"\n=== INSERT 결과 ===")
log(f"tried={result['tried']} success={result['success']} fail={result['fail']}")
for err in result.get("errors", []):
    log(f"  ERROR: {err}")

# ── 결과 저장 ──────────────────────────────────────────────────────
out = {
    "parse_count": len(items),
    "parse_skip_count": len(parse_skip),
    "parse_skip": parse_skip,
    "db_result": {
        "tried":   result["tried"],
        "success": result["success"],
        "fail":    result["fail"],
        "errors":  result.get("errors", []),
        "outputs": result.get("outputs", []),
    },
    "log": log_lines,
}
out_path = BASE / "reports" / "batch_load_result.json"
out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\n결과 저장: {out_path}")
