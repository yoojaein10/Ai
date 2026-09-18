-- a10_bank_account_map.reconcile_only — 일계표 대사에만 쓰는 계좌 표시 (2026-08-26).
-- 지사 계좌(예: 북부 1946…7375)는 지사가 직접 전표를 넣으므로 입금전표 배치가 쓰면 안 된다.
-- 그런 계좌는 active='N' + reconcile_only='Y' 로 넣는다: 배치(active='Y'만)는 건너뛰고,
-- 대사(active='Y' OR reconcile_only='Y')는 읽는다. 멱등 — 열이 있으면 아무것도 안 한다.
SET NOCOUNT ON;

IF OBJECT_ID(N'dbo.a10_bank_account_map', N'U') IS NOT NULL
   AND COL_LENGTH(N'dbo.a10_bank_account_map', N'reconcile_only') IS NULL
BEGIN
    ALTER TABLE dbo.a10_bank_account_map
        ADD reconcile_only CHAR(1) NOT NULL
            CONSTRAINT df_a10_bank_account_map_reconcile_only DEFAULT 'N';
END
