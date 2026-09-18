
CREATE Procedure [dbo].[SP_IW_S_TaskStats_Mon]
	
	@F_Date		Varchar(10), 		
	@Manager	Varchar(10) = ''

AS
Begin

        SET NOCOUNT ON;

		
    DECLARE @StartDate datetime;
    DECLARE @EndDate datetime;

	Set @StartDate = CONVERT(datetime, LEFT(@F_Date, 7) + '-01', 120);
    Set @EndDate = DATEADD(month, 1, @StartDate);
    -- SQL Server 구버전/낮은 호환성 수준에서도 동작하도록 작성한다.

    SET @StartDate = CONVERT(datetime, LEFT(@F_Date, 7) + '-01', 120);
    SET @EndDate = DATEADD(month, 1, @StartDate);

	Declare @StandYear varchar(20)

	SELECT @StandYear = Case When Left(@F_Date, 7) < '2020-07' Then  Left(@F_Date, 7)
																	 When (Left(@F_Date, 7) >= '2020-07' And Left(@F_Date, 7) < '2022-07' ) Then '2020-1'
																	 When (Left(@F_Date, 7) >= '2022-07' And Left(@F_Date, 7) < '2023-07' ) Then '2022' 
																	 When (Left(@F_Date, 7) >= '2023-07' And Left(@F_Date, 7) < '2024-01') Then '2023' 
																	 When (Left(@F_Date, 7) >= '2024-01' And Left(@F_Date, 7) < '2025-01') Then '2024' 
																	 When (Left(@F_Date, 7) >= '2025-01' And Left(@F_Date, 7) < '2026-01') Then '2025' 
																	 When (Left(@F_Date, 7) >= '2026-01') Then '2026' End

	SELECT Stand_Year, Gubun, Price
	INTO #StandardPrice
	FROM APW_YJI_StandardPrice
	WHERE Stand_Year = @StandYear;

	CREATE NONCLUSTERED INDEX IX_StandardPrice_Gubun
		ON #StandardPrice (Gubun)
		INCLUDE (Stand_Year, Price);

	SELECT MasterID,
		   MAX(CASE WHEN iType = 1 THEN Names END) AS Manager
	INTO #ChargeManager
	FROM APW_Charge_IDX
	GROUP BY MasterID;

	CREATE UNIQUE CLUSTERED INDEX IX_ChargeManager_MasterID
		ON #ChargeManager (MasterID);

	SELECT UName 
	into #Tmp_Name
	FROM Seat_UserInfo 
	Where team_name in ('P1', 'J1', 'P2') and Udtel <> ''

	-- 월 데이터만 한 번 읽어 이후 11개 집계에서 재사용한다.
	SELECT WorkHour, WorkDate, GUBUN, Ugrade, Docid, Manager, writeman
	INTO #MonthWork
	FROM APW_IW_MANDAYWORK
	WHERE WorkDate >= @StartDate
	  AND WorkDate < @EndDate;

	CREATE NONCLUSTERED INDEX IX_MonthWork_Gubun_Ugrade
		ON #MonthWork (GUBUN, Ugrade)
		INCLUDE (WorkDate, Docid, Manager, writeman, WorkHour);

		--남직원 
	Select Convert(varchar(20) ,isnull(Round(Sum(a.WorkHour/60), 0), 0)) + ':' + RIGHT('00' + Convert(varchar(30), Convert(Numeric(18, 0), Sum(a.WorkHour)) % 60), 2) IM1_Time
		, (  isnull(Round(Sum(a.WorkHour), 0), 0) * a.Price)  IM1_Price	 
		, a.Manager
	Into #TmpIM1
	From
	(
		SELECT a.WorkHour
			, B.Price
				, d.Manager
		From #MonthWork A
			Left join #StandardPrice B ON B.Stand_Year =@StandYear
			Left join TMWCMN_USR_BAC_INFO c On a.writeman = c.EMP		
			Left join Apw_MasterEx d On a.Docid = d.Docid	
			Where
			A.workdate >= @StartDate And A.workdate < @EndDate 
			and A.GUBUN =1  
			And B.Gubun =1  
			And C.OFFICE_ID='10'
			And C.MyGroups <> 0
			And A.Ugrade in ('사원', '주임', '대리', '과장', '차장', '실장', '부장', '팀장')
			--And A.Manager = @SManager
			and D.Manager not like '%공(%'
			And isnull(c.Insertdate,'2000-01-01') <= a.workdate - 365 

			Union all

			Select a.WorkHour
				, B.Price
				, a.Manager
			From #MonthWork a
				Left join #StandardPrice B ON B.Stand_Year = @StandYear
				Left join TMWCMN_USR_BAC_INFO c On a.writeman = c.EMP	
			Where 1=1
				And a.GUBUN =1  
				And b.Gubun = 1
				And a.workdate >= @StartDate And a.workdate < @EndDate 
				And a.Docid = '기타'
				And C.MyGroups <> 0
				And isnull(a.Manager, '') <> ''
				And a.Manager not like '%공(%'
				And a.Manager <> '공통'
				And a.Ugrade in ('사원', '주임', '대리', '과장', '차장', '실장', '부장', '팀장')
				And isnull(c.Insertdate,'2000-01-01') <= a.workdate - 365 
	) a
	GROUP BY a.Price, a.Manager

	
	Select Convert(varchar(20) ,isnull(Round(Sum(a.WorkHour/60), 0), 0)) + ':' + RIGHT('00' + Convert(varchar(30), Convert(Numeric(18, 0), Sum(a.WorkHour)) % 60), 2) ISM_Time,
		(  isnull(Round(Sum(a.WorkHour), 0), 0) * a.Price) ISM_Price
		, a.Manager
	Into #TmpISM
	From
	(
		SELECT a.WorkHour
					, B.Price
				, d.Manager
		From #MonthWork A
			Left join #StandardPrice B ON B.Stand_Year = @StandYear
			Left join TMWCMN_USR_BAC_INFO c On a.writeman = c.EMP
			Left join Apw_MasterEx d On a.Docid = d.Docid	
		Where
			A.workdate >= @StartDate And A.workdate < @EndDate 
			and A.GUBUN = 1  
			And B.Gubun =2  
			And C.OFFICE_ID='10'
			And A.Ugrade='사원'		 		 --And A.Manager = @SManager
			And isnull(c.Insertdate,'2000-01-01') >= a.workdate - 365 
			and d.Manager not like '%공(%'

		Union All

		Select a.WorkHour
				, B.Price
				, a.Manager
		From #MonthWork a
			Left join #StandardPrice B ON B.Stand_Year = @StandYear
			Left join TMWCMN_USR_BAC_INFO c On a.writeman = c.EMP	
		Where 1=1
			And a.GUBUN =1  
			And b.Gubun = 2
			And A.workdate >= @StartDate And A.workdate < @EndDate 
			And a.Docid = '기타'
			And isnull(a.Manager, '') <> ''
			And a.Manager not like '%공(%'
			And a.Manager <> '공통'
			And a.Ugrade='사원'	
			And isnull(c.Insertdate,'2000-01-01') >= a.workdate - 365 
	) a
	GROUP BY a.Price, a.Manager
		
	---소속

	Select Convert(varchar(20) ,isnull(Round(Sum(a.WorkHour/60), 0), 0)) + ':' + RIGHT('00' + Convert(varchar(30), Convert(Numeric(18, 0), Sum(a.WorkHour)) % 60), 2) ISMP_Time,
			(  isnull(Round(Sum(a.WorkHour), 0), 0) * a.Price) ISMP_Price
			, a.Manager
	Into #TmpISMP
	From 		
	(
		SELECT a.WorkHour
				, B.Price
				, d.Manager
		From #MonthWork A
			Left join #StandardPrice B ON B.Stand_Year =@StandYear
			Left join TMWCMN_USR_BAC_INFO c On a.writeman = c.EMP
			Left join Apw_MasterEx d On a.Docid = d.Docid	
			Where
			workdate >= @StartDate And workdate < @EndDate 
			and A.GUBUN = 1  
			And B.Gubun =6  
			And C.OFFICE_ID='10'
			--And A.Manager = @SManager
			And a.Ugrade = '소속평가사'
			and d.Manager not like '%공(%'

			Union All

			Select a.WorkHour
					, B.Price
					, a.Manager
			From #MonthWork a
				Left join #StandardPrice B ON B.Stand_Year = @StandYear
				Left join TMWCMN_USR_BAC_INFO c On a.writeman = c.EMP	
			Where 1=1
				And a.GUBUN =1  
				And b.Gubun = 6
				And workdate >= @StartDate And workdate < @EndDate 
				And a.Docid = '기타'
				And isnull(a.Manager, '') <> ''
				And a.Manager not like '%공(%'
				And a.Manager <> '공통'
				And a.Ugrade = '소속평가사'
	) a
	GROUP BY a.Price, a.Manager

		 --수습평가사
		Select Convert(varchar(20) ,isnull(Round(Sum(a.WorkHour/60), 0), 0)) + ':' + RIGHT('00' + Convert(varchar(30), Convert(Numeric(18, 0), Sum(a.WorkHour)) % 60), 2) ISo_Time ,
				(  isnull(Round(Sum(a.WorkHour), 0), 0) * a.Price) ISo_Price
				, a.Manager
		Into #TmpISo
		  From 
		  (
			  SELECT a.WorkHour
						, B.Price
					, d.Manager
			From #MonthWork A
				Left join #StandardPrice B ON B.Stand_Year =@StandYear
				Left join TMWCMN_USR_BAC_INFO c On a.writeman = c.EMP
				Left join Apw_MasterEx d On a.Docid = d.Docid	
			 Where
			 workdate >= @StartDate And workdate < @EndDate 
			 and A.GUBUN = 1  
			 And C.OFFICE_ID='10'
			 And B.Gubun = 7
			 --And A.Manager = @SManager
			  and d.Manager not like '%공(%'
			 And a.Ugrade = '수습평가사'

			 Union All

			 SELECT a.WorkHour
						, B.Price
						, a.Manager
			From #MonthWork A
				Left join #StandardPrice B ON B.Stand_Year =@StandYear
				Left join TMWCMN_USR_BAC_INFO c On a.writeman = c.EMP
				Left join Apw_MasterEx d On a.Docid = d.Docid	
				Where
				workdate >= @StartDate And workdate < @EndDate 
					And a.GUBUN =1  
					And b.Gubun = 7
					And workdate >= @StartDate And workdate < @EndDate 
					And a.Docid = '기타'
					And isnull(a.Manager, '') <> ''
					And a.Manager not like '%공(%'
					And a.Manager <> '공통'
					And a.Ugrade = '수습평가사'
			) a
		  GROUP BY a.Price, a.Manager
		  --접수
	  
		  SELECT  Count(A.DocID) IJub_Cnt,
				Count(A.DocID) * b.Price IJub_Price
				, cia.Manager
		Into #TmpIJub
				From APW_MASTER A
				Left join #StandardPrice B ON B.Stand_Year =@StandYear
				Left join #ChargeManager cia On cia.MasterID = A.MasterID
		 Where
		 ReceiptDate >= @StartDate And ReceiptDate < @EndDate 
		 And B.Gubun =9  
		 --And Cia.Manager = @SManager
		  and cia.Manager not like '%공(%'
		 And SUBSTRING(a.docid, 9, 1) <>'6' 
		  GROUP BY B.Price, cia.Manager
		 --발송
		  SELECT  Count(A.DocID) IBal_Cnt,
				Count(A.DocID) * b.Price IBal_Price
				, cia.Manager
			Into #TmpIBal
				From APW_MASTER A
				Left join #StandardPrice B ON B.Stand_Year =@StandYear
			--	Left join APW_Process C ON A.MasterID  = C.MasterID
			 
				Left join #ChargeManager cia On cia.MasterID = A.MasterID
		 Where
		 A.SendDate >= @StartDate And A.SendDate < @EndDate 
		 And B.Gubun =10  
		 And A.Office = '10'
		 and cia.Manager not like '%공(%'
		-- And C.iType = 2 
		 --And C.Code = '10'
		 --And Cia.Manager = @SManager
		 And SUBSTRING(a.docid, 9, 1) <>'6' 
		  GROUP BY B.Price, cia.Manager

		  --심사
		 --  SELECT  Count(A.DocID) ISim_Cnt,
			--	Count(A.DocID) * b.Price   ISim_Price
			--	, d.Manager
			--Into #TmpISim
			--	From APW_simsa_form A
			--	Left join #StandardPrice B ON B.Stand_Year =@StandYear
			--	--Left join TMWCMN_USR_BAC_INFO c On a.writeman = c.EMP
			--	Left join Apw_MasterEx d On a.Docid = d.Docid	
		 --Where
		 --Convert(varchar(10), A.simsadate, 23) like  LEFT(@F_Date,7) + '%' 
		 --And B.Gubun =11  
		 ----And A.pung = @SManager 
		 --And d.Manager not like '공(%'
		 -- And d.Office = '10'
		 -- GROUP BY B.Price, a.pung, d.Manager
		 Select Count(*) ISim_Cnt
					, Count(*) * a.Price ISim_Price
					, a.Manager
			Into #TmpISim
			From
			(
				Select Distinct a.Docid
						, d.Manager
						, b.Price
				From APW_simsa_form a
					Left join #StandardPrice B ON B.Stand_Year =@StandYear
					Left join Apw_MasterEx d On a.Docid = d.Docid	
				Where 1=1
					And A.simsadate >= @StartDate And A.simsadate < @EndDate 
					And B.Gubun =11  
					And d.Manager not like '공(%'
					And d.Office = '10'
			) a
			GROUP BY a.Price, a.Manager

	--dl탁상접수
	if @StandYear >= '2025'
	begin
	
	--	Select ITSJub_Cnt ITSJub_Cnt_1
	--			, Sum(ITSJub_Price) ITSJub_Price_1
	--			, Manager
	--	Into #TmpITSJub_1
	--	From
	--	 (
			Select Count(A.MasterID) ITSJub_Cnt,
					Count(A.MasterID) * b.Price ITSJub_Price
					, d.Emp Manager
			Into #TmpITSJub_1
			From APW_TS_Master A
				Left join #StandardPrice B ON B.Stand_Year =@StandYear
				Left join TMWCMN_USR_BAC_INFO C ON A.Reg_Charge = C.USR_SEQ
				Left join TMWCMN_USR_BAC_INFO D ON A.Manager = D.USR_SEQ
			Where 1=1
				And Reg_DateTime >= @StartDate And Reg_DateTime < @EndDate 
				And C.APPRAISAL_FL = 1
				And B.Gubun = 8  
				And A.Office = '10'
				And Left(isnull(a.HFDocid, ''), 3) <> '400'
			Group by B.Price, d.EMP
	--	)
			
      --  Select ITSJub_Cnt ITSJub_Cnt_1
	--			, Sum(ITSJub_Price) ITSJub_Price_1
	--			, Manager
	--	Into #TmpITSJub_2
	--	From
	--	(
			Select Count(A.MasterID) ITSJub_Cnt,
					Count(A.MasterID) * b.Price ITSJub_Price
					, d.Emp Manager
			Into #TmpITSJub_2
			From APW_TS_Master A
				Left join #StandardPrice B ON B.Stand_Year =@StandYear
				Left join TMWCMN_USR_BAC_INFO C ON A.Reg_Charge = C.USR_SEQ
				Left join TMWCMN_USR_BAC_INFO D ON A.Manager = D.USR_SEQ
			Where 1=1
				And Reg_DateTime >= @StartDate And Reg_DateTime < @EndDate 
				And C.APPRAISAL_FL = 1
				And B.Gubun = 16
				And A.Office = '10'
				And Left(isnull(a.HFDocid, ''), 3) = '400'
			Group by B.Price, d.EMP
		--)

	end
	else if @StandYear < '2025'
	begin

	  SELECT    Count(A.MasterID) ITSJub_Cnt,
				Count(A.MasterID) * b.Price ITSJub_Price
				, d.Emp Manager
		Into #TmpITSJub
			From APW_TS_Master A
			Left join #StandardPrice B ON B.Stand_Year =@StandYear
			Left join TMWCMN_USR_BAC_INFO C ON A.Reg_Charge = C.USR_SEQ
			Left join TMWCMN_USR_BAC_INFO D ON A.Manager = D.USR_SEQ
		 Where
		 Reg_DateTime >= @StartDate And Reg_DateTime < @EndDate 
		 And C.APPRAISAL_FL = 1
		 And B.Gubun =8  
		 And A.Office = '10'
		 --And D.EMP = @SManager
		  GROUP BY B.Price, d.EMP
		  
	end

		  --탁상감정
	if @StandYear >= '2025'
	begin

		Select  Count(*) ITS_Cnt
				,  Count(*) * B.Price ITS_Price
				, a.Manager
		Into #TmpITS_1
		From
		--(
		--	Select Count(*) ITS_Cnt 
		--			, Count(*) * B.Price  ITS_Price
		--			, a.Manager
			--From 
			#MonthWork A
				Left join #StandardPrice B ON B.Stand_Year =@StandYear
				Left join APW_TS_Master c On a.Docid = c.MasterID
			Where 1=1
				And workdate >= @StartDate And workdate < @EndDate 
				And A.GUBUN =2  
				And B.Gubun =5  
				And Left(isnull(c.HFDocid, ''), 3) <> '400'
			Group by B.Price, a.Manager

		
		
		Select  Count(*) ITS_Cnt
				,  Count(*) * B.Price ITS_Price
				, a.Manager
		Into #TmpITS_2
		From
		--	Select Count(*) ITS_Cnt 
		--			, Count(*) * B.Price  ITS_Price
		--			, a.Manager
		--	From 
			#MonthWork A
				Left join #StandardPrice B ON B.Stand_Year =@StandYear
				Left join APW_TS_Master c On a.Docid = c.MasterID
			Where 1=1
				And workdate >= @StartDate And workdate < @EndDate 
				And A.GUBUN =2  
				And B.Gubun =17
				And Left(isnull(c.HFDocid, ''), 3) = '400'
			Group by B.Price, a.Manager
		--) a
		--Group by a.ITS_Cnt, a.Manager

	end
	Else if @StandYear < '2025'
	Begin

		SELECT  Count(*) ITS_Cnt ,
					Count(*) * B.Price  ITS_Price
					, a.Manager
		Into #TmpITS
			From #MonthWork A
			Left join #StandardPrice B ON B.Stand_Year =@StandYear
		Where
			workdate >= @StartDate And workdate < @EndDate 
			and A.GUBUN =2  
			And B.Gubun =5  
			--And A.Manager = @SManager
		GROUP BY B.Price, a.Manager

	End

		  --비지오
		SELECT  Count(A.Docid) IVISI_Cnt
				 , Count(A.Docid) * B.Price IVISI_Price 
				 , d.Manager
		Into #TmpIVISI
		From Apw_VIsio A
			Left join #StandardPrice B ON B.Stand_Year =@StandYear
         	Left join TMWCMN_USR_BAC_INFO c On a.Emp_Dam = c.EMP
			Left join Apw_MasterEx d On a.Docid = d.Docid	
		 Where
		 A.Update_Date >= @StartDate And A.Update_Date < @EndDate 
		 and A.GUBUN ='VISIO'
		 And B.Gubun =3  
		 And C.OFFICE_ID='10'
		  and d.Manager not like '%공(%'
		 --And A.Manager = @SManager
		 And isnull(c.Insertdate,'2000-01-01') <= a.Update_Date - 365 
		  And d.Office = '10'
		  And a.Gubun = 'VISIO'
		  and c.RTRM_FL = 0
		  GROUP BY B.Price, d.Manager

		--수습비지오
			SELECT Count(A.Docid) ISVISI_Cnt,
				  Count(A.Docid) * B.Price ISVISI_Price
				 , d.Manager
			Into #TmpISVISI
			From Apw_VIsio A
				Left join #StandardPrice B ON B.Stand_Year =@StandYear
         		Left join TMWCMN_USR_BAC_INFO c On a.Emp_Dam = c.EMP
				Left join Apw_MasterEx d On a.Docid = d.Docid	
			 Where
			 A.Update_Date >= @StartDate And A.Update_Date < @EndDate 
			 And C.OFFICE_ID='10'
			 and A.GUBUN ='VISIO'
			 And B.Gubun =4  
			  and d.Manager not like '%공(%'
			   And d.Office = '10'
			 --And A.Manager = @SManager
			 And isnull(c.Insertdate,'2000-01-01') >= a.Update_Date - 365 
			 And a.Emp_Dam <> '이은선'
			 And a.Gubun = 'VISIO'
			 and c.RTRM_FL = 0
			  GROUP BY B.Price, d.Manager

		 ----시조위
		  SELECT Count(A.DocID) ISIJO_Cnt,
				Count(A.DocID) * b.Price ISIJO_Price
				, C.Manager
			Into #TmpISIJO
				From APW_IW_SIJO A
				Left join #StandardPrice B ON B.Stand_Year =@StandYear
		        Left join APW_Masterex C ON A.docid =  C.DocID
				 Where
				 simsadate >= @StartDate And simsadate < @EndDate  
				 And B.Gubun =12  
				 And C.Manager not like '공(%'
				  And C.Office = '10'
				 --And A.pung = @SManager 
				  GROUP BY B.Price, C.Manager
		--검산
		
			Select 0 ICHK_Cnt
				   , 0.0 ICHK_Price
				   , '' Manager
			Into #TmpICHK



			--SELECT Count(*) ICHK_Cnt,
			--	   COUNT(*) * B.Price ICHK_Price
			--	  , '유영조' Manager
			--Into #TmpICHK
		 --  From Apw_Master a
			--			Left join #StandardPrice b On b.Stand_Year = @StandYear
			--		Where 1=1
			--			And  Convert(varchar(10), SendDate, 23) like  LEFT(@F_Date,7) + '%' 
			--			--And A.Office = '10'
			--			And CustName like '%신한은행%'-- or CustName like '%국민은행%' or CustName like '%기업은행%' or CustName like '%우리은행%')
			--			And b.Gubun = 15
			--		Group by  b.Price
	  ---약식
		SELECT Count(*) IYAK_Cnt,
				  COUNT(*) * B.Price IYAK_Price
				   , a.Manager
			Into #TmpIYAK
		   From APW_IW_YACKMASTER a
						Left join #StandardPrice b On b.Stand_Year = @StandYear
					Left join APW_MASTER C ON A.Docid= C.DocID
					Where 1=1
						And  Writedate >= @StartDate And Writedate < @EndDate 
						And C.Office = '10'
						And b.Gubun = 13
						--and A.Manager= @SManager
					Group by  b.Price , a.Manager


	--------- 국민약식

	if @StandYear >= '2025'
	Begin

		Select '김형수' Manager
				, Count(*) KB_Cnt_1
				, Count(*) * a.Price KB_Cnt_Price_1
		Into #Tmp_KB_1
		From
		(
			Select DIStinct a.RequestNM
					, d.Price
			From Bank_kb_master a
				Inner join Bank_KB_apt b On a.requestNM = b.requestNM
				Inner join Bank_KB_Header c On a.KB_MasterID = c.KB_MasterID
				Left join #StandardPrice d On d.Stand_Year = @StandYear
			where 1=1
				And b.appgubun = '2'
				And a.OfficeID = '10'
				And Left(Convert(Char(10), c.Apptime ,126), 4) + '-' + Substring(Convert(Char(10), c.Apptime ,126), 5, 2) like Left(@F_Date, 7) + '%'
				And d.Gubun = 18
				And a.WorkResult = 6
		) a
		Group by a.Price

	End
	Else if @StandYear < '2025'
	Begin

		Select '김형수' Manager
				, Count(*) KB_Cnt
				, Count(*) * a.Price KB_Cnt_Price
		Into #Tmp_KB
		From
		(
			Select DIStinct a.RequestNM
					, d.Price
			From Bank_kb_master a
				Inner join Bank_KB_apt b On a.requestNM = b.requestNM
				Inner join Bank_KB_Header c On a.KB_MasterID = c.KB_MasterID
				Left join #StandardPrice d On d.Stand_Year = @StandYear
			where 1=1
				And b.appgubun = '2'
				And a.OfficeID = '10'
				And Left(Convert(Char(10), c.Apptime ,126), 4) + '-' + Substring(Convert(Char(10), c.Apptime ,126), 5, 2) like Left(@F_Date, 7) + '%'
				And d.Gubun = 13
				And a.WorkResult = 6
		) a
		Group by a.Price

	End

		-------------------------------


      ---협회심사비 
	    Select Count(*) IHubSIM_Cnt,
				Sum(Floor(((A.수수료합계-(A.여비 + A.물건조사비+ A.토지조사비+ A.특별용역비 + A.공부발급비 +A.기타실비)) * 0.008)/10)*10) AS IHubSIMPrice
				, A.Manager
		Into #TmpIHubSim
		From
		(
			Select Distinct A.수수료합계
						, A.여비
						, A.물건조사비
						, A.토지조사비
						, A.특별용역비 
						, A.공부발급비 
						, A.기타실비
						, A.Manager
					From APW_MASTEREX A
					--Left join #StandardPrice B ON B.Stand_Year ='2022'
					Left join ( Select Masterid , Ratio From APW_Booking a Inner join TMWCMN_USR_BAC_INFO b On a.Manager = b.USR_SEQ
								Where 1=1 And b.Emp = @Manager ) bo On A.MasterID = bo.MasterID
					Left join (Select Masterid , Sum(Ratio) T_Ratio From APW_Booking a Group by MasterID) Sbo On A.MasterID = Sbo.MasterID
					Left join APW_Process P on A.MasterID = P.MasterID 
				 Where
				 P.ISSUEDATE >= @StartDate And P.ISSUEDATE < @EndDate 
				-- And B.Gubun =9  
				 And A.Manager like '%'+@Manager+'%'
				 and A.Manager not like '%공(%'
				 And SUBSTRING(A.docid, 9, 1) <>'6'
				 And P.Code = '0C'
			) a
			GROUP BY A.Manager

		-- 감정서경비(X)

		Select Count(*) GamX_Cnt
				, Sum(a.Price) GamX_Price
				, a.Manager
		Into #TmpGamX
		From
		(
			Select '' docid
					, Price
					, Manager
			From apw_iw_bonus_DocCost
			Where 1=1
			   And isnull(Docid, '') = ''
				--And Manager like '%' + @Manager + '%'
				And JunpyoDate >= @StartDate And JunpyoDate < @EndDate
				And Gubun  in ('세금과공과' ,'도서인쇄비')
				and Bigo not like '%자동차세%'

		) a
		Group by a.Manager


		-- 감정서경비(O)
		Select Count(*) GamO_Cnt
				, Sum(a.Price) GamO_Price
				, b.Manager
		Into #TmpGamO
		From apw_iw_bonus_DocCost a
			Left join Apw_MasterEx b On a.Docid = b.Docid
		Where 1=1
			 And isnull(a.Docid, '') <> ''
			And a.JunpyoDate >= @StartDate And a.JunpyoDate < @EndDate
			And a.Gubun  in ('세금과공과' ,'도서인쇄비')		
		Group by b.Manager

	
	-- HUG탁상 접수
	Select '안창덕' Manager
			, Count(*) HugJup_Cnt
			, Count(*) * a.Price HugJup_Price
	Into #TmpHugJup
	From
	(
		Select distinct Docid
				, b.Price
		From Hug_info a
			Left join #StandardPrice b On b.Stand_Year = @StandYear
		Where 1=1
			And a.ReceiptDate >= @StartDate And a.ReceiptDate < @EndDate
			And b.Gubun = '19'
	) a
	Group by a.Price

	-- HUG탁상 감정
	Select '안창덕' Manager
			, Count(*) HugGam_Cnt
			, Count(*) * a.Price HugGam_Price
	Into #TmpHugGam
	From
	(
		Select distinct Docid
				, b.Price
		From Hug_info a
			Left join #StandardPrice b On b.Stand_Year = @StandYear
		Where 1=1
			And a.Complete_Date >= @StartDate And a.Complete_Date < @EndDate
			And b.Gubun = '20'
	) a
	Group by a.Price


		if (@Manager = '')
		begin

			if @StandYear >= '2025'
			Begin

				  Select a.Uname Manager
					, isnull(b.IM1_Time, 0) M1Time
					, isnull(b.IM1_Price, 0) M1Price
					, isnull(c.ISM_Time, 0) SMTime
					, isnull(c.ISM_Price, 0) SMPrice
					, isnull(d.ISMP_Time, 0) SoPTime
					, isnull(d.ISMP_Price, 0) SoPPrice
					, isnull(e.ISo_Time, 0) SuPTime
					, isnull(e.ISo_Price, 0) SuPrice
					, isnull(f.IJub_Cnt, 0) JubC
					, isnull(f.IJub_Price, 0) JubP
					, isnull(g.IBal_Cnt, 0) BalC
					, isnull(g.IBal_Price, 0) BalP
					, isnull(h.ISim_Cnt, 0) SimC
					, isnull(h.ISim_Price, 0) SimP
					, isnull(t1.ITSJub_Cnt, 0) TSJubC
					, isnull(t1.ITSJub_Price, 0)  TSJubP
					, isnull(t2.ITSJub_Cnt, 0) TSJubC2
					, isnull(t2.ITSJub_Price, 0)  TSJubP2
					, isnull(u1.ITS_Cnt, 0) TSC
					, isnull(u1.ITS_Price, 0) TSP
					, isnull(u2.ITS_Cnt, 0) TSC2
					, isnull(u2.ITS_Price, 0) TSP2
					, isnull(k.IVISI_Cnt, 0) VISIC
					, isnull(k.IVISI_Price, 0) VISIP
					, isnull(l.ISVISI_Cnt, 0) SVISIC
					, isnull(l.ISVISI_Price, 0) SVISIP
					, isnull(m.ISIJO_Cnt, 0) SIJOC
					, isnull(m.ISIJO_Price, 0) SIJOP
					, isnull(n.ICHK_Cnt, 0) CHKC
					, isnull(n.ICHK_Price, 0) CHKP
					, isnull(o.IYAK_Cnt, 0)  YAKC
					, isnull(o.IYAK_Price, 0)  YAKP
					, isnull(p.IHubSIM_Cnt, 0) HSIMC
					, isnull(p.IHubSIMPrice, 0) HSIMP
					, isnull(q.GamX_Cnt, 0) GamX_Cnt
					, isnull(q.GamX_Price, 0) GamX_Price
					, isnull(r.GamO_Cnt, 0) GamO_Cnt
					, isnull(r.GamO_Price, 0) GamO_Price
					, isnull(v.KB_Cnt_1, 0)  KBYAKC
					, isnull(v.KB_Cnt_Price_1, 0) KBYAKP
					, isnull(t.HugJup_Cnt, 0) HugJup_Cnt
					, isnull(t.HugJup_Price, 0) HugJup_Price
					, isnull(u.HugGam_Cnt, 0) HugGam_Cnt
					, isnull(u.HugGam_Price, 0) HugGam_Price
			From #Tmp_Name a
				Left join #TmpIM1 b	on a.Uname = b.Manager
				Left join #TmpISM c	on a.Uname = c.Manager
				Left join #TmpISMP d	on a.Uname = d.Manager
				Left join #TmpISo e		on a.Uname = e.Manager
				Left join #TmpIJub f	on a.Uname = f.Manager
				Left join #TmpIBal g	on a.Uname = g.Manager
				Left join #TmpISim h	on a.Uname = h.Manager
				Left join #TmpIVISI k	on a.Uname = k.Manager
				Left join #TmpISVISI l	on a.Uname = l.Manager
				Left join #TmpISIJO m	on a.Uname = m.Manager
				Left join #TmpICHK n 	on a.Uname = n.Manager
				Left join #TmpIYAK o	on a.Uname = o.Manager
				Left join #TmpIHubSim p on a.Uname = p.Manager
				Left join #TmpGamX q On a.Uname = q.Manager
				Left join #TmpGamO r On a.Uname = r.Manager
				Left join #TmpITSJub_1 t1 On a.Uname = t1.Manager
				Left join #TmpITSJub_2 t2  On a.Uname = t2.Manager
				Left join #TmpITS_1 u1 On a.Uname = u1.Manager
				Left join #TmpITS_2 u2 On a.Uname = u2.Manager
				Left join #Tmp_KB_1 v On a.Uname = v.Manager
				Left join #TmpHugJup t On a.Uname = t.Manager
				Left join #TmpHugGam	 u On a.Uname = u.Manager
			order by Uname

			End
			Else if @StandYear < '2025'
			Begin

				Select a.Uname Manager
						, isnull(b.IM1_Time, 0) M1Time
						, isnull(b.IM1_Price, 0) M1Price
						, isnull(c.ISM_Time, 0) SMTime
						, isnull(c.ISM_Price, 0) SMPrice
						, isnull(d.ISMP_Time, 0) SoPTime
						, isnull(d.ISMP_Price, 0) SoPPrice
						, isnull(e.ISo_Time, 0) SuPTime
						, isnull(e.ISo_Price, 0) SuPrice
						, isnull(f.IJub_Cnt, 0) JubC
						, isnull(f.IJub_Price, 0) JubP
						, isnull(g.IBal_Cnt, 0) BalC
						, isnull(g.IBal_Price, 0) BalP
						, isnull(h.ISim_Cnt, 0) SimC
						, isnull(h.ISim_Price, 0) SimP
						, isnull(i.ITSJub_Cnt, 0) TSJubC
						, isnull(i.ITSJub_Price, 0) TSJubP
						, 0 TSJubC2
						, Convert(money, 0) TSJubP2
						, isnull(j.ITS_Cnt, 0) TSC
						, isnull(j.ITS_Price, 0) TSP
						, 0 TSC2
						, Convert(money, 0) TSP2
						, isnull(k.IVISI_Cnt, 0) VISIC
						, isnull(k.IVISI_Price, 0) VISIP
						, isnull(l.ISVISI_Cnt, 0) SVISIC
						, isnull(l.ISVISI_Price, 0) SVISIP
						, isnull(m.ISIJO_Cnt, 0) SIJOC
						, isnull(m.ISIJO_Price, 0) SIJOP
						, isnull(n.ICHK_Cnt, 0) CHKC
						, isnull(n.ICHK_Price, 0) CHKP
						, isnull(o.IYAK_Cnt, 0)  YAKC
						, isnull(o.IYAK_Price, 0)  YAKP
                        , isnull(s.KB_Cnt, 0) KBYAKC
					    , isnull(s.KB_Cnt_Price, 0)  KBYAKP
						, isnull(p.IHubSIM_Cnt, 0) HSIMC
						, isnull(p.IHubSIMPrice, 0) HSIMP
						, isnull(q.GamX_Cnt, 0) GamX_Cnt
						, isnull(q.GamX_Price, 0) GamX_Price
						, isnull(r.GamO_Cnt, 0) GamO_Cnt
						, isnull(r.GamO_Price, 0) GamO_Price
						, 0 HugJup_Cnt
						, 0 HugJup_Price
						, 0 HugGam_Cnt
						, 0 HugGam_Price
				From #Tmp_Name a
					Left join #TmpIM1 b	on a.Uname = b.Manager
					Left join #TmpISM c	on a.Uname = c.Manager
					Left join #TmpISMP d	on a.Uname = d.Manager
					Left join #TmpISo e		on a.Uname = e.Manager
					Left join #TmpIJub f	on a.Uname = f.Manager
					Left join #TmpIBal g	on a.Uname = g.Manager
					Left join #TmpISim h	on a.Uname = h.Manager
					Left join #TmpITSJub i	on a.Uname = i.Manager
					Left join #TmpITS j		on a.Uname = j.Manager
					Left join #TmpIVISI k	on a.Uname = k.Manager
					Left join #TmpISVISI l	on a.Uname = l.Manager
					Left join #TmpISIJO m	on a.Uname = m.Manager
					Left join #TmpICHK n 	on a.Uname = n.Manager
					Left join #TmpIYAK o	on a.Uname = o.Manager
					Left join #TmpIHubSim p on a.Uname = p.Manager
					Left join #TmpGamX q On a.Uname = q.Manager
					Left join #TmpGamO r On a.Uname = r.Manager
					Left join #Tmp_KB s On a.Uname = s.Manager
					order by Uname

			End
		
		end
		else
		begin
		
			if @StandYear >= '2025'
			Begin

				  Select a.Uname Manager
					, isnull(b.IM1_Time, 0) M1Time
					, isnull(b.IM1_Price, 0) M1Price
					, isnull(c.ISM_Time, 0) SMTime
					, isnull(c.ISM_Price, 0) SMPrice
					, isnull(d.ISMP_Time, 0) SoPTime
					, isnull(d.ISMP_Price, 0) SoPPrice
					, isnull(e.ISo_Time, 0) SuPTime
					, isnull(e.ISo_Price, 0) SuPrice
					, isnull(f.IJub_Cnt, 0) JubC
					, isnull(f.IJub_Price, 0) JubP
					, isnull(g.IBal_Cnt, 0) BalC
					, isnull(g.IBal_Price, 0) BalP
					, isnull(h.ISim_Cnt, 0) SimC
					, isnull(h.ISim_Price, 0) SimP
					, isnull(t1.ITSJub_Cnt, 0) TSJubC
					, isnull(t1.ITSJub_Price, 0)  TSJubP
					, isnull(t2.ITSJub_Cnt, 0) TSJubC2
					, isnull(t2.ITSJub_Price, 0)  TSJubP2
					, isnull(u1.ITS_Cnt, 0) TSC
					, isnull(u1.ITS_Price, 0) TSP
					, isnull(u2.ITS_Cnt, 0) TSC2
					, isnull(u2.ITS_Price, 0) TSP2
					, isnull(k.IVISI_Cnt, 0) VISIC
					, isnull(k.IVISI_Price, 0) VISIP
					, isnull(l.ISVISI_Cnt, 0) SVISIC
					, isnull(l.ISVISI_Price, 0) SVISIP
					, isnull(m.ISIJO_Cnt, 0) SIJOC
					, isnull(m.ISIJO_Price, 0) SIJOP
					, isnull(n.ICHK_Cnt, 0) CHKC
					, isnull(n.ICHK_Price, 0) CHKP
					--, isnull(o.IYAK_Cnt, 0) + isnull(v.KB_Cnt_1, 0) YAKC
					--, isnull(o.IYAK_Price, 0) + isnull(v.KB_Cnt_Price_1, 0) YAKP
					, isnull(o.IYAK_Cnt, 0) YAKC
					, isnull(o.IYAK_Price, 0) YAKP
					, isnull(p.IHubSIM_Cnt, 0) HSIMC
					, isnull(p.IHubSIMPrice, 0) HSIMP
					, isnull(q.GamX_Cnt, 0) GamX_Cnt
					, isnull(q.GamX_Price, 0) GamX_Price
					, isnull(r.GamO_Cnt, 0) GamO_Cnt
					, isnull(r.GamO_Price, 0) GamO_Price
					, isnull(v.KB_Cnt_1, 0)  KBYAKC
					, isnull(v.KB_Cnt_Price_1, 0) KBYAKP
					, isnull(t.HugJup_Cnt, 0) HugJup_Cnt
					, isnull(t.HugJup_Price, 0) HugJup_Price
					, isnull(u.HugGam_Cnt, 0) HugGam_Cnt
					, isnull(u.HugGam_Price, 0) HugGam_Price
			From #Tmp_Name a
				Left join #TmpIM1 b	on a.Uname = b.Manager
				Left join #TmpISM c	on a.Uname = c.Manager
				Left join #TmpISMP d	on a.Uname = d.Manager
				Left join #TmpISo e		on a.Uname = e.Manager
				Left join #TmpIJub f	on a.Uname = f.Manager
				Left join #TmpIBal g	on a.Uname = g.Manager
				Left join #TmpISim h	on a.Uname = h.Manager
				Left join #TmpIVISI k	on a.Uname = k.Manager
				Left join #TmpISVISI l	on a.Uname = l.Manager
				Left join #TmpISIJO m	on a.Uname = m.Manager
				Left join #TmpICHK n 	on a.Uname = n.Manager
				Left join #TmpIYAK o	on a.Uname = o.Manager
				Left join #TmpIHubSim p on a.Uname = p.Manager
				Left join #TmpGamX q On a.Uname = q.Manager
				Left join #TmpGamO r On a.Uname = r.Manager
				Left join #TmpITSJub_1 t1 On a.Uname = t1.Manager
				Left join #TmpITSJub_2 t2  On a.Uname = t2.Manager
				Left join #TmpITS_1 u1 On a.Uname = u1.Manager
				Left join #TmpITS_2 u2 On a.Uname = u2.Manager
				Left join #Tmp_KB_1 v On a.Uname = v.Manager
				Left join #TmpHugJup t On a.Uname = t.Manager
				Left join #TmpHugGam	 u On a.Uname = u.Manager
			Where a.Uname = @Manager
			order by Uname

			End
			Else if @StandYear < '2025'
			Begin

				Select a.Uname Manager
						, isnull(b.IM1_Time, 0) M1Time
						, isnull(b.IM1_Price, 0) M1Price
						, isnull(c.ISM_Time, 0) SMTime
						, isnull(c.ISM_Price, 0) SMPrice
						, isnull(d.ISMP_Time, 0) SoPTime
						, isnull(d.ISMP_Price, 0) SoPPrice
						, isnull(e.ISo_Time, 0) SuPTime
						, isnull(e.ISo_Price, 0) SuPrice
						, isnull(f.IJub_Cnt, 0) JubC
						, isnull(f.IJub_Price, 0) JubP
						, isnull(g.IBal_Cnt, 0) BalC
						, isnull(g.IBal_Price, 0) BalP
						, isnull(h.ISim_Cnt, 0) SimC
						, isnull(h.ISim_Price, 0) SimP
						, isnull(i.ITSJub_Cnt, 0) TSJubC
						, isnull(i.ITSJub_Price, 0) TSJubP
						, 0 TSJubC2
						, Convert(money, 0) TSJubP2
						, isnull(j.ITS_Cnt, 0) TSC
						, isnull(j.ITS_Price, 0) TSP
						, 0 TSC2
						, Convert(money, 0) TSP2
						, isnull(k.IVISI_Cnt, 0) VISIC
						, isnull(k.IVISI_Price, 0) VISIP
						, isnull(l.ISVISI_Cnt, 0) SVISIC
						, isnull(l.ISVISI_Price, 0) SVISIP
						, isnull(m.ISIJO_Cnt, 0) SIJOC
						, isnull(m.ISIJO_Price, 0) SIJOP
						, isnull(n.ICHK_Cnt, 0) CHKC
						, isnull(n.ICHK_Price, 0) CHKP
						, isnull(o.IYAK_Cnt, 0)  YAKC
						, isnull(o.IYAK_Price, 0)  YAKP
						, isnull(p.IHubSIM_Cnt, 0) HSIMC
						, isnull(p.IHubSIMPrice, 0) HSIMP
						, isnull(q.GamX_Cnt, 0) GamX_Cnt
						, isnull(q.GamX_Price, 0) GamX_Price
						, isnull(r.GamO_Cnt, 0) GamO_Cnt
						, isnull(r.GamO_Price, 0) GamO_Price
						, isnull(s.KB_Cnt, 0) KBYAKC
						, isnull(s.KB_Cnt_Price, 0) KBYAKP
						, 0 HugJup_Cnt
						, 0 HugJup_Price
						, 0 HugGam_Cnt
						, 0 HugGam_Price
				From #Tmp_Name a
					Left join #TmpIM1 b	on a.Uname = b.Manager
					Left join #TmpISM c	on a.Uname = c.Manager
					Left join #TmpISMP d	on a.Uname = d.Manager
					Left join #TmpISo e		on a.Uname = e.Manager
					Left join #TmpIJub f	on a.Uname = f.Manager
					Left join #TmpIBal g	on a.Uname = g.Manager
					Left join #TmpISim h	on a.Uname = h.Manager
					Left join #TmpITSJub i	on a.Uname = i.Manager
					Left join #TmpITS j		on a.Uname = j.Manager
					Left join #TmpIVISI k	on a.Uname = k.Manager
					Left join #TmpISVISI l	on a.Uname = l.Manager
					Left join #TmpISIJO m	on a.Uname = m.Manager
					Left join #TmpICHK n 	on a.Uname = n.Manager
					Left join #TmpIYAK o	on a.Uname = o.Manager
					Left join #TmpIHubSim p on a.Uname = p.Manager
					Left join #TmpGamX q On a.Uname = q.Manager
					Left join #TmpGamO r On a.Uname = r.Manager
					Left join #Tmp_KB s On a.Uname = s.Manager
					Where a.Uname = @Manager
					order by Uname

			End

		end
      

End
