/*
SP_S_BONSAJUNLIST — 완납 건 중 협회 전례로 보낼 본사 목록 (2026-08-26 개정).

옛 이름 usp_FullPaymentPrecedentStatus(2026-08-24) 를 SP_S_BONSAJUNLIST 로 바꾼 뒤,
사용자 요청으로 조건과 출력을 손봤다.

기준
  - 완납: GamJunDW.dbo.a10_payment_status.pay_result = N'입금완료', 조회일 = paid_date(최근 입금일)
  - 감정서 유형: 감정서번호 세 번째 마디(01-2608-X-0125 의 X)가 3·4·7·A 인 건만.
      표준 XX-XXXX-X-XXXX(부번호 -1 붙어도 됨)와 하이픈 하나 빠진 XXXXXX-X-XXXX 둘 다 읽는다.
      번호 형식이 아닌 건('(호남)26-016' 같은 것)은 유형을 알 수 없으니 빠진다.
  - 제외: apworksdw.dbo.APW_MASTER.CustName 에 '허그' 또는 'HUG'(대소문자 무관)가 든 거래처.
  - 전례 상태(2026-08-27 단순화): JUN_MASTER.USE_YN 이 S 또는 Y → '등록', 그 외(N·빈값·행 없음) → '미등록'.
    감정서번호가 JUN_MASTER·APW_MASTEREX 에 중복될 수 있어 감정서당 한 행으로 집계한다.
  - 청구금액(2026-08-27): apw_masterex.[청구금액](= APW_Bill.BILL) — 착수금을 미리 받은 건은 잔금만 적혀 있다.
  - 입금금액(2026-08-27): a10_receivable_summary.received_amount — 전표 기반 입금 합계라 분할입금도 합쳐진 값.

출력 (엑셀 목록 순서 그대로 + 금액 두 열)
  감정서번호, 목적(LWorkinfo), 물건종류(LCategory), 거래처명(CustName), 유치자(Manager),
  발송일(SendDate), 최근 입금일(paid_date), 청구금액, 입금금액, 진행상태(LStatus), 전례상태

실행 예
  EXEC dbo.SP_S_BONSAJUNLIST @PaidDateFrom = '2026-08-20';
  EXEC dbo.SP_S_BONSAJUNLIST @PaidDateFrom = '2026-08-01', @PaidDateTo = '2026-08-25';
*/

USE [GamJunDW];
GO

IF OBJECT_ID(N'dbo.SP_S_BONSAJUNLIST', N'P') IS NOT NULL
    DROP PROCEDURE dbo.SP_S_BONSAJUNLIST;
GO

CREATE PROCEDURE dbo.SP_S_BONSAJUNLIST
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
        SELECT
            p.doc_id,
            p.paid_date,
            CASE
                WHEN p.doc_id LIKE '[0-9][0-9]-[0-9][0-9][0-9][0-9]-[0-9A-Za-z]-[0-9][0-9][0-9][0-9]%'
                    THEN UPPER(SUBSTRING(p.doc_id, 9, 1))                   -- 01-2608-X-0125(-1)
                WHEN p.doc_id LIKE '[0-9][0-9][0-9][0-9][0-9][0-9]-[0-9A-Za-z]-[0-9][0-9][0-9][0-9]%'
                    THEN UPPER(SUBSTRING(p.doc_id, 8, 1))                   -- 012608-X-0125 (하이픈 하나 빠짐)
            END AS DocType
        FROM dbo.a10_payment_status p
        WHERE p.pay_result = N'입금완료'
          AND p.paid_date >= @PaidDateFrom
          AND p.paid_date <= @PaidDateTo
    ),
    TargetDocs AS (
        SELECT p.doc_id, p.paid_date
        FROM PaidDocs p
        WHERE p.DocType IN ('3', '4', '7', 'A')
          AND LEFT(p.doc_id, 2) = '01'                 -- 본사 건만 (두 형식 모두 앞 두 자리가 사무소)
    ),
    CustByDoc AS (
        SELECT a.DocID, MAX(NULLIF(RTRIM(a.CustName), '')) AS CustName
        FROM [apworksdw].dbo.APW_MASTER a
        INNER JOIN TargetDocs t ON t.doc_id = a.DocID
        GROUP BY a.DocID
    ),
    MasterByDoc AS (
        SELECT
            m.DocID,
            MAX(NULLIF(RTRIM(m.Manager), ''))     AS Manager,
            MAX(m.SendDate)                       AS SendDate,
            MAX(NULLIF(RTRIM(m.LWorkinfo), ''))   AS LWorkinfo,
            MAX(NULLIF(RTRIM(m.LCategory), ''))   AS LCategory,
            MAX(NULLIF(RTRIM(m.LStatus), ''))     AS LStatus,
            MAX(m.[청구금액])                     AS BillAmount
        FROM [apworksdw].dbo.APW_MASTEREX m
        INNER JOIN TargetDocs t ON t.doc_id = m.DocID
        GROUP BY m.DocID
    ),
    JunByDoc AS (
        SELECT
            j.ID_NUM AS DocID,
            -- S(전송)든 Y(대기)든 협회 시스템에 올라가 있으면 '등록' — 그 외는 전부 '미등록'
            MAX(CASE WHEN UPPER(LTRIM(RTRIM(ISNULL(j.USE_YN, '')))) IN ('S', 'Y') THEN 1 ELSE 0 END) AS HasReg
        FROM [apworksdw].dbo.JUN_MASTER j
        INNER JOIN TargetDocs t ON t.doc_id = j.ID_NUM
        GROUP BY j.ID_NUM
    )
    SELECT
        t.doc_id                        AS [감정서번호],
        m.LWorkinfo                     AS [목적],
        m.LCategory                     AS [물건종류],
        c.CustName                      AS [거래처명],
        m.Manager                       AS [유치자],
        CAST(m.SendDate AS DATE)        AS [발송일],
        t.paid_date                     AS [최근 입금일],
        m.BillAmount                    AS [청구금액],
        s.received_amount               AS [입금금액],
        m.LStatus                       AS [진행상태],
        CASE WHEN j.HasReg = 1 THEN N'등록' ELSE N'미등록' END AS [전례상태]
    FROM TargetDocs t
    LEFT JOIN CustByDoc c ON c.DocID = t.doc_id
    LEFT JOIN MasterByDoc m ON m.DocID = t.doc_id
    LEFT JOIN JunByDoc j ON j.DocID = t.doc_id
    LEFT JOIN dbo.a10_receivable_summary s ON s.doc_id = t.doc_id
    WHERE NOT (
        c.CustName LIKE N'%허그%'
        OR UPPER(c.CustName) LIKE N'%HUG%'
    )
    ORDER BY t.paid_date DESC, t.doc_id DESC;
END;
GO
