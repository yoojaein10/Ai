/*
입금 완납 건의 전례 전송 상태 조회 프로시저.

기준
  - 완납: GamJunDW.dbo.a10_payment_status.pay_result = N'입금완료'
  - 조회일: a10_payment_status.paid_date(완납 입금일자)
  - 전례 상태: apworksdw.dbo.JUN_MASTER.USE_YN
      S          전례 전송
      Y          전송 대기
      NULL/공백/N 작업 필요
      그 외(E/F) 상태 확인 필요

JUN_MASTER와 APW_MASTEREX에는 감정서번호가 중복될 수 있으므로 감정서번호당
한 행으로 집계한다. 현재 실데이터에는 한 감정서 안에서 서로 다른 USE_YN이
섞인 최근 사례가 없지만, 섞일 경우 S > Y > N/공백 > 기타 순으로 표시한다.

실행 예
  EXEC dbo.usp_FullPaymentPrecedentStatus @PaidDateFrom = '2026-08-24';
  EXEC dbo.usp_FullPaymentPrecedentStatus
       @PaidDateFrom = '2026-08-01', @PaidDateTo = '2026-08-24';
*/

USE [GamJunDW];
GO

IF OBJECT_ID(N'dbo.usp_FullPaymentPrecedentStatus', N'P') IS NOT NULL
    DROP PROCEDURE dbo.usp_FullPaymentPrecedentStatus;
GO

CREATE PROCEDURE dbo.usp_FullPaymentPrecedentStatus
    @PaidDateFrom DATE,
    @PaidDateTo   DATE = NULL
AS
BEGIN
    SET NOCOUNT ON;

    SET @PaidDateTo = ISNULL(@PaidDateTo, @PaidDateFrom);

    IF @PaidDateFrom IS NULL
    BEGIN
        RAISERROR(N'@PaidDateFrom은 필수입니다.', 16, 1);
        RETURN;
    END;

    IF @PaidDateFrom > @PaidDateTo
    BEGIN
        RAISERROR(N'@PaidDateFrom은 @PaidDateTo보다 늦을 수 없습니다.', 16, 1);
        RETURN;
    END;

    ;WITH PaidDocs AS (
        SELECT p.doc_id, p.paid_date
        FROM dbo.a10_payment_status p
        WHERE p.pay_result = N'입금완료'
          AND p.paid_date >= @PaidDateFrom
          AND p.paid_date <= @PaidDateTo
    ),
    MasterByDoc AS (
        SELECT
            m.DocID,
            MAX(NULLIF(RTRIM(m.Manager), ''))     AS Manager,
            MAX(NULLIF(RTRIM(m.Charge), ''))      AS Charge,
            MAX(m.ReceiptDate)                    AS ReceiptDate,
            MAX(m.SendDate)                       AS SendDate,
            MAX(NULLIF(RTRIM(m.LPurpose), ''))    AS LPurpose,
            MAX(NULLIF(RTRIM(m.LWorkinfo), ''))   AS LWorkinfo,
            MAX(NULLIF(RTRIM(m.LStatus), ''))     AS LStatus,
            MAX(NULLIF(RTRIM(m.Address), ''))     AS Address
        FROM [apworksdw].dbo.APW_MASTEREX m
        INNER JOIN PaidDocs p ON p.doc_id = m.DocID
        GROUP BY m.DocID
    ),
    JunByDoc AS (
        SELECT
            j.ID_NUM AS DocID,
            MAX(CASE WHEN LTRIM(RTRIM(ISNULL(j.USE_YN, ''))) = 'S' THEN 1 ELSE 0 END) AS HasS,
            MAX(CASE WHEN LTRIM(RTRIM(ISNULL(j.USE_YN, ''))) = 'Y' THEN 1 ELSE 0 END) AS HasY,
            MAX(CASE WHEN LTRIM(RTRIM(ISNULL(j.USE_YN, ''))) IN ('', 'N') THEN 1 ELSE 0 END) AS HasWork,
            MAX(CASE WHEN LTRIM(RTRIM(ISNULL(j.USE_YN, ''))) NOT IN ('', 'N', 'S', 'Y') THEN 1 ELSE 0 END) AS HasOther,
            MAX(CASE
                    WHEN LTRIM(RTRIM(ISNULL(j.USE_YN, ''))) NOT IN ('', 'N', 'S', 'Y')
                    THEN LTRIM(RTRIM(j.USE_YN))
                END) AS OtherUseYn
        FROM [apworksdw].dbo.JUN_MASTER j
        INNER JOIN PaidDocs p ON p.doc_id = j.ID_NUM
        GROUP BY j.ID_NUM
    )
    SELECT
        p.doc_id                     AS DocID,
        m.Manager                    AS Manager,
        m.Charge                     AS Charge,
        m.ReceiptDate                AS ReceiptDate,
        m.SendDate                   AS SendDate,
        p.paid_date                  AS PaidDate,
        m.LPurpose                   AS LPurpose,
        m.LWorkinfo                  AS LWorkinfo,
        m.LStatus                    AS LStatus,
        m.Address                    AS Address,
        CASE
            WHEN j.HasS = 1 THEN 'S'
            WHEN j.HasY = 1 THEN 'Y'
            WHEN j.HasWork = 1 THEN 'N'
            WHEN j.HasOther = 1 THEN j.OtherUseYn
            ELSE NULL
        END                          AS Use_YN,
        CASE
            WHEN j.HasS = 1 THEN N'전례 전송'
            WHEN j.HasY = 1 THEN N'전송 대기'
            WHEN j.HasWork = 1 OR j.DocID IS NULL THEN N'작업 필요'
            ELSE N'상태 확인 필요'
        END                          AS PrecedentStatus
    FROM PaidDocs p
    LEFT JOIN MasterByDoc m ON m.DocID = p.doc_id
    LEFT JOIN JunByDoc j ON j.DocID = p.doc_id
    ORDER BY p.paid_date DESC, p.doc_id DESC;
END;
GO
