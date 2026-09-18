/*
MOA 사용자별 권한 예외 테이블.

- 한 사람(USR_SEQ)당 한 행
- 조직/직군 기본값은 애플리케이션에서 계산
- 아래에는 기본값과 다른 예외만 저장
- 메뉴 추가 시 menu_overrides_json에 키만 추가하므로 컬럼 변경 불필요

운영 반영 전에 반드시 백업·검토 후 DBA가 실행한다.
*/
SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

IF OBJECT_ID(N'dbo.a10_access_policy', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.a10_access_policy (
        usr_seq BIGINT NOT NULL,
        usr_id VARCHAR(50) NOT NULL,
        view_all_offices_override CHAR(1) NULL,
        view_other_users_override CHAR(1) NULL,
        menu_overrides_json NVARCHAR(MAX) NULL,
        active CHAR(1) NOT NULL
            CONSTRAINT DF_a10_access_policy_active DEFAULT ('Y'),
        updated_by_usr_seq BIGINT NULL,
        memo VARCHAR(200) NULL,
        created_at DATETIME2 NOT NULL
            CONSTRAINT DF_a10_access_policy_created_at DEFAULT (SYSDATETIME()),
        updated_at DATETIME2 NOT NULL
            CONSTRAINT DF_a10_access_policy_updated_at DEFAULT (SYSDATETIME()),
        CONSTRAINT PK_a10_access_policy PRIMARY KEY (usr_seq),
        CONSTRAINT CK_a10_access_policy_view_all
            CHECK (view_all_offices_override IS NULL OR view_all_offices_override IN ('Y', 'N')),
        CONSTRAINT CK_a10_access_policy_view_others
            CHECK (view_other_users_override IS NULL OR view_other_users_override IN ('Y', 'N')),
        CONSTRAINT CK_a10_access_policy_active
            CHECK (active IN ('Y', 'N')),
        CONSTRAINT CK_a10_access_policy_menu_json
            CHECK (menu_overrides_json IS NULL OR ISJSON(menu_overrides_json) = 1)
    );

    CREATE INDEX IX_a10_access_policy_usr_id
        ON dbo.a10_access_policy (usr_id);
END;

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0
        ROLLBACK TRANSACTION;
    THROW;
END CATCH;
