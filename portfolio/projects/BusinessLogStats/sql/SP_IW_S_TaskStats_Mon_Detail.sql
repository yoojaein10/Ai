/*==============================================================================
  SP_IW_S_TaskStats_Mon_WebDetail
  가변비 화면 "항목별 상세내역" 전용 프로시저.

  - 합계 SP(SP_IW_S_TaskStats_Mon)의 각 항목 산식(GROUP BY 직전 인라인뷰)을
    그대로 복제하되, GROUP BY 대신 건별로 반환한다.
  - 담당자는 합계 SP 최종 결과와 동일하게 @Manager 정확 일치로 필터한다.
    (합계 SP는 항목별 Manager 로 GROUP BY 후 @Manager 로 매칭하므로,
     공동담당 "안창덕,김형수" 같은 행은 정확 일치가 아니라 제외된다 → 합계와 일치)
  - @Item 으로 한 항목만 계산한다(가변비 화면이 항목을 펼칠 때 그 항목만 조회).

  파라미터
    @F_Date  varchar(10)  'YYYY-MM-01'
    @Manager varchar(20)  담당자 이름(정확 일치)
    @Item    varchar(20)  항목 코드(가변비 화면 수량컬럼명과 동일):
             M1Time 남직원 / SMTime 수습남 / SoPTime 소속평가사 / SuPTime 수습평가사
             JubC 접수 / BalC 발송 / SimC 심사
             TSJubC 탁상접수 / TSJubC2 탁상접수HF / TSC 탁상감정 / TSC2 탁상감정HF
             VISIC 비지오 / SVISIC 수습비지오 / SIJOC 시조위 / CHKC 검산
             YAKC 약식 / KBYAKC KB약식 / HSIMC 협회심사비
             GamX_Cnt 감정서경비(문서없음) / GamO_Cnt 감정서경비(문서있음)
             HugJup_Cnt HUG탁상접수 / HugGam_Cnt HUG탁상감정

  결과 컬럼(고정): Workdate, Docid, Charger, WorkTime, CustName, Address, Price
    - WorkTime : 시간형 항목의 "시:분"(showhour), 건수형은 ''
    - Price    : 해당 건 금액(합계 SP와 동일 산식)
==============================================================================*/
CREATE OR ALTER Procedure [dbo].[SP_IW_S_TaskStats_Mon_WebDetail]

    @F_Date   Varchar(10),
    @Manager  Varchar(20),
    @Item     Varchar(20)

AS
Begin
    SET NOCOUNT ON;

    DECLARE @StartDate datetime, @EndDate datetime, @StandYear varchar(20);
    SET @StartDate = CONVERT(datetime, LEFT(@F_Date, 7) + '-01', 120);
    SET @EndDate   = DATEADD(month, 1, @StartDate);

    SELECT @StandYear = Case When Left(@F_Date, 7) < '2020-07' Then Left(@F_Date, 7)
                             When (Left(@F_Date, 7) >= '2020-07' And Left(@F_Date, 7) < '2022-07') Then '2020-1'
                             When (Left(@F_Date, 7) >= '2022-07' And Left(@F_Date, 7) < '2023-07') Then '2022'
                             When (Left(@F_Date, 7) >= '2023-07' And Left(@F_Date, 7) < '2024-01') Then '2023'
                             When (Left(@F_Date, 7) >= '2024-01' And Left(@F_Date, 7) < '2025-01') Then '2024'
                             When (Left(@F_Date, 7) >= '2025-01' And Left(@F_Date, 7) < '2026-01') Then '2025'
                             When (Left(@F_Date, 7) >= '2026-01') Then '2026' End;

    SELECT Stand_Year, Gubun, Price
    INTO #StandardPrice
    FROM APW_YJI_StandardPrice
    WHERE Stand_Year = @StandYear;

    -- 남직원 (MANDAYWORK Gubun1, Ugrade 사원~팀장, 근속 1년 이상, MyGroups<>0)
    IF @Item = 'M1Time'
    BEGIN
        SELECT Convert(varchar(10), a.WorkDate, 23) AS Workdate, a.Docid,
               a.writeman AS Charger, a.showhour AS WorkTime,
               d.CustName, d.Address, Round(a.WorkHour * B.Price, 0) AS Price
        FROM APW_IW_MANDAYWORK A
            Left join #StandardPrice B ON B.Gubun = 1
            Left join TMWCMN_USR_BAC_INFO c On a.writeman = c.EMP
            Left join Apw_MasterEx d On a.Docid = d.Docid
        WHERE A.workdate >= @StartDate And A.workdate < @EndDate
          And A.GUBUN = 1 And C.OFFICE_ID = '10' And C.MyGroups <> 0
          And A.Ugrade in ('사원','주임','대리','과장','차장','실장','부장','팀장')
          And d.Manager not like '%공(%'
          And isnull(c.Insertdate,'2000-01-01') <= a.workdate - 365
          And d.Manager = @Manager
        UNION ALL
        SELECT Convert(varchar(10), a.WorkDate, 23), a.Docid, a.writeman, a.showhour, '', '',
               Round(a.WorkHour * B.Price, 0)
        FROM APW_IW_MANDAYWORK a
            Left join #StandardPrice B ON B.Gubun = 1
            Left join TMWCMN_USR_BAC_INFO c On a.writeman = c.EMP
        WHERE a.workdate >= @StartDate And a.workdate < @EndDate
          And a.GUBUN = 1 And a.Docid = '기타' And C.MyGroups <> 0
          And isnull(a.Manager,'') <> '' And a.Manager not like '%공(%' And a.Manager <> '공통'
          And a.Ugrade in ('사원','주임','대리','과장','차장','실장','부장','팀장')
          And isnull(c.Insertdate,'2000-01-01') <= a.workdate - 365
          And a.Manager = @Manager
        ORDER BY Workdate;
        RETURN;
    END

    -- 수습남 (Gubun2, Ugrade 사원, 근속 1년 미만)
    IF @Item = 'SMTime'
    BEGIN
        SELECT Convert(varchar(10), a.WorkDate, 23) AS Workdate, a.Docid,
               a.writeman AS Charger, a.showhour AS WorkTime,
               d.CustName, d.Address, Round(a.WorkHour * B.Price, 0) AS Price
        FROM APW_IW_MANDAYWORK A
            Left join #StandardPrice B ON B.Gubun = 2
            Left join TMWCMN_USR_BAC_INFO c On a.writeman = c.EMP
            Left join Apw_MasterEx d On a.Docid = d.Docid
        WHERE A.workdate >= @StartDate And A.workdate < @EndDate
          And A.GUBUN = 1 And C.OFFICE_ID = '10' And A.Ugrade = '사원'
          And isnull(c.Insertdate,'2000-01-01') >= a.workdate - 365
          And d.Manager not like '%공(%'
          And d.Manager = @Manager
        UNION ALL
        SELECT Convert(varchar(10), a.WorkDate, 23), a.Docid, a.writeman, a.showhour, '', '',
               Round(a.WorkHour * B.Price, 0)
        FROM APW_IW_MANDAYWORK a
            Left join #StandardPrice B ON B.Gubun = 2
            Left join TMWCMN_USR_BAC_INFO c On a.writeman = c.EMP
        WHERE a.workdate >= @StartDate And a.workdate < @EndDate
          And a.GUBUN = 1 And a.Docid = '기타' And A.Ugrade = '사원'
          And isnull(a.Manager,'') <> '' And a.Manager not like '%공(%' And a.Manager <> '공통'
          And isnull(c.Insertdate,'2000-01-01') >= a.workdate - 365
          And a.Manager = @Manager
        ORDER BY Workdate;
        RETURN;
    END

    -- 소속평가사 (Gubun6, Ugrade 소속평가사, 근속조건 없음)
    IF @Item = 'SoPTime'
    BEGIN
        SELECT Convert(varchar(10), a.WorkDate, 23) AS Workdate, a.Docid,
               a.writeman AS Charger, a.showhour AS WorkTime,
               d.CustName, d.Address, Round(a.WorkHour * B.Price, 0) AS Price
        FROM APW_IW_MANDAYWORK A
            Left join #StandardPrice B ON B.Gubun = 6
            Left join TMWCMN_USR_BAC_INFO c On a.writeman = c.EMP
            Left join Apw_MasterEx d On a.Docid = d.Docid
        WHERE A.workdate >= @StartDate And A.workdate < @EndDate
          And A.GUBUN = 1 And C.OFFICE_ID = '10' And A.Ugrade = '소속평가사'
          And d.Manager not like '%공(%'
          And d.Manager = @Manager
        UNION ALL
        SELECT Convert(varchar(10), a.WorkDate, 23), a.Docid, a.writeman, a.showhour, '', '',
               Round(a.WorkHour * B.Price, 0)
        FROM APW_IW_MANDAYWORK a
            Left join #StandardPrice B ON B.Gubun = 6
        WHERE a.workdate >= @StartDate And a.workdate < @EndDate
          And a.GUBUN = 1 And a.Docid = '기타' And a.Ugrade = '소속평가사'
          And isnull(a.Manager,'') <> '' And a.Manager not like '%공(%' And a.Manager <> '공통'
          And a.Manager = @Manager
        ORDER BY Workdate;
        RETURN;
    END

    -- 수습평가사 (Gubun7, Ugrade 수습평가사, 근속조건 없음)
    IF @Item = 'SuPTime'
    BEGIN
        SELECT Convert(varchar(10), a.WorkDate, 23) AS Workdate, a.Docid,
               a.writeman AS Charger, a.showhour AS WorkTime,
               d.CustName, d.Address, Round(a.WorkHour * B.Price, 0) AS Price
        FROM APW_IW_MANDAYWORK A
            Left join #StandardPrice B ON B.Gubun = 7
            Left join TMWCMN_USR_BAC_INFO c On a.writeman = c.EMP
            Left join Apw_MasterEx d On a.Docid = d.Docid
        WHERE A.workdate >= @StartDate And A.workdate < @EndDate
          And A.GUBUN = 1 And C.OFFICE_ID = '10' And A.Ugrade = '수습평가사'
          And d.Manager not like '%공(%'
          And d.Manager = @Manager
        UNION ALL
        SELECT Convert(varchar(10), a.WorkDate, 23), a.Docid, a.writeman, a.showhour, '', '',
               Round(a.WorkHour * B.Price, 0)
        FROM APW_IW_MANDAYWORK a
            Left join #StandardPrice B ON B.Gubun = 7
        WHERE a.workdate >= @StartDate And a.workdate < @EndDate
          And a.GUBUN = 1 And a.Docid = '기타' And a.Ugrade = '수습평가사'
          And isnull(a.Manager,'') <> '' And a.Manager not like '%공(%' And a.Manager <> '공통'
          And a.Manager = @Manager
        ORDER BY Workdate;
        RETURN;
    END

    -- 접수
    IF @Item = 'JubC'
    BEGIN
        SELECT Convert(varchar(10), A.ReceiptDate, 23) AS Workdate,
               A.DocID AS Docid, A.ReceiptCharge AS Charger, '' AS WorkTime,
               A.CustName, A.AddrEtc AS Address, B.Price
        FROM APW_MASTER A
            Left join #StandardPrice B ON B.Gubun = 9
            Left join ( SELECT MasterID, MAX(CASE WHEN iType = 1 THEN Names END) AS Manager
                        FROM APW_Charge_IDX GROUP BY MasterID ) cia On cia.MasterID = A.MasterID
        WHERE A.ReceiptDate >= @StartDate And A.ReceiptDate < @EndDate
          And SUBSTRING(A.docid, 9, 1) <> '6'
          And cia.Manager = @Manager
        ORDER BY Workdate;
        RETURN;
    END

    -- 발송
    IF @Item = 'BalC'
    BEGIN
        SELECT Convert(varchar(10), A.SendDate, 23) AS Workdate,
               A.DocID AS Docid, A.SendMan AS Charger, '' AS WorkTime,
               A.CustName, A.AddrEtc AS Address, B.Price
        FROM APW_MASTER A
            Left join #StandardPrice B ON B.Gubun = 10
            Left join ( SELECT MasterID, MAX(CASE WHEN iType = 1 THEN Names END) AS Manager
                        FROM APW_Charge_IDX GROUP BY MasterID ) cia On cia.MasterID = A.MasterID
        WHERE A.SendDate >= @StartDate And A.SendDate < @EndDate
          And A.Office = '10'
          And SUBSTRING(A.docid, 9, 1) <> '6'
          And cia.Manager = @Manager
        ORDER BY Workdate;
        RETURN;
    END

    -- 심사
    IF @Item = 'SimC'
    BEGIN
        SELECT Distinct Convert(varchar(10), a.simsadate, 23) AS Workdate,
               a.Docid, '' AS Charger, '' AS WorkTime,
               d.CustName, d.Address, b.Price
        FROM APW_simsa_form a
            Left join #StandardPrice B ON B.Gubun = 11
            Left join Apw_MasterEx d On a.Docid = d.Docid
        WHERE a.simsadate >= @StartDate And a.simsadate < @EndDate
          And d.Office = '10'
          And d.Manager = @Manager
        ORDER BY Workdate;
        RETURN;
    END

    -- 탁상접수 (일반) / 탁상접수 HF (KB, HFDocid 400)
    IF @Item IN ('TSJubC','TSJubC2')
    BEGIN
        DECLARE @tsGubun int; SET @tsGubun = CASE @Item WHEN 'TSJubC' THEN 8 ELSE 16 END;
        SELECT Convert(varchar(10), A.Reg_DateTime, 23) AS Workdate,
               A.MasterID AS Docid, C.EMP AS Charger, '' AS WorkTime,
               A.CustName, A.Addr AS Address, B.Price
        FROM APW_TS_Master A
            Left join #StandardPrice B ON B.Gubun = @tsGubun
            Left join TMWCMN_USR_BAC_INFO C ON A.Reg_Charge = C.USR_SEQ
            Left join TMWCMN_USR_BAC_INFO D ON A.Manager = D.USR_SEQ
        WHERE A.Reg_DateTime >= @StartDate And A.Reg_DateTime < @EndDate
          And C.APPRAISAL_FL = 1
          And A.Office = '10'
          And ( (@Item = 'TSJubC'  And Left(isnull(a.HFDocid, ''), 3) <> '400')
             OR (@Item = 'TSJubC2' And Left(isnull(a.HFDocid, ''), 3) = '400') )
          And D.EMP = @Manager
        ORDER BY Workdate;
        RETURN;
    END

    -- 탁상감정 (일반) / 탁상감정 HF (KB)
    IF @Item IN ('TSC','TSC2')
    BEGIN
        DECLARE @tscGubun int; SET @tscGubun = CASE @Item WHEN 'TSC' THEN 5 ELSE 17 END;
        SELECT Convert(varchar(10), A.Workdate, 23) AS Workdate,
               A.Docid, A.writeman AS Charger, '' AS WorkTime,
               c.CustName, c.Addr AS Address, B.Price
        FROM APW_IW_MANDAYWORK A
            Left join #StandardPrice B ON B.Gubun = @tscGubun
            Left join APW_TS_Master c On A.Docid = c.MasterID
        WHERE A.workdate >= @StartDate And A.workdate < @EndDate
          And A.GUBUN = 2
          And ( (@Item = 'TSC'  And Left(isnull(c.HFDocid, ''), 3) <> '400')
             OR (@Item = 'TSC2' And Left(isnull(c.HFDocid, ''), 3) = '400') )
          And A.Manager = @Manager
        ORDER BY Workdate;
        RETURN;
    END

    -- 비지오 / 수습비지오
    IF @Item IN ('VISIC','SVISIC')
    BEGIN
        DECLARE @viGubun int; SET @viGubun = CASE @Item WHEN 'VISIC' THEN 3 ELSE 4 END;
        SELECT Convert(varchar(10), A.Update_Date, 23) AS Workdate,
               A.Docid, A.Emp_Dam AS Charger, '' AS WorkTime,
               d.CustName, d.Address, B.Price
        FROM Apw_VIsio A
            Left join #StandardPrice B ON B.Gubun = @viGubun
            Left join TMWCMN_USR_BAC_INFO c On a.Emp_Dam = c.EMP
            Left join Apw_MasterEx d On a.Docid = d.Docid
        WHERE A.Update_Date >= @StartDate And A.Update_Date < @EndDate
          And C.OFFICE_ID = '10'
          And a.Gubun = 'VISIO'
          And d.Office = '10'
          And d.Manager not like '%공(%'
          And c.RTRM_FL = 0
          And ( (@Item = 'VISIC'  And isnull(c.Insertdate,'2000-01-01') <= a.Update_Date - 365)
             OR (@Item = 'SVISIC' And isnull(c.Insertdate,'2000-01-01') >= a.Update_Date - 365 And a.Emp_Dam <> '이은선') )
          And d.Manager = @Manager
        ORDER BY Workdate;
        RETURN;
    END

    -- 시조위
    IF @Item = 'SIJOC'
    BEGIN
        SELECT Convert(varchar(10), A.simsadate, 23) AS Workdate,
               A.docid AS Docid, '' AS Charger, '' AS WorkTime,
               A.CustName, A.Addr AS Address, B.Price
        FROM APW_IW_SIJO A
            Left join #StandardPrice B ON B.Gubun = 12
            Left join APW_Masterex C ON A.docid = C.DocID
        WHERE A.simsadate >= @StartDate And A.simsadate < @EndDate
          And C.Office = '10'
          And C.Manager not like '공(%'
          And C.Manager = @Manager
        ORDER BY Workdate;
        RETURN;
    END

    -- 검산 (합계 SP 상 항상 0 → 상세 없음)
    IF @Item = 'CHKC'
    BEGIN
        SELECT Convert(varchar(10),@StartDate,23) AS Workdate, '' AS Docid, '' AS Charger,
               '' AS WorkTime, '' AS CustName, '' AS Address, CAST(0 AS money) AS Price
        WHERE 1 = 0;
        RETURN;
    END

    -- 약식
    IF @Item = 'YAKC'
    BEGIN
        SELECT Convert(varchar(10), a.Writedate, 23) AS Workdate,
               a.DOCID AS Docid, a.Writeman AS Charger, '' AS WorkTime,
               a.CustName, a.ADDR AS Address, b.Price
        FROM APW_IW_YACKMASTER a
            Left join #StandardPrice b On b.Gubun = 13
            Left join APW_MASTER C ON A.Docid = C.DocID
        WHERE a.Writedate >= @StartDate And a.Writedate < @EndDate
          And C.Office = '10'
          And a.Manager = @Manager
        ORDER BY Workdate;
        RETURN;
    END

    -- KB약식 (합계 SP 상 김형수 고정)
    IF @Item = 'KBYAKC'
    BEGIN
        IF @Manager = '김형수'
        BEGIN
            SELECT a.WorkDate AS Workdate, a.RequestNM AS Docid, '' AS Charger, '' AS WorkTime,
                   '국민은행' AS CustName, '' AS Address, a.Price
            FROM
            (
                Select DISTINCT a.RequestNM, d.Price,
                       Left(Convert(Char(10), c.Apptime,126),4) + '-' + Substring(Convert(Char(10), c.Apptime,126),5,2)
                       + CASE WHEN @StandYear >= '2025' THEN '' ELSE '-' + Substring(Convert(Char(10), c.Apptime,126),7,2) END AS WorkDate
                From Bank_kb_master a
                    Inner join Bank_KB_apt b On a.requestNM = b.requestNM
                    Inner join Bank_KB_Header c On a.KB_MasterID = c.KB_MasterID
                    Left join #StandardPrice d On d.Gubun = CASE WHEN @StandYear >= '2025' THEN 18 ELSE 13 END
                where b.appgubun = '2'
                  And a.OfficeID = '10'
                  And Left(Convert(Char(10), c.Apptime,126),4) + '-' + Substring(Convert(Char(10), c.Apptime,126),5,2) like Left(@F_Date,7) + '%'
                  And a.WorkResult = 6
            ) a
            ORDER BY Workdate;
        END
        ELSE
            SELECT Convert(varchar(10),@StartDate,23) AS Workdate, '' AS Docid, '' AS Charger,
                   '' AS WorkTime, '' AS CustName, '' AS Address, CAST(0 AS money) AS Price WHERE 1 = 0;
        RETURN;
    END

    -- 협회심사비
    IF @Item = 'HSIMC'
    BEGIN
        SELECT Convert(varchar(10), P.ISSUEDATE, 23) AS Workdate,
               A.docid AS Docid, '' AS Charger, '' AS WorkTime,
               A.CustName, A.Address,
               Floor(((A.수수료합계 - (A.여비 + A.물건조사비 + A.토지조사비 + A.특별용역비 + A.공부발급비 + A.기타실비)) * 0.008)/10)*10 AS Price
        FROM APW_MASTEREX A
            Left join APW_Process P on A.MasterID = P.MasterID
        WHERE P.ISSUEDATE >= @StartDate And P.ISSUEDATE < @EndDate
          And SUBSTRING(A.docid, 9, 1) <> '6'
          And P.Code = '0C'
          And A.Manager not like '%공(%'
          And A.Manager = @Manager
        ORDER BY Workdate;
        RETURN;
    END

    -- 감정서경비(문서없음)
    IF @Item = 'GamX_Cnt'
    BEGIN
        SELECT Convert(varchar(10), a.JunpyoDate, 23) AS Workdate,
               '' AS Docid, a.WriteMan AS Charger, '' AS WorkTime,
               a.CustName, '' AS Address, a.Price
        FROM apw_iw_bonus_DocCost a
        WHERE isnull(a.Docid, '') = ''
          And a.JunpyoDate >= @StartDate And a.JunpyoDate < @EndDate
          And a.Gubun in ('세금과공과','도서인쇄비')
          And a.Bigo not like '%자동차세%'
          And a.Manager = @Manager
        ORDER BY Workdate;
        RETURN;
    END

    -- 감정서경비(문서있음)
    IF @Item = 'GamO_Cnt'
    BEGIN
        SELECT Convert(varchar(10), a.JunpyoDate, 23) AS Workdate,
               a.Docid, a.WriteMan AS Charger, '' AS WorkTime,
               b.CustName, b.Address, a.Price
        FROM apw_iw_bonus_DocCost a
            Left join Apw_MasterEx b On a.Docid = b.Docid
        WHERE isnull(a.Docid, '') <> ''
          And a.JunpyoDate >= @StartDate And a.JunpyoDate < @EndDate
          And a.Gubun in ('세금과공과','도서인쇄비')
          And b.Manager = @Manager
        ORDER BY Workdate;
        RETURN;
    END

    -- HUG 탁상접수 / HUG 탁상감정 (합계 SP 상 안창덕 고정)
    IF @Item IN ('HugJup_Cnt','HugGam_Cnt')
    BEGIN
        IF @Manager = '안창덕'
        BEGIN
            IF @Item = 'HugJup_Cnt'
                SELECT Convert(varchar(10), a.ReceiptDate, 23) AS Workdate,
                       a.Docid, '' AS Charger, '' AS WorkTime,
                       '주택도시보증공사(HUG)' AS CustName, a.Addr AS Address, b.Price
                FROM Hug_info a Left join #StandardPrice b On b.Gubun = 19
                WHERE a.ReceiptDate >= @StartDate And a.ReceiptDate < @EndDate
                ORDER BY Workdate;
            ELSE
                SELECT Convert(varchar(10), a.Complete_Date, 23) AS Workdate,
                       a.Docid, '' AS Charger, '' AS WorkTime,
                       '주택도시보증공사(HUG)' AS CustName, a.Addr AS Address, b.Price
                FROM Hug_info a Left join #StandardPrice b On b.Gubun = 20
                WHERE a.Complete_Date >= @StartDate And a.Complete_Date < @EndDate
                ORDER BY Workdate;
        END
        ELSE
            SELECT Convert(varchar(10),@StartDate,23) AS Workdate, '' AS Docid, '' AS Charger,
                   '' AS WorkTime, '' AS CustName, '' AS Address, CAST(0 AS money) AS Price WHERE 1 = 0;
        RETURN;
    END

    -- 알 수 없는 항목: 빈 결과
    SELECT Convert(varchar(10),@StartDate,23) AS Workdate, '' AS Docid, '' AS Charger,
           '' AS WorkTime, '' AS CustName, '' AS Address, CAST(0 AS money) AS Price
    WHERE 1 = 0;
End
GO
