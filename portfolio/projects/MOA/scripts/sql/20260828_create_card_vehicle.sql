-- 업무용승용차 (a10_card_vehicle) — 카드전표 차량유지비(8220000) 라인의 아마란스 차량코드(carCd).
-- 멱등: 있으면 건너뛴다. 재배포의 create_all 이 먼저 만들어도 안전하다.
SET NOCOUNT ON;
BEGIN TRY
IF OBJECT_ID(N'dbo.a10_card_vehicle', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.a10_card_vehicle (
        vehicle_id INT IDENTITY(1, 1) NOT NULL,
        plate VARCHAR(20) NOT NULL,                  -- 차량번호 313도5539
        car_cd VARCHAR(10) NOT NULL,                 -- 아마란스 차량코드 0000002166
        person NVARCHAR(30) NOT NULL,                -- 관리사원 (카드 사용자명)
        model NVARCHAR(50) NULL,
        division_code VARCHAR(4) NOT NULL
            CONSTRAINT DF_a10_card_vehicle_division DEFAULT ('1000'),
        active CHAR(1) NOT NULL
            CONSTRAINT DF_a10_card_vehicle_active DEFAULT ('Y'),
        memo NVARCHAR(200) NULL,
        updated_at DATETIME2 NOT NULL
            CONSTRAINT DF_a10_card_vehicle_updated_at DEFAULT (SYSDATETIME()),
        CONSTRAINT PK_a10_card_vehicle PRIMARY KEY CLUSTERED (vehicle_id),
        CONSTRAINT UQ_a10_card_vehicle_plate UNIQUE (plate)
    );
    CREATE INDEX IX_a10_card_vehicle_person ON dbo.a10_card_vehicle (person);
    PRINT N'  + a10_card_vehicle';
END
IF OBJECT_ID(N'dbo.a10_card_vehicle', N'U') IS NULL
    THROW 50020, N'a10_card_vehicle 이 만들어지지 않았습니다.', 1;
PRINT N'완료: a10_card_vehicle';
END TRY
BEGIN CATCH
    PRINT N'오류: ' + ERROR_MESSAGE();
    THROW;
END CATCH
