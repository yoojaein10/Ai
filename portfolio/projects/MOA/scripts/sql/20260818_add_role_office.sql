/* 2026-08-18 — a10_access_role 에 소속(office_id) 추가.
   공용 없이 각 소속(본사 '10' · 지사코드)이 자기 묶음을 따로 가진다(사용자 결정).
   권한일괄적용은 대상(사람/부서)의 소속과 같은 office_id 묶음만 보여 준다.

   누구의 권한도 바꾸지 않는다 — 컬럼과 '이름 유일성 범위'만 바꾼다. 되돌리려면
   컬럼을 지우고 옛 인덱스를 되살리면 된다. 여러 번 실행해도 안전(idempotent).
   운영(main)은 이 표를 안 읽으므로 운영 동작에는 영향이 없다. */
SET NOCOUNT ON;

-- ① office_id 컬럼(없으면 추가). 우선 NULL 로 넣고 기존 행을 본사(10)로 채운다.
IF NOT EXISTS (SELECT 1 FROM sys.columns
               WHERE object_id = OBJECT_ID(N'dbo.a10_access_role') AND name = N'office_id')
BEGIN
    ALTER TABLE dbo.a10_access_role ADD office_id VARCHAR(10) NULL;
    PRINT N'  + office_id 컬럼 추가';
END

UPDATE dbo.a10_access_role SET office_id = '10' WHERE office_id IS NULL;
PRINT N'  기존 묶음 소속을 본사(10)로 채움';

-- NOT NULL 로 조인다(이미 NOT NULL 이면 건너뜀).
IF EXISTS (SELECT 1 FROM sys.columns
           WHERE object_id = OBJECT_ID(N'dbo.a10_access_role')
             AND name = N'office_id' AND is_nullable = 1)
BEGIN
    ALTER TABLE dbo.a10_access_role ALTER COLUMN office_id VARCHAR(10) NOT NULL;
    PRINT N'  office_id NOT NULL 로 전환';
END

-- ② 이름 유일성을 (office_id, name) 으로 — 지사마다 같은 이름('평가사 기본' 등)을 허용.
IF EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'UX_a10_access_role_name'
           AND object_id = OBJECT_ID(N'dbo.a10_access_role'))
BEGIN
    DROP INDEX UX_a10_access_role_name ON dbo.a10_access_role;
    PRINT N'  - 옛 이름 유일 인덱스(UX_a10_access_role_name) 제거';
END
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'UX_a10_access_role_office_name'
               AND object_id = OBJECT_ID(N'dbo.a10_access_role'))
BEGIN
    CREATE UNIQUE INDEX UX_a10_access_role_office_name
        ON dbo.a10_access_role (office_id, name) WHERE active = 'Y';
    PRINT N'  + 소속별 이름 유일 인덱스(UX_a10_access_role_office_name) 생성';
END

PRINT N'완료 — a10_access_role.office_id (지사별 묶음)';
