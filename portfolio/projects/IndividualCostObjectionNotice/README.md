# 개별부담비용 이의신청 문자

기존 프로젝트와 분리된 독립 실행형 프로그램이다. Windows 작업 스케줄러가 매일 실행하며, 대한민국 공휴일·대체공휴일과 주말을 제외한 매월 마지막 영업일에 DB 저장 프로시저 `dbo.MMS_SEND`로 안내 문자를 발송한다. 실행 후 즉시 종료하므로 프로그램을 계속 켜둘 필요가 없다.

## 더블클릭 실행

명령어 없이 bat 파일을 순서대로 더블클릭하면 된다.

1. `1_install.bat` — 파이썬 가상환경 설치
2. `2_setup_env_and_test.bat` — DB 접속 정보를 입력받아 환경변수로 저장하고, 원하면 바로 테스트 발송
3. `3_test_send.bat` — 승인된 테스트 번호(010-0000-0000)로만 발송
4. `4_register_schedule.bat` — 매일 16:00 작업 스케줄러 등록

## 설치

PowerShell에서 `setup.ps1`을 실행한다. 운영 수신번호는 설정 파일에 저장하지 않고 `Seat_UserInfo`에서 매 실행 시 조회한다. `Dept_Nm`이 `sim`, `yj`, `ju`, `jip`인 행의 `Uptel`만 사용한다.

다음 값은 소스나 `config.json`에 저장하지 말고 작업을 실행할 Windows 계정의 사용자 환경변수로 설정한다.

- `SMS_DB_SERVER`
- `SMS_DB_NAME`
- `SMS_DB_USER`
- `SMS_DB_PASSWORD`
- `SMS_CALL_FROM`
- `SMS_RECIPIENT_DB_NAME`
- `SMS_TEST_PHONE` (테스트 명령에서만 사용)
- `SMS_ODBC_DRIVER` (선택, 기본값: ODBC Driver 18 for SQL Server)
- `SMS_DB_ENCRYPT` (선택, 기본값: yes)
- `SMS_DB_TRUST_SERVER_CERTIFICATE` (선택, 기본값: no)

## 명령

```powershell
.\.venv\Scripts\python.exe .\app.py check-date 2026-08
.\.venv\Scripts\python.exe .\app.py test-send
.\.venv\Scripts\python.exe .\app.py run
```

`test-send`는 `Seat_UserInfo`를 조회하지 않는다. `SMS_TEST_PHONE`이 프로그램에 등록된 승인 번호의 해시와 일치할 때만 `subject.txt` 제목과 `message.txt` 원문을 보낸다. 다른 번호는 실행 전에 차단한다. 번호는 로그에서 마스킹되며 운영 발송 이력에는 SHA-256 해시만 저장한다.

## 작업 스케줄러

환경변수와 운영 수신번호를 설정한 후 다음 명령으로 매일 실행 작업을 등록한다.

```powershell
.\install_task.ps1 -At "16:00"
```

예약 시각을 놓친 경우 가능한 즉시 실행한다. 마지막 영업일부터 달력상 말일까지는 미발송 수신자만 재시도하고, SQLite 발송 이력으로 정상 발송된 수신자의 월별 중복 발송을 막는다.

## 달력 예외

`calendar_overrides.json`에 회사 휴무일을 `additional_holidays`로 추가할 수 있다. 법정 휴일이지만 정상 근무하는 날짜는 `forced_workdays`에 추가한다. 날짜 형식은 `YYYY-MM-DD`이다.
