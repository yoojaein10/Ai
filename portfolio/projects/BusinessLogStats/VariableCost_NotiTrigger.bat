@echo off
rem VariableCost noti trigger - scheduled monthly on day 1,2,3 at 09:00
rem JSP decides the actual send day (weekday 1st, or next Monday); off-days return "skip"
rem Log is written next to this file: VariableCost_Noti.log

set LOG=%~dp0VariableCost_Noti.log

echo [%date% %time%] trigger start >> "%LOG%"
curl -s "https://desk.dhapp.co.kr/Main/WebContent/siljuk/VariableCost_NotiSend.jsp?key=fa47ba8642e1792328ef86ed070f6435&auto=1" >> "%LOG%" 2>&1
echo. >> "%LOG%"
