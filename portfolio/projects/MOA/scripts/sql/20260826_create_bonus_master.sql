/*
성과상여 마스터 — 사람 파라미터 · 요율 스케줄 · 감정서 지분 (2026-08-25 상여 재작성 1단계).

왜 필요한가
  재무팀 성과상여 엑셀에서 "규칙"은 수식이 아니라 사람 손에 있었다: 상여율 40/45/35/30 은
  사람별 접수기간 라벨로, 공동 건 지분은 거래처명 괄호 '(김5 강2.5 조2.5)' 로,
  소속평가사 지급률 70%·소득세율 15% 는 합계행 수식 안에. 이걸 표로 꺼내야
  화면이 스스로 계산하고 재무팀은 예외만 고친다.

세 표가 하는 일
  a10_bonus_person  사람 → 주주/소속, 지급률, 소득세율
  a10_bonus_rate    사람 → 감정서 접수일 구간 → 요율 (from NULL=처음부터, to NULL=계속)
  a10_bonus_share   감정서 × 사람 → 지분 % (독립 백분율 — 합이 100 이 아닐 수 있다),
                    법인카드 몫(bc_pct)이 다르면 따로

빼는 대신 active='N' (누가 언제 뺐는지 남는다). 초기값은 scripts/seed_bonus_master.py 가
엑셀에서 읽어 넣는다(--dry-run 으로 먼저 본다).

운영 반영 전에 백업·검토 후 DBA가 실행한다.
*/
SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

IF OBJECT_ID(N'dbo.a10_bonus_person', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.a10_bonus_person (
        -- 엑셀·APWorks(apw_masterex.Manager)와 같은 표기의 이름
        person NVARCHAR(30) NOT NULL,
        -- 'SHAREHOLDER' 주주 · 'ASSOCIATE' 소속평가사(평·동)
        kind VARCHAR(12) NOT NULL,
        -- 소속 합계에 곱하는 지급률 (기본 전액)
        pay_ratio DECIMAL(5, 4) NOT NULL
            CONSTRAINT DF_a10_bonus_person_pay_ratio DEFAULT (1),
        -- 소득세율 — 주주 0.30, 소속 대부분 0.15
        tax_rate DECIMAL(5, 4) NOT NULL
            CONSTRAINT DF_a10_bonus_person_tax_rate DEFAULT (0.30),
        active CHAR(1) NOT NULL
            CONSTRAINT DF_a10_bonus_person_active DEFAULT ('Y'),
        memo NVARCHAR(200) NULL,
        updated_by_usr_seq BIGINT NULL,
        created_at DATETIME2 NOT NULL
            CONSTRAINT DF_a10_bonus_person_created_at DEFAULT (SYSDATETIME()),
        updated_at DATETIME2 NOT NULL
            CONSTRAINT DF_a10_bonus_person_updated_at DEFAULT (SYSDATETIME()),
        CONSTRAINT PK_a10_bonus_person PRIMARY KEY CLUSTERED (person),
        CONSTRAINT CK_a10_bonus_person_kind CHECK (kind IN ('SHAREHOLDER', 'ASSOCIATE')),
        CONSTRAINT CK_a10_bonus_person_pay_ratio CHECK (pay_ratio > 0 AND pay_ratio <= 1),
        CONSTRAINT CK_a10_bonus_person_tax_rate CHECK (tax_rate >= 0 AND tax_rate < 1)
    );
END

IF OBJECT_ID(N'dbo.a10_bonus_rate', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.a10_bonus_rate (
        rate_id INT IDENTITY(1, 1) NOT NULL,
        person NVARCHAR(30) NOT NULL,
        -- 감정서 접수일 구간. NULL 은 처음부터 / 계속.
        from_date DATE NULL,
        to_date DATE NULL,
        -- 40 / 45 / 35 / 30 (퍼센트)
        rate DECIMAL(5, 2) NOT NULL,
        -- 엑셀 합계행 라벨 원문 (시드 근거)
        label NVARCHAR(100) NULL,
        -- 'SEED' 엑셀 시드 · 'MANUAL' 화면 입력
        source VARCHAR(8) NOT NULL
            CONSTRAINT DF_a10_bonus_rate_source DEFAULT ('SEED'),
        active CHAR(1) NOT NULL
            CONSTRAINT DF_a10_bonus_rate_active DEFAULT ('Y'),
        updated_by_usr_seq BIGINT NULL,
        created_at DATETIME2 NOT NULL
            CONSTRAINT DF_a10_bonus_rate_created_at DEFAULT (SYSDATETIME()),
        updated_at DATETIME2 NOT NULL
            CONSTRAINT DF_a10_bonus_rate_updated_at DEFAULT (SYSDATETIME()),
        CONSTRAINT PK_a10_bonus_rate PRIMARY KEY CLUSTERED (rate_id),
        CONSTRAINT CK_a10_bonus_rate_rate CHECK (rate > 0 AND rate <= 100)
    );
END

IF OBJECT_ID(N'dbo.a10_bonus_share', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.a10_bonus_share (
        share_id INT IDENTITY(1, 1) NOT NULL,
        -- a10_voucher_cache.management_no 와 같은 값 (RTRIM 된 감정서번호)
        doc_id VARCHAR(50) NOT NULL,
        person NVARCHAR(30) NOT NULL,
        share_pct DECIMAL(6, 3) NOT NULL,
        -- 법인카드 몫이 지분과 다를 때만 ('안6:황4/법카 안100')
        bc_pct DECIMAL(6, 3) NULL,
        -- 'SEED' 엑셀 시드 · 'MANUAL' 화면 입력 · 'PARSED' 괄호 파서 제안
        source VARCHAR(8) NOT NULL
            CONSTRAINT DF_a10_bonus_share_source DEFAULT ('SEED'),
        note NVARCHAR(200) NULL,
        active CHAR(1) NOT NULL
            CONSTRAINT DF_a10_bonus_share_active DEFAULT ('Y'),
        updated_by_usr_seq BIGINT NULL,
        created_at DATETIME2 NOT NULL
            CONSTRAINT DF_a10_bonus_share_created_at DEFAULT (SYSDATETIME()),
        updated_at DATETIME2 NOT NULL
            CONSTRAINT DF_a10_bonus_share_updated_at DEFAULT (SYSDATETIME()),
        CONSTRAINT PK_a10_bonus_share PRIMARY KEY CLUSTERED (share_id),
        CONSTRAINT CK_a10_bonus_share_pct CHECK (share_pct > 0 AND share_pct <= 100)
    );
END

/* ── 뒤늦게 붙이는 것들 ───────────────────────────────────────────────
   배포 스크립트(server_redeploy.ps1 → scripts/create_tables.py → create_all)가 먼저
   돌아 표를 만들어 놓았을 수 있다. 그러면 위 블록은 건너뛰어 인덱스가 빠진 표가
   남으므로, 표가 이미 있어도 빠진 것을 여기서 채운다. */
IF OBJECT_ID(N'dbo.a10_bonus_share', N'U') IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM sys.indexes
                   WHERE name = N'UX_a10_bonus_share_doc_person'
                     AND object_id = OBJECT_ID(N'dbo.a10_bonus_share'))
BEGIN
    -- 같은 감정서에 같은 사람의 살아 있는 지분이 둘이면 두 번 곱한다. 뺀 행(active='N')은
    -- 같은 사람으로 다시 넣을 수 있어야 하므로 조건부 유니크다.
    IF EXISTS (SELECT doc_id, person FROM dbo.a10_bonus_share
               WHERE active = 'Y' GROUP BY doc_id, person HAVING COUNT(*) > 1)
        THROW 50011, N'같은 감정서에 같은 사람의 지분이 둘 이상입니다. 먼저 정리하세요.', 1;
    CREATE UNIQUE INDEX UX_a10_bonus_share_doc_person
        ON dbo.a10_bonus_share (doc_id, person) WHERE active = 'Y';
    PRINT N'  + UX_a10_bonus_share_doc_person';
END

IF OBJECT_ID(N'dbo.a10_bonus_rate', N'U') IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM sys.indexes
                   WHERE name = N'IX_a10_bonus_rate_person'
                     AND object_id = OBJECT_ID(N'dbo.a10_bonus_rate'))
BEGIN
    CREATE INDEX IX_a10_bonus_rate_person
        ON dbo.a10_bonus_rate (person, from_date) WHERE active = 'Y';
    PRINT N'  + IX_a10_bonus_rate_person';
END

IF OBJECT_ID(N'dbo.a10_bonus_share', N'U') IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM sys.indexes
                   WHERE name = N'IX_a10_bonus_share_doc'
                     AND object_id = OBJECT_ID(N'dbo.a10_bonus_share'))
BEGIN
    CREATE INDEX IX_a10_bonus_share_doc
        ON dbo.a10_bonus_share (doc_id) INCLUDE (person, share_pct, bc_pct, active);
    PRINT N'  + IX_a10_bonus_share_doc';
END

/* ── 만들어졌는지 확인하고 나서 완료라고 말한다 ───────────────────────── */
DECLARE @missing NVARCHAR(200) = N'';
IF OBJECT_ID(N'dbo.a10_bonus_person', N'U') IS NULL
    SET @missing = @missing + N'a10_bonus_person ';
IF OBJECT_ID(N'dbo.a10_bonus_rate', N'U') IS NULL
    SET @missing = @missing + N'a10_bonus_rate ';
IF OBJECT_ID(N'dbo.a10_bonus_share', N'U') IS NULL
    SET @missing = @missing + N'a10_bonus_share ';
IF @missing <> N''
    THROW 50012, N'표가 만들어지지 않았습니다. 위 오류를 확인하세요.', 1;

    COMMIT TRANSACTION;
    PRINT N'완료: a10_bonus_person · a10_bonus_rate · a10_bonus_share (3개 확인됨)';
    PRINT N'다음: python -m scripts.seed_bonus_master --xlsx <성과상여.xlsx> --dry-run 으로 초기값을 확인한다.';

-- 2026-08-27 공통건 요율 열 — 먼저 만든 표에 뒤늦게 붙인다 (비우면 규칙/기본 3%)
IF OBJECT_ID(N'dbo.a10_bonus_person', N'U') IS NOT NULL
   AND COL_LENGTH(N'dbo.a10_bonus_person', N'common_rate') IS NULL
BEGIN
    ALTER TABLE dbo.a10_bonus_person ADD common_rate DECIMAL(5, 2) NULL;
    PRINT N'  + a10_bonus_person.common_rate';
END

END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH
