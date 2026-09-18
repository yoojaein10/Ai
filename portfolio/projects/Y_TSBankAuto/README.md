# Y_TSBankAuto

Bank24 신규 **탁상 의뢰 PDF**를 안전하게 저장·파싱하고, **PDF에서 파싱했거나 PDF 주소에서
직접 파생한 값만**으로 `dbo.SP_I_APW_TS_Master` 입력 파라미터를 구성하는 Windows 자동화
프로그램.

> ⚠️ **안전 모드 빌드**: 이 저장소의 현재 구현은 실제 Bank24 실행/로그인/조작, 실제 DB
> 연결/SP 호출, INSERT·UPDATE·DELETE·COMMIT, 외부 네트워크 통신을 **하지 않는다.**
> SQL 래퍼와 OUTPUT 처리는 **fake connection / fake cursor**로만 검증한다.

---

## 1. SP 정의는 PROVISIONAL 이다 (반드시 읽을 것)

`SP_I_APW_TS_Master`의 파라미터 개수·이름·타입·길이·기본값과 대상 컬럼 nullable 여부는
**분석 보고서(`은행별_필드매칭_분석.md`) 기반 provisional 정의**다. DB에 접속해 메타데이터로
검증한 값이 **아니다.**

- 코드에서 `ts_db_writer.SP_DEFINITION_SOURCE == "provisional_report"`.
- **실SP 호출 전 메타데이터 검증 필요.** 메타데이터로 확인되어
  `SP_DEFINITION_SOURCE`가 `"metadata"`로 바뀌고 차이가 반영되기 전에는 실제 쓰기(COMMIT)가
  코드 가드(`check_commit_guards`)에 의해 **차단**된다.
- `Addr` 파라미터 길이만 보고서에서 `varchar(40)`으로 명시되어 반영했다. 나머지 길이/타입은
  provisional. 실제 콜레이션이 확인되지 않아 길이 검증 상태는 `provisional`이다(아래 6절).

## 2. 프로젝트 구조

```
gui.py                 # tkinter GUI (드라이런만, DB/PDF/자동화는 워커 스레드)
bank24_automation.py   # Bank24 신뢰 검증 (실제 자동화 비활성, FakeWindow 검증)
models.py              # 공통 RequestModel / StructuredAddress (PII 메모리 전용)
address_mapper.py      # 주소 구조화, RegHist 바인딩 조회(미실행), 길이/인코딩 검증
ts_db_writer.py        # SP 파라미터 조립, OUTPUT 래퍼, COMMIT 가드, fake 실행
pipeline.py            # PDF라인→모델→주소→파라미터 오케스트레이션(GUI/테스트 공용)
config.py              # 비시크릿 설정 + fail-closed 시크릿 로딩(keyring→env)
security.py            # 마스킹, 경로/PDF 안전검증, 시크릿 검출
parsers/
  base.py              # 추출(worker 격리)+은행판별+공통헬퍼
  woori.py kookmin.py saemaeul.py ibk.py nonghyup.py suhyup.py
tests/                 # unittest (fake DB/UI, 격리 가드)
  fixtures/            # 합성·비식별 자료만
  regression_external.py  # 외부 37건 읽기전용 회귀(성공/필드존재율만)
settings.ini.example   # 비시크릿 placeholder
requirements.txt .gitignore README.md
```

> 테스트는 `pytest` 미설치 환경을 고려해 **표준 라이브러리 `unittest`**로 작성했다.
> 실행: `python -m unittest discover -s tests`

## 3. 처리 흐름

1. Bank24 탁상 신규 행에서 PDF 저장(파일명은 무작위 UUID+타임스탬프, PII 미포함; S12).
2. PDF 안전 검증(루트/확장자/`%PDF-`/크기) 후 **worker process**로 텍스트 추출(페이지·문자
   상한, 타임아웃; S6/S11).
3. **헤더로 은행 판별** — 문서 제목으로 탁상/담보를 판별하지 않는다(국민은 제목이
   `담보감정평가의뢰서`라도 탁상). 헤더 은행판별과 Bank24 출처 판별을 분리.
4. 은행별 파서로 공통 `RequestModel` 생성.
5. 은행별 규칙으로 `CustName` 정규화(각 은행 모듈에 격리).
6. 주소 구조화 → (실서버에서는 `APW_RegHist` 바인딩 조회로 `Reg`/`Eub`; **이번 작업은 미조회**).
7. 의뢰번호 기준 실행 내 중복 확인.
8. PDF 파싱값 외 파라미터는 명시적 `NULL`로 구성.
9. `SP_I_APW_TS_Master` 호출(이번 작업은 fake) → `NewMasterID`/`NewSEQ` 수신·표시.
10. 실패 시 롤백, PDF 보존.

## 4. 자문번호 / 고정값

- `@MasterID = NULL` (신규는 MasterID로 조회·매칭하지 않음), `@Office='10'`,
  `@AppCode='300611'`.
- 자문번호는 **클라이언트에서 생성하지 않는다.** SP 내부
  `ufn_NewCreate_Ts_DocID_ByCommon(@Office, @Reg_DateTime)`가 생성하고 `@NewMasterID`,
  `@NewSEQ`로 OUTPUT 반환한다.
- `@HFDocid = NULL` — 우리은행 의뢰번호 `T...`가 있어도 항상 NULL(모든 은행 테스트).
- `Jun_Master`/`Score`는 전달하되 SP가 각각 `0`/`1`을 강제 저장한다.
- `PungCallYn`은 테이블 컬럼이지만 SP 파라미터가 아니므로 전달하지 않는다.

## 5. 개인정보(PII)

- `debtor`, `owner`, `owner_phone`은 **메모리 모델에만** 보존하며 SP로 전송하지 않는다.
- `CustName`/`CustPhone`/`CustCharge`는 은행·영업점·담당자 정보다(PII 아님).
- PII 원문은 로그·콘솔·리포트·스크린샷에 출력하지 않는다(마스킹: 이름 가운데, 전화 끝 4자리,
  주소 상세 번지/동/호). 전체 파싱 dict와 PDF 원문 텍스트를 저장하지 않으며, 모델을
  pickle/JSON/CSV로 영속화하지 않는다.

## 6. 주소 처리 / 길이 / 인코딩

- 주소를 행정구역·법정동/리, 산 여부, 본번/부번, 건물명/동/호로 구조화.
- `Addr`에는 행정구역과 법정동/리까지만. `BUN1`/`BUN2`는 앞자리 0 포함 **4자리 문자열**.
- `Building/Building_Nm/Dong/Ho/AddrEtc`에는 PDF에서 **명확히 식별된 값만** 넣는다(주소
  잔여 문자열을 임의로 채우지 않음). `AddrEtc`는 `외 N필지`처럼 다필지가 명확할 때만.
- `DongHo`는 주소 컬럼으로 쓰지 않는다(항상 NULL).
- **대표 주소 선택 기준**: 한 의뢰에 물건이 여러 개여도 SP 호출 모델은 **하나**만 만든다.
  대표는 **PDF의 첫 번째 물건**(결정적 기준)으로 선택한다. 농협 반복 물건내역, 국민 다물건,
  수협 층수 등 은행별로 처리하며, 나머지 필지·호수는 구조화 가능한 값만 병합한다.
- **길이 검증**: 실제 콜레이션이 확인되지 않아 기본 상태는 `provisional`(문자 길이만 검사).
  CP949를 하드코딩해 가정하지 않는다. codec이 주어지면 바이트 길이 + round-trip 손실을
  검사한다. **길이 초과/인코딩 손실 값은 조용히 자르지 않고 해당 건을 실패 처리**한다.

## 7. 보안 (S1~S18 요약)

- **S1 자격증명**: keyring(Windows 자격증명) → 전용 환경변수 순. `settings.ini`에는 비시크릿만,
  시크릿 fallback 없음. 시크릿 없으면 **fail-closed**(빈 비밀번호/익명 금지). 시크릿 값은
  로깅하지 않는다.
  - 환경변수: `YTS_DB_SERVER/PORT/NAME/USER/PASSWORD`, `YTS_BANK24_ID/PASSWORD`,
    `YTS_ALLOW_COMMIT`.
  - **이번 작업에서는 실제 keyring/환경변수 시크릿을 읽지 않는다.** 단위 테스트는 fake 설정만 주입.
- **S2 .gitignore**: 실 PDF/엑셀/스크린샷/로그/DB 덤프/시크릿을 커밋하지 않는다. `tests/fixtures`만
  예외(합성 자료). `.gitignore`를 보안 경계로 간주하지 않는다.
- **S3 SQL**: 모든 값은 pyodbc `?` 바인딩. 테이블명/SP명은 고정 상수·allowlist. `APW_RegHist`도
  고정 SQL+바인딩. 최소권한 계정 가정.
- **S4 마스킹**: 접속문자열 미로깅(`DRIVER`+`SERVER` 동시 등장 시 전체 차단), PWD/UID/Token 등
  마스킹, traceback 기록 전 마스킹. `NewMasterID`/`NewSEQ`/은행/마스킹된 의뢰번호/결과만 기록.
- **S5 DB 접속**: `Encrypt=yes`, `TrustServerCertificate=false` 기본. TLS 오류 자동 우회 금지.
  - **ODBC 드라이버**: `ODBC Driver 18 for SQL Server` 권장. Driver 17은 `Encrypt` 기본이
    `no`, Driver 18은 기본 `yes`이며 인증서 검증이 강화됨. `TrustServerCertificate=true`는
    중간자 공격에 취약하므로 사용 시 위험을 인지하고 GUI/문서에 표시해야 한다.
  - 실제 연결 전 서버·DB allowlist 검증 필요(이번 작업은 미연결).
- **S6 PDF/경로**: 허용 루트만, resolve 후 루트 내부 검증, symlink/junction/reparse 탈출 거부,
  확장자+`%PDF-` 확인, 최대 50MB/100페이지/추출 5MB, 암호화·손상 건별 실패, 파일명 allowlist
  (`..`/구분자/제어문자/예약장치명/후행점·공백 제거), 최종 경로 재검증, 기존 파일 덮어쓰기 금지.
- **S7 DB 쓰기 가드**: `rollback_test=true`/`autocommit=false` 기본. 이번 작업 SP 호출·쓰기·
  COMMIT 금지. 실제 COMMIT은 **다중 독립 가드 전부 통과 시에만**(아래 9절). CLI 플래그 하나로
  COMMIT 불가.
- **S8 의존성**: `requirements.txt` 버전 고정, lock/hash 방식 안내. PyInstaller에 시크릿/PDF/로그/
  테스트데이터 미포함, **UPX 비활성**, EXE SHA-256 산출 방법 문서화(아래 10절).
- **S9 파일권한**: 설정/로그/PDF 디렉터리는 현재 사용자 전용 권장, 보존·삭제 정책 제공, crash 로그
  마스킹, 메모리 덤프 자동생성 금지.
- **S10 Bank24**: 이번 작업 실제 실행/로그인/조작 금지. 창 제목만으로 신뢰 금지(PID/클래스/
  실행경로 allowlist + 입력 직전 PID/HWND 재검증). 비밀번호 클립보드 금지, 불확실 컨트롤
  send_keys/좌표 금지, pyautogui FAILSAFE 유지, 긴급 중지, 전면창 변경 시 중단, 타 프로세스 종료
  금지, 기존 Bank24 프로세스 연결/종료/전면화 금지.
- **S11 PDF 격리**: PDF 불신, PyMuPDF 버전 고정, worker process + 건별 timeout + 실패 격리,
  worker에 시크릿 미전달, 허용 모델 필드만 반환, PDF 원문 영속화 금지. (강제하지 못한 메모리
  제한을 구현했다고 주장하지 않는다 — 페이지/문자 상한과 타임아웃, 시크릿 미전달만 보장.)
- **S12 PDF 보관**: PDF는 개인정보 파일. 사용자 전용 출력 경로, 네트워크 공유는 명시 설정만,
  보존 기간 설정, 자동 삭제 금지, **파일명 무작위 UUID+타임스탬프**(요청번호 해시는 추측 가능
  하므로 미사용), request_no↔UUID 대응표를 파일로 저장하지 않는다.
- **S13 DB 대상**: 연결 시 `@@SERVERNAME`/`DB_NAME()` 확인 + allowlist 정확 일치, 불일치 시 쓰기
  거부, 운영/테스트 구분, 롤백도 테스트 DB 우선.
- **S14 통신**: BankOnline/KAPA 호출·불필요 HTTP·텔레메트리·업데이트 확인 금지. urllib/requests
  추가 없음. 외부 네트워크 통신 없음.
- **S15 시크릿 검사**: `security.scan_text_for_secrets` 제공(값 미출력, 파일/줄/종류만). 변수명·
  placeholder와 실제 값을 구분.
- **S16 개발환경**: 전역 설치 금지(프로젝트 `.venv`만). 현재 도구로 구현. pytest 미설치 →
  unittest 사용.
- **S17 파일시스템**: 기존 파일 보존, 프로젝트 밖 신규 파일 금지(tmp도 내부), 원자적 저장 지향,
  충돌 시 중단. git init/commit/push 안 함.
- **S18 테스트 격리**: fake DB/UI. 실제 `pyodbc.connect`/네트워크/`requests` 호출 시 테스트 실패
  (`tests/_fakes.install_isolation_guards`). 실제 환경변수/keyring 시크릿 미사용.

## 8. 설정

`settings.ini`(비시크릿)은 `settings.ini.example`을 복사해 작성. 시크릿은 keyring/환경변수로만.

## 9. 향후 실제 COMMIT 조건 (전부 충족 시에만)

`ts_db_writer.check_commit_guards`가 검사한다. 하나라도 실패하면 롤백:
1. `rollback_test=false`
2. `YTS_ALLOW_COMMIT == I_UNDERSTAND_PRODUCTION_WRITE`
3. GUI에서 `실서버 저장` 직접 입력
4. 서버·DB 표시
5. 서버·DB allowlist 정확 일치
6. 대상 건수 확인
7. 실행 내 중복 검사 통과
8. 개인정보 없는 감사 로그
9. (추가) **SP 메타데이터 검증 완료**(`SP_DEFINITION_SOURCE == "metadata"`)

### 알려진 한계
- 신규는 MasterID가 없고 HFDocid를 저장하지 않으므로 **실행 간 중복키가 없다.**
  동일 PDF를 재실행하면 **중복 INSERT가 가능**하다(GUI/README에 표시). 실행 내 중복은 의뢰번호로
  검사하지만, 실행 간 중복은 운영 메타데이터 검증 후 별도 정책이 필요하다.

## 10. 배포(EXE) 메모

- `.venv`에서 `pyinstaller`로 빌드(전역 설치 금지). UPX 기본 비활성(`--noupx`).
- 시크릿/PDF/로그/테스트 데이터를 번들에 포함하지 않는다.
- 무결성: `Get-FileHash dist\Y_TSBankAuto.exe -Algorithm SHA256`.

## 11. 테스트 / 회귀

```
python -m unittest discover -s tests           # 단위(82) — fake DB/UI
python tests\regression_external.py            # 외부 37건 읽기전용 회귀(성공/필드존재율만)
```
외부 회귀는 `D:\AI\Claude\Y_BankAuto\탁상`의 PDF를 **읽기 전용**으로 사용하며 신규 프로젝트로
복사하지 않는다(6/9/40 제외, 37건). 원문 정답/PII는 저장하지 않고 성공 여부와 필드 존재율만
출력한다. Reg/Eub DB 조회 테스트는 이번 작업에서 실행하지 않는다.

## 12. SP 매핑표

`은행별_필드매칭_분석.md`와 본 README, 그리고 `ts_db_writer.INPUT_PARAM_SPECS`(정의 출처 표시)
참조. 모든 정의는 위 1절대로 **provisional**이며 실SP 호출 전 메타데이터 검증이 필요하다.
