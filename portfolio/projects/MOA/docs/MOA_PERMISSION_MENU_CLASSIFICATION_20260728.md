# MOA 권한 메뉴 분류 정리

작성일: 2026-07-28
대상: `D:\MOA\a10bridge` (feature/permission-management)

이 문서는 "어떤 메뉴가 **소스상 본사 데이터만** 조회해오는지", "어떤 메뉴가 **조건(office_code)으로 본·지사를 걸러** 가져올 수 있는지", 그리고 "지금 **권한상 꼬여 있는 곳**은 없는지"를 한 번에 정리한다.

---

## 1. 한눈에 — 메뉴별 분류

| 메뉴 | 데스크톱 페이지 | 데이터 소스 | 데이터 성격 | 최종 분류 |
|---|---|---|---|---|
| 감정서 LIST | `/desktop` | apw_masterex (`WHERE Office`) | 지사 스코프 | **지사 노출** |
| 입금 현황 | `/desktop/receivables?mode=received` | a10_receivable_summary + 원본 뷰 | 지사 스코프 | **지사 노출** |
| 미수금 현황 | `/desktop/receivables?mode=outstanding` | 〃 | 지사 스코프 | **지사 노출** |
| 업무실적 보고 | `/desktop/work-report` | build_kapa_rows(office_id) | 지사 스코프(집계) | **재무·관리자 전용** ✅변경 |
| 기간별 매출실적 | `/desktop/sales-stats` | 전표(division_code 필터) | 지사 스코프(집계) | **재무·관리자 전용** ✅변경 |
| 배분 수금 진행 | `/desktop/collection` | collection-progress(office) | 지사 스코프 | **지사 노출 · 평가사 기본 off** ✅변경 |
| **매출 입력(배분)** | `/desktop/allocation` | gaprice outbox | **본사 감정서(01-%)만** | **본사 재무·집행부 전용** ✅변경 |
| **상여** | `/desktop/bonus` | Apw_Mae_GaPrice | **본사 접두사 01-%만** | **본사 재무·집행부 전용** ✅변경 |
| **외상매출금 반제** | `/desktop/banje-receivable` | 반제 데이터 | 본사 재무 관리 화면 | **본사 전용**(전 직원) |
| **선수금 반제** | `/desktop/banje-advance` | 반제 데이터 | 본사 재무 관리 화면 | **본사 전용**(전 직원) |
| 데이터 품질 점검 | `/desktop/data-quality` | a10_voucher_cache(division) | (지사 스코프 가능) | 본사 관리도구(유지) |
| 엑셀 대사 | `/desktop/reconcile` | 업로드 vs 우리 매출(office) | (지사 스코프 가능) | 본사 관리도구(유지) |
| 권한 관리 | `/desktop/permissions` | a10_access_policy | 개인 예외 | 개별 부여(permissionManage) |

> ✅변경 = 재분류 항목.
> - **매출 입력·상여 → 본사 재무·집행부 전용**(본사 데이터 입력화면 → 평가사·일반·지사 미노출).
> - **업무실적보고·기간별 매출실적 → 재무·관리자 전용**(집계/통계라 평가사·일반 미노출; 지사 재무는 자기 지사).
> - **반제(외상/선수금)** 는 요청에 따라 "일단" 본사 전 직원 노출 유지.
>
> 참고 1: **전표 가져오기/생성**(감정서 화면 내 `GET/POST .../vouchers*`)은 별도 메뉴가 아니라 감정서 API의 하위 기능이며 **본사 재무팀만** 허용(`require_head_office_finance`).
>
> 참고 2: 매출입력·상여는 **입력 화면**이다. 조회용 화면은 추후 별도 메뉴로 각각 추가 예정(요건 미확정 — 대상/데이터 결정 후 분류).

---

## 2. 소스상 "본사 데이터만" 조회하는 메뉴 → **본사 전용** (지사 미노출)

지사 사용자가 열어도 자기 지사 데이터가 **구조적으로 나올 수 없는** 메뉴다. 그래서 지사에게는 **메뉴 자체를 숨기고**(nav·권한화면) API도 막는다. 이 중 매출입력·상여는 본사 안에서도 **재무·집행부로 한 번 더** 좁힌다(3-2 참조).

- **매출 입력(salesInput)** — `/api/gaprice/outbox`. 초안 테이블 `a10_gaprice_outbox`가 `generate_gaprice_drafts`에서 `docid_prefixes(db, "10")`의 `01-%`/`01[0-9]%`로만 적재된다. 즉 **본사 감정서만** 담긴다(주석: "배분 승인은 본사 감정서만 해당"). 지사가 열면 0건. → **본사 재무·집행부 전용**(3-2).
- **상여(bonus)** — `_DOCS_SQL`이 `Apw_Mae_GaPrice`를 `Docid LIKE '01-%'`로만 조회하고 `office_code` 파라미터 자체가 없다. → **본사 재무·집행부 전용**(3-2).
- **반제리스트(receivableReconcile / advanceReconcile)** — 데이터는 office로 거를 수 있으나, **업무상 본사 재무 관리 화면**(banje.py 독스트링)으로 확정. **본사 전 직원** 노출 유지(요청상 "일단" 재무·집행부로 좁히지 않음).

정의 위치: `app/services/access_policy.py` → `HEAD_OFFICE_MENU_KEYS = {receivableReconcile, advanceReconcile}` (본사 전 직원), 매출입력·상여는 `HEAD_OFFICE_FINANCE_MENU_KEYS`(3-2).

---

## 3. 조건(office_code)으로 본·지사를 걸러 오는 메뉴 → **지사 노출(자기 지사만)**

`office_code`를 받아 실제 SQL에서 필터하므로, **본사는 전체, 지사는 자기 지사만** 정확히 볼 수 있다.

- 감정서 LIST / 입금현황 / 미수금현황 / 배분 수금 진행(allocation)
- 강제 방식: 라우터에서 `resolve_office_scope(access, office_code)` — 지사 사용자는 자기 지사로 고정, 타지사·전체(all) 요청은 `OFFICE_SCOPE_DENIED(403)`.
- 평가사(다른 직원 조회 권한 없음)는 추가로 `scoped_employee_name`으로 **자기 유치/조사 건만** (감정서·입금·미수금 등 개별 거래 데이터).
- **배분 수금 진행**은 `allocation` 키로 게이트한다(이전엔 `receivables`에 얹혀 있던 것을 재배선). **평가사는 기본 off** — 단 `allocation`이 `available`에는 남아 개별 부여는 가능. 미수금(receivables)과 완전히 분리된다.

정의 위치: `SHARED_MENU_KEYS = {appraisals, payments, receivables, allocation}` (전부 available). 단 평가사 `default_menu_keys`는 `allocation`을 제외해 **기본 off**로 둔다.

---

## 3-2. 재무·관리자 전용 메뉴 (평가사·일반직원 미노출)

"평가사는 자기 것만" 원칙은 **개별 거래 데이터**(감정서·입금·미수금)에만 적용한다. 아래 두 부류는 성격이 달라 재무·관리자로 좁힌다. 공통적으로 권한관리 화면에서 **토글이 안 보이고**(menuPolicy), API도 `MENU_ACCESS_DENIED(403)`로 막힌다.

### (a) 집계/통계 — 업무실적보고 · 기간별 매출실적
개별 거래가 아니라 **지사 단위 집계/통계**라 개인 단위로 좁히면 통계가 성립하지 않는다.
- 볼 수 있는 사람: **본사 재무팀·집행부**(`OPERATIONS_DEPARTMENTS`) **+ 지사 재무**(부서명에 "재무").
- 지사 재무는 `resolve_office_scope`로 **자기 지사만**(타지사·전체는 `OFFICE_SCOPE_DENIED`).
- 프런트: `menuGroups`의 `workReport`/`salesStats` `access: 'financeOnly'`.

### (b) 본사 데이터 입력화면 — 매출입력 · 상여
본사 감정서(01-%)만 다루는 **입력 화면**이라 지사에는 데이터가 없고, 본사 안에서도 입력 권한을 재무·집행부로 제한한다.
- 볼 수 있는 사람: **본사 재무팀·집행부만**. (집계/통계와 달리 **지사 재무도 제외** — 본사 데이터 전용.)
- 프런트: `menuGroups`의 `salesInput`/`bonus` `access: 'headOfficeOperations'`.
- 조회 전용 화면은 추후 별도 메뉴로 추가 예정(요건 미확정).

정의 위치: `HEAD_OFFICE_FINANCE_MENU_KEYS = {feeReview, workReport, salesStats, salesInput, bonus}` (본사 재무·집행부, `department_name in OPERATIONS_DEPARTMENTS`일 때만 부여). 집계/통계는 지사 재무용으로 `BRANCH_FINANCE_MENU_KEYS`에도 포함.

---

## 4. 권한이 어떻게 강제되나 (2단 방어)

1. **메뉴 노출** — `access_policy`의 분류로 계산된 `menu_permissions`를 기준으로:
   - 데스크톱 좌측 메뉴(`context.js`): 권한 없는 링크 숨김(`A10_CAN`).
   - 권한관리 화면(`permissions-preview.js`): **본사** 직원은 역할과 무관하게 **모든 본사 토글을 동일하게 노출**(역할상 안 쓰는 건 기본 off) — 사람마다 창이 달라 헷갈리는 것 방지. **지사** 직원은 본사 전용 메뉴를 **숨김**(available 자체가 없음).
2. **데이터 격리** — 화면 숨김에만 의존하지 않고, **각 라우터가 API에서 다시 검사**:
   `require_menu(...)` + `resolve_office_scope(...)` + `scoped_employee_name(...)`.

---

## 5. 지금 남아 있는 "꼬인 것" / 주의 (개선 후보)

| # | 항목 | 내용 | 심각도 |
|---|---|---|---|
| 1 | **feeReview 화면 누락** | 백엔드 메뉴 14개인데 권한화면 `menuGroups`는 13개(feeReview 없음) → 화면에서 토글 불가 | 중 |
| 2 | ~~배분수금진행 메뉴키 혼동~~ **(해소)** | `/desktop/collection`·`/api/collection-progress`를 `allocation` 키로 재배선하고 평가사 기본 off 처리(2026-07-29). `allocation`이 이제 배분수금진행을 실제로 게이트한다. | ✅ |
| 3 | **평가사 격리 이름 매칭** | 자기 데이터 범위를 `Manager/Charge LIKE '%이름%'`로 판정 → 동명이인·표기변형 취약 (USR_SEQ 기반으로 개선 필요, APW_Charge_IDX.USR_SEQs 활용 가능) | 중 |
| 4 | **본사 평가사 기본메뉴 과다** | 집계/통계(salesStats·workReport)는 재무·관리자 전용으로 분리 완료. 다만 본사 평가사는 여전히 `HEAD_OFFICE_MENU_KEYS`(매출입력·상여·반제)를 **기본 부여** — 지사 평가사와 달리 과다(이번 범위 밖, 필요 시 별도 조정) | 낮 |
| 5 | **조회/처리 권한 미분리** | 메뉴 하나로 조회와 처리(세금계산서 발급 등)가 같이 열림. (이번 범위 밖 — 발급은 손대지 않음) | 낮 |
| 6 | **감사 이력 없음** | `a10_access_policy`는 현재값만 보관(updated_by/at는 있음). 변경 이력 테이블 없음 | 낮 |
| 7 | **레거시 호환 API** | `a10_user_permission` grant/revoke는 지사 제한이 느슨(현재 0행, 신규 화면 미사용 — 사실상 죽은 코드) | 낮 |

> dataQuality/reconcile은 데이터상 지사 스코프가 **가능**하지만, 현재는 본사 관리 도구로 **본사 전용 유지**. 지사 노출이 필요하면 `SHARED`로 옮기고 라우터는 그대로(이미 office 스코프) 두면 된다.

---

## 6. 검증 (실서버 8031, 2026-07-28)

- 지사 평가사(2049·대전세종): `매출입력`=403 MENU_ACCESS_DENIED, `반제`=미부여.
- 본사(1171): 전 메뉴 노출.
- 지사 데스크톱 nav 숨김: 매출입력·상여·데이터품질·엑셀대사·외상/선수금 반제리스트.

### 6-1. 집계/통계 재무·관리자 전용 재검증 (실서버 8031, 2026-07-29)

| 사용자 | 정책 available | sales-stats API |
|---|---|---|
| 본사 재무(1171) | salesStats·workReport = O | 200 |
| 지사 재무(95·office 11) | O | 자기지사(11) 200 / 본사(10) `OFFICE_SCOPE_DENIED` |
| 지사 평가사(2049·office 25) | X | 자기지사(25)도 **403** MENU_ACCESS_DENIED |
| 본사 미분류(299) | X | 미노출 |
| 무인증 | — | **401** |

- 프런트 `menuPolicy('financeOnly')`: 지사평가사·본사평가사·지사일반 = 숨김, 본사 재무·집행부·지사 재무 = 노출 (6/6 통과).
- 전표 가져오기/생성: 본사 재무팀 200 / 지사·본사 비재무 403 `HEAD_OFFICE_FINANCE_ONLY` / 무인증 401.
- 자동 테스트: **149 passed, 2 skipped**(xlrd 옵션).

### 6-2. 매출입력·상여 본사 재무·집행부 전용 검증 (실서버 8031, 2026-07-29)

| 사용자 | 매출입력 `/api/gaprice/outbox` | 상여 `/api/bonus` | 반제 available |
|---|---|---|---|
| 본사 재무(1171) | 200 | 422(메뉴통과·파라미터누락) | O |
| 본사 평가사(22·심사부) | **403** MENU_ACCESS_DENIED | **403** | **O (유지)** |
| 지사 재무(95) | 403 | 403 | X |
| 지사 평가사(2049) | 403 | 403 | X |
| 무인증 | 401 | 401 | — |

- 프런트 `menuPolicy('headOfficeOperations')`: 본사 재무·집행부만 노출, 본사평가사·지사재무·지사평가사 숨김 (6/6 통과).
- 반제(receivableReconcile)는 본사 평가사에게 `available=True`로 **그대로 노출**(요청상 유지).

### 6-3. 배분수금진행 평가사 기본 off + allocation 재배선 검증 (실서버 8031, 2026-07-29)

| 사용자 | allocation 정책 | 배분수금진행 API | 미수금(receivables) API |
|---|---|---|---|
| 본사 재무(1171) | avail=O, eff=O | 200 | 200 |
| 지사 재무(95·office 11) | avail=O, eff=O | 자기지사(11) 200 | 200 |
| 지사 평가사(2049·office 25) | avail=O, **eff=off** | 자기지사도 **403** MENU_ACCESS_DENIED | **200** |
| 본사 평가사(22) | avail=O, **eff=off** | **403** MENU_ACCESS_DENIED | 200 |
| 무인증 | — | **401** | — |

- 핵심: 배분수금진행만 평가사 기본 off, **미수금은 분리 유지**(재배선으로 서로 독립). `allocation`은 available이라 개별 부여 가능.
- 자동 테스트: **169 passed, 2 skipped**(병렬 fee 테스트 포함 전체 통과).

### 6-4. 본사 권한관리 화면 토글 통일 검증 (실서버 8031, 2026-07-29)

본사는 평가사·일반직원도 재무·집행부와 **동일한 토글 목록**을 보되 역할상 기본 off. 지사는 종전대로.

| 사용자 | salesInput | bonus | salesStats | workReport |
|---|---|---|---|---|
| 본사 평가사(22) | 보임/off | 보임/off | 보임/off | 보임/off |
| 본사 일반(299) | 보임/off | 보임/off | 보임/off | 보임/off |
| 본사 재무(1171) | 보임/on | 보임/on | 보임/on | 보임/on |
| 지사 평가사(2049) | 숨김 | 숨김 | 숨김 | 숨김 |
| 지사 재무(95) | 숨김 | 숨김 | 보임/on | 보임/on |

- 구현: `available_menu_keys`가 본사면 `HEAD_OFFICE_FINANCE_MENU_KEYS`까지 포함(부서 무관) + 프런트 `menuPolicy`의 `financeOnly`·`headOfficeOperations`가 본사면 `available=true`.
- **기본값·enforcement 불변**: 평가사 `default_menu_keys`에는 미포함 → 토글은 보이되 off, API는 여전히 403. 개별 부여(override)는 가능.
- 자동 테스트: **200 passed, 2 skipped**(본사 통일 노출 회귀 테스트 포함).

---

## 7. 배포 참고 — `⚙ 권한부여` 화면 교체 & 전표 가져오기 이식

- `/desktop/permissions`(⚙ 링크 대상)가 베이스에서는 옛 `permissions.html`(레거시 grant/revoke + **전표 가져오기**)을 서빙했으나, `e894db7`부터 새 토글 화면 `permissions-preview.html`을 서빙한다.
- 옛 화면에만 있던 **전표 가져오기(대량 캐시 동기화)** 는 `0a4e846`에서 **새 화면 상단 카드로 이식**했다. 로직·엔드포인트(`/api/cache-sync/run`·`/status`)는 그대로.
- 노출 조건: **본사 + `permissionManage`(권한관리) 권한** 사용자에게만 카드 표시(기본 hidden), API도 `require_menu("permissionManage")`로 동일 보호(`bbd3db7` — 카드가 권한관리 화면에 있으므로 dataQuality→permissionManage로 통일, 죽은 버튼 방지). 검증(8031): 본사재무(permissionManage O) 노출·status 200 / 본사평가사·지사재무 403 / 무인증 401.
- 레거시 `permissions.html`/`permissions.js`는 더 이상 서빙되지 않음(어느 라우트에도 연결 안 됨). grant/revoke(레거시 allowlist)는 새 `a10_access_policy` 정책으로 대체됨.

---

## 8. 부서별 기본 메뉴(default_menu_keys) 요약

`available`(토글 노출)과 별개로, 부서 선택 시 **기본으로 켜지는 메뉴**는 다음과 같다. 본사는 화면 통일로 토글 14종이 모두 보이며, 아래는 그중 기본 ON 집합이다.

| 부서 | 기본 ON 메뉴 |
|---|---|
| 본사 재무팀 | 전체(14) |
| **본사 집행부** | 감정서·입금현황·미수금현황·기간별매출실적·매출입력·상여 **(6종)** — `HEAD_OFFICE_EXECUTIVE_MENU_KEYS`, `f98a8e2` |
| **본사 평가사** | 감정서·입금현황·미수금현황 **(3종)** — `APPRAISER_DEFAULT_MENU_KEYS`, `5e9f99f` |
| 본사 일반직원 | 없음(0) |
| **지사 집행부** | 감정서·입금현황·미수금현황 **(3종)** — `dddea77` |
| **지사 평가사** | 감정서·입금현황·미수금현황 **(3종)** — 자기 지사·자기 것만 |
| **지사 재무권한 담당자**(개인 18명) | 감정서·입금·미수금·기간별매출실적·업무실적보고·배분수금진행 **(6종, feeReview 제외)** — `BRANCH_FINANCE_HOLDERS`, `8d98495` |
| **지사 그 외(재무팀·일반직원)** | **없음(0)** — 지사는 재무팀 부서 특례 없음(재무팀 없는 지사도 있어 개인 지정으로 전환, `dddea77`) |

- 집행부 검증(8031): 본사 usr 911·429 = 6종, available=14. pytest 203 passed(내 테스트).

### 지사 단순화(`dddea77`)
- 지사는 **재무팀이 없는 지사도 있어** 재무 특례를 두지 않는다. `available_menu_keys`에서 지사 `BRANCH_FINANCE` 제거 → 지사는 **공용 메뉴(감정서·입금·미수금·배분수금)+권한관리**만 available.
- 기본값: **지사 집행부·평가사 → 3종(감정서·입금·미수금)**, 재무·일반직원 → 0.
- **feeReview(보수기준검토)·workReport·salesStats는 본사 전용** — 지사에는 토글 자체가 안 보인다(`menuPolicy` financeOnly = 본사 전용). feeReview는 `BRANCH_FINANCE_MENU_KEYS`에서도 제거.
- 검증(8031): 지사 재무(1986)=0, 집행부(860)=3, 평가사(333)=3, 일반(1419)=0. 지사 avail=공용5.
- ⚠️ **병렬 fee 세션 충돌**: feeReview를 지사에서 뺐으므로 fee 세션이 지사 재무용으로 만든 가정(`"feeReview" in BRANCH_FINANCE_MENU_KEYS`)과 어긋남 → 해당 fee 테스트 1건 실패. feeReview 본사 전용 방침을 fee 세션과 조율 필요.

### 지사 재무권한 담당자 = 샘플사용자 지정(`8d98495`)
- 지사는 **재무팀 부서가 없거나 담당자가 재무팀이 아닌 경우**가 있어(예: 부산 신명옥=업무1팀, 제주 박지혜=업무팀, 대전세종 김새봄=총무회계팀), 부서가 아니라 **개인(usr_seq)** 으로 재무권한을 지정한다.
- `BRANCH_FINANCE_HOLDERS`(18명, 지사별 1~2명)에 등록된 사람만 `BRANCH_FINANCE_MENU_KEYS` 6종을 받는다. **담당자 변경 시 이 명단만 수정.**
- **재무팀에 있어도 명단에 없으면 0**(비담당), **재무팀이 아니어도 명단에 있으면 6종**(담당).
- 프런트: `availableMenuKeys`·`departmentDefaultMenus`가 서버 정책(`serverPolicy.menus`) 로드 시 **백엔드 available/default를 그대로 신뢰** → 화면이 개인 지정을 정확히 반영(저장 시 유실 방지).
- 검증(8031): 담당(95·216·2016)=6종, 비담당 재무팀(1986)=0. pytest 204 passed.
