/*
MOA 권한 묶음(역할) · 부서 적용 · 개인 적용 테이블.

왜 필요한가
  지금은 부서·직군 기본값이 **코드에 박혀** 있어(app/services/access_policy.py 의
  HEAD_OFFICE_FULL_ACCESS_DEPARTMENTS·OPERATIONS_DEPARTMENTS 등) 권한을 바꾸려면
  배포를 해야 한다. 그리고 화면에서는 사람을 하나씩만 고칠 수 있어, 부서 하나를
  통째로 바꾸려면 사람 수만큼 반복해야 한다.

이 세 표가 하는 일
  a10_access_role        '집행부'·'일반' 처럼 이름을 붙인 권한 묶음(메뉴 체크 + 두 플래그)
  a10_access_dept_role   부서 → 묶음
  a10_access_user_role   개인 → 묶음

해석 순서 (2026-08-13 사용자 확정)
  ① 코드 기본값(과도기 동안만 남는다. 표가 채워지면 걷어낸다)
  ② 부서 묶음      — 있으면 ①을 **대체**한다
  ③ 개인 묶음      — 있으면 ②를 **대체**한다
  ④ 개인 예외      — a10_access_policy 의 menu_overrides_json 이 그 위에 얹힌다
  즉 **개인이 부서를 이긴다.**

묶음은 **참조**다 — 묶음을 고치면 그걸 쓰는 부서·사람이 즉시 따라간다(복사 아님).
그래서 묶음 하나를 잘못 고치면 여러 사람이 한꺼번에 바뀐다. 화면에서 '이 묶음을
쓰는 곳 N군데' 를 먼저 보여 준다.

운영 반영 전에 반드시 백업·검토 후 DBA가 실행한다.
이 파일은 표만 만든다. 현행 코드 기본값을 묶음으로 옮기는 시드는
20260813_seed_access_role.sql 이 한다 — **둘 다 실행해야** 권한이 지금과 같아진다.
*/
SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

IF OBJECT_ID(N'dbo.a10_access_role', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.a10_access_role (
        role_id INT IDENTITY(1, 1) NOT NULL,
        name NVARCHAR(60) NOT NULL,
        -- 켜진 메뉴 키 배열. 예: ["appraisals","payments","receivables","mySales"]
        -- 배열로 두는 이유는 a10_access_policy 와 같다 — 메뉴가 늘어도 컬럼을 안 바꾼다.
        menu_keys_json NVARCHAR(MAX) NULL,
        -- 'Y'/'N'/NULL. NULL 은 '이 묶음은 이 플래그를 정하지 않는다'는 뜻이라
        -- 아래 층(코드 기본값)이 그대로 산다.
        view_all_offices CHAR(1) NULL,
        view_other_users CHAR(1) NULL,
        active CHAR(1) NOT NULL
            CONSTRAINT DF_a10_access_role_active DEFAULT ('Y'),
        memo NVARCHAR(200) NULL,
        updated_by_usr_seq BIGINT NULL,
        created_at DATETIME2 NOT NULL
            CONSTRAINT DF_a10_access_role_created_at DEFAULT (SYSDATETIME()),
        updated_at DATETIME2 NOT NULL
            CONSTRAINT DF_a10_access_role_updated_at DEFAULT (SYSDATETIME()),
        CONSTRAINT PK_a10_access_role PRIMARY KEY CLUSTERED (role_id)
    );
    -- 살아 있는 묶음끼리만 이름이 겹치지 않게. 지운(active='N') 이름은 재사용 가능.
    CREATE UNIQUE INDEX UX_a10_access_role_name
        ON dbo.a10_access_role (name) WHERE active = 'Y';
END

IF OBJECT_ID(N'dbo.a10_access_dept_role', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.a10_access_dept_role (
        -- 본사는 office_id='10' + 부서명(집행부·재무팀…), 지사는 지사코드 + 부서명.
        -- 부서명은 app/services/access_policy.py 의 identity_from_row 가 만드는 값과
        -- 같은 문자열이어야 한다(본사는 좌석 코드→이름 변환, 지사는 chrg_biz).
        office_id VARCHAR(10) NOT NULL,
        department_name NVARCHAR(60) NOT NULL,
        role_id INT NOT NULL,
        active CHAR(1) NOT NULL
            CONSTRAINT DF_a10_access_dept_role_active DEFAULT ('Y'),
        updated_by_usr_seq BIGINT NULL,
        created_at DATETIME2 NOT NULL
            CONSTRAINT DF_a10_access_dept_role_created_at DEFAULT (SYSDATETIME()),
        updated_at DATETIME2 NOT NULL
            CONSTRAINT DF_a10_access_dept_role_updated_at DEFAULT (SYSDATETIME()),
        CONSTRAINT PK_a10_access_dept_role PRIMARY KEY CLUSTERED (office_id, department_name),
        CONSTRAINT FK_a10_access_dept_role_role FOREIGN KEY (role_id)
            REFERENCES dbo.a10_access_role (role_id)
    );
END

IF OBJECT_ID(N'dbo.a10_access_user_role', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.a10_access_user_role (
        -- APWorks TMWCMN_USR_BAC_INFO.USR_SEQ 와 1:1
        usr_seq BIGINT NOT NULL,
        role_id INT NOT NULL,
        active CHAR(1) NOT NULL
            CONSTRAINT DF_a10_access_user_role_active DEFAULT ('Y'),
        updated_by_usr_seq BIGINT NULL,
        created_at DATETIME2 NOT NULL
            CONSTRAINT DF_a10_access_user_role_created_at DEFAULT (SYSDATETIME()),
        updated_at DATETIME2 NOT NULL
            CONSTRAINT DF_a10_access_user_role_updated_at DEFAULT (SYSDATETIME()),
        CONSTRAINT PK_a10_access_user_role PRIMARY KEY CLUSTERED (usr_seq),
        CONSTRAINT FK_a10_access_user_role_role FOREIGN KEY (role_id)
            REFERENCES dbo.a10_access_role (role_id)
    );
    CREATE INDEX IX_a10_access_user_role_role ON dbo.a10_access_user_role (role_id);
END

/* ── 뒤늦게 붙이는 것들 ───────────────────────────────────────────────
   위의 CREATE TABLE 은 표가 없을 때만 돈다. 그런데 배포 스크립트
   (server_redeploy.ps1 → scripts/create_tables.py → Base.metadata.create_all)
   가 **먼저 돌아 표를 이미 만들어 놓았을 수 있다**. 그 경우 위 블록은 통째로
   건너뛰므로, 인덱스와 외래키가 빠진 표가 남는다 — 그런데도 아래에서 '완료'만
   찍히면 다 된 줄 알게 된다(2026-08-13 검수). 그래서 표가 이미 있어도
   빠진 것을 여기서 채운다. */
IF OBJECT_ID(N'dbo.a10_access_role', N'U') IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM sys.indexes
                   WHERE name = N'UX_a10_access_role_name'
                     AND object_id = OBJECT_ID(N'dbo.a10_access_role'))
BEGIN
    -- 같은 이름 묶음이 이미 둘 이상이면 인덱스가 안 걸린다. 그때는 이름을 먼저
    -- 정리해야 하므로, 조용히 넘어가지 말고 분명히 세운다.
    IF EXISTS (SELECT name FROM dbo.a10_access_role WHERE active = 'Y'
               GROUP BY name HAVING COUNT(*) > 1)
        THROW 50001, N'같은 이름의 살아 있는 묶음이 둘 이상입니다. 이름을 먼저 정리하세요.', 1;
    CREATE UNIQUE INDEX UX_a10_access_role_name
        ON dbo.a10_access_role (name) WHERE active = 'Y';
    PRINT N'  + UX_a10_access_role_name (기존 표에 추가)';
END

IF OBJECT_ID(N'dbo.a10_access_user_role', N'U') IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM sys.indexes
                   WHERE name = N'IX_a10_access_user_role_role'
                     AND object_id = OBJECT_ID(N'dbo.a10_access_user_role'))
BEGIN
    CREATE INDEX IX_a10_access_user_role_role ON dbo.a10_access_user_role (role_id);
    PRINT N'  + IX_a10_access_user_role_role (기존 표에 추가)';
END

/* ── 실제로 만들어졌는지 확인하고 나서 완료라고 말한다 ─────────────────── */
DECLARE @missing NVARCHAR(400) = N'';
IF OBJECT_ID(N'dbo.a10_access_role', N'U') IS NULL
    SET @missing = @missing + N'a10_access_role ';
IF OBJECT_ID(N'dbo.a10_access_dept_role', N'U') IS NULL
    SET @missing = @missing + N'a10_access_dept_role ';
IF OBJECT_ID(N'dbo.a10_access_user_role', N'U') IS NULL
    SET @missing = @missing + N'a10_access_user_role ';
IF @missing <> N''
    THROW 50002, N'표가 만들어지지 않았습니다. 위 오류를 확인하세요.', 1;

    COMMIT TRANSACTION;
    PRINT N'완료: a10_access_role · a10_access_dept_role · a10_access_user_role (3개 확인됨)';
    PRINT N'다음: 20260813_seed_access_role.sql 을 실행해야 권한이 지금과 같아진다.';
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH
