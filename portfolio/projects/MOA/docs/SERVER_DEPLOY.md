# A10 Bridge 중앙 서버 배포 (192.0.2.10)

중앙 서버 1대가 웹 UI(`/dashboard`, `/receivables`), 데스크톱 UI(`/desktop`), API, DB 연동, 전표 캐시 동기화를 전부 담당한다. 직원 PC의 thin EXE는 이 서버에 접속만 한다.

## 사전 요구사항 (서버)

- Python 3.13 (설치 확인: `python --version`)
- **ODBC Driver 17 또는 18 for SQL Server** (`odbcad32.exe` → 드라이버 탭 확인)
- MSSQL 서버(GamJunDW/apworksdw)로 네트워크 접근 가능
- 관리자 권한 (작업 스케줄러·방화벽 등록)

## 최초 배포 절차

1. **소스 복사**: 프로젝트 폴더 전체를 서버로 복사 (예: `C:\A10Bridge`).
   `dist/`, `build/`, `__pycache__/`, `.venv/`는 복사 불필요.
2. **.env 작성**: `C:\A10Bridge\.env` — `.env.example` 복사 후 MSSQL_* 입력.
   `MSSQL_DRIVER`는 서버에 설치된 드라이버명과 정확히 일치시킬 것.
   A10_*(Amaranth)는 전표 캐시 동기화·회계단위 매칭·전표 생성에 필요.
3. **설치 스크립트 실행** (관리자 PowerShell):
   ```powershell
   cd C:\A10Bridge
   powershell -ExecutionPolicy Bypass -File scripts\server_setup.ps1
   ```
   수행 내용: venv 생성 → 의존성 설치 → 테이블 생성(`scripts.create_tables`) →
   지사 매핑 시드(`scripts.seed_office_map`) → 작업 스케줄러 등록 →
   방화벽 8010 인바운드 허용 → 서버 기동 + 헬스체크.
4. **최초 캐시 백필** (1회, 수동):
   ```powershell
   .venv\Scripts\python.exe -m app.batch.voucher_cache_sync --days 365 --monthly-chunks
   ```
5. **검증**: 다른 PC 브라우저에서
   - `http://192.0.2.10:8010/health` → `{"status":"ok", ...}`
   - `http://192.0.2.10:8010/desktop?usr=본인ID` → 사용자명·지사 표시 확인

## 등록되는 작업 스케줄러

| 작업명 | 주기 | 내용 |
|---|---|---|
| `A10Bridge_Server` | 부팅 시(onstart) | uvicorn 서버 (0.0.0.0:8010), 로그 `logs\server.log` (타임스탬프 포함) |
| `A10Bridge_CacheSync` | 1시간마다 | 최근 7일 전표 캐시 동기화 + 입금·미수 요약(`a10_receivable_summary`) 재집계 + 입금 결과(`a10_payment_status`) 갱신(2026-07-30, 입금문자내역용), 로그 `logs\cache_sync.log` |
| `A10Bridge_CacheSyncYear` | 매일 23:00 | 최근 365일을 월별로 나눠 동기화. 과거 전표 수정 반영, 로그 `logs\cache_sync_year.log` |
| `A10Bridge_PaymentSync` | 매일 22:30 | APWorks 조회용 입금 결과(`a10_payment_status`) 정리, 로그 `logs\payment_sync.log` |
| `A10Bridge_FeeBasisPrepare` | 매일 23:00 | 보수기준 점검 스냅숏 사전생성(당월 포함 최근 6개월, 본사). 로그 `logs\fee_basis_prepare.log` |
| `A10Bridge_PartnerCache` | 매일 04:20 | 아마란스 거래처 전체(6.2만건)를 `a10_partner_cache`에 적재. 카드전표 가맹점 조회를 우리 DB에서 끝내려는 것 — 없으면 화면이 아마란스에 한 건씩 물어 한 달치에 2분이 걸린다. 실패해도 옛 캐시가 남고 화면은 느리게라도 동작한다. 로그 `logs\partner_cache.log` |
| `A10Bridge_AccountOpeningRoll` | **매년 1월 2일 06:00** | 계정별원장 전기이월 해 넘기기(`scripts.roll_account_opening`). 지난해 이월 + 지난해 증감으로 새해 이월을 만든다. 이미 값이 있으면 덮어쓰지 않는다. 로그 `logs\account_opening_roll.log` |
| `A10Bridge_Watchdog` | 5분마다 | `/health` 무응답이면 서버 자동 재기동. 정상일 땐 기록 없음, 재기동 시에만 `logs\watchdog.log` 기록 |

## 해마다 한 번 — 계정별원장 전기이월 (매년 1월)

계정별원장의 전일이월은 **전기이월 + 그 해 누계**다. 전기이월(`a10_account_opening`)은
연도별로 들어 있고, 해가 바뀌면 **새 해 값을 만들어 줘야 한다.**

**2026-08-24부터 예약 작업 `A10Bridge_AccountOpeningRoll` 이 매년 1월 2일 06:00 에 자동으로
돈다.** 아래는 손으로 돌릴 때 쓴다.

```
python -m scripts.roll_account_opening --year 2027 --dry-run   # 계산만 해 본다
python -m scripts.roll_account_opening --year 2027             # 저장 (연도를 생략하면 올해)
python -m scripts.roll_account_opening --year 2027 --force     # 1월 말, 소급 전표 반영해 다시 굳힌다
```

`--force` 는 자동으로 돌리지 않는다. 손으로 맞춰 둔 값을 배치가 조용히 지우면 안 되기
때문이다. 1월 말에 소급 전표까지 반영해 한 번 더 굳히는 것은 사람이 확인하며 한다.

새 이월 = 지난해 이월 + 지난해 차변 − 지난해 대변 (지난해 전표는 우리 캐시에서 읽는다).
저장한 뒤 아마란스 계정별원장 화면의 `[전 기 이 월]` 과 한두 계정만 대조해 보면 된다.

자동 실행이 실패해도 **틀린 원장이 지사로 나가지는 않는다** — 그 해 이월이 없는 계정은 발송이 실패로
막히고(로그에 `전기이월이 없습니다` 로 남는다), 화면 미리보기에도 빨간 경고가 뜬다.
다만 그날 지사 원장이 안 나가므로 1월 첫 발송 전에 돌려 두는 것이 좋다.

- 보수기준 사전생성은 2026-08-07에 **120분 주기 → 매일 23:00 한 번**으로 바꿨다. 2시간 주기로
  등록돼 있었지만 실제로는 하루 1~2회만 돌았고, 당월+전월만 커버해서 그보다 과거 반월은
  조회할 때마다 130초를 기다려야 했다. `A10Bridge_FeeBasisPrepareHistory`는 이 작업에
  흡수돼 제거된다. 시각·개월수는 `-FeeBasisTime 23:00 -FeeBasisMonthsBack 5`로 바꿀 수 있다.

- 전표 자동·수동 동기화는 SQL Server 공통 잠금을 사용한다. 365일 작업 중 매시간 7일 작업이 겹치면 해당 회차는 안전하게 건너뛴다.
- **주기 변경**: `server_setup.ps1 -SyncIntervalMinutes 60 -SyncDays 7 -YearSyncDays 365 -YearSyncTime 23:00`으로 재실행한다.
- **기간 직접 동기화**:
  ```powershell
  .venv\Scripts\python.exe -m app.batch.voucher_cache_sync --date-from 2026-01-01 --date-to 2026-01-31 --monthly-chunks
  ```
  본사 관리자 화면의 `권한부여 → 전표 가져오기 → 기간 직접 지정`에서도 같은 작업을 실행할 수 있다.
- **수동 재시작**: `schtasks /end /tn A10Bridge_Server` → `schtasks /run /tn A10Bridge_Server`

## 재배포 (코드 업데이트)

**반드시 `scripts\server_redeploy.ps1`로 배포한다** (관리자 PowerShell):

```powershell
cd C:\A10Bridge
powershell -ExecutionPolicy Bypass -File scripts\server_redeploy.ps1 -ZipPath C:\Temp\A10Bridge_server.zip
```

배포 ZIP에 `server_redeploy.ps1` 자체 변경이 포함된 릴리스는 새 스크립트를 먼저
`C:\Temp`에 복사한 뒤 그 파일로 실행한다. 그래야 같은 배포에서 새 예약 작업까지
즉시 반영된다.

```powershell
powershell -ExecutionPolicy Bypass -File C:\Temp\server_redeploy.ps1 `
  -InstallDir C:\A10Bridge `
  -ZipPath C:\Temp\A10Bridge_server.zip
```

수행 내용: 서버 중지 → zip 반영(`.env`는 서버 것 유지) → `pip install -r requirements.txt` →
`scripts.create_tables` → 동기화 예약 작업 갱신 → 재기동 → **헬스체크 200 확인**
(실패 시 로그 tail을 출력하고 exit 1).
파일을 이미 수동으로 덮어쓴 경우 `-ZipPath` 생략 가능.

> 수동 배포 금지 이유: 2026-07-22 장애 — 파일만 덮어쓰고 pip install을 빠뜨려
> openpyxl 미설치로 서버가 기동 즉시 크래시 루프, 헬스체크도 없어 밤새 다운된 채 방치됐다.

- 기존 테이블의 **컬럼 추가**는 여전히 수동 ALTER 필요 (create_all은 새 테이블만 생성)

thin EXE 구조 덕분에 **화면/로직 수정은 서버 재배포만으로 전 직원에게 반영**된다. EXE 재배포는 EXE 자체(창/설정 로직)가 바뀔 때만 필요하다.

## 신규 테이블

- `a10_office_map`: 지사↔감정서번호 접두사↔Amaranth 회계단위 (시드 스크립트가 관리, 본사=4210)
- `a10_user_permission`: 지사 사용자에게 전체 조회를 예외 허용할 때 INSERT
  ```sql
  INSERT INTO dbo.a10_user_permission (usr_id, view_all_offices, memo) VALUES ('사용자ID', 'Y', '사유');
  ```
- `a10_access_log`: EXE 실행(사용자 컨텍스트 조회) 감사 로그 — usr_id, result, client_ip
- `a10_receivable_summary`: 감정서별 청구·입금·미수 집계 캐시 (캐시 동기화가 30분마다 재집계)
- `a10_payment_status`: APWorks(델파이) 조회용 입금 결과. 감정서번호당 1행 —
  `doc_id`(감정서번호), `paid_date`(최근 입금일), `paid_amount`(누적 입금액),
  `pay_result`(N'입금완료' | N'분할입금'). 분할입금이 완납되면 다음 배치에서 입금완료로 UPDATE.
  ```sql
  SELECT doc_id, paid_date, paid_amount, pay_result
  FROM GamJunDW.dbo.a10_payment_status WHERE doc_id = '01-2607-3-2291';
  ```
  - 2026-07-30 컬럼 추가(입금발송내역 화면): `sms_sent_at`(문자 전송시각),
    `sms_sent_by`(처리자 usr_seq). 개발 DB에는 반영됨 — 다른 환경은 수동 ALTER:
    ```sql
    ALTER TABLE dbo.a10_payment_status ADD sms_sent_at DATETIME NULL, sms_sent_by INT NULL;
    ```
- `a10_card_voucher` 컬럼 추가(2026-08-14, 아마란스 삭제 동기화):
  `amaranth_checked_at`(아마란스 잔존 확인 시각). 개발 DB(192.0.2.10)에는 반영됨 —
  다른 환경은 수동 ALTER:
  ```sql
  ALTER TABLE dbo.a10_card_voucher ADD amaranth_checked_at DATETIME NULL;
  ```
- `a10_issued_taxinvoice` 컬럼 추가(2026-08-13, 발급 팝업 계정과목 기록):
  `account_code`(매출 계정 401xxxx, 기록용). 개발 DB(192.0.2.10)에는 반영됨 —
  다른 환경은 수동 ALTER:
  ```sql
  ALTER TABLE dbo.a10_issued_taxinvoice ADD account_code varchar(10) NULL;
  ```
- `a10_partner_cache`: 아마란스 거래처(api16S11) 사업자번호 색인 (2026-08-20 신설).
  카드전표 검증이 가맹점을 찾을 때 쓴다. 표가 없는 환경은 서버 기동/redeploy의
  테이블 생성 단계가 자동으로 만든다. 최초 적재는 한 번 수동 실행:
  ```powershell
  .venv\Scripts\python.exe -m app.batch.partner_cache_sync
  ```
  캐시가 36시간 넘게 낡으면 '여기 없다'를 믿지 않고 예전처럼 아마란스에 물어본다.
- `a10_payment_notify`: **재도입(2026-07-31)** — 입금 알림 큐(Leeilwoo 방식) 복원.
  재집계가 누적 입금액이 늘어난 감정서를 큐에 적재하고, 자동발송이 큐를 소비한다
  (발송 정책 필터는 payment_status 기준으로 재검증, 처리 행은 sent_at/send_result로 닫음).
  2026-07-30 하루 폐기됐다가 사용자 결정으로 복원. 테이블 없는 환경은 서버 기동/
  redeploy의 테이블 생성 단계가 자동으로 만든다.

## 트러블슈팅

| 증상 | 조치 |
|---|---|
| 헬스체크 실패 | `logs\server.log` 확인. 대부분 .env의 MSSQL_DRIVER 불일치 또는 DB 접근 불가 |
| 서버가 반복해서 죽음 | `Select-String logs\server.log -Pattern "Traceback\|ModuleNotFoundError"` — 새 의존성 미설치(2026-07-22 openpyxl 사례)면 재배포 스크립트로 pip install. `logs\watchdog.log`에서 재기동 이력 확인 |
| EXE에서 "서버에 연결할 수 없습니다" | 방화벽 8010 인바운드, `A10Bridge_Server` 작업 실행 상태 확인 |
| 지사 화면이 비어 있음 | 캐시 백필(`--days 365 --monthly-chunks`) 실행 여부, `A10Bridge_CacheSync` 마지막 실행 로그 확인 |
| 과거 수정 전표가 안 보임 | `A10Bridge_CacheSyncYear` 마지막 실행 결과와 `logs\cache_sync_year.log` 확인. 필요하면 관리자 화면에서 해당 기간만 직접 실행 |
| “다른 전표 동기화가 실행 중” | 정상적인 중복 방지다. 실행 중인 365일/수동 작업 완료 후 다시 시도 |
| 사용자 "OFFICE_NOT_MAPPED" | 소속 지사가 a10_office_map에 없음 (구제주 20 등 폐기 지사). 필요 시 매핑 추가 |
| SYSTEM 계정에서 DB 접속 실패 | .env는 파일 기반이라 계정 무관. ODBC 드라이버가 시스템 전역 설치인지 확인 |
