-- 같은 400번호의 일부입금·잔금을 각각 기록할 수 있게 한다.
-- 중복 기준은 yak_no가 아니라 CB2 개별 입금인 outbox_id다.
SET NOCOUNT ON;

IF OBJECT_ID(N'dbo.a10_kb_yak_item', N'U') IS NOT NULL
BEGIN
    DECLARE @ddl nvarchar(max);
    DECLARE @yakUq sysname;
    SELECT TOP (1) @yakUq = kc.name
    FROM sys.key_constraints kc
    JOIN sys.index_columns ic
      ON ic.object_id = kc.parent_object_id
     AND ic.index_id = kc.unique_index_id
     AND ic.key_ordinal > 0
    JOIN sys.columns c
      ON c.object_id = ic.object_id AND c.column_id = ic.column_id
    WHERE kc.parent_object_id = OBJECT_ID(N'dbo.a10_kb_yak_item')
      AND kc.type = 'UQ'
    GROUP BY kc.name
    HAVING COUNT(*) = 1 AND MAX(CASE WHEN c.name = N'yak_no' THEN 1 ELSE 0 END) = 1;

    IF @yakUq IS NOT NULL
    BEGIN
        SET @ddl = N'ALTER TABLE dbo.a10_kb_yak_item DROP CONSTRAINT ' + QUOTENAME(@yakUq);
        EXEC sys.sp_executesql @ddl;
    END

    DECLARE @yakUniqueIndex sysname;
    SELECT TOP (1) @yakUniqueIndex = i.name
    FROM sys.indexes i
    JOIN sys.index_columns ic
      ON ic.object_id = i.object_id AND ic.index_id = i.index_id AND ic.key_ordinal > 0
    JOIN sys.columns c
      ON c.object_id = ic.object_id AND c.column_id = ic.column_id
    WHERE i.object_id = OBJECT_ID(N'dbo.a10_kb_yak_item')
      AND i.is_unique = 1 AND i.is_primary_key = 0
      AND NOT EXISTS (
          SELECT 1 FROM sys.key_constraints kc
          WHERE kc.parent_object_id = i.object_id AND kc.unique_index_id = i.index_id
      )
    GROUP BY i.name
    HAVING COUNT(*) = 1 AND MAX(CASE WHEN c.name = N'yak_no' THEN 1 ELSE 0 END) = 1;

    IF @yakUniqueIndex IS NOT NULL
    BEGIN
        SET @ddl = N'DROP INDEX ' + QUOTENAME(@yakUniqueIndex) + N' ON dbo.a10_kb_yak_item';
        EXEC sys.sp_executesql @ddl;
    END

    IF NOT EXISTS (
        SELECT 1 FROM sys.indexes
        WHERE object_id = OBJECT_ID(N'dbo.a10_kb_yak_item')
          AND name = N'ix_a10_kb_yak_item_yak_no'
    )
        CREATE INDEX ix_a10_kb_yak_item_yak_no
            ON dbo.a10_kb_yak_item(yak_no);

    IF EXISTS (
        SELECT 1 FROM sys.indexes
        WHERE object_id = OBJECT_ID(N'dbo.a10_kb_yak_item')
          AND name = N'ix_a10_kb_yak_item_outbox_id' AND is_unique = 0
    )
        DROP INDEX ix_a10_kb_yak_item_outbox_id ON dbo.a10_kb_yak_item;

    IF NOT EXISTS (
        SELECT 1
        FROM sys.indexes i
        JOIN sys.index_columns ic
          ON ic.object_id = i.object_id AND ic.index_id = i.index_id AND ic.key_ordinal = 1
        JOIN sys.columns c
          ON c.object_id = ic.object_id AND c.column_id = ic.column_id
        WHERE i.object_id = OBJECT_ID(N'dbo.a10_kb_yak_item')
          AND i.is_unique = 1 AND c.name = N'outbox_id'
    )
        CREATE UNIQUE INDEX ux_a10_kb_yak_item_outbox_id
            ON dbo.a10_kb_yak_item(outbox_id);
END
