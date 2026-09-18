/*
  권한 묶음·이력 표 되돌림 (2026-08-17)

  "테이블 필요 없으면 바로 삭제도 되지?" — 된다. 이 파일이 그 손잡이다.

  왜 안전하게 지울 수 있나
    · 운영 앱(main)은 이 표 4개를 **아예 읽지 않는다** — 권한 브랜치가 아직
      미병합이라, 지워도 운영 사용자에게는 아무 일도 안 일어난다.
    · 권한 브랜치 화면도 표가 없으면 조용히 코드 기본값으로 떨어진다
      (resolve_role 이 SQLAlchemyError 를 삼킨다 — 시험으로 지키는 성질).
      화면은 '묶음이 없습니다 / 표를 먼저 만드세요' 상태로 돌아갈 뿐이다.
    · 시드는 현행 코드 기본값의 사본이라(2026-08-17 전 직원 462명 등가 실측,
      달라진 사람 0명) 지워도 대부분의 권한이 변하지 않는다.

  ★ 딱 하나 예외 (2026-08-17 이후)
    지사 재무담당 18명은 코드 상수(BRANCH_FINANCE_HOLDERS)를 걷어내고 DB 묶음
    ('지사 재무담당')으로 옮겼다 — 담당자 교체에 배포가 필요 없게 하려는 것이다.
    그래서 이 표들을 지우면 **그 18명은 메뉴 0개가 되어 로그인이 거절된다.**
    되돌리려면 20260813_seed_access_role.sql 을 다시 실행하면 된다(명단이 거기 있다).

  지워지지 않는 것 하나
    memo 컬럼의 VARCHAR→NVARCHAR 전환(a10_access_policy·a10_user_permission)은
    되돌리지 않는다 — 무손실 개선이고, 되돌리면 한글 사유가 다시 깨진다.

  주의: a10_access_change 를 지우면 그동안 쌓인 권한 변경 이력이 함께 사라진다.
  이력을 남기고 표만 접고 싶으면 마지막 DROP 한 줄을 빼고 실행한다.
*/
SET XACT_ABORT ON;
BEGIN TRY
    BEGIN TRANSACTION;

DECLARE @n INT;
IF OBJECT_ID(N'dbo.a10_access_user_role', N'U') IS NOT NULL
BEGIN
    SELECT @n = COUNT(*) FROM dbo.a10_access_user_role;
    PRINT CONCAT(N'  - a10_access_user_role 삭제 (', @n, N'행)');
    DROP TABLE dbo.a10_access_user_role;
END
IF OBJECT_ID(N'dbo.a10_access_dept_role', N'U') IS NOT NULL
BEGIN
    SELECT @n = COUNT(*) FROM dbo.a10_access_dept_role;
    PRINT CONCAT(N'  - a10_access_dept_role 삭제 (', @n, N'행)');
    DROP TABLE dbo.a10_access_dept_role;
END
IF OBJECT_ID(N'dbo.a10_access_role', N'U') IS NOT NULL
BEGIN
    SELECT @n = COUNT(*) FROM dbo.a10_access_role;
    PRINT CONCAT(N'  - a10_access_role 삭제 (', @n, N'행)');
    DROP TABLE dbo.a10_access_role;
END
IF OBJECT_ID(N'dbo.a10_access_change', N'U') IS NOT NULL
BEGIN
    SELECT @n = COUNT(*) FROM dbo.a10_access_change;
    PRINT CONCAT(N'  - a10_access_change 삭제 (', @n, N'행 — 이력도 함께 사라짐)');
    DROP TABLE dbo.a10_access_change;
END

    COMMIT TRANSACTION;
    PRINT N'완료. 권한은 코드 기본값으로 돌아갔고, 운영(main)은 영향 없음.';
    PRINT N'다시 켜려면 20260813_create → 20260813_seed → 20260816_create 순서.';
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH
