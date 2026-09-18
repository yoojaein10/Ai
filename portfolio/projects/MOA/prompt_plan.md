# 일계표 대사(은행 거래 ↔ 아마란스 보통예금 전표) 계획 — 2026-08-26

## Context

재무팀은 매일 사이버브랜치 거래내역 엑셀(예: `0825ㅁㄱ.xls`)에 메모를 달아 아마란스 **일월계표**(회계단위별 계정 차·대변 합계)와 손으로 맞춘다. 사용자 결정(2026-08-26):
1. **입금·출금 모두** 대사한다.
2. **지사 계좌도** 지사 회계단위 전표와 맞춘다.
3. 메뉴는 "입금·미수" 그룹, **이일우(813)·장세희(1171) 두 사람만** 보이게 한다.

실측(8/25): 사이버브랜치 본사 계좌 입금 45건 711,350,107 = 일계표 본사 보통예금 차변 계, 출금 40건 1,656,953,214 = 대변 계 — **둘 다 원 단위 일치**. 원천은 이미 MOA에 있다(사이버브랜치 `CB2_ACCT_HIS` 준실시간, `a10_voucher_cache` 10분 주기·전 회계단위). 아마란스 화면을 긁을 필요 없음.

이름: 사이드바 라벨 **"일계표 대사"** (라벨 "입금 대사"는 `/desktop/gamjun-chat`(`depositMatch`)이 이미 씀), 메뉴 키 `bankReconcile`, 화면 `/desktop/bank-reconcile`, API `/api/bank-reconcile`.

## 사양

### 원천
- **은행 쪽**: `CB2_ACCT_HIS` + `CB2_ACCT`(닉네임). `INOUT_GUBUN` `'2'`=입금, `'1'`=출금, `TX_AMT` 양수. `deposit_source.fetch_transactions(date_from, date_to, inout=None)`로 일반화(기존 `fetch_deposits`는 `inout='2'` 래퍼, 동작 불변). 읽기 전용(테스트가 UPDATE/INSERT 금지 고정).
- **전표 쪽**: `a10_voucher_cache` `account_code='1030000'`, `debit_credit '3'`=차변(입금)/`'4'`=대변(출금), 전 `division_code`. 신선도 = `MAX(synced_at)`(10분 배치) 화면에 표시.
- **계좌 ↔ 거래처**: `a10_bank_account_map(bank_cd, acct_no → partner_code)`. 8월 활동 계좌 28개 중 22개 매핑, **6개 미매핑**(북부 1946…7375, 신한서초남 1400…5335, 창신동 1400…2827, 이수역 0439…8465, 부천제일 9002…4196, 2060…2672). `seed_bank_account_map.py` 투표를 **출금·대변 포함, 메모 무관**으로 넓혀 채우고, 남으면 `--add bank_cd acct_no partner_code` 수동 등록. 화면은 미매핑 계좌를 "매핑 필요" 블록으로 따로 보여 준다(숨기지 않음).
- **회계단위**: 계좌에는 회계단위가 없다 → 전표줄의 `division_code`로 표시·필터. 같은 계좌에 여러 회계단위 전표가 섞이면 합쳐서 대사하고 회계단위별 소계를 함께 보인다(본사 소계 = 일계표 본사 값).

### 대사 규칙 (계좌 × 일자 단위, 순수 함수)
1. **합계 대사**: 입금 합계 vs 차변 합계, 출금 합계 vs 대변 합계 → 차이. 상태 = `일치` / `합계 일치·건수 다름` / `차이 N원`.
2. **건별 짝짓기** (설명용, 합계가 어긋났을 때 어디가 빠졌는지 찾기 위해):
   a. 배치 묶음: `a10_deposit_outbox`(status S)에서 같은 `menu_sq`·`tx_day`·계좌인 행들의 합 ↔ 전표줄 1개 (약식·지사·급여 묶음).
   b. 1:1 정확 금액 (같은 금액 여럿이면 적요 토큰/관리번호 일치 우선, 그래도 남으면 순서대로).
   c. 잔여 소집합 합(≤6개, 양방향).
   d. 남은 것 = "전표 없는 거래" / "거래 없는 전표줄".
3. 미승인 전표(`document_status='0'`)는 포함하되 표시(기본) — 재무팀 확인 항목.
4. 카드사 결제 출금 등 보통예금이 아닌 계정으로 나가는 거래는 없다(전부 1030000) — 실측으로 확인, 예외가 나오면 "거래 없는 전표줄"이 아니라 "다른 계정" 분류로 노출.

### 화면 `/desktop/bank-reconcile`
- 조회: 일자(기본 전일) 또는 기간(≤31일), 회계단위(전체/본사/지사별), "차이만 보기".
- 요약 띠: 입금(은행 건·합 / 전표 건·합 / 차이), 출금(같음), 본사 소계(=일계표 값), 전표 캐시 갱신 시각.
- 본표: 계좌(닉네임·은행·끝 4자리) × [입금: 은행/전표/차이] [출금: 은행/전표/차이] 상태 배지. 행 펼치면 짝 안 맞은 건 양쪽 목록(일자·적요·메모·금액·전표번호·회계단위).
- "매핑 필요" 블록: 매핑 없는 계좌의 거래 합계와 후보 거래처(전표 캐시 partner_name).
- 엑셀 내보내기: 계좌 요약 + 미일치 건 2시트.
- 권한: `A10_READY` 뒤 본사 아님 → 안내문. 메뉴는 권한 키로 숨김(fail-closed 기존 방식).

### 권한(두 사람만)
- `access_policy.MENU_KEYS`에 `bankReconcile`, `HEAD_OFFICE_PRIVILEGED_MENU_KEYS`(본사·개별권한)에 추가. **어떤 묶음(role)에도 넣지 않는다.**
- 개인 예외 `a10_access_policy.menu_overrides_json={"bankReconcile": true}` 를 813·1171에 — `scripts/seed_bank_reconcile_access.py`가 `permissions.save_access_policy()`(변경 이력 기록)로 넣는다. 권한관리 화면에서도 켜고 끌 수 있다(코드 박기 금지 관례 유지).
- 라우터 게이트: `require_menu("bankReconcile")` + `require_operations_user`.

## 파일
| 파일 | 내용 |
|---|---|
| `app/services/deposit_source.py` | `fetch_transactions(date_from, date_to, inout=None)`; `fetch_deposits` = 래퍼 |
| `app/services/bank_reconcile.py` (신규) | 리더: 은행 거래, 1030000 전표줄, 계좌 매핑, outbox 묶음; `build_report(db, date_from, date_to, division)` |
| `app/services/bank_reconcile_match.py` (신규, 순수) | `match_account_day(bank_rows, voucher_rows, bundles)` → 합계·짝·잔여 |
| `app/routers/bank_reconcile.py` (신규) | `GET /api/bank-reconcile`, `GET /api/bank-reconcile/export.xlsx` |
| `app/main.py` | 라우터 등록, `@app.get("/desktop/bank-reconcile")` → `_screen("bank-reconcile.html")` |
| `app/services/access_policy.py` | `MENU_KEYS`, `HEAD_OFFICE_PRIVILEGED_MENU_KEYS` |
| `desktop/ui/context.js` | `A10_MENU` 입금·미수 그룹 `{label:'일계표 대사', href:'/desktop/bank-reconcile'}`, `menuKeyForUrl` |
| `desktop/ui/permissions-preview.js`, `permission-roles.js` | 키·이름(사이드바와 글자 동일)·access `headOfficePrivileged` |
| `desktop/ui/bank-reconcile.html/.js` (신규) | 화면 (`reconcile.*` 골격, `?v=` 붙임, `A10_COLUMN_RESIZE`) |
| `scripts/seed_bank_account_map.py` | 투표 범위 확장(출금·대변, 메모 무관), `--add` |
| `scripts/seed_bank_reconcile_access.py` (신규) | 813·1171 개인 예외 |
| tests | `test_bank_reconcile_match.py`(8/25 모양 골든: 약식 17건→10줄, 급여 묶음, 1:1, 잔여), `test_bank_reconcile_service.py`(sqlite: 캐시·매핑·outbox 픽스처, 미매핑 블록), `test_bank_reconcile_router.py`(게이트 401/403·게이트 수), `test_bank_reconcile_screen.py`(`_screen`·메뉴 키·`?v=`·권한화면 이름), `test_branch_scope.HEAD_OFFICE_ONLY` 갱신, `test_deposit_source` 읽기전용·래퍼 불변 |

새 테이블 없음. 파일당 400줄 이하.

## 단계
0. **권한 배선** — 키·메뉴·권한화면·테스트(`test_permission_wiring`·`menu_names`·`branch_scope` 통과). 시드 스크립트.
1. **원천 + 매칭 엔진(TDD)** — `fetch_transactions`, 리더, 순수 매칭. 골든: 8/25 본사 입금 711,350,107·출금 1,656,953,214 재현, 국민남부 약식 17→10줄 묶음, 국민선릉 급여 36건 vs 21줄 "합계 일치·건수 다름".
2. **API + 화면** — 조회·펼침·엑셀. Playwright 스모크(`?usr=813`).
3. **실측·시딩** — 8/20~8/26 전 계좌 대조, 미매핑 6계좌 채움, 차이 나는 날 원인 분류(미승인·수기·타계정).
4. **배포** — dist, 서버 복사·재시작, 두 사람 권한 시드, 첫 주 재무팀 병행.

## 검증
- `python -m pytest tests/test_bank_reconcile*.py tests/test_permission*.py tests/test_branch_scope.py tests/test_screen_no_cache.py -q` + 전체 스위트.
- 실측 스크립트 `scripts/bank_reconcile_check.py --date 2026-08-25` → 본사 차·대변 합계가 일계표와 같음을 출력.

## 위험·미결(기본값)
- 계좌 매핑 6개는 시딩 후 남으면 수동 등록(기본: 화면에 "매핑 필요"로 노출, 막지 않음).
- 같은 날 같은 계좌·같은 금액 여러 건의 1:1 짝은 임의성 있음 — 합계 대사에는 영향 없음(설명용).
- 전표 캐시 10분 지연: 방금 보낸 전표는 "전표 없는 거래"로 보일 수 있음 → 갱신 시각 표시 + "지금 갱신" 버튼은 이번 범위 밖(배치가 곧 따라잡음).
- 일별 자동 스냅샷·알림은 이번 범위 밖(필요하면 2차).
- 예상 규모: 서비스·화면·테스트 약 12파일, 1.5~2일.
