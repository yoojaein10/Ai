/*
업무실적 기반 보수검토 스냅숏.

- 원본 조회 결과는 gzip JSON(VARBINARY(MAX))으로 한 번 고정한다.
- 의견/제외/채택 상태는 JSON으로 전체 교체 저장한다.
- 사용자·지사·기간 범위가 일치하는 실행만 애플리케이션에서 복원한다.

운영 반영 전에 반드시 백업·검토 후 DBA가 실행한다.
*/
SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

IF OBJECT_ID(N'dbo.a10_fee_review_run', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.a10_fee_review_run (
        run_id VARCHAR(40) NOT NULL,
        owner_usr_seq BIGINT NOT NULL,
        office_code VARCHAR(10) NOT NULL,
        period_year INT NOT NULL,
        period_month INT NOT NULL,
        half NVARCHAR(10) NOT NULL,
        basis NVARCHAR(10) NOT NULL,
        profile VARCHAR(40) NOT NULL,
        snapshot_schema_version INT NOT NULL
            CONSTRAINT DF_a10_fee_review_run_schema DEFAULT (1),
        source_sha256 VARCHAR(64) NOT NULL,
        snapshot_blob VARBINARY(MAX) NOT NULL,
        decisions_json NVARCHAR(MAX) NOT NULL
            CONSTRAINT DF_a10_fee_review_run_decisions DEFAULT (N'{}'),
        status VARCHAR(16) NOT NULL
            CONSTRAINT DF_a10_fee_review_run_status DEFAULT ('ACTIVE'),
        expires_at DATETIME2 NOT NULL,
        created_at DATETIME2 NOT NULL
            CONSTRAINT DF_a10_fee_review_run_created DEFAULT (SYSUTCDATETIME()),
        updated_at DATETIME2 NOT NULL
            CONSTRAINT DF_a10_fee_review_run_updated DEFAULT (SYSUTCDATETIME()),
        CONSTRAINT PK_a10_fee_review_run PRIMARY KEY (run_id),
        CONSTRAINT CK_a10_fee_review_run_year CHECK (period_year BETWEEN 2020 AND 2100),
        CONSTRAINT CK_a10_fee_review_run_month CHECK (period_month BETWEEN 1 AND 12),
        CONSTRAINT CK_a10_fee_review_run_json CHECK (ISJSON(decisions_json) = 1),
        CONSTRAINT CK_a10_fee_review_run_status
            CHECK (status IN ('ACTIVE', 'FINALIZED', 'EXPIRED'))
    );

    CREATE INDEX IX_a10_fee_review_run_owner
        ON dbo.a10_fee_review_run (owner_usr_seq);
    CREATE INDEX IX_a10_fee_review_run_office
        ON dbo.a10_fee_review_run (office_code);
    CREATE INDEX IX_a10_fee_review_run_expires
        ON dbo.a10_fee_review_run (expires_at);
    CREATE INDEX IX_a10_fee_review_run_latest
        ON dbo.a10_fee_review_run (
            owner_usr_seq, office_code, period_year, period_month,
            half, basis, created_at DESC
        );
END;

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0
        ROLLBACK TRANSACTION;
    THROW;
END CATCH;
