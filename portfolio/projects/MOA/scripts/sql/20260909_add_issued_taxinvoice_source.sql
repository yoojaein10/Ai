-- 발급 원장에 출처·작성일자 추가 (2026-09-09)
-- source: MOA팝빌 / 팝빌동기화 / TAMS / 나라장터 / 나라빌 / 국세청 / 기타
-- 기존 행은 전부 MOA 에서 팝빌로 발급한 것이라 기본값 'MOA팝빌' 로 채워진다.
IF COL_LENGTH('dbo.a10_issued_taxinvoice', 'source') IS NULL
    ALTER TABLE dbo.a10_issued_taxinvoice ADD source VARCHAR(20) NOT NULL CONSTRAINT DF_a10_issued_taxinvoice_source DEFAULT 'MOA팝빌';
IF COL_LENGTH('dbo.a10_issued_taxinvoice', 'write_date') IS NULL
    ALTER TABLE dbo.a10_issued_taxinvoice ADD write_date DATE NULL;
