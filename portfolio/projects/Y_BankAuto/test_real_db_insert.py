"""
실제 Bank24 데이터 추출 + DB INSERT 통합 테스트
- 1건만 처리하려면 should_stop 콜백으로 첫 item 이후 중단
"""
import sys, time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, r'D:\AI\Claude\Y_BankAuto')
import extract_shinhan as es

TODAY    = datetime.today()
DATE_TO  = TODAY.strftime("%Y-%m-%d")
DATE_FROM = (TODAY - timedelta(days=3)).strftime("%Y-%m-%d")

config = {
    "bank24_id":  "dbwodls00",
    'REDACTED_CONFIGURE_LOCALLY':  'REDACTED_CONFIGURE_LOCALLY',
    "date_from":  DATE_FROM,
    "date_to":    DATE_TO,
    "banks":      ["신한"],
    "output_dir": r"C:\Bank24Extractor\output",
    "save_txt":   False,
    "db_insert":  True,
    "restart":    True,
    "database": {
        "driver":                   "ODBC Driver 17 for SQL Server",
        "server":                   '192.0.2.10',
        "port":                     1433,
        "database":                 "apworksdw",
        "username":                 "dh",
        "password":                 'REDACTED_CONFIGURE_LOCALLY',
        "trust_server_certificate": True,
        "table":                    "YJI_BankRequest",
        "rollback_test":             False,
        "reg_lookup_database":      "apworksdw",
        "reg_lookup_table":         "APW_RegHist",
    },
}

items_seen = []

def on_log(msg):
    print(msg)

def on_step(name, state):
    print(f"\n>>> [{state.upper()}] {name}")

def on_item(item):
    items_seen.append(item)
    print(f"\n{'='*60}")
    print(f"  [ITEM] 의뢰번호={item.get('의뢰번호')}  감정서번호={item.get('감정서번호')}")
    print(f"  처리상태 : {item.get('처리상태')}")
    print(f"  은행     : {item.get('은행')}")
    print(f"  영업점   : {item.get('영업점')}")
    print(f"  소유자   : {item.get('소유자')}")
    print(f"  채무자   : {item.get('채무자')}")
    print(f"  비고     : {item.get('비고', '')[:80]}")
    print(f"  소재지   : {item.get('pdf_소재지')}")
    print(f"{'='*60}")

def on_summary(d):
    print(f"\n{'='*60}")
    print("  추출 완료 요약")
    print(f"  총건수: {d.get('total')}  성공: {d.get('success')}  실패: {d.get('fail')}")
    db = d.get('db', {})
    if db:
        print(f"  DB INSERT tried={db.get('tried')} success={db.get('success')} fail={db.get('fail')}")
    print(f"{'='*60}")

callbacks = {
    "on_log":     on_log,
    "on_step":    on_step,
    "on_item":    on_item,
    "on_summary": on_summary,
}

print(f"날짜 범위: {DATE_FROM} ~ {DATE_TO}")
print("Bank24 실행 중...\n")

es.run_extraction(config, callbacks)
