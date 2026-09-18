-- 카카오 톡캘린더 연동을 위한 컬럼 추가
-- YJI_CalendarEvents 테이블에 실행

IF NOT EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('YJI_CalendarEvents') AND name = 'source'
)
BEGIN
    ALTER TABLE YJI_CalendarEvents
    ADD source NVARCHAR(20) DEFAULT 'manual';
END
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('YJI_CalendarEvents') AND name = 'kakao_event_id'
)
BEGIN
    ALTER TABLE YJI_CalendarEvents
    ADD kakao_event_id NVARCHAR(100) NULL;
END
GO

-- 중복 방지 인덱스 (kakao_event_id 컬럼 추가 후 실행)
IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID('YJI_CalendarEvents') AND name = 'IX_CalendarEvents_Kakao'
)
BEGIN
    CREATE INDEX IX_CalendarEvents_Kakao
    ON YJI_CalendarEvents (kakao_event_id, creator_id)
    WHERE kakao_event_id IS NOT NULL AND is_deleted = 0;
END
GO
