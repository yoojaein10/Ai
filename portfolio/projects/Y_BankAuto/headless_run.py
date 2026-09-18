"""
HUG 실테스트 — GUI 없이 run_extraction() 직접 호출
settings.ini: C:\Bank24Extractor\settings.ini
"""
import configparser
import sys
import os
import threading
import datetime

# Y_BankAuto 디렉터리를 sys.path에 추가
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

SETTINGS_INI = r"C:\Bank24Extractor\settings.ini"
LOG_DIR = r"C:\Bank24Extractor\logs"
DEFAULT_PDF_DIR = r"\\data\DATA\6.업무2팀\온라인접수"


def load_ini():
    cfg = configparser.ConfigParser()
    cfg.read(SETTINGS_INI, encoding="utf-8")
    return cfg


def build_config(cfg):
    uid = cfg.get("login", "bank24_id", fallback="")
    pwd = cfg.get("login", 'REDACTED_CONFIGURE_LOCALLY', fallback="")
    banks_raw = cfg.get("options", "banks", fallback="주택도시보증공사")
    banks = [b.strip() for b in banks_raw.split(",") if b.strip()]

    date_from = cfg.get("options", "date_from", fallback=datetime.date.today().isoformat())
    date_to   = cfg.get("options", "date_to",   fallback=datetime.date.today().isoformat())
    source_tab = cfg.get("options", "source_tab", fallback="미접수")
    work_type  = cfg.get("options", "work_type",  fallback="담보")
    pdf_dir    = cfg.get("pdf", "dir", fallback=DEFAULT_PDF_DIR)
    if os.path.normcase(os.path.normpath(pdf_dir)) == os.path.normcase(
        os.path.normpath(r"C:\Bank24Extractor\pdf")
    ):
        pdf_dir = DEFAULT_PDF_DIR

    db_cfg = {
        "enabled":                  cfg.getboolean("database", "enabled", fallback=True),
        "server":                   cfg.get("database", "server",   fallback='192.0.2.10'),
        "port":                     cfg.get("database", "port",     fallback="1433"),
        "database":                 cfg.get("database", "database", fallback="apworksdw"),
        "username":                 cfg.get("database", "username", fallback="dh"),
        "password":                 cfg.get("database", "password", fallback=""),
        "driver":                   cfg.get("database", "driver",   fallback="ODBC Driver 17 for SQL Server"),
        "trust_server_certificate": cfg.getboolean("database", "trust_server_certificate", fallback=True),
        "table":                    cfg.get("database", "table",               fallback="YJI_BankRequest"),
        "rollback_test":            cfg.getboolean("database", "rollback_test", fallback=False),
        "reg_lookup_database":      cfg.get("database", "reg_lookup_database", fallback="apworksdw"),
        "reg_lookup_table":         cfg.get("database", "reg_lookup_table",    fallback="APW_RegHist"),
    }

    return {
        "bank24_id":  uid,
        'REDACTED_CONFIGURE_LOCALLY':  pwd,
        "date_mode":  "manual",
        "date_from":  date_from,
        "date_to":    date_to,
        "banks":      banks,
        "bank":       banks[0] if banks else "",
        "work_type":  work_type,
        "output_dir": pdf_dir,
        "save_txt":   True,
        "db_insert":  db_cfg["enabled"],
        "database":   db_cfg,
        "restart":    False,
        "auto_launch_if_closed": cfg.getboolean("options", "auto_launch_if_closed", fallback=True),
        "pdf_enabled": cfg.getboolean("pdf", "enabled", fallback=True),
        "pdf_dir":     pdf_dir,
        "source_tab":  source_tab,
    }


def make_log(log_file):
    lock = threading.Lock()

    def _log(msg):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        with lock:
            print(line, flush=True)
            if log_file:
                log_file.write(line + "\n")
                log_file.flush()

    return _log


def main():
    cfg = load_ini()
    config = build_config(cfg)

    print("=" * 64)
    print("  Y_BankAuto 헤드리스 실테스트")
    print(f"  은행: {config['banks']}")
    print(f"  기간: {config['date_from']} ~ {config['date_to']}")
    print(f"  탭: {config['source_tab']}  업무: {config['work_type']}")
    print(f"  DB: {config['database']['server']} / {config['database']['database']}")
    rollback = config["database"].get("rollback_test", False)
    print(f"  rollback_test: {rollback}")
    print("=" * 64)
    print()

    os.makedirs(LOG_DIR, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(LOG_DIR, f"headless_{ts}.log")
    log_file = open(log_path, "w", encoding="utf-8")
    log = make_log(log_file)

    log(f"로그 파일: {log_path}")

    try:
        import extract_shinhan as es

        stopped = []

        callbacks = {
            "log":        log,
            "on_step":    lambda name, state: log(f"[STEP] {name} → {state}"),
            "on_item":    lambda item: log(f"[ITEM] {item.get('의뢰번호','?')} {item.get('처리상태','?')}"),
            "should_stop": lambda: False,
        }

        es.run_extraction(config, callbacks)

    except Exception as exc:
        import traceback
        log(f"[FATAL] {exc}")
        log(traceback.format_exc())
        sys.exit(1)
    finally:
        log_file.close()

    print()
    print(f"완료. 전체 로그: {log_path}")


if __name__ == "__main__":
    main()
