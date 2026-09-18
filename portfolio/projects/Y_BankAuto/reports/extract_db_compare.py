import configparser
import datetime as dt
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import pyodbc

BASE = Path(r"D:\AI\Claude\Y_BankAuto")
OUT_DIR = BASE / "reports"
OUT_DIR.mkdir(parents=True, exist_ok=True)

settings = Path(r"C:\Bank24Extractor\settings.ini")
cfg = configparser.ConfigParser()
cfg.read(settings, encoding="utf-8")
db = cfg["database"]
driver = db.get("driver", "ODBC Driver 17 for SQL Server")
port = db.get("port", "1433")


def conn_str(server, user, pwd):
    return (
        f"DRIVER={{{driver}}};SERVER={server},{port};DATABASE=apworksdw;"
        f"UID={user};PWD={pwd};TrustServerCertificate=yes;"
    )


test_cs = conn_str(db.get("server"), db.get("username"), db.get("password"))
real_cs = conn_str('192.0.2.10', "dh", 'REDACTED_CONFIGURE_LOCALLY')

log_path = max(Path(r"C:\Bank24Extractor\logs").glob("*.log"), key=lambda p: p.stat().st_mtime)
log_text = log_path.read_text(encoding="utf-8", errors="replace")
batch_master_ids = [int(x) for x in re.findall(r"MstID=(\d+)", log_text)]
if not batch_master_ids:
    raise RuntimeError(f"No MstID found in {log_path}")

master_cols = [
    "MasterID", "DocID", "CustDocID", "ReceiptDate", "RequestDate", "LimitDate",
    "WorkInfo", "Purpose", "Category", "CustID", "CustName", "CustPart",
    "CustCharge", "CustPhone", "OwnerName", "OwnerPhone", "Debtor", "DebtrID",
    "DebtrPhone", "Title", "SendMethod", "Bigo", "AddrEtc", "AddrPyoung",
    "BuildingEtc", "BuildingPyoung", "CustChargeHP", "HouseCnt", "CustCategory1",
    "RefDocID", "Report_bungi", "ORD_HOI", "GUBUN_CODE", "DEBTOR_ADDR",
]
ignore_master_compare = {"MasterID", "DocID", "ReceiptDate"}
compare_master_cols = [c for c in master_cols if c not in ignore_master_compare]

inv_cols = [
    "SEQ", "MasterID", "DocID", "Row_ID", "REG", "EUB", "SAN", "ADDR", "BUN1",
    "BUN2", "REG1", "EUB1", "Building", "Dong", "Floor", "Ho", "hoetc", "InDate",
]
ignore_inv_compare = {"SEQ", "MasterID", "DocID", "Row_ID", "InDate"}
compare_inv_cols = [c for c in inv_cols if c not in ignore_inv_compare]

phone_fields = {"CustPhone", "OwnerPhone", "DebtrPhone", "CustChargeHP"}
numeric_text_fields = {"BUN1", "BUN2", "REG", "EUB", "REG1", "EUB1"}


def ph(n):
    return ",".join("?" for _ in range(n))


def raw_norm(v):
    if v is None:
        return ""
    if isinstance(v, dt.datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, dt.date):
        return v.strftime("%Y-%m-%d")
    return str(v).strip()


def cmp_norm(field, v):
    s = raw_norm(v)
    if field in phone_fields:
        return re.sub(r"\D+", "", s)
    if field in numeric_text_fields and re.fullmatch(r"0*\d+", s or ""):
        return str(int(s))
    if field in {"Bigo", "Title", "CustName", "OwnerName", "Debtor", "ADDR", "Building", "Dong", "Floor", "Ho", "hoetc"}:
        return re.sub(r"\s+", " ", s)
    return s


def fetch_test_master(conn):
    cur = conn.cursor()
    sql = f"SELECT {','.join(master_cols)} FROM dbo.APW_Master WHERE MasterID IN ({ph(len(batch_master_ids))}) ORDER BY MasterID"
    cur.execute(sql, batch_master_ids)
    return [{col: getattr(row, col) for col in master_cols} for row in cur.fetchall()]


def fetch_real_master(conn, cust_docids):
    cur = conn.cursor()
    sql = f"""
    WITH ranked AS (
        SELECT {','.join(master_cols)},
               ROW_NUMBER() OVER (PARTITION BY CustDocID ORDER BY MasterID DESC) AS rn
        FROM dbo.APW_Master
        WHERE CustDocID IN ({ph(len(cust_docids))})
    )
    SELECT {','.join(master_cols)}
    FROM ranked
    WHERE rn = 1
    ORDER BY CustDocID
    """
    cur.execute(sql, cust_docids)
    return [{col: getattr(row, col) for col in master_cols} for row in cur.fetchall()]


def fetch_inventory(conn, master_rows):
    out = defaultdict(list)
    if not master_rows:
        return out
    cur = conn.cursor()
    pairs = [(int(r["MasterID"]), raw_norm(r["DocID"])) for r in master_rows]
    for start in range(0, len(pairs), 40):
        chunk = pairs[start:start + 40]
        where = " OR ".join("(MasterID=? AND DocID=?)" for _ in chunk)
        params = []
        for mid, docid in chunk:
            params.extend([mid, docid])
        sql = f"SELECT {','.join(inv_cols)} FROM dbo.APW_Inventory WHERE {where} ORDER BY MasterID, DocID, SEQ"
        cur.execute(sql, params)
        for row in cur.fetchall():
            d = {col: getattr(row, col) for col in inv_cols}
            out[(int(d["MasterID"]), raw_norm(d["DocID"]))].append(d)
    return out


with pyodbc.connect(test_cs, timeout=15) as test_conn, pyodbc.connect(real_cs, timeout=15) as real_conn:
    test_master = fetch_test_master(test_conn)
    cust_docids = [raw_norm(r["CustDocID"]) for r in test_master]
    real_master = fetch_real_master(real_conn, cust_docids)
    test_inventory = fetch_inventory(test_conn, test_master)
    real_inventory = fetch_inventory(real_conn, real_master)

real_by_custdoc = {raw_norm(r["CustDocID"]): r for r in real_master}

summary_by_doc = []
master_diffs = []
inventory_diffs = []
missing_real = []
master_raw_rows = []
master_field_counts = Counter()
inventory_field_counts = Counter()

for test_row in test_master:
    custdoc = raw_norm(test_row["CustDocID"])
    real_row = real_by_custdoc.get(custdoc)
    test_key = (int(test_row["MasterID"]), raw_norm(test_row["DocID"]))
    test_inv = test_inventory.get(test_key, [])

    if not real_row:
        missing_real.append({
            "CustDocID": custdoc,
            "TestMasterID": raw_norm(test_row["MasterID"]),
            "TestDocID": raw_norm(test_row["DocID"]),
            "TestCustName": raw_norm(test_row["CustName"]),
            "TestTitle": raw_norm(test_row["Title"]),
        })
        summary_by_doc.append({
            "CustDocID": custdoc,
            "BankCustomer": raw_norm(test_row["CustName"]),
            "Status": "REAL_MASTER_MISSING",
            "MasterDiffCount": "REAL_MISSING",
            "InventoryDiffCount": "REAL_MISSING",
            "TestInvRows": len(test_inv),
            "RealInvRows": 0,
            "TestMasterID": raw_norm(test_row["MasterID"]),
            "RealMasterID": "",
            "TestDocID": raw_norm(test_row["DocID"]),
            "RealDocID": "",
        })
        continue

    real_key = (int(real_row["MasterID"]), raw_norm(real_row["DocID"]))
    real_inv = real_inventory.get(real_key, [])
    doc_master_diff_count = 0

    for col in compare_master_cols:
        test_raw = raw_norm(test_row.get(col))
        real_raw = raw_norm(real_row.get(col))
        if cmp_norm(col, test_row.get(col)) != cmp_norm(col, real_row.get(col)):
            doc_master_diff_count += 1
            master_field_counts[col] += 1
            master_diffs.append({
                "CustDocID": custdoc,
                "BankCustomer": raw_norm(test_row["CustName"]),
                "Field": col,
                "TestValue": test_raw,
                "RealValue": real_raw,
                "TestMasterID": raw_norm(test_row["MasterID"]),
                "RealMasterID": raw_norm(real_row["MasterID"]),
                "TestDocID": raw_norm(test_row["DocID"]),
                "RealDocID": raw_norm(real_row["DocID"]),
            })

    doc_inv_diff_count = 0
    if len(test_inv) != len(real_inv):
        doc_inv_diff_count += 1
        inventory_field_counts["RowCount"] += 1
        inventory_diffs.append({
            "CustDocID": custdoc,
            "BankCustomer": raw_norm(test_row["CustName"]),
            "InventoryIndex": "RowCount",
            "Field": "RowCount",
            "TestValue": str(len(test_inv)),
            "RealValue": str(len(real_inv)),
            "TestMasterID": raw_norm(test_row["MasterID"]),
            "RealMasterID": raw_norm(real_row["MasterID"]),
            "TestDocID": raw_norm(test_row["DocID"]),
            "RealDocID": raw_norm(real_row["DocID"]),
        })

    for idx in range(max(len(test_inv), len(real_inv))):
        test_i = test_inv[idx] if idx < len(test_inv) else None
        real_i = real_inv[idx] if idx < len(real_inv) else None
        for col in compare_inv_cols:
            test_raw = raw_norm(test_i.get(col)) if test_i else ""
            real_raw = raw_norm(real_i.get(col)) if real_i else ""
            test_cmp = cmp_norm(col, test_i.get(col)) if test_i else ""
            real_cmp = cmp_norm(col, real_i.get(col)) if real_i else ""
            if test_cmp != real_cmp:
                doc_inv_diff_count += 1
                inventory_field_counts[col] += 1
                inventory_diffs.append({
                    "CustDocID": custdoc,
                    "BankCustomer": raw_norm(test_row["CustName"]),
                    "InventoryIndex": idx + 1,
                    "Field": col,
                    "TestValue": test_raw,
                    "RealValue": real_raw,
                    "TestMasterID": raw_norm(test_row["MasterID"]),
                    "RealMasterID": raw_norm(real_row["MasterID"]),
                    "TestDocID": raw_norm(test_row["DocID"]),
                    "RealDocID": raw_norm(real_row["DocID"]),
                })

    summary_by_doc.append({
        "CustDocID": custdoc,
        "BankCustomer": raw_norm(test_row["CustName"]),
        "Status": "DIFF" if doc_master_diff_count or doc_inv_diff_count else "MATCH",
        "MasterDiffCount": doc_master_diff_count,
        "InventoryDiffCount": doc_inv_diff_count,
        "TestInvRows": len(test_inv),
        "RealInvRows": len(real_inv),
        "TestMasterID": raw_norm(test_row["MasterID"]),
        "RealMasterID": raw_norm(real_row["MasterID"]),
        "TestDocID": raw_norm(test_row["DocID"]),
        "RealDocID": raw_norm(real_row["DocID"]),
    })

    master_raw_rows.append({
        "CustDocID": custdoc,
        "TestMasterID": raw_norm(test_row["MasterID"]),
        "RealMasterID": raw_norm(real_row["MasterID"]),
        "TestDocID": raw_norm(test_row["DocID"]),
        "RealDocID": raw_norm(real_row["DocID"]),
        "TestCustName": raw_norm(test_row["CustName"]),
        "RealCustName": raw_norm(real_row["CustName"]),
        "TestTitle": raw_norm(test_row["Title"]),
        "RealTitle": raw_norm(real_row["Title"]),
    })

summary_metrics = [
    {"Metric": "LatestLog", "Value": str(log_path)},
    {"Metric": "TestBatchMasterIDRange", "Value": f"{min(batch_master_ids)} ~ {max(batch_master_ids)}"},
    {"Metric": "TestBatchMstIDCount", "Value": len(batch_master_ids)},
    {"Metric": "TestAPWMasterRows", "Value": len(test_master)},
    {"Metric": "RealAPWMasterMatchedRows", "Value": len(real_master)},
    {"Metric": "RealAPWMasterMissingRows", "Value": len(missing_real)},
    {"Metric": "MasterDiffCustDocIDCount", "Value": len({d["CustDocID"] for d in master_diffs})},
    {"Metric": "MasterDiffCellCount", "Value": len(master_diffs)},
    {"Metric": "InventoryDiffCustDocIDCount", "Value": len({d["CustDocID"] for d in inventory_diffs})},
    {"Metric": "InventoryDiffCellOrRowCount", "Value": len(inventory_diffs)},
    {"Metric": "TestInventoryRows", "Value": sum(len(v) for v in test_inventory.values())},
    {"Metric": "RealInventoryRows", "Value": sum(len(v) for v in real_inventory.values())},
    {"Metric": "InventoryJoinRule", "Value": "APW_Inventory.MasterID + APW_Inventory.DocID matched to APW_Master.MasterID + APW_Master.DocID"},
]

payload = {
    "created_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "summary_metrics": summary_metrics,
    "summary_by_doc": summary_by_doc,
    "master_diffs": master_diffs,
    "inventory_diffs": inventory_diffs,
    "missing_real": missing_real,
    "master_raw_rows": master_raw_rows,
    "master_field_counts": [{"Field": k, "DiffCount": v} for k, v in master_field_counts.most_common()],
    "inventory_field_counts": [{"Field": k, "DiffCount": v} for k, v in inventory_field_counts.most_common()],
}

out_json = OUT_DIR / f"db_compare_clean_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
print(out_json)
for item in summary_metrics:
    print(f"{item['Metric']}: {item['Value']}")
