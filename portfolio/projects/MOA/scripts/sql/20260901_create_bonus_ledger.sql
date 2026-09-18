/*
성과상여 원장 — 공제 · 오버라이드 · 마감 · 결과 스냅샷 (2026-08-25 상여 재작성 2단계).

왜 필요한가
  엑셀은 매달 새 시트에 계산을 다시 하고, 지난달 시트의 '미납비용' 칸을 이번 달 '미납비-이월'
  로 손으로 옮긴다. 같은 감정서가 두 달에 두 번 들어가는지도 사람이 기억으로 막는다.
  마감 스냅샷이 있어야 (1) 다음 달 이월이 자동이고 (2) 기지급 감정서를 차액만 주며
  (3) 마감 뒤에 전표 캐시가 바뀌어도 지급한 숫자가 흔들리지 않는다.

네 표가 하는 일
  a10_bonus_deduction  공제 대장 — 사람별 공제 항목(화환·패널티·보험료·기타공제·처리수당(+)·선지급·감정서경비 …)을
                       대기(PENDING)로 두었다가 지급월에 적용(APPLIED). 2026-08-27 재정의.
                       amount 는 항상 양수 — 부호는 kind 가 정한다.
  a10_bonus_override   월별 (감정서, 사람) 포함/제외·수수료·요율·지분 덮어쓰기.
  a10_bonus_close      지급월 마감 상태(OPEN/CLOSED). source='EXCEL' 은 도입 전 엑셀로 지급한 달의 이력.
  a10_bonus_result     마감 스냅샷 — 행(감정서×사람)과 사람 합계 행(doc_id NULL).

운영 반영 전에 백업·검토 후 DBA가 실행한다.
*/
SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

-- 2026-08-27 공제 대장으로 재정의. 옛 모양(period 열, 비어 있음)이면 지우고 다시 만든다.
IF OBJECT_ID(N'dbo.a10_bonus_deduction', N'U') IS NOT NULL
   AND COL_LENGTH(N'dbo.a10_bonus_deduction', N'applied_period') IS NULL
BEGIN
    IF EXISTS (SELECT 1 FROM dbo.a10_bonus_deduction)
        THROW 50013, N'a10_bonus_deduction 에 옛 모양(period)의 행이 있습니다. 공제 대장으로 옮긴 뒤 다시 실행하세요.', 1;
    DROP TABLE dbo.a10_bonus_deduction;
    PRINT N'  - a10_bonus_deduction (옛 모양, 0행) 삭제';
END

IF OBJECT_ID(N'dbo.a10_bonus_deduction', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.a10_bonus_deduction (
        deduction_id BIGINT IDENTITY(1, 1) NOT NULL,
        person NVARCHAR(30) NOT NULL,
        kind VARCHAR(16) NOT NULL,               -- WREATH|PENALTY|INSURANCE|OTHER_EXPENSE|OTHER_DEDUCT|HANDLING|ADVANCE_PAID|UNPAID_CARRY|VARIABLE_ADJ|VARIABLE_CREDIT|DOC_EXPENSE|MISC
        doc_id VARCHAR(50) NULL,                 -- 감정서 관련 공제만
        amount DECIMAL(19, 4) NOT NULL,          -- 항상 양수, 부호는 kind
        occurred_on DATE NULL,                   -- 발생일
        memo NVARCHAR(200) NULL,
        source VARCHAR(10) NOT NULL              -- MANUAL|EXCEL|VOUCHER
            CONSTRAINT DF_a10_bonus_deduction_source DEFAULT ('MANUAL'),
        source_key VARCHAR(80) NULL,             -- 엑셀 행·전표 키 (중복 방지)
        status VARCHAR(8) NOT NULL               -- PENDING|APPLIED|VOID
            CONSTRAINT DF_a10_bonus_deduction_status DEFAULT ('PENDING'),
        applied_period CHAR(6) NULL,             -- 적용 지급월 YYYYMM
        applied_by_usr_seq BIGINT NULL,
        applied_at DATETIME2 NULL,
        void_reason NVARCHAR(200) NULL,
        voided_at DATETIME2 NULL,
        created_by_usr_seq BIGINT NULL,
        created_at DATETIME2 NOT NULL
            CONSTRAINT DF_a10_bonus_deduction_created_at DEFAULT (SYSDATETIME()),
        updated_at DATETIME2 NULL,
        CONSTRAINT PK_a10_bonus_deduction PRIMARY KEY CLUSTERED (deduction_id),
        CONSTRAINT CK_a10_bonus_deduction_amount CHECK (amount >= 0),
        CONSTRAINT CK_a10_bonus_deduction_status CHECK (status IN ('PENDING', 'APPLIED', 'VOID')),
        CONSTRAINT CK_a10_bonus_deduction_source CHECK (source IN ('MANUAL', 'EXCEL', 'VOUCHER'))
    );
END

IF OBJECT_ID(N'dbo.a10_bonus_override', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.a10_bonus_override (
        override_id BIGINT IDENTITY(1, 1) NOT NULL,
        period CHAR(6) NOT NULL,
        doc_id VARCHAR(50) NOT NULL,
        person NVARCHAR(30) NOT NULL,
        action VARCHAR(8) NOT NULL,              -- INCLUDE|EXCLUDE|FEE|RATE|SHARE
        value DECIMAL(19, 4) NULL,               -- FEE 금액 / RATE % / SHARE %
        memo NVARCHAR(200) NULL,
        created_by_usr_seq BIGINT NULL,
        created_at DATETIME2 NOT NULL
            CONSTRAINT DF_a10_bonus_override_created_at DEFAULT (SYSDATETIME()),
        CONSTRAINT PK_a10_bonus_override PRIMARY KEY CLUSTERED (override_id),
        CONSTRAINT CK_a10_bonus_override_action CHECK (action IN ('INCLUDE', 'EXCLUDE', 'FEE', 'RATE', 'SHARE', 'WORK'))
    );
END

IF OBJECT_ID(N'dbo.a10_bonus_close', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.a10_bonus_close (
        period CHAR(6) NOT NULL,
        status VARCHAR(8) NOT NULL
            CONSTRAINT DF_a10_bonus_close_status DEFAULT ('OPEN'),
        source VARCHAR(8) NOT NULL
            CONSTRAINT DF_a10_bonus_close_source DEFAULT ('MOA'),
        closed_by_usr_seq BIGINT NULL,
        closed_at DATETIME2 NULL,
        reopened_by_usr_seq BIGINT NULL,
        reopened_at DATETIME2 NULL,
        memo NVARCHAR(200) NULL,
        CONSTRAINT PK_a10_bonus_close PRIMARY KEY CLUSTERED (period),
        CONSTRAINT CK_a10_bonus_close_status CHECK (status IN ('OPEN', 'CLOSED'))
    );
END

IF OBJECT_ID(N'dbo.a10_bonus_result', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.a10_bonus_result (
        result_id BIGINT IDENTITY(1, 1) NOT NULL,
        period CHAR(6) NOT NULL,
        person NVARCHAR(30) NOT NULL,
        kind VARCHAR(12) NOT NULL,               -- SHAREHOLDER|ASSOCIATE|COMMON
        doc_id VARCHAR(50) NULL,                 -- NULL = 사람 합계 행
        block_from DATE NULL,
        rate DECIMAL(5, 2) NULL,
        share_pct DECIMAL(6, 3) NULL,
        fee DECIMAL(19, 4) NOT NULL CONSTRAINT DF_a10_bonus_result_fee DEFAULT (0),
        assessed DECIMAL(19, 4) NOT NULL CONSTRAINT DF_a10_bonus_result_assessed DEFAULT (0),
        indemnity DECIMAL(19, 4) NOT NULL CONSTRAINT DF_a10_bonus_result_indemnity DEFAULT (0),
        association_fee DECIMAL(19, 4) NOT NULL CONSTRAINT DF_a10_bonus_result_association DEFAULT (0),
        payout_base DECIMAL(19, 4) NULL,
        bonus DECIMAL(19, 4) NULL,
        pretax DECIMAL(19, 4) NULL,
        income_tax DECIMAL(19, 4) NULL,
        resident_tax DECIMAL(19, 4) NULL,
        other_deduct DECIMAL(19, 4) NULL,
        payment DECIMAL(19, 4) NULL,
        unpaid_carry_out DECIMAL(19, 4) NULL,    -- 엑셀 AE → 다음 달 M
        card_limit DECIMAL(19, 4) NULL,
        retired CHAR(1) NOT NULL CONSTRAINT DF_a10_bonus_result_retired DEFAULT ('N'),
        source VARCHAR(8) NOT NULL CONSTRAINT DF_a10_bonus_result_source DEFAULT ('MOA'),
        detail_json NVARCHAR(MAX) NULL,
        CONSTRAINT PK_a10_bonus_result PRIMARY KEY CLUSTERED (result_id)
    );
END

/* ── 뒤늦게 붙이는 것들 (재배포 create_all 이 먼저 표를 만들어 놓았을 수 있다) ─────── */
-- 뒤늦게 붙은 WORK(수기 행 업무분류) — 먼저 만든 표의 CHECK 를 넓힌다.
IF EXISTS (SELECT 1 FROM sys.check_constraints
           WHERE name = N'CK_a10_bonus_override_action'
             AND parent_object_id = OBJECT_ID(N'dbo.a10_bonus_override')
             AND definition NOT LIKE N'%WORK%')
BEGIN
    ALTER TABLE dbo.a10_bonus_override DROP CONSTRAINT CK_a10_bonus_override_action;
    ALTER TABLE dbo.a10_bonus_override ADD CONSTRAINT CK_a10_bonus_override_action
        CHECK (action IN ('INCLUDE', 'EXCLUDE', 'FEE', 'RATE', 'SHARE', 'WORK'));
    PRINT N'  ~ CK_a10_bonus_override_action 에 WORK 추가';
END

IF OBJECT_ID(N'dbo.a10_bonus_override', N'U') IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM sys.indexes
                   WHERE name = N'UX_a10_bonus_override'
                     AND object_id = OBJECT_ID(N'dbo.a10_bonus_override'))
BEGIN
    IF EXISTS (SELECT period, doc_id, person, action FROM dbo.a10_bonus_override
               GROUP BY period, doc_id, person, action HAVING COUNT(*) > 1)
        THROW 50011, N'같은 달·감정서·사람에 같은 오버라이드가 둘 이상입니다. 먼저 정리하세요.', 1;
    CREATE UNIQUE INDEX UX_a10_bonus_override
        ON dbo.a10_bonus_override (period, doc_id, person, action);
    PRINT N'  + UX_a10_bonus_override';
END

IF OBJECT_ID(N'dbo.a10_bonus_deduction', N'U') IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM sys.indexes
                   WHERE name = N'IX_a10_bonus_deduction_applied'
                     AND object_id = OBJECT_ID(N'dbo.a10_bonus_deduction'))
BEGIN
    EXEC (N'CREATE INDEX IX_a10_bonus_deduction_applied ON dbo.a10_bonus_deduction (applied_period, person)');
    EXEC (N'CREATE INDEX IX_a10_bonus_deduction_status ON dbo.a10_bonus_deduction (status, person)');
    PRINT N'  + IX_a10_bonus_deduction_applied / _status';
END

IF OBJECT_ID(N'dbo.a10_bonus_deduction', N'U') IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM sys.indexes
                   WHERE name = N'UX_a10_bonus_deduction_source'
                     AND object_id = OBJECT_ID(N'dbo.a10_bonus_deduction'))
BEGIN
    -- 동적 SQL: 같은 배치 안에서 표를 다시 만들기 때문에 새 열 이름을 컴파일 시점에 못 본다
    DECLARE @dup INT;
    EXEC sp_executesql
        N'SELECT @n = COUNT(*) FROM (SELECT source, source_key FROM dbo.a10_bonus_deduction
                                     WHERE source_key IS NOT NULL GROUP BY source, source_key HAVING COUNT(*) > 1) d',
        N'@n INT OUTPUT', @n = @dup OUTPUT;
    IF @dup > 0
        THROW 50014, N'같은 출처 키의 공제 항목이 둘 이상입니다. 먼저 정리하세요.', 1;
    EXEC (N'CREATE UNIQUE INDEX UX_a10_bonus_deduction_source
            ON dbo.a10_bonus_deduction (source, source_key) WHERE source_key IS NOT NULL');
    PRINT N'  + UX_a10_bonus_deduction_source';
END

IF OBJECT_ID(N'dbo.a10_bonus_result', N'U') IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM sys.indexes
                   WHERE name = N'IX_a10_bonus_result_period'
                     AND object_id = OBJECT_ID(N'dbo.a10_bonus_result'))
BEGIN
    CREATE INDEX IX_a10_bonus_result_period ON dbo.a10_bonus_result (period, person);
    PRINT N'  + IX_a10_bonus_result_period';
END

IF OBJECT_ID(N'dbo.a10_bonus_result', N'U') IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM sys.indexes
                   WHERE name = N'IX_a10_bonus_result_doc'
                     AND object_id = OBJECT_ID(N'dbo.a10_bonus_result'))
BEGIN
    -- 기지급 차감: (감정서, 사람) 으로 마감 행을 찾는다
    CREATE INDEX IX_a10_bonus_result_doc ON dbo.a10_bonus_result (doc_id, person) INCLUDE (period, fee);
    PRINT N'  + IX_a10_bonus_result_doc';
END

/* ── 만들어졌는지 확인하고 나서 완료라고 말한다 ───────────────────────── */
DECLARE @missing NVARCHAR(200) = N'';
IF OBJECT_ID(N'dbo.a10_bonus_deduction', N'U') IS NULL SET @missing = @missing + N'a10_bonus_deduction ';
IF OBJECT_ID(N'dbo.a10_bonus_override', N'U') IS NULL SET @missing = @missing + N'a10_bonus_override ';
IF OBJECT_ID(N'dbo.a10_bonus_close', N'U') IS NULL SET @missing = @missing + N'a10_bonus_close ';
IF OBJECT_ID(N'dbo.a10_bonus_result', N'U') IS NULL SET @missing = @missing + N'a10_bonus_result ';
IF @missing <> N''
    THROW 50012, N'표가 만들어지지 않았습니다. 위 오류를 확인하세요.', 1;

    COMMIT TRANSACTION;
    PRINT N'완료: a10_bonus_deduction · a10_bonus_override · a10_bonus_close · a10_bonus_result (4개 확인됨)';
    PRINT N'다음: python -m scripts.seed_bonus_master --xlsx <성과상여.xlsx> --history 로 엑셀 지급 이력을 마감으로 넣는다.';
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH
