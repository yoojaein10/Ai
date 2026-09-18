/*
  권한 변경 이력 표 (2026-08-16)

  왜 필요한가
    권한 변경이 지금 **아무 흔적도 안 남는다.** a10_access_log 5,499행은 전부
    EXE_LAUNCH(로그인)이고 권한 변경은 한 줄도 없다. 남는 것은 현재 상태와
    updated_by_usr_seq 뿐이라 '누가 언제 무엇을 무엇으로 바꿨나'가 어디에도 없다.
    묶음은 참조라 하나를 고치면 지사 여러 곳이 동시에 바뀌는데, 잘못 건드려도
    원래 무엇이었는지 되돌릴 근거가 없다.

  왜 신청 표를 따로 안 만드는가
    이력과 신청은 컬럼이 대부분 겹친다(대상·행위자·요청자·사유·시각·before/after).
    따로 만들면 '왜 줬나'가 세 곳으로 흩어지고 이을 키가 없다. 한 표에 담고
    status 로 가른다 — applied(직접 변경) / pending(신청) / rejected(반려).
    신청 흐름을 붙이는 날 표를 새로 만들 필요 없이 pending 행을 쓰기 시작하면 된다.

  실행 순서
    1) 20260813_create_access_role.sql   ← 묶음 3표 (아직 실행 전이면 먼저)
    2) 20260813_seed_access_role.sql
    3) 이 파일
    모델은 app/models/access_change.py 다 — **둘이 같은 것을 만들어야 한다.**
    배포(server_redeploy.ps1 → scripts/create_tables.py)의 create_all 도 같은
    표를 만들므로, 어느 쪽이 먼저 돌아도 결과가 같아야 한다.

  이 표는 **쌓기만 한다(append-only).** 행을 고치면 이력이 아니다.
*/
SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

IF OBJECT_ID(N'dbo.a10_access_change', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.a10_access_change (
        change_id BIGINT IDENTITY(1, 1) NOT NULL,
        -- policy(개인 예외) | role(묶음 정의) | dept_role(부서 부여)
        -- | user_role(개인 부여) | grant(전체지사 조회)
        target_kind VARCHAR(20) NOT NULL,
        -- 사람이면 usr_seq, 묶음이면 role_id, 부서면 'office_id|부서명'
        target_key NVARCHAR(120) NOT NULL,
        -- 그때 그 대상의 이름. 원본이 바뀌어도 '누구였는지'가 남는다.
        target_label NVARCHAR(120) NULL,
        action VARCHAR(20) NOT NULL,        -- create|update|delete|assign|unassign
        status VARCHAR(12) NOT NULL
            CONSTRAINT DF_a10_access_change_status DEFAULT ('applied'),
        -- 되돌리려면 before 가 있어야 한다. 이게 이 표의 존재 이유다.
        before_json NVARCHAR(MAX) NULL,
        after_json NVARCHAR(MAX) NULL,
        -- 지금은 둘이 같다(관리자 직접 변경). 신청 흐름이 붙으면 갈리고,
        -- 그때 결재선이 이 두 칸에서 읽힌다.
        actor_usr_seq BIGINT NULL,
        requested_by_usr_seq BIGINT NULL,
        -- 사유는 반드시 NVARCHAR 다. a10_access_policy.memo 가 VARCHAR 라
        -- 운영에 저장된 단 하나의 한글 사유가 '??? ?? ???? ???' 로 죽어 있다.
        reason NVARCHAR(400) NULL,
        created_at DATETIME2 NOT NULL
            CONSTRAINT DF_a10_access_change_created_at DEFAULT (SYSDATETIME()),
        CONSTRAINT PK_a10_access_change PRIMARY KEY CLUSTERED (change_id)
    );
    -- '이 사람 권한이 언제부터 이랬나' — 가장 잦은 질문.
    CREATE INDEX IX_a10_access_change_target
        ON dbo.a10_access_change (target_kind, target_key, created_at);
    -- '지난주에 누가 뭘 만졌나' — 사고 직후에 보는 축.
    CREATE INDEX IX_a10_access_change_time
        ON dbo.a10_access_change (created_at);
    -- 신청 흐름이 붙으면 '대기 N건' 을 이 인덱스로 센다.
    CREATE INDEX IX_a10_access_change_status
        ON dbo.a10_access_change (status, created_at);
END

/* ── 표가 이미 있어도 빠진 인덱스를 채운다 ────────────────────────────────
   배포의 create_all 이 먼저 돌아 표를 만들어 놓았을 수 있다. 그 경우 위 블록은
   통째로 건너뛰므로 인덱스가 빠진 표가 남는다. */
IF OBJECT_ID(N'dbo.a10_access_change', N'U') IS NOT NULL
BEGIN
    IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_a10_access_change_target'
                     AND object_id = OBJECT_ID(N'dbo.a10_access_change'))
        CREATE INDEX IX_a10_access_change_target
            ON dbo.a10_access_change (target_kind, target_key, created_at);
    IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_a10_access_change_time'
                     AND object_id = OBJECT_ID(N'dbo.a10_access_change'))
        CREATE INDEX IX_a10_access_change_time
            ON dbo.a10_access_change (created_at);
    IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_a10_access_change_status'
                     AND object_id = OBJECT_ID(N'dbo.a10_access_change'))
        CREATE INDEX IX_a10_access_change_status
            ON dbo.a10_access_change (status, created_at);
END

/* ── 사유 칸의 한글을 살린다 ──────────────────────────────────────────────
   a10_access_policy.memo 와 a10_user_permission.memo 가 VARCHAR(200) 이라
   한글이 물음표로 저장된다. 운영에 실제로 그렇게 죽은 사유가 하나 있다
   (usr_seq 1148: '??? ?? ???? ???'). 이미 죽은 글자는 되살릴 수 없지만,
   앞으로 적는 사유는 읽히게 한다. 같은 저장소의 다른 memo 는 전부 NVARCHAR 다. */
IF EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
           WHERE TABLE_NAME = 'a10_access_policy' AND COLUMN_NAME = 'memo'
             AND DATA_TYPE = 'varchar')
BEGIN
    ALTER TABLE dbo.a10_access_policy ALTER COLUMN memo NVARCHAR(200) NULL;
    PRINT N'  * a10_access_policy.memo VARCHAR -> NVARCHAR (한글 사유 복구)';
END

IF EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
           WHERE TABLE_NAME = 'a10_user_permission' AND COLUMN_NAME = 'memo'
             AND DATA_TYPE = 'varchar')
BEGIN
    ALTER TABLE dbo.a10_user_permission ALTER COLUMN memo NVARCHAR(200) NULL;
    PRINT N'  * a10_user_permission.memo VARCHAR -> NVARCHAR';
END

/* ── 만들어졌는지 확인하고 나서 완료라고 말한다 ───────────────────────── */
IF OBJECT_ID(N'dbo.a10_access_change', N'U') IS NULL
    THROW 50003, N'a10_access_change 가 만들어지지 않았습니다.', 1;

    COMMIT TRANSACTION;
    PRINT N'완료: a10_access_change (확인됨)';
    PRINT N'이제부터 권한 변경이 before/after 와 함께 남습니다.';
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH
