/*
계정별원장 메일 — 지사 담당자 명단 · 발송 로그 (2026-08-24 사용자 요청).

왜 필요한가
  지금은 원장을 보낼 주소를 화면에서 **한 번에 하나** 손으로 적는다. 계정이 20개니
  누가 어느 지사 담당인지는 아무 데도 없고, 보냈는지 여부도 남지 않는다. 지사가
  "못 받았다"고 하면 확인할 방법이 없다.

두 표가 하는 일
  a10_ledger_recipient   지사 계정 → 담당자(받는사람 TO · 참조 CC). 사람이 바뀌면
                         이 표만 고친다 — 배포가 필요 없다.
  a10_ledger_mail_log    한 통이 한 행. 성공·실패를 **모두** 남긴다. 실패만 조용히
                         사라지면 안 보낸 지사를 보낸 줄 안다.

담당자가 없는 계정은 안 나간다(fail-closed). 서버에 LEDGER_MAIL_TEST_TO 가 있으면
누구에게 보내든 그 주소로만 가고, 로그에 test_mode='Y' 로 남는다 — 지사는 못 받은
것이므로 로그에서 구분돼야 한다.

운영 반영 전에 백업·검토 후 DBA가 실행한다.
*/
SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

IF OBJECT_ID(N'dbo.a10_ledger_recipient', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.a10_ledger_recipient (
        recipient_id INT IDENTITY(1, 1) NOT NULL,
        -- 지사 계정 코드(1410002~1410022). a10_voucher_cache.account_code 와 같은 값.
        account_code VARCHAR(20) NOT NULL,
        -- a10_office_map.office_id. 계정만으로 충분하지만 지사 화면과 이어 붙일 때 쓴다.
        office_id VARCHAR(10) NULL,
        name NVARCHAR(60) NULL,
        email NVARCHAR(200) NOT NULL,
        -- 'TO' 받는사람 · 'CC' 참조
        kind VARCHAR(2) NOT NULL
            CONSTRAINT DF_a10_ledger_recipient_kind DEFAULT ('TO'),
        active CHAR(1) NOT NULL
            CONSTRAINT DF_a10_ledger_recipient_active DEFAULT ('Y'),
        memo NVARCHAR(200) NULL,
        updated_by_usr_seq BIGINT NULL,
        created_at DATETIME2 NOT NULL
            CONSTRAINT DF_a10_ledger_recipient_created_at DEFAULT (SYSDATETIME()),
        updated_at DATETIME2 NOT NULL
            CONSTRAINT DF_a10_ledger_recipient_updated_at DEFAULT (SYSDATETIME()),
        CONSTRAINT PK_a10_ledger_recipient PRIMARY KEY CLUSTERED (recipient_id),
        CONSTRAINT CK_a10_ledger_recipient_kind CHECK (kind IN ('TO', 'CC'))
    );
END

IF OBJECT_ID(N'dbo.a10_ledger_mail_log', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.a10_ledger_mail_log (
        log_id BIGINT IDENTITY(1, 1) NOT NULL,
        sent_at DATETIME2 NOT NULL
            CONSTRAINT DF_a10_ledger_mail_log_sent_at DEFAULT (SYSDATETIME()),
        account_code VARCHAR(20) NOT NULL,
        account_name NVARCHAR(60) NULL,
        -- 보낸 원장의 기간. 어느 날짜 원장이었는지가 문의의 핵심이다.
        date_from DATE NOT NULL,
        date_to DATE NOT NULL,
        -- 실제로 메일 헤더에 넣은 주소를 그대로 남긴다(여럿이면 쉼표).
        to_email NVARCHAR(400) NULL,
        cc_email NVARCHAR(400) NULL,
        subject NVARCHAR(300) NULL,
        -- 'SENT' 보냄 · 'FAILED' 실패
        status VARCHAR(10) NOT NULL,
        fail_reason NVARCHAR(400) NULL,
        -- 테스트 수신자로 돌려보낸 건 — 지사는 못 받은 것이다.
        test_mode CHAR(1) NOT NULL
            CONSTRAINT DF_a10_ledger_mail_log_test_mode DEFAULT ('N'),
        -- 본문은 안 남긴다(용량). 나중에 대조할 요약만 남긴다.
        item_count INT NOT NULL
            CONSTRAINT DF_a10_ledger_mail_log_item_count DEFAULT (0),
        closing_balance DECIMAL(19, 4) NULL,
        requested_by_usr_seq BIGINT NULL,
        CONSTRAINT PK_a10_ledger_mail_log PRIMARY KEY CLUSTERED (log_id),
        CONSTRAINT CK_a10_ledger_mail_log_status CHECK (status IN ('SENT', 'FAILED'))
    );
END

/* ── 뒤늦게 붙이는 것들 ───────────────────────────────────────────────
   배포 스크립트(server_redeploy.ps1 → scripts/create_tables.py →
   Base.metadata.create_all)가 **먼저 돌아 표를 만들어 놓았을 수 있다**. 그러면 위
   블록은 통째로 건너뛰어 인덱스·제약이 빠진 표가 남는다. 그래서 표가 이미 있어도
   빠진 것을 여기서 채운다 (20260813_create_access_role.sql 과 같은 이유). */
IF OBJECT_ID(N'dbo.a10_ledger_recipient', N'U') IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM sys.indexes
                   WHERE name = N'UX_a10_ledger_recipient_account_email'
                     AND object_id = OBJECT_ID(N'dbo.a10_ledger_recipient'))
BEGIN
    -- 같은 계정에 같은 주소가 살아 있으면 메일이 두 통 간다. 뺀 사람(active='N')은
    -- 같은 주소로 다시 넣을 수 있어야 하므로 조건부 유니크다.
    IF EXISTS (SELECT account_code, email FROM dbo.a10_ledger_recipient
               WHERE active = 'Y' GROUP BY account_code, email HAVING COUNT(*) > 1)
        THROW 50011, N'같은 계정에 같은 주소가 둘 이상입니다. 먼저 정리하세요.', 1;
    CREATE UNIQUE INDEX UX_a10_ledger_recipient_account_email
        ON dbo.a10_ledger_recipient (account_code, email) WHERE active = 'Y';
    PRINT N'  + UX_a10_ledger_recipient_account_email';
END

IF OBJECT_ID(N'dbo.a10_ledger_mail_log', N'U') IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM sys.indexes
                   WHERE name = N'IX_a10_ledger_mail_log_account'
                     AND object_id = OBJECT_ID(N'dbo.a10_ledger_mail_log'))
BEGIN
    CREATE INDEX IX_a10_ledger_mail_log_account
        ON dbo.a10_ledger_mail_log (account_code, sent_at);
    PRINT N'  + IX_a10_ledger_mail_log_account';
END

IF OBJECT_ID(N'dbo.a10_ledger_mail_log', N'U') IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM sys.indexes
                   WHERE name = N'IX_a10_ledger_mail_log_sent_at'
                     AND object_id = OBJECT_ID(N'dbo.a10_ledger_mail_log'))
BEGIN
    CREATE INDEX IX_a10_ledger_mail_log_sent_at
        ON dbo.a10_ledger_mail_log (sent_at);
    PRINT N'  + IX_a10_ledger_mail_log_sent_at';
END

/* ── 만들어졌는지 확인하고 나서 완료라고 말한다 ───────────────────────── */
DECLARE @missing NVARCHAR(200) = N'';
IF OBJECT_ID(N'dbo.a10_ledger_recipient', N'U') IS NULL
    SET @missing = @missing + N'a10_ledger_recipient ';
IF OBJECT_ID(N'dbo.a10_ledger_mail_log', N'U') IS NULL
    SET @missing = @missing + N'a10_ledger_mail_log ';
IF @missing <> N''
    THROW 50012, N'표가 만들어지지 않았습니다. 위 오류를 확인하세요.', 1;

    COMMIT TRANSACTION;
    PRINT N'완료: a10_ledger_recipient · a10_ledger_mail_log (2개 확인됨)';
    PRINT N'다음: 계정별원장 화면 > 담당자 에서 지사별 주소를 채운다.';
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH
