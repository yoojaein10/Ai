-- 발급 원장에 '입금 적용용 계산서' 열 두 개 추가 (2026-09-10)
-- is_pool : 1 이면 대표 감정서번호로 크게 끊어 둔 모계산서 — 어느 감정서 발행금액에도 안 잡히고 잔액 계산에만 쓴다
-- pool_id : 적용 행이 어느 모계산서(id)에서 떼어 온 것인지. 취소·잔액 계산에 쓴다
IF COL_LENGTH('dbo.a10_issued_taxinvoice', 'is_pool') IS NULL
    ALTER TABLE dbo.a10_issued_taxinvoice ADD is_pool BIT NOT NULL CONSTRAINT DF_a10_issued_taxinvoice_is_pool DEFAULT 0;
IF COL_LENGTH('dbo.a10_issued_taxinvoice', 'pool_id') IS NULL
    ALTER TABLE dbo.a10_issued_taxinvoice ADD pool_id INT NULL;
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_a10_issued_taxinvoice_pool_id')
    CREATE INDEX IX_a10_issued_taxinvoice_pool_id ON dbo.a10_issued_taxinvoice (pool_id) WHERE pool_id IS NOT NULL;
