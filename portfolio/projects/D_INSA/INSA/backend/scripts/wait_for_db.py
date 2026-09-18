import pyodbc
import time
import sys

CONN_STR = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=db,1433;"
    "UID=sa;"
    'PWD=REDACTED_CONFIGURE_LOCALLY;'
    "TrustServerCertificate=yes"
)

for attempt in range(30):
    try:
        conn = pyodbc.connect(CONN_STR, autocommit=True)
        cursor = conn.cursor()
        cursor.execute(
            "IF NOT EXISTS (SELECT * FROM sys.databases WHERE name='insa') "
            "CREATE DATABASE insa"
        )
        conn.close()
        print("Database ready")
        sys.exit(0)
    except Exception as e:
        print(f"Waiting for DB... {e}", flush=True)
        time.sleep(2)

print("Failed to connect to DB after 30 attempts", file=sys.stderr)
sys.exit(1)
