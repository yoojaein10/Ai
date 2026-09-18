"""로컬 테스트 DB 생성 (개발 전용) — python make_testdb.py

DBAONE_TEST DB + Query Store + 계획서 시나리오 스키마/데이터/프로시저를 만들고,
읽기 전용 계정 dbaone_reader를 생성한 뒤 config.json의 mssql_conn을 갱신한다.
관리자 권한(Windows 인증)으로 localhost에 접속한다. 운영 서버에서 실행 금지.

정리(전부 삭제)하려면:
  DROP DATABASE DBAONE_TEST; DROP LOGIN dbaone_reader;
"""
import json
import secrets
import string
import random
import pyodbc
from pathlib import Path

BASE = Path(__file__).resolve().parent
ADMIN = "DRIVER={ODBC Driver 17 for SQL Server};SERVER=localhost;DATABASE=master;Trusted_Connection=yes"

conn = pyodbc.connect(ADMIN, timeout=10, autocommit=True)
cur = conn.cursor()

# 1) DB + Query Store
if not cur.execute("SELECT DB_ID('DBAONE_TEST')").fetchone()[0]:
    cur.execute("CREATE DATABASE DBAONE_TEST")
    print("DB 생성: DBAONE_TEST")
cur.execute("ALTER DATABASE DBAONE_TEST SET QUERY_STORE = ON")
cur.execute("ALTER DATABASE DBAONE_TEST SET QUERY_STORE"
            " (OPERATION_MODE = READ_WRITE, INTERVAL_LENGTH_MINUTES = 1, QUERY_CAPTURE_MODE = ALL)")
print("Query Store: READ_WRITE, 1분 간격")

cur.execute("USE DBAONE_TEST")

# 2) 스키마·테이블
def exec_if_missing(check_sql, ddl, label):
    if not cur.execute(check_sql).fetchone():
        cur.execute(ddl)
        print("생성:", label)

exec_if_missing("SELECT 1 FROM sys.schemas WHERE name='sales'", "CREATE SCHEMA sales", "schema sales")
exec_if_missing("SELECT 1 FROM sys.schemas WHERE name='common'", "CREATE SCHEMA common", "schema common")
exec_if_missing(
    "SELECT 1 FROM sys.tables WHERE name='OrderStatus'",
    "CREATE TABLE common.OrderStatus (StatusId int PRIMARY KEY, StatusName nvarchar(30) NOT NULL)",
    "common.OrderStatus")
exec_if_missing(
    "SELECT 1 FROM sys.tables WHERE name='Orders'",
    "CREATE TABLE sales.Orders (OrderId int IDENTITY PRIMARY KEY, CustomerId int NOT NULL,"
    " OrderDate datetime2 NOT NULL, StatusId int NOT NULL)",
    "sales.Orders")
exec_if_missing(
    "SELECT 1 FROM sys.tables WHERE name='OrderItems'",
    "CREATE TABLE sales.OrderItems (OrderItemId int IDENTITY PRIMARY KEY, OrderId int NOT NULL,"
    " Quantity int NOT NULL, UnitPrice decimal(12,2) NOT NULL)",
    "sales.OrderItems")
exec_if_missing(
    "SELECT 1 FROM sys.indexes WHERE name='IX_Orders_Customer_Date'",
    "CREATE INDEX IX_Orders_Customer_Date ON sales.Orders (CustomerId, OrderDate)",
    "IX_Orders_Customer_Date")
exec_if_missing(
    "SELECT 1 FROM sys.indexes WHERE name='IX_OrderItems_Order'",
    "CREATE INDEX IX_OrderItems_Order ON sales.OrderItems (OrderId)",
    "IX_OrderItems_Order")

# 3) 데이터 (이미 있으면 건너뜀)
if cur.execute("SELECT COUNT(*) FROM sales.Orders").fetchone()[0] == 0:
    cur.execute("INSERT INTO common.OrderStatus VALUES (1,N'접수'),(2,N'배송중'),(3,N'완료'),(4,N'취소')")
    cur.execute("""
        ;WITH n AS (
          SELECT TOP (40000) ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) AS i
          FROM sys.all_objects a CROSS JOIN sys.all_objects b)
        INSERT INTO sales.Orders (CustomerId, OrderDate, StatusId)
        SELECT (i % 200) + 1,
               DATEADD(MINUTE, -(ABS(CHECKSUM(NEWID())) % (180*24*60)), SYSDATETIME()),
               (i % 4) + 1
        FROM n""")
    cur.execute("""
        INSERT INTO sales.OrderItems (OrderId, Quantity, UnitPrice)
        SELECT o.OrderId, (ABS(CHECKSUM(NEWID())) % 5) + 1,
               ((ABS(CHECKSUM(NEWID())) % 90000) + 1000) / 100.0
        FROM sales.Orders o
        CROSS JOIN (VALUES (1),(2)) v(k)""")
    print("데이터: Orders 40,000 · OrderItems 80,000")

# 4) 프로시저 (계획서 시나리오 — 17행 CONVERT 안티패턴 포함)
cur.execute("IF OBJECT_ID('sales.usp_GetOrderSummary') IS NOT NULL DROP PROCEDURE sales.usp_GetOrderSummary")
cur.execute("""
CREATE PROCEDURE sales.usp_GetOrderSummary
    @CustomerId INT,
    @StartDate  DATETIME2,
    @EndDate    DATETIME2
AS
BEGIN
    SET NOCOUNT ON;
    SELECT  o.OrderId, o.OrderDate,
            SUM(oi.Quantity * oi.UnitPrice) AS TotalAmount,
            s.StatusName
    FROM sales.Orders o
    INNER JOIN sales.OrderItems oi ON oi.OrderId = o.OrderId
    LEFT JOIN common.OrderStatus s ON s.StatusId = o.StatusId
    WHERE o.CustomerId = @CustomerId
      AND CONVERT(VARCHAR(10), o.OrderDate, 120) >= CONVERT(VARCHAR(10), @StartDate, 120)
      AND o.OrderDate < @EndDate
    GROUP BY o.OrderId, o.OrderDate, s.StatusName
    ORDER BY o.OrderDate DESC;
END""")
print("프로시저: sales.usp_GetOrderSummary (CONVERT 안티패턴)")

# 5) 읽기 전용 계정 (SR-5) — 비밀번호는 config.json에만 기록, 출력하지 않음
# 원칙: 기존 로그인의 비밀번호는 변경하지 않는다. EXECUTE는 부여하지 않는다
# (워크로드는 아래 6)에서 관리자 연결로 실행 — 계정 분리).
pw = None
cur.execute("USE master")
if not cur.execute("SELECT 1 FROM sys.server_principals WHERE name='dbaone_reader'").fetchone():
    pw = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(24)) + "!a1"
    cur.execute(f"CREATE LOGIN dbaone_reader WITH PASSWORD = '{pw}', CHECK_POLICY = ON")
    print("로그인 생성: dbaone_reader")
else:
    print("로그인 dbaone_reader 이미 존재 — 비밀번호를 변경하지 않습니다."
          " (config.json의 기존 연결이 유지됩니다. 재발급하려면 DROP LOGIN 후 재실행)")
cur.execute("GRANT VIEW SERVER STATE TO dbaone_reader")
cur.execute("USE DBAONE_TEST")
if not cur.execute("SELECT 1 FROM sys.database_principals WHERE name='dbaone_reader'").fetchone():
    cur.execute("CREATE USER dbaone_reader FOR LOGIN dbaone_reader")
cur.execute("ALTER ROLE db_datareader ADD MEMBER dbaone_reader")
cur.execute("GRANT VIEW DATABASE STATE TO dbaone_reader")
cur.execute("GRANT VIEW DEFINITION TO dbaone_reader")
# 과거 스크립트가 부여한 EXECUTE가 있으면 회수 (읽기 전용 계정에 EXECUTE는 부적합)
cur.execute("REVOKE EXECUTE ON SCHEMA::sales FROM dbaone_reader")
print("권한: db_datareader + VIEW SERVER/DATABASE STATE + VIEW DEFINITION (EXECUTE 없음)")

# 6) 워크로드 — Query Store에 실행 이력 생성 (관리자 연결로 실행: 읽기 계정과 분리)
random.seed(7)
work = pyodbc.connect(ADMIN.replace("DATABASE=master", "DATABASE=DBAONE_TEST"), timeout=10, autocommit=True)
wcur = work.cursor()
for i in range(80):
    cid = random.randint(1, 200)
    wcur.execute("EXEC sales.usp_GetOrderSummary @CustomerId=?, @StartDate=?, @EndDate=?",
                 (cid, "2026-05-01", "2026-07-21"))
    wcur.fetchall()
# 비교용 정상 쿼리도 몇 번 실행
for i in range(30):
    wcur.execute("SELECT COUNT(*) FROM sales.Orders WHERE CustomerId = ?", (random.randint(1, 200),))
    wcur.fetchall()
work.close()
print("워크로드: usp_GetOrderSummary 80회 + 조회 30회 실행")

# 7) config.json 갱신 — 새 비밀번호가 발급된 경우에만 (키 등 기존 값 보존, 미출력)
if pw:
    cfg_path = BASE / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
    cfg["mssql_conn"] = ("DRIVER={ODBC Driver 17 for SQL Server};SERVER=localhost;DATABASE=DBAONE_TEST;"
                         f"UID=dbaone_reader;PWD={pw}")
    cfg.setdefault("env_label", "개발")
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print("config.json 갱신: mssql_conn → dbaone_reader@DBAONE_TEST (비밀번호는 파일에만 저장)")

conn.close()
print("\n완료 — 서버를 재시작하면 실연결 모드로 동작합니다.")
