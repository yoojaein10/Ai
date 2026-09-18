
CREATE Procedure [dbo].[SP_IW_S_TaskStats_MonPung]
	
	@F_Date		Varchar(10), 		
	@Manager	Varchar(10)= ''

AS
Begin
    Declare @TB_Result Table(iNo int identity(1,1) , Docid varchar(20) , Gubun varchar(20),Charger varchar(20) , Manager varchar(20) , Workdate varchar(10), Time varchar(10), 
	                         CustName varchar(250) , Address varchar(300),  Beprice money, AFPrice money )
	Declare @StandYear varchar(20), @Min int , @Max int , @ManagerSeq int
    delete from @TB_Result
	SELECT  @ManagerSeq = USR_SEQ  FROM TMWCMN_USR_BAC_INFO Where EMP = @Manager and OFFICE_ID = '10'

	SELECT @StandYear = Case When Left(@F_Date, 7) < '2020-07' Then  Left(@F_Date, 7)
																	 When (Left(@F_Date, 7) >= '2020-07' And Left(@F_Date, 7) < '2022-07' ) Then '2020-1'
																	 When (Left(@F_Date, 7) >= '2022-07' And Left(@F_Date, 7) < '2023-07' ) Then '2022' 
																	 When (Left(@F_Date, 7) >= '2023-07' And Left(@F_Date, 7) < '2024-01') Then '2023' 
																	 When (Left(@F_Date, 7) >= '2024-01' And Left(@F_Date, 7) < '2025-01') Then '2024' 
																	 When (Left(@F_Date, 7) >= '2025-01' And Left(@F_Date, 7) < '2026-01') Then '2025' 
																	 When (Left(@F_Date, 7) >= '2026-01') Then '2026' End
	
		 --남직원 
		 INSERT INTO @TB_Result (Docid , Gubun,  Charger, Manager  , Workdate , Time , CustName  , Address ,Beprice, AFPrice)
		 (SELECT A.Docid , B.Bigo, A.writeman, D.Manager, Convert(varchar(10), A.WorkDate, 23) , A.showhour, D.CustName , D.Address,
		 Round(A.workhour * B.Price,0)  , round((A.workhour * B.Price) *(Convert(float , bo.Ratio) / Sbo.T_Ratio),0) 
		        From APW_IW_MANDAYWORK a
         Left join APW_YJI_StandardPrice b On b.Stand_Year = @StandYear
         Left join TMWCMN_USR_BAC_INFO c On a.writeman = c.EMP
         Left join APW_Masterex D ON A.Docid = D.DocID 
	     Left join ( Select Masterid , Ratio From APW_Booking a Inner join TMWCMN_USR_BAC_INFO b On a.Manager = b.USR_SEQ
               Where 1=1 And b.Emp = @Manager ) bo On D.MasterID = bo.MasterID
         Left join (Select Masterid , Sum(Ratio) T_Ratio From APW_Booking a Group by MasterID) Sbo On D.MasterID = Sbo.MasterID
			Where
			 Convert(varchar(7), A.workdate, 23) like  LEFT(@F_Date,7) + '%' 
			 and A.GUBUN =1  
			 And B.Gubun =1  
			 And C.OFFICE_ID='10'
			 And C.MyGroups <> 0
			 And A.Ugrade in ('사원', '주임', '대리', '과장', '차장', '실장', '부장', '팀장')
			 And D.Manager like '%'+@Manager+'%'
			 And D.Manager not like '%공(%'
			 And isnull(c.Insertdate,'2000-01-01') <= a.workdate - 365
			 
			 Union All

			 Select a.Docid
					, b.Bigo
					, a.writeman
					, a.Manager
					, Convert(varchar(10), a.WorkDate, 23) 
					, a.showhour
					, ''
					, ''
					, Round(a.workhour * b.Price,0)
					, Round(a.workhour * b.Price,0)
			From APW_IW_MANDAYWORK a
				Left join APW_YJI_StandardPrice B ON B.Stand_Year = @StandYear
				Left join TMWCMN_USR_BAC_INFO c On a.writeman = c.EMP	
			Where 1=1
				And a.GUBUN =1  
				And b.Gubun = 1
				And Convert(varchar(7), a.workdate, 23) like  LEFT(@F_Date,7) + '%' 
				And a.Docid = '기타'
				And isnull(a.Manager, '') <> ''
				And a.Manager not like '%공(%'
				And a.Manager <> '공통'
				And C.MyGroups <> 0
				And a.Ugrade in ('사원', '주임', '대리', '과장', '차장', '실장', '부장', '팀장')
				And isnull(c.Insertdate,'2000-01-01') <= a.workdate - 365 
				And a.Manager like '%'+@Manager+'%'
			 
			  )

		 --수습남
		 INSERT INTO @TB_Result (Docid , Gubun,  Charger, Manager  , Workdate , Time , CustName  , Address ,Beprice, AFPrice)
		 (SELECT A.Docid , B.Bigo, A.writeman, D.Manager, Convert(varchar(10), A.WorkDate, 23) , A.showhour, D.CustName , D.Address,
		 Round(A.workhour * B.Price,0)  , round((A.workhour * B.Price) *(Convert(float , bo.Ratio) / Sbo.T_Ratio),0) 
		        From APW_IW_MANDAYWORK a
         Left join APW_YJI_StandardPrice b On b.Stand_Year = @StandYear
         Left join TMWCMN_USR_BAC_INFO c On a.writeman = c.EMP
         Left join APW_Masterex D ON A.Docid = D.DocID 
	     Left join ( Select Masterid , Ratio From APW_Booking a Inner join TMWCMN_USR_BAC_INFO b On a.Manager = b.USR_SEQ
               Where 1=1 And b.Emp = @Manager ) bo On D.MasterID = bo.MasterID
         Left join (Select Masterid , Sum(Ratio) T_Ratio From APW_Booking a Group by MasterID) Sbo On D.MasterID = Sbo.MasterID
			Where
			 Convert(varchar(7), A.workdate, 23) like  LEFT(@F_Date,7) + '%' 
			 and A.GUBUN =1  
			 And B.Gubun =2 
			 And C.OFFICE_ID='10'
			 And C.MyGroups <> 0
			 And A.Ugrade='사원'		 		 
			 And D.Manager like '%'+@Manager+'%'
			 And D.Manager not like '%공(%'
			 And isnull(c.Insertdate,'2000-01-01') >= a.workdate - 365
			 
			Union All

			 Select a.Docid
					, b.Bigo
					, a.writeman
					, a.Manager
					, Convert(varchar(10), a.WorkDate, 23) 
					, a.showhour
					, ''
					, ''
					, Round(a.workhour * b.Price,0)
					, Round(a.workhour * b.Price,0)
			From APW_IW_MANDAYWORK a
				Left join APW_YJI_StandardPrice B ON B.Stand_Year = @StandYear
				Left join TMWCMN_USR_BAC_INFO c On a.writeman = c.EMP	
			Where 1=1
				And a.GUBUN =1  
				And b.Gubun = 2
				And Convert(varchar(10), A.workdate, 23) like  LEFT(@F_Date,7) + '%' 
				And a.Docid = '기타'
				And C.MyGroups <> 0
				And isnull(a.Manager, '') <> ''
				And a.Manager not like '%공(%'
				And a.Manager <> '공통'
				And a.Ugrade='사원'	
				And isnull(c.Insertdate,'2000-01-01') >= a.workdate - 365 		
				And a.Manager like '%'+@Manager+'%'	 
			  )
			 
		
		---소속
		 INSERT INTO @TB_Result (Docid , Gubun,  Charger, Manager  , Workdate , Time , CustName  , Address ,Beprice, AFPrice)
		 (SELECT A.Docid , B.Bigo, A.writeman, D.Manager, Convert(varchar(10), A.WorkDate, 23) , A.showhour, D.CustName , D.Address,
		 Round(A.workhour * B.Price,0)  , round((A.workhour * B.Price) *(Convert(float , bo.Ratio) / Sbo.T_Ratio),0) 
		        From APW_IW_MANDAYWORK a
         Left join APW_YJI_StandardPrice b On b.Stand_Year = @StandYear
         Left join TMWCMN_USR_BAC_INFO c On a.writeman = c.EMP
         Left join APW_Masterex D ON A.Docid = D.DocID 
	     Left join ( Select Masterid , Ratio From APW_Booking a Inner join TMWCMN_USR_BAC_INFO b On a.Manager = b.USR_SEQ
               Where 1=1 And b.Emp = @Manager ) bo On D.MasterID = bo.MasterID
         Left join (Select Masterid , Sum(Ratio) T_Ratio From APW_Booking a Group by MasterID) Sbo On D.MasterID = Sbo.MasterID
			Where
			 Convert(varchar(7), A.workdate, 23) like  LEFT(@F_Date,7) + '%' 
			 and A.GUBUN =1  
			 And B.Gubun =6  
			 And C.OFFICE_ID='10'
		     And D.Manager like '%'+@Manager+'%'
			 And D.Manager not like '%공(%'
		     And a.Ugrade = '소속평가사'
			
		Union All

		Select a.Docid
				, b.Bigo
				, a.writeman
				, a.Manager
				, Convert(varchar(10), a.WorkDate, 23) 
				, a.showhour
				, ''
				, ''
				, Round(a.workhour * b.Price,0)
				, Round(a.workhour * b.Price,0)
		From APW_IW_MANDAYWORK a
			Left join APW_YJI_StandardPrice B ON B.Stand_Year = @StandYear
			Left join TMWCMN_USR_BAC_INFO c On a.writeman = c.EMP	
		Where 1=1
			And a.GUBUN =1  
			And b.Gubun = 6
			And Convert(varchar(7), workdate, 23) = LEFT(@F_Date,7) 
			And a.Docid = '기타'
			And isnull(a.Manager, '') <> ''
			And a.Manager not like '%공(%'
			And a.Manager <> '공통'
			And a.Ugrade = '소속평가사'
			And a.Manager like '%'+@Manager+'%'
			 
			 )
		 
		  --수습평가사
		   INSERT INTO @TB_Result (Docid , Gubun,  Charger, Manager  , Workdate , Time , CustName  , Address ,Beprice, AFPrice)
		 (SELECT A.Docid , B.Bigo, A.writeman, D.Manager, Convert(varchar(10), A.WorkDate, 23) , A.showhour, D.CustName , D.Address,
		 Round(A.workhour * B.Price,0)  , round((A.workhour * B.Price) *(Convert(float , bo.Ratio) / Sbo.T_Ratio),0) 
		        From APW_IW_MANDAYWORK a
         Left join APW_YJI_StandardPrice b On b.Stand_Year = @StandYear
         Left join TMWCMN_USR_BAC_INFO c On a.writeman = c.EMP
         Left join APW_Masterex D ON A.Docid = D.DocID 
	     Left join ( Select Masterid , Ratio From APW_Booking a Inner join TMWCMN_USR_BAC_INFO b On a.Manager = b.USR_SEQ
               Where 1=1 And b.Emp = @Manager ) bo On D.MasterID = bo.MasterID
         Left join (Select Masterid , Sum(Ratio) T_Ratio From APW_Booking a Group by MasterID) Sbo On D.MasterID = Sbo.MasterID
			Where
			 Convert(varchar(7), A.workdate, 23) like  LEFT(@F_Date,7) + '%' 
			 and A.GUBUN =1  
			 And B.Gubun =7  
			 And C.OFFICE_ID='10'
		     And D.Manager like '%'+@Manager+'%'
			 And D.Manager not like '%공(%'
		 And a.Ugrade = '수습평가사'
		 
		 Union All

		Select a.Docid
				, b.Bigo
				, a.writeman
				, a.Manager
				, Convert(varchar(10), a.WorkDate, 23) 
				, a.showhour
				, ''
				, ''
				, Round(a.workhour * b.Price,0)
				, Round(a.workhour * b.Price,0)
		From APW_IW_MANDAYWORK a
			Left join APW_YJI_StandardPrice B ON B.Stand_Year = @StandYear
			Left join TMWCMN_USR_BAC_INFO c On a.writeman = c.EMP	
		Where 1=1
			And Convert(varchar(10), workdate, 23) like  LEFT(@F_Date,7) + '%' 
			And a.GUBUN =1  
			And b.Gubun = 7
			And Convert(varchar(7), workdate, 23) = LEFT(@F_Date,7) 
			And a.Docid = '기타'
			And isnull(a.Manager, '') <> ''
			And a.Manager not like '%공(%'
			And a.Manager <> '공통'
			And a.Ugrade = '수습평가사'
			And a.Manager like '%'+@Manager+'%'
		 
		 )
		 
		  --접수
	   INSERT INTO @TB_Result (Docid , Gubun,  Charger, Manager  , Workdate , Time , CustName  , Address ,Beprice, AFPrice)
		 (SELECT A.Docid , '접수', A.LReceiptCharge, A.Manager, Convert(varchar(10), A.Receiptdate, 23) ,'', A.CustName , A.Address, B.Price
		  ,  round(( B.Price) *(Convert(float , bo.Ratio) / Sbo.T_Ratio),0) 
				From APW_MASTEREX A
				Left join APW_YJI_StandardPrice B ON B.Stand_Year =@StandYear
				Left join ( Select Masterid , Ratio From APW_Booking a Inner join TMWCMN_USR_BAC_INFO b On a.Manager = b.USR_SEQ
                            Where 1=1 And b.Emp = @Manager ) bo On A.MasterID = bo.MasterID
                Left join (Select Masterid , Sum(Ratio) T_Ratio From APW_Booking a Group by MasterID) Sbo On A.MasterID = Sbo.MasterID
		 Where
		 Convert(varchar(10), ReceiptDate, 23) like  LEFT(@F_Date,7) + '%' 
		 And B.Gubun =9  
		 And A.Manager like '%'+@Manager+'%'
		 And A.Manager not like '%공(%'
		 And SUBSTRING(A.docid, 9, 1) <>'6' 
		 And A.office = '10')
		
		 --발송
		  INSERT INTO @TB_Result (Docid , Gubun,  Charger, Manager  , Workdate , Time , CustName  , Address ,Beprice, AFPrice)
		 (SELECT A.Docid , '발송', C.EMP, A.Manager, Convert(varchar(10), A.SendDate, 23) ,'', A.CustName , A.Address,B.Price 
		  ,  round(( B.Price) *(Convert(float , bo.Ratio) / Sbo.T_Ratio),0) 
				From APW_MASTEREX A
				Left join APW_YJI_StandardPrice B ON B.Stand_Year =@StandYear
				Left join TMWCMN_USR_BAC_INFO C ON A.Sendman = C.USR_SEQ
				Left join ( Select Masterid , Ratio From APW_Booking a Inner join TMWCMN_USR_BAC_INFO b On a.Manager = b.USR_SEQ
                            Where 1=1 And b.Emp = @Manager ) bo On A.MasterID = bo.MasterID
                Left join (Select Masterid , Sum(Ratio) T_Ratio From APW_Booking a Group by MasterID) Sbo On A.MasterID = Sbo.MasterID
		 Where
		 Convert(varchar(10), A.SendDate, 23) like  LEFT(@F_Date,7) + '%' 
		 And B.Gubun =10  
		 And A.Manager like '%'+@Manager+'%'
		 And A.Manager not like '%공(%'
		 And SUBSTRING(a.docid, 9, 1) <>'6'
		 And A.Office=  '10')

		  --심사
		 INSERT INTO @TB_Result (Docid , Gubun,  Charger, Manager  , Workdate , Time , CustName  , Address ,Beprice, AFPrice)
		  ( SELECT distinct  A.docid , '심사', '', C.Manager, Convert(varchar(10) , A.simsadate, 23), '-', C.CustName, C.Address, B.Price, 
		       round(( B.Price) *(Convert(float , bo.Ratio) / Sbo.T_Ratio),0) 
				From APW_simsa_form A
				Left join APW_YJI_StandardPrice B ON B.Stand_Year =@StandYear
				Left join APW_Masterex C ON A.docid = C.DocID
				Left join ( Select Masterid , Ratio From APW_Booking a Inner join TMWCMN_USR_BAC_INFO b On a.Manager = b.USR_SEQ
                            Where 1=1 And b.Emp = @Manager ) bo On C.MasterID = bo.MasterID
                Left join (Select Masterid , Sum(Ratio) T_Ratio From APW_Booking a Group by MasterID) Sbo On C.MasterID = Sbo.MasterID
		 Where
			 Convert(varchar(10), A.simsadate, 23) like  LEFT(@F_Date,7) + '%' 
			 And B.Gubun =11  
			 And C.Manager like '%'+@Manager+'%'
			 And C.Manager not like '%공(%'
			 And C.Office ='10'
			 )
		 -- GROUP BY B.Price, a.pung

	--탁상접수
	if @StandYear >= '2025'
	Begin

		INSERT INTO @TB_Result (Docid , Gubun,  Charger, Manager  , Workdate , Time , CustName  , Address ,Beprice, AFPrice)
		(Select  A.MasterID, '탁상접수', C.EMP ,D.EMP , Convert(varchar(10), A.Reg_DateTime,23), '' , A.CustName, A.Addr, B.Price, B.Price
				From APW_TS_Master A
				Left join APW_YJI_StandardPrice B ON B.Stand_Year =@StandYear
				Left join TMWCMN_USR_BAC_INFO C ON A.Reg_Charge = C.USR_SEQ
				Left join TMWCMN_USR_BAC_INFO D ON A.Manager = D.USR_SEQ
			Where
			Convert(varchar(10), Reg_DateTime, 23) like  LEFT(@F_Date,7) + '%' 
			And C.APPRAISAL_FL = 1
			And B.Gubun =8  
			And A.Office = '10'
			And D.EMP = @Manager
			And Left(isnull(a.HFDocid, ''), 3) <> '400'
			)

		INSERT INTO @TB_Result (Docid , Gubun,  Charger, Manager  , Workdate , Time , CustName  , Address ,Beprice, AFPrice)
		(Select  A.MasterID, 'KB탁상접수', C.EMP ,D.EMP , Convert(varchar(10), A.Reg_DateTime,23), '' , A.CustName, A.Addr, B.Price, B.Price
				From APW_TS_Master A
				Left join APW_YJI_StandardPrice B ON B.Stand_Year =@StandYear
				Left join TMWCMN_USR_BAC_INFO C ON A.Reg_Charge = C.USR_SEQ
				Left join TMWCMN_USR_BAC_INFO D ON A.Manager = D.USR_SEQ
			Where
			Convert(varchar(10), Reg_DateTime, 23) like  LEFT(@F_Date,7) + '%' 
			And C.APPRAISAL_FL = 1
			And B.Gubun =16
			And A.Office = '10'
			And D.EMP = @Manager
			And Left(isnull(a.HFDocid, ''), 3) = '400'
			)

	End
	Else if @StandYear < '2025'
	Begin

		INSERT INTO @TB_Result (Docid , Gubun,  Charger, Manager  , Workdate , Time , CustName  , Address ,Beprice, AFPrice)
		(SELECT  A.MasterID, '탁상접수', C.EMP ,D.EMP , Convert(varchar(10), A.Reg_DateTime,23), '' , A.CustName, A.Addr, B.Price, B.Price
				From APW_TS_Master A
				Left join APW_YJI_StandardPrice B ON B.Stand_Year =@StandYear
				Left join TMWCMN_USR_BAC_INFO C ON A.Reg_Charge = C.USR_SEQ
				Left join TMWCMN_USR_BAC_INFO D ON A.Manager = D.USR_SEQ
			Where
			Convert(varchar(10), Reg_DateTime, 23) like  LEFT(@F_Date,7) + '%' 
			And C.APPRAISAL_FL = 1
			And B.Gubun =8  
			And A.Office = '10'
			And D.EMP = @Manager)
			--GROUP BY B.Price, d.EMP)
	End
	
		  --탁상감정
	if @StandYear >= '2025'
	Begin

		 INSERT INTO @TB_Result (Docid , Gubun,  Charger, Manager  , Workdate , Time , CustName  , Address ,Beprice, AFPrice)
		(
		  SELECT  A.Docid, '탁상감정',A.writeman, A.Manager, Convert(varchar(10), A.Workdate,23), '',c.CustName , C.Addr,B.Price, B.Price  
				 From APW_IW_MANDAYWORK A
				 Left join APW_YJI_StandardPrice B ON B.Stand_Year =@StandYear
				 Left join APW_TS_Master C  ON A.Docid = C.MasterID
				
		 Where
         Convert(varchar(10), workdate, 23) like  LEFT(@F_Date,7) + '%' 
		 and A.GUBUN =2  
		 And B.Gubun =5  
		 And A.Manager  = @Manager
		 And Left(isnull(c.HFDocid, ''), 3) <> '400'
		 )

		 INSERT INTO @TB_Result (Docid , Gubun,  Charger, Manager  , Workdate , Time , CustName  , Address ,Beprice, AFPrice)
		(
		  SELECT  A.Docid, 'KB탁상감정',A.writeman, A.Manager, Convert(varchar(10), A.Workdate,23), '',c.CustName , C.Addr,B.Price, B.Price  
				 From APW_IW_MANDAYWORK A
				 Left join APW_YJI_StandardPrice B ON B.Stand_Year =@StandYear
				 Left join APW_TS_Master C  ON A.Docid = C.MasterID
				
		 Where
         Convert(varchar(10), workdate, 23) like  LEFT(@F_Date,7) + '%' 
		 and A.GUBUN =2  
		 And B.Gubun =17  
		 And A.Manager  = @Manager
		 And Left(isnull(c.HFDocid, ''), 3) = '400'
		 )

	End
	Else if @StandYear < '2025'
	Begin
		
        INSERT INTO @TB_Result (Docid , Gubun,  Charger, Manager  , Workdate , Time , CustName  , Address ,Beprice, AFPrice)
		(
		  SELECT  A.Docid, '탁상감정',A.writeman, A.Manager, Convert(varchar(10), A.Workdate,23), '',c.CustName , C.Addr,B.Price, B.Price  
				 From APW_IW_MANDAYWORK A
				 Left join APW_YJI_StandardPrice B ON B.Stand_Year =@StandYear
				 Left join APW_TS_Master C  ON A.Docid = C.MasterID
				
		 Where
         Convert(varchar(10), workdate, 23) like  LEFT(@F_Date,7) + '%' 
		 and A.GUBUN =2  
		 And B.Gubun =5  
		 And A.Manager  = @Manager
		 )

	End

		  --비지오
		INSERT INTO @TB_Result (Docid , Gubun,  Charger, Manager  , Workdate , Time , CustName  , Address ,Beprice, AFPrice)
		(
		SELECT A.Docid , '비지오' , A.Emp_Dam, D.Manager, Convert(varchar(10) , A.Update_Date, 23),'', D.CustName, D.Address, B.Price,
		 round(( B.Price) *(Convert(float , bo.Ratio) / Sbo.T_Ratio),0) 
				 From Apw_VIsio A
				 Left join APW_YJI_StandardPrice B ON B.Stand_Year =@StandYear
         		Left join TMWCMN_USR_BAC_INFO c On a.Emp_Dam = c.EMP
				Left join APW_MASTEREX D ON A.Docid = D.DocID
				Left join ( Select Masterid , Ratio From APW_Booking a Inner join TMWCMN_USR_BAC_INFO b On a.Manager = b.USR_SEQ
                            Where 1=1 And b.Emp = @Manager ) bo On D.MasterID = bo.MasterID
                Left join (Select Masterid , Sum(Ratio) T_Ratio From APW_Booking a Group by MasterID) Sbo On D.MasterID = Sbo.MasterID
		 Where
		 Convert(varchar(10), a.Update_Date, 23) like  LEFT(@F_Date,7) + '%' 
		 --and A.GUBUN =3 
		 And B.Gubun =3  
		 And C.OFFICE_ID='10'
		 And D.Manager  Like '%'+@Manager+'%'
		 And D.Manager not like '%공(%'		 
		 And a.Gubun = 'VISIO'
		 and c.RTRM_FL = 0
		 And isnull(c.Insertdate,'2000-01-01') <= a.Update_Date - 365 )
		 

		--수습비지오
		INSERT INTO @TB_Result (Docid , Gubun,  Charger, Manager  , Workdate , Time , CustName  , Address ,Beprice, AFPrice)
		(
		SELECT A.Docid , '수습비지오' , A.Emp_Dam, D.Manager, Convert(varchar(10) , A.Update_Date, 23),'', D.CustName, D.Address, B.Price,
		 round(( B.Price) *(Convert(float , bo.Ratio) / Sbo.T_Ratio),0) 
				 From Apw_VIsio A
				 Left join APW_YJI_StandardPrice B ON B.Stand_Year =@StandYear
         		Left join TMWCMN_USR_BAC_INFO c On a.Emp_Dam = c.EMP
				Left join APW_MASTEREX D ON A.Docid = D.DocID
				Left join ( Select Masterid , Ratio From APW_Booking a Inner join TMWCMN_USR_BAC_INFO b On a.Manager = b.USR_SEQ
                            Where 1=1 And b.Emp = @Manager ) bo On D.MasterID = bo.MasterID
                Left join (Select Masterid , Sum(Ratio) T_Ratio From APW_Booking a Group by MasterID) Sbo On D.MasterID = Sbo.MasterID
		 Where
		 Convert(varchar(10), a.Update_Date, 23) like  LEFT(@F_Date,7) + '%' 
		 --and A.GUBUN =3 
		 And B.Gubun =4  
		 And C.OFFICE_ID='10'
		 And D.Manager  Like '%'+@Manager+'%'
		 And D.Manager not like '%공(%'
		 And a.Emp_Dam <> '이은선'
		And a.Gubun = 'VISIO'
		and c.RTRM_FL = 0
		And isnull(c.Insertdate,'2000-01-01') >= a.Update_Date - 365 )
	

		 ----시조위
		  INSERT INTO @TB_Result (Docid , Gubun,  Charger, Manager  , Workdate , Time , CustName  , Address ,Beprice, AFPrice)
		(
		SELECT A.Docid , '시조위', '',D.Manager, Convert(varchar(10) , A.simsadate, 23),'', D.CustName, D.Address,B.Price,
		round(( B.Price) *(Convert(float , bo.Ratio) / Sbo.T_Ratio),0) 
				From APW_IW_SIJO A
				Left join APW_YJI_StandardPrice B ON B.Stand_Year =@StandYear
			    Left join APW_MASTEREX D ON A.Docid = D.DocID
				Left join ( Select Masterid , Ratio From APW_Booking a Inner join TMWCMN_USR_BAC_INFO b On a.Manager = b.USR_SEQ
                            Where 1=1 And b.Emp = @Manager ) bo On D.MasterID = bo.MasterID
                Left join (Select Masterid , Sum(Ratio) T_Ratio From APW_Booking a Group by MasterID) Sbo On D.MasterID = Sbo.MasterID
				 Where
				 Convert(varchar(10), A.simsadate, 23)like  LEFT(@F_Date,7) + '%'  
				 And B.Gubun =12  
				 And D.Manager  Like '%'+@Manager+'%'
				 And D.Manager not like '%공(%'
				 And D.Office = '10')
				 
		--검산
		if (@Manager = '유영조')
	    begin
		 INSERT INTO @TB_Result (Docid , Gubun,  Charger, Manager  , Workdate , Time , CustName  , Address ,Beprice, AFPrice)
		(
		SELECT A.Docid , '검산',a.Charge, A.Manager, Convert(varchar(10) , A.SendDate, 23), '', a.CustName, a.Address, b.Price,b.Price
		   From Apw_MasterEX a
						Left join Apw_YJI_StandardPrice b On b.Stand_Year = @StandYear
					Where 1=1
						And  Convert(varchar(10), SendDate, 23) like  LEFT(@F_Date,7) + '%' 
						--And A.Office = '10'
						And CustName like '%신한은행%'-- or CustName like '%국민은행%' or CustName like '%기업은행%' or CustName like '%우리은행%')
						And b.Gubun = 15)
		End
					
	  ---약식
		INSERT INTO @TB_Result (Docid , Gubun,  Charger, Manager  , Workdate , Time , CustName  , Address ,Beprice, AFPrice)
		(

			SELECT a.Docid
					, '약식'
					, a.Writeman
					, c.Manager 
					, Convert(varchar(10) , C.Senddate, 23)
					, ''
					, c.CustName
					, c.Address
					, b.Price
					, round((b.Price) * (Convert(float, bo.Ratio) / Sbo.T_Ratio),0) 
			From APW_IW_YACKMASTER a
					Left join Apw_YJI_StandardPrice b On b.Stand_Year = @StandYear
					Left join APW_MASTEREX C ON A.Docid= C.DocID
					Left join ( Select Masterid , Ratio, Emp From APW_Booking a Inner join TMWCMN_USR_BAC_INFO b On a.Manager = b.USR_SEQ
								Where 1=1 And b.Emp = @Manager ) bo On c.MasterID = bo.MasterID
					Left join (Select Masterid , Sum(Ratio) T_Ratio From APW_Booking a Group by MasterID) Sbo On c.MasterID = Sbo.MasterID
			Where 1=1
				And  Convert(varchar(10), Writedate, 23) like  LEFT(@F_Date,7) + '%' 
				And C.Office = '10'
				And b.Gubun = 13
				and c.Manager Like '%'+@Manager+'%'

		--SELECT A.Docid , '약식',a.Writeman, c.Manager , Convert(varchar(10) , C.Senddate, 23),'', C.CustName, C.Address, b.Price,b.Price
		--   From APW_IW_YACKMASTER a
		--				Left join Apw_YJI_StandardPrice b On b.Stand_Year = @StandYear
		--			Left join APW_MASTEREX C ON A.Docid= C.DocID
		--			Where 1=1
		--				And  Convert(varchar(10), Writedate, 23) like  LEFT(@F_Date,7) + '%' 
		--				And C.Office = '10'
		--				And b.Gubun = 13
		--				and c.Manager = @Manager
		)
				--	Group by  b.Price , a.Manager

		--------- 국민약식

	if @Manager = '김형수'
	Begin

		if @StandYear >= '2025'
		Begin

			INSERT INTO @TB_Result (Docid , Gubun,  Charger, Manager  , Workdate , Time , CustName  , Address ,Beprice, AFPrice)
			(
			Select a.RequestNM, 'KB약식', '', '김형수', a.WorkDate, '', '국민은행', '', a.Price, a.Price
			From
			(
				Select DIStinct a.RequestNM
						, d.Price
						, Left(Convert(Char(10), c.Apptime ,126), 4) + '-' + Substring(Convert(Char(10), c.Apptime ,126), 5, 2) WorkDate
				From Bank_kb_master a
					Inner join Bank_KB_apt b On a.requestNM = b.requestNM
					Inner join Bank_KB_Header c On a.KB_MasterID = c.KB_MasterID
					Left join Apw_YJI_StandardPrice d On d.Stand_Year = @StandYear
				where 1=1
					And b.appgubun = '2'
					And a.OfficeID = '10'
					And Left(Convert(Char(10), c.Apptime ,126), 4) + '-' + Substring(Convert(Char(10), c.Apptime ,126), 5, 2) like Left(@F_Date, 7) + '%'
					And d.Gubun = 18
					And a.WorkResult = 6
			) a
			)

		End
		Else if @StandYear < '2025'
		Begin

			INSERT INTO @TB_Result (Docid , Gubun,  Charger, Manager  , Workdate , Time , CustName  , Address ,Beprice, AFPrice)
			(
			Select a.RequestNM, 'KB약식', '', '김형수', a.WorkDate, '', '국민은행', '', a.Price, a.Price
			From
			(
				Select DIStinct a.RequestNM
						, d.Price
						, Left(Convert(Char(10), c.Apptime ,126), 4) + '-' + Substring(Convert(Char(10), c.Apptime ,126), 5, 2) + '-' + Substring(Convert(Char(10), c.Apptime ,126), 7, 2) WorkDate
				From Bank_kb_master a
					Inner join Bank_KB_apt b On a.requestNM = b.requestNM
					Inner join Bank_KB_Header c On a.KB_MasterID = c.KB_MasterID
					Left join Apw_YJI_StandardPrice d On d.Stand_Year = @StandYear
				where 1=1
					And b.appgubun = '2'
					And a.OfficeID = '10'
					And Left(Convert(Char(10), c.Apptime ,126), 4) + '-' + Substring(Convert(Char(10), c.Apptime ,126), 5, 2) like Left(@F_Date, 7) + '%'
					And d.Gubun = 13
					And a.WorkResult = 6
			) a
			)

		End

	End

				--협회심사비
      INSERT INTO @TB_Result (Docid , Gubun,  Charger, Manager  , Workdate , Time , CustName  , Address ,Beprice, AFPrice)
		(
		SELECT Distinct A.Docid , '협회심사', A.LReceiptCharge, A.Manager, Convert(varchar(10), A.Receiptdate, 23) ,'', A.CustName , A.Address, Floor(((수수료합계-(여비 + 물건조사비+ 토지조사비+ 특별용역비 + 공부발급비 +기타실비)) * 0.008)/10)*10
		  ,    round(( Floor(((수수료합계-(여비 + 물건조사비+ 토지조사비+ 특별용역비 + 공부발급비 +기타실비)) * 0.008)/10)*10) *(Convert(float , bo.Ratio) / Sbo.T_Ratio),0) 
				From APW_MASTEREX A
				--Left join APW_YJI_StandardPrice B ON B.Stand_Year ='2022'
				Left join ( Select Masterid , Ratio From APW_Booking a Inner join TMWCMN_USR_BAC_INFO b On a.Manager = b.USR_SEQ
                            Where 1=1 And b.Emp = @Manager ) bo On A.MasterID = bo.MasterID
                Left join (Select Masterid , Sum(Ratio) T_Ratio From APW_Booking a Group by MasterID) Sbo On A.MasterID = Sbo.MasterID
				Left join APW_Process P on A.MasterID = P.MasterID 
		 Where
		 Convert(varchar(10), P.ISSUEDATE, 23) like  LEFT(@F_Date,7) + '%' 
		-- And B.Gubun =9  
		 And (A.Manager  like '%'+@Manager+'%' )--or A.Manager = '공(' +@Manager + ')')
		 And P.Code = '0C'
		 And A.Office = '10'
		 )

		 ---감정서경비
		 INSERT INTO @TB_Result (Docid , Gubun,  Charger, Manager  , Workdate , Time , CustName  , Address ,Beprice, AFPrice)
		(
		SELECT A.Docid , '감정서경비', '', A.Manager, Convert(varchar(10), cost.JunpyoDate, 23) ,'', A.CustName , A.Address, Cost.Price
		  ,    round(Cost.Price *(Convert(float , bo.Ratio) / Sbo.T_Ratio),0) 
				From APW_MASTEREX A
				
				Left join ( Select Masterid , Ratio From APW_Booking a Inner join TMWCMN_USR_BAC_INFO b On a.Manager = b.USR_SEQ
                            Where 1=1 And b.Emp = @Manager ) bo On A.MasterID = bo.MasterID
                Left join (Select Masterid , Sum(Ratio) T_Ratio From APW_Booking a Group by MasterID) Sbo On A.MasterID = Sbo.MasterID
				Left join APW_IW_Bonus_DocCost cost on A.DocID = cost.Docid
		 Where
		 Convert(varchar(10), cost.JunpyoDate, 23) like  LEFT(@F_Date,7) + '%' 
		 And A.Manager like '%'+@Manager+'%'
		 And A.Manager not like '%공(%'
		 And cost.Gubun  in ('세금과공과' ,'도서인쇄비')
		 And isnull(cost.Docid, '') <> ''
		 --And cost.Gubun = 1
		 union all
		 SELECT isnull(A.Docid,'') , '감정서경비', '', A.Manager, Convert(varchar(10), a.JunpyoDate, 23) ,'', A.CustName ,'', a.Price
		  ,    round(a.Price ,0) 
				From APW_IW_Bonus_DocCost A
		 Where
		 Convert(varchar(10), a.JunpyoDate, 23) like  LEFT(@F_Date,7) + '%' 
		 And A.Manager like '%'+@Manager+'%'
		 And A.Manager not like '%공(%'
		 And a.Gubun  in ('세금과공과' ,'도서인쇄비')
		and  a.Bigo not like '%자동차세%'
		 And isnull(a.Docid, '') = ''
		 )
		 
	-- HUG 탁상 접수
	if (@Manager = '안창덕')
	begin

		INSERT INTO @TB_Result (Docid , Gubun,  Charger, Manager  , Workdate , Time , CustName  , Address ,Beprice, AFPrice)
		(
			Select a.Docid , 'HUG탁상접수', '', '안창덕', Convert(varchar(10), a.ReceiptDate, 23), '', '주택도시보증공사(HUG)', a.Addr, b.Price, b.Price
			From Hug_info a
				Left join Apw_YJI_StandardPrice b On b.Stand_Year = @StandYear
			Where 1=1
				And  Convert(varchar(10), a.ReceiptDate, 23) like Left(@F_Date,7) + '%' 
				And b.Gubun = 19
		)

		INSERT INTO @TB_Result (Docid , Gubun,  Charger, Manager  , Workdate , Time , CustName  , Address ,Beprice, AFPrice)
		(
			Select a.Docid , 'HUG탁상감정', '', '안창덕', Convert(varchar(10), a.Complete_Date, 23), '', '주택도시보증공사(HUG)', a.Addr, b.Price, b.Price
			From Hug_info a
				Left join Apw_YJI_StandardPrice b On b.Stand_Year = @StandYear
			Where 1=1
				And  Convert(varchar(10), a.Complete_Date, 23) like Left(@F_Date,7) + '%' 
				And b.Gubun = 20
		)

	End


  SELECT * FROM @TB_Result order by Workdate

End