-- a10_deposit_outbox.voucher_kind VARCHAR(10) -> VARCHAR(16)
-- 2026-08-24 잡이익(MISC_INCOME, 11자) 전표 종류가 생기면서 UPDATE 가 8152(잘림)로 실패 → 입금 스캔 전체가 서고
-- 이후 약식·일반 전표가 아마란스로 안 나갔다. 넓히기만 하는 ALTER 라 데이터 손실 없음.
SET NOCOUNT ON;
IF COL_LENGTH(N'dbo.a10_deposit_outbox', N'voucher_kind') < 16
BEGIN
    ALTER TABLE dbo.a10_deposit_outbox ALTER COLUMN voucher_kind VARCHAR(16) NULL;
    PRINT N'  ~ a10_deposit_outbox.voucher_kind VARCHAR(16)';
END
