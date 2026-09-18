# HR Operations 확장 모듈 (PHASE 12~16)

> 대상: `D:\AI\INSA` 인사관리 시스템에 HR Operations 기능 추가  
> 전제: `CLAUDE.md` 규칙 준수 + `insa_eval_prompts_v3.md` 완료 권장  
> 스택/규칙: sync routes, `insa_` 접두사, Immutable, Zustand UI only, React Query server only

---

## 🎯 개요

### 추가할 기능
1. **연차 관리** — 회계연도 기준 (매년 1월 1일 일괄 리셋)
2. **전자결재 시스템** — 회사 자체 구축 (다단계 결재선)
3. **근태 전자결재** — 연차/반차/공가/병가/경조휴가/도시업무(외근)
4. **출장명령부** — 결재 + 자체 공유 캘린더 연동
5. **근로계약서 + 전자서명** — 사용자 사인, 인사정보 자동 반영

### 구조 전략
```
PHASE 12 — 전자결재 기반 시스템 (모든 결재 기능의 공통 기반)
   ↓
PHASE 13 — 회사 공유 캘린더 (연차/출장 표시 대상)
   ↓
PHASE 14 — 연차 관리 (회계연도 리셋 + 발생 규칙)
   ↓
PHASE 15 — 근태 전자결재 (휴가 신청 → 결재 → 자동 차감)
   ↓
PHASE 16 — 출장명령부 (결재 + 캘린더)
   ↓
PHASE 17 — 근로계약서 + 전자서명 (인사정보 자동 반영)
```

### 공통 규칙 (모든 PHASE)
- Backend: sync routes (`def` 사용, `async def` 금지)
- DB: `insa_` 접두사 엄수
- Immutable 패턴
- Zustand UI only / React Query server only
- pytest + Vitest 커버리지 70%+
- 커밋: `feat|fix|refactor|docs|test|chore: <description>`

### 한국 근로기준법 참고
- **연차**: 회계연도 기준 1월 1일 일괄 리셋 (관리 편의 + 근로자 유리 원칙)
  - 1년 미만: 매월 1일 발생 (최대 11일)
  - 1년 이상: 15일 기본, 3년 이상부터 2년마다 +1일 (최대 25일)
  - 전년도 80% 이상 출근 조건
- **근로계약서**: 근로 종료 후 3년 보관 의무
- **전자서명**: 본인 인증 + 타임스탬프 + IP 로그 보관 시 효력 인정

---

## 📌 사전 준비

```bash
cd D:\AI\INSA
claude
```

---

## PHASE 12 — 전자결재 기반 시스템

```
회사 자체 전자결재 시스템 기반을 구축해줘. 
이후 연차, 출장, 근로계약서 등 모든 결재가 이 시스템 위에서 동작한다.
최상위 규칙 엄수 (sync routes, insa_ 접두사, Immutable).

=== 설계 원칙 ===
- 모든 결재 문서는 "문서 타입 + 양식 + 결재선"으로 구성
- 문서 타입별로 결재선이 다를 수 있음
- 결재선은 사전 등록(조직별 기본) + 문서별 커스터마이징 가능
- 결재 순서는 직렬(순차) 기본, 병렬 옵션 추후 확장
- 결재 상태 변경 이력 필수 (감사 대응)

=== DB 모델 ===

1. insa_approval_doc_type (문서 타입 마스터)
   id, code, name, category ('HR'|'ATTENDANCE'|'TRAVEL'|'CONTRACT'|'OTHER'),
   description, is_active, created_at
   
   초기 데이터:
   - ATT_LEAVE (휴가신청서)
   - ATT_FIELD (도시업무/외근 신청서)
   - TRAVEL_ORDER (출장명령부)
   - CONTRACT_LABOR (근로계약서)

2. insa_approval_line_template (결재선 템플릿)
   id, doc_type_id (FK), name, 
   scope ('GLOBAL'|'DEPT'), scope_ref (부서 id, GLOBAL이면 null),
   is_default, created_at
   
   예: "경영지원부 휴가신청서 기본 결재선"

3. insa_approval_line_step (결재선 단계)
   id, template_id (FK), step_order (1, 2, 3...),
   approver_type ('USER'|'ROLE'|'POSITION'|'DEPT_HEAD'|'DIRECT_MANAGER'),
   approver_ref,  -- user_id 또는 role 코드 등
   is_required  -- 필수/참조
   
   예: 1단계=DIRECT_MANAGER, 2단계=DEPT_HEAD, 3단계=USER(HR팀장)

4. insa_approval_doc (결재 문서 본문)
   id, doc_type_id (FK), doc_no (자동 채번: YYYYMMDD-0001),
   title, drafter_id (FK → insa_employee),
   content (JSON, 폼 데이터),
   status ('DRAFT'|'PENDING'|'IN_PROGRESS'|'APPROVED'|'REJECTED'|'RECALLED'),
   current_step, total_steps,
   drafted_at, completed_at

5. insa_approval_step_history (결재 진행 이력)
   id, doc_id (FK), step_order,
   approver_id (FK),
   action ('PENDING'|'APPROVED'|'REJECTED'|'DELEGATED'|'COMMENTED'),
   comment, acted_at

6. insa_approval_attachment (첨부파일)
   id, doc_id (FK), filename, filesize, 
   filepath, uploaded_at

=== Pydantic 스키마 (backend/app/schemas/) ===
approval_doc_type.py, approval_line.py, approval_doc.py 등
Base, Create, Update, Response 각각

=== 서비스 (backend/app/services/) ===
approval_service.py (Immutable):
- submit_doc(doc_id, user_id): DRAFT → PENDING, 1단계 결재자 알림
- approve_step(doc_id, user_id, comment): 다음 단계로 진행 또는 완료
- reject_step(doc_id, user_id, comment): REJECTED 처리, 기안자 알림
- recall_doc(doc_id, user_id): 진행 중 회수 (PENDING일 때만)
- get_inbox(user_id): 내가 결재해야 할 문서 목록
- get_drafts(user_id): 내가 기안한 문서 목록
- resolve_approver(step): approver_type에 따라 실제 user_id 도출
  - DIRECT_MANAGER: insa_employee의 상사 매핑 활용
  - DEPT_HEAD: 부서장
  - ROLE: 해당 role 가진 user 중 한 명 (규칙 필요)

[트랜잭션 주의]
결재 액션은 단일 트랜잭션 내에서:
1. step_history 기록
2. doc.current_step/status 업데이트
3. 다음 결재자 알림 생성 (있으면)

=== API (sync) ===
/api/v1/approval/

- GET    /doc-types                     # 문서 타입 목록
- GET    /doc-types/{id}                # 특정 타입 상세
- POST   /doc-types                     # (admin only)

- GET    /lines?doc_type_id=            # 결재선 템플릿 목록
- POST   /lines                         # 결재선 템플릿 생성
- PUT    /lines/{id}
- DELETE /lines/{id}

- GET    /docs/inbox                    # 내 결재함
- GET    /docs/drafts                   # 내 기안함
- GET    /docs/{id}                     # 문서 상세 + 이력
- POST   /docs                          # 기안 (임시저장 가능)
- PUT    /docs/{id}                     # 수정 (DRAFT 상태만)
- POST   /docs/{id}/submit              # 상신
- POST   /docs/{id}/approve             # 승인
- POST   /docs/{id}/reject              # 반려
- POST   /docs/{id}/recall              # 회수
- GET    /docs/{id}/history             # 진행 이력
- POST   /docs/{id}/attachments         # 첨부파일 업로드

=== 프론트엔드 (frontend/src/pages/approval/) ===

[페이지]
- Inbox.tsx             # 결재함 (대기/진행/완료 탭)
- Drafts.tsx            # 기안함
- DocDetail.tsx         # 문서 상세 (결재 이력 포함)
- DocTypeMgmt.tsx       # 문서 타입 관리 (admin)
- LineTemplateMgmt.tsx  # 결재선 템플릿 관리 (admin)

[공통 컴포넌트]
- ApprovalLineView.tsx  # 결재선 시각화 (가로 스텝퍼)
  Props: steps, currentStep, history
  상태별 색상: 대기(회색)/진행중(파랑)/승인(초록)/반려(빨강)

[React Query hooks]
frontend/src/hooks/approval/
- useInbox, useDrafts, useDocDetail
- useSubmitDocMutation, useApproveStepMutation, useRejectStepMutation

[Zustand] (UI 상태만)
approvalUIStore: 선택된 문서 id, 결재 코멘트 모달 open 상태 등

[사이드바 메뉴 추가]
전자결재
  ├ 결재함 (뱃지: 미결재 건수)
  ├ 기안함
  ├ 문서 타입 관리 (admin)
  └ 결재선 템플릿 (admin)

=== 공통 컴포넌트: 문서 본문 렌더러 ===
각 문서 타입별로 서로 다른 form을 렌더링해야 함.
DocDetail.tsx 내부에서 doc_type에 따라 적절한 폼 컴포넌트 로드:

frontend/src/components/approval/forms/
- LeaveRequestForm.tsx   (PHASE 15에서 구현)
- FieldWorkForm.tsx      (PHASE 15에서 구현)
- TravelOrderForm.tsx    (PHASE 16에서 구현)
- LaborContractForm.tsx  (PHASE 17에서 구현)

PHASE 12에서는 interface만 정의:
interface ApprovalFormProps {
  mode: 'draft' | 'view';
  initialData?: any;
  onChange?: (data: any) => void;
  readOnly?: boolean;
}

=== 알림 연동 ===
기존 PHASE 8 (알림 시스템)이 있으면 연동:
- 결재 요청 받음
- 내 문서 승인/반려됨
없으면 일단 인앱 뱃지(결재함 카운트)로 대체.

=== 테스트 ===
pytest:
- 결재 순차 진행 (step 1 → 2 → 3)
- 반려 시 상태 전이
- 회수 (PENDING 상태만 가능)
- 결재자 해석 (DIRECT_MANAGER, DEPT_HEAD 등)
- 문서번호 자동 채번 (YYYYMMDD-0001)
- 트랜잭션 원자성

Vitest:
- Inbox 탭 전환
- 결재 승인/반려 모달
- ApprovalLineView 상태별 색상

커버리지 70%+

=== 완료 후 ===
시나리오:
1. admin이 "휴가신청서" 문서 타입 + 결재선 등록
2. 사원이 테스트 문서 기안 → 상신
3. 팀장 결재함에 뜸 → 승인
4. 부서장 결재함에 뜸 → 반려
5. 사원 기안함에서 반려 사유 확인

Git 커밋:
git commit -m "feat: add electronic approval foundation (doc types, lines, workflow)"
git commit -m "feat: add approval inbox and drafts UI"
```

---

## PHASE 13 — 회사 공유 캘린더

```
회사 내부 공유 캘린더를 구축해줘. 
연차, 출장, 회의 등 전사 일정을 공유.
최상위 규칙 엄수.

=== DB 모델 ===

1. insa_calendar (캘린더 채널)
   id, name, color_hex, 
   scope ('COMPANY'|'DEPT'|'PERSONAL'),
   scope_ref (부서 id 등, COMPANY면 null),
   is_default, created_by, created_at

2. insa_calendar_event (일정)
   id, calendar_id (FK), 
   title, description,
   event_type ('MANUAL'|'LEAVE'|'TRAVEL'|'MEETING'|'OTHER'),
   source_type ('APPROVAL_DOC'|'MANUAL'),
   source_ref (doc_id 등, 자동 생성 시 추적),
   start_at, end_at, all_day,
   owner_id (FK → insa_employee),
   location, 
   visibility ('PUBLIC'|'DEPT'|'PRIVATE'),
   created_at, updated_at

3. insa_calendar_event_participant (참석자)
   id, event_id (FK), emp_id (FK),
   role ('ORGANIZER'|'REQUIRED'|'OPTIONAL'),
   response ('PENDING'|'ACCEPTED'|'DECLINED'|'TENTATIVE')

=== API (sync) ===
/api/v1/calendar/

- GET    /calendars                      # 내가 볼 수 있는 캘린더 목록
- POST   /calendars                      # 캘린더 생성
- PUT    /calendars/{id}
- DELETE /calendars/{id}

- GET    /events?start=&end=&calendar_ids=   # 기간 내 이벤트
- POST   /events                         # 수동 생성
- PUT    /events/{id}
- DELETE /events/{id}
- POST   /events/{id}/participants       # 참석자 추가
- PUT    /events/{id}/respond            # 참석 응답

- GET    /events/me?start=&end=          # 내 일정만
- GET    /events/dept/{dept_id}?start=&end=  # 부서 일정

=== 권한 ===
- PUBLIC 이벤트: 전사 조회 가능
- DEPT 이벤트: 해당 부서원만
- PRIVATE 이벤트: owner + 참석자만

=== 다른 모듈에서 이벤트 자동 생성 ===
PHASE 15 (휴가), PHASE 16 (출장)에서 결재 완료 시:
- 서비스 함수: create_event_from_approval(doc_id)
- 해당 문서의 owner, 기간, 종류 기반으로 event 생성
- event.source_type = 'APPROVAL_DOC', source_ref = doc_id
- 결재 회수/취소 시 연결된 event 자동 삭제

=== 프론트엔드 ===

[라이브러리]
FullCalendar (react) 사용 권장:
- 월/주/일 뷰 지원
- 드래그 생성, 리사이즈, 클릭 핸들러
- 기존 프로젝트에 캘린더 라이브러리 있으면 재사용

설치:
@fullcalendar/react, @fullcalendar/daygrid, 
@fullcalendar/timegrid, @fullcalendar/interaction

[페이지]
frontend/src/pages/calendar/
- CompanyCalendar.tsx   # 회사 전체 캘린더
- MyCalendar.tsx        # 내 일정
- DeptCalendar.tsx      # 부서 캘린더
- EventDetailModal.tsx  # 이벤트 상세/편집

[필터 UI]
- 캘린더 채널별 체크박스 (색상 표시)
- 부서 필터
- 이벤트 타입 필터 (휴가만 보기 등)

[React Query hooks]
useCalendars, useEvents(start, end, filters), 
useEventMutation, useParticipantResponseMutation

[사이드바]
캘린더
  ├ 회사 캘린더
  ├ 내 일정
  └ 부서 캘린더

=== 이벤트 색상 규칙 (제안) ===
- 연차: 파랑
- 반차: 하늘색
- 공가: 연두
- 병가: 주황
- 경조휴가: 보라
- 도시업무(외근): 노랑
- 출장: 빨강
- 회의: 회색

=== 테스트 ===
pytest:
- 이벤트 CRUD
- 권한 분기 (PRIVATE 접근 제한)
- 참석자 응답
- 기간 필터

Vitest:
- FullCalendar 렌더링
- 이벤트 클릭 → 상세 모달
- 필터 인터랙션

커버리지 70%+

=== 완료 후 ===
시나리오:
1. HR이 "공휴일" 이벤트를 회사 캘린더에 등록
2. 팀장이 "팀 회의" 이벤트 생성 + 참석자 초대
3. 사원이 참석 응답
4. 내 캘린더에서 본인 일정 확인

Git 커밋:
git commit -m "feat: add shared company calendar (channels, events, participants)"
git commit -m "feat: integrate calendar into sidebar with color-coded event types"
```

---

## PHASE 14 — 연차 관리 (회계연도 기준)

```
연차 관리 시스템을 구현해줘. 회계연도 기준 (매년 1월 1일 일괄 리셋).
최상위 규칙 엄수.

=== 설계 원칙 ===
- 회계연도 기준: 매년 1월 1일 일괄 리셋
- 1년 미만 입사자: 매월 1일씩 발생 (매월 1일에 +1, 최대 11일)
- 1년 이상 근속: 15일 기본 + (근속 3년 이상부터 2년마다 +1, 최대 25일)
- 전년도 80% 이상 출근 조건 (단순화: 관리자가 제외 여부 수동 체크)
- 전년도 연차 이월 규칙: 기본 "사용 촉진제 적용으로 이월 없음" (관리자 설정 가능)

=== DB 모델 ===

1. insa_leave_type (휴가 종류)
   id, code, name, 
   deduct_from ('ANNUAL'|'SEPARATE'),  -- ANNUAL=연차에서 차감, SEPARATE=별도
   unit ('DAY'|'HALF_DAY'|'HOUR'),
   is_paid, requires_evidence,
   sort_order, is_active
   
   초기 데이터:
   - ANNUAL (연차) — ANNUAL, DAY
   - HALF_AM (오전반차) — ANNUAL, HALF_DAY
   - HALF_PM (오후반차) — ANNUAL, HALF_DAY
   - OFFICIAL (공가) — SEPARATE, DAY
   - SICK (병가) — SEPARATE, DAY
   - FAMILY (경조휴가) — SEPARATE, DAY (requires_evidence=true)
   - FIELD (도시업무/외근) — SEPARATE, DAY (근태 처리용, 연차 아님)

2. insa_leave_balance (연차 잔여)
   id, emp_id (FK), year,
   initial_days,        -- 해당 연도 초기 발생 연차
   carried_over_days,   -- 전년도 이월 (기본 0)
   additional_days,     -- 특별 부여 (관리자)
   used_days,           -- 사용한 일수
   scheduled_days,      -- 결재 진행 중 (승인 전, 표시용)
   updated_at
   
   remaining_days = initial + carried_over + additional - used
   available_days = remaining - scheduled (실제 신청 가능한 일수)

3. insa_leave_accrual_rule (연차 발생 규칙)
   id, year, 
   under_1year_monthly INT,    -- 1년 미만 월 발생: 1
   under_1year_max INT,        -- 최대: 11
   base_days INT,              -- 기본: 15
   tenure_bonus_start_years INT, -- 3 (3년부터)
   tenure_bonus_interval INT,    -- 2 (2년마다)
   max_days INT,                 -- 25
   updated_by, updated_at

4. insa_leave_transaction (연차 변동 이력)
   id, emp_id (FK), year,
   transaction_type ('INITIAL_GRANT'|'MONTHLY_GRANT'|'ADDITIONAL'|'USE'|'CANCEL'|'EXPIRE'|'CARRY_OVER'|'ADJUST'),
   amount,  -- 양수=증가, 음수=감소
   reason,
   ref_doc_id (FK → insa_approval_doc, 휴가신청서 연결 시),
   balance_after,  -- 거래 후 잔액
   created_by, created_at

=== 연차 발생 로직 (backend/app/services/leave_service.py) ===

1. create_initial_balance(emp_id, year):
   - 입사일 기준 year 초 현재 근속 연수 계산
   - 근속 < 1년:
     * 입사 후 경과 개월 × 1일 (최대 11)
   - 근속 >= 1년:
     * base_days(15) + (tenure - 3) // 2 if tenure >= 3 else 0
     * max_days(25) 상한
   - insa_leave_balance 생성 + transaction 기록 ('INITIAL_GRANT')

2. monthly_accrual(year, month):
   - 1년 미만 입사자 중 아직 11일 미달인 사람만
   - +1일 부여 + transaction 기록 ('MONTHLY_GRANT')

3. yearly_reset(year):
   - 1월 1일 실행 (스케줄러 또는 수동)
   - 전 사원 대상 create_initial_balance(emp_id, year) 호출
   - 전년도 잔여 연차 처리:
     * 사용촉진제 기본 적용 시: carried_over_days = 0
     * 미적용 설정 사원: carried_over_days = 전년도 remaining
     * transaction 기록 ('CARRY_OVER' 또는 'EXPIRE')

4. consume_leave(emp_id, leave_type, days, ref_doc_id):
   - balance.used_days += days
   - transaction 기록 ('USE')
   - remaining < 0이면 에러

5. release_leave(ref_doc_id):
   - 결재 반려/회수 시 사용한 일수 되돌리기
   - balance.used_days -= days
   - transaction 기록 ('CANCEL')

=== 스케줄러 ===
APScheduler 또는 간단한 cron:
- 매월 1일 00:00: monthly_accrual(year, month)
- 매년 1월 1일 00:01: yearly_reset(year)

기존 프로젝트에 스케줄러 있으면 재사용, 없으면 APScheduler 추가.

⚠️ 스케줄러는 중복 실행 방지 필수 (lock 테이블 또는 멱등 처리).

=== API (sync) ===
/api/v1/leave/

- GET  /types                         # 휴가 종류 목록
- POST /types                         # 관리자
- PUT  /types/{id}

- GET  /balance/me                    # 내 연차 잔여
- GET  /balance/{emp_id}              # 특정 사원 (권한 체크)
- GET  /balance?year=&dept_id=        # 관리자: 전체/부서
- GET  /transactions/{emp_id}?year=   # 변동 이력

- POST /balance/adjust                # 관리자 수동 조정
  body: { emp_id, amount, reason }

- POST /accrual/run-monthly           # 수동 트리거 (관리자)
- POST /accrual/run-yearly-reset      # 수동 트리거 (관리자)

- GET  /rules?year=                   # 발생 규칙 조회
- PUT  /rules                         # 규칙 수정 (관리자)

=== 프론트엔드 ===

frontend/src/pages/leave/
- MyBalance.tsx          # 내 연차 현황 (잔여/사용/예정)
- LeaveTransactions.tsx  # 내 연차 변동 이력
- TeamBalance.tsx        # 팀장: 팀원 연차 현황
- AdminBalance.tsx       # HR: 전체 연차 관리
- AccrualRuleMgmt.tsx    # HR: 연차 발생 규칙 관리
- YearlyResetPanel.tsx   # HR: 일괄 리셋 패널

[MyBalance.tsx 구성]
- 상단 카드: 
  * 총 발생: N일
  * 사용: M일
  * 잔여: (N-M)일
  * 신청 진행 중: K일
- 원형 차트 (사용률)
- 월별 연차 발생 타임라인 (1년 미만자)
- 최근 변동 이력 테이블

[React Query hooks]
useMyBalance, useTransactions, useTeamBalance,
useAdjustBalanceMutation, useRunAccrualMutation

[사이드바]
근태/연차
  ├ 내 연차 현황
  ├ 연차 변동 이력
  ├ 팀원 연차 현황 (팀장)
  └ 연차 관리 (HR)

=== 테스트 ===
pytest (이 PHASE가 가장 중요):
- 입사 1개월차 → 1일 발생
- 입사 11개월차 → 11일 발생 후 종료
- 입사 1년 0개월 → 15일
- 근속 3년 → 16일
- 근속 5년 → 17일
- 근속 30년 → 25일 (상한)
- 회계연도 리셋 (1/1 실행 시뮬레이션)
- 이월 규칙 (기본 0일)
- 사용/취소 트랜잭션
- balance_after 누적 계산 정확성
- 음수 잔여 방지

Vitest:
- MyBalance 카드 렌더링
- 원형 차트 비율
- 변동 이력 테이블

커버리지 80%+ (핵심 로직)

=== 완료 후 ===
시나리오:
1. admin이 연차 발생 규칙 확인/조정
2. 신규 입사자 시드 → 월 1일씩 발생 확인
3. 1년 이상 근속자 → 15일 이상 부여 확인
4. 수동 "연간 리셋" 실행 → 모든 사원 재발생
5. 관리자가 특정 사원에게 특별연차 +3일 부여

Git 커밋:
git commit -m "feat: add leave types and balance management"
git commit -m "feat: add leave accrual logic (monthly, yearly reset)"
git commit -m "feat: add leave transactions and admin adjustment"
```

---

## PHASE 15 — 근태 전자결재 (휴가 신청)

```
근태 전자결재 기능을 추가해줘. 
휴가 신청 → 결재 → 승인 시 연차 자동 차감 + 캘린더 자동 등록.
최상위 규칙 엄수.

전제: PHASE 12 (전자결재), PHASE 13 (캘린더), PHASE 14 (연차) 완료.

=== 연동 구조 ===
휴가 신청서 = insa_approval_doc 레코드 (doc_type=ATT_LEAVE)
  ↓ 결재 완료 시
  ├─ insa_leave_balance.used_days 증가
  ├─ insa_leave_transaction 기록 (ref_doc_id)
  └─ insa_calendar_event 자동 생성

결재 반려/회수 시:
  ├─ 연차 되돌리기 (scheduled_days 복구)
  └─ 캘린더 이벤트 삭제

=== DB 모델 (추가) ===

insa_leave_request_detail (휴가신청서 상세)
  id, doc_id (FK → insa_approval_doc, unique),
  leave_type_id (FK → insa_leave_type),
  start_date, end_date,
  half_type (NULL|'AM'|'PM'),  -- 반차일 때
  days,                          -- 실제 일수 (자동 계산)
  reason, 
  delegate_emp_id (FK, nullable), -- 업무 위임자
  contact_during_leave,           -- 연락처
  evidence_file_url               -- 병가/경조 증빙

=== 휴가 일수 계산 로직 ===
calculate_leave_days(start_date, end_date, half_type):
- 공휴일/주말 제외 영업일 계산
- 반차: 0.5일
- 전일: 1일 × 영업일 수
- 공휴일 테이블 필요 (insa_holiday) 또는 한국 공휴일 라이브러리 활용

insa_holiday
  id, date, name, is_recurring  -- 매년 반복 (설날 등은 음력이라 주의)

초기 데이터: 양력 공휴일 (신정, 삼일절, 어린이날, 현충일, 광복절, 개천절, 한글날, 성탄절)
음력 공휴일은 관리자가 연도별 수동 입력 또는 API 연동.

=== 신청 플로우 ===

1. 사원이 휴가 신청서 작성
   - 휴가 종류 선택
   - 기간 선택 (반차면 반일 타입)
   - 사유 입력
   - (선택) 업무 위임자, 연락처, 증빙파일
   - 일수 자동 계산 표시
   - 연차 잔여 실시간 확인 (부족하면 제출 불가)

2. 상신(제출)
   - insa_approval_doc 생성 (DRAFT → PENDING)
   - insa_leave_request_detail 생성
   - insa_leave_balance.scheduled_days 증가 (예약)
   - 1단계 결재자 알림

3. 결재 진행
   - 각 단계 승인 시: 다음 단계로
   - 반려 시: 
     * status = REJECTED
     * scheduled_days 감소 (예약 해제)
     * 기안자 알림

4. 최종 승인 시
   - status = APPROVED
   - leave_service.consume_leave() 호출:
     * used_days 증가
     * scheduled_days 감소
     * transaction 기록 (ref_doc_id 연결)
   - calendar_service.create_event_from_approval() 호출:
     * 공유 캘린더에 이벤트 생성
     * 색상은 휴가 종류별

5. 이미 승인된 휴가 취소 (별도 결재)
   - "휴가 취소 신청서" 별도 문서 또는 기존 문서 회수 정책
   - 회수 시점에 따라 처리 분기:
     * 휴가 시작 전: 자동 취소 가능
     * 휴가 시작 후: 관리자 수동 처리

=== API 추가 (기존 approval API 활용 + 추가) ===
/api/v1/leave-request/

- POST /calculate-days                # 일수 계산 프리뷰
  body: { leave_type_id, start_date, end_date, half_type }
  응답: { days, business_days, excluded_holidays }

- GET  /my?year=&status=              # 내 휴가 신청 내역
- GET  /team?dept_id=&year=           # 팀장: 팀원 내역

- POST /{doc_id}/cancel               # 승인된 휴가 취소 신청

/api/v1/holiday/

- GET  /?year=
- POST /                              # 관리자 공휴일 추가
- DELETE /{id}

=== 프론트엔드 ===

frontend/src/components/approval/forms/LeaveRequestForm.tsx
  - 휴가 종류 드롭다운
  - 기간 선택 (DatePicker.RangePicker)
  - 반차 옵션 (종류가 반차일 때)
  - 사유 textarea
  - 일수 자동 계산 (실시간, useQuery로 서버 호출)
  - 잔여 연차 확인 카드 (연차 종류일 때)
  - 업무 위임자 선택 (사원 검색)
  - 연락처, 증빙파일

frontend/src/pages/leave-request/
  - MyLeaveRequests.tsx    # 내 휴가 신청 내역
  - TeamLeaveRequests.tsx  # 팀 휴가 현황
  - HolidayMgmt.tsx        # 공휴일 관리 (admin)

[사이드바 추가]
근태/연차 
  ├ 휴가 신청 (+ 버튼)       → 결재 기안 화면
  ├ 내 휴가 내역
  ├ 팀 휴가 현황 (팀장)
  └ 공휴일 관리 (admin)

=== 테스트 ===
pytest:
- 일수 계산 (주말/공휴일 제외)
- 반차 0.5일 처리
- 잔여 부족 시 신청 실패
- 결재 승인 → 연차 차감 + 캘린더 이벤트 생성 (통합 테스트)
- 결재 반려 → 예약 해제
- 휴가 취소 처리
- 동일 기간 중복 신청 방지 (선택)

Vitest:
- LeaveRequestForm 실시간 일수 계산
- 잔여 부족 시 버튼 비활성화
- 반차 옵션 토글

커버리지 70%+

=== 완료 후 ===
E2E 시나리오:
1. 사원 A: 연차 3일 신청 → 상신
2. 팀장: 결재함에 뜸 → 승인
3. 부서장: 승인 → 최종 완료
4. A의 연차 잔여 3일 감소 확인
5. 공유 캘린더에 "A 사원 연차" 이벤트 자동 생성 확인
6. 반차 신청 → 0.5일 차감 확인
7. 반려 케이스: 잔여 원복 확인
8. 승인된 휴가 취소 요청 플로우

Git 커밋:
git commit -m "feat: add holiday management (Korean public holidays)"
git commit -m "feat: add leave request form and day calculation"
git commit -m "feat: integrate leave request with approval and auto-deduction"
git commit -m "feat: auto-create calendar event on leave approval"
```

---

## PHASE 16 — 출장명령부

```
출장명령부 전자결재 + 캘린더 자동 반영을 추가해줘.
최상위 규칙 엄수.

전제: PHASE 12, 13, 15 완료.

=== 출장의 특징 (휴가와 차이) ===
- 업무의 연장이므로 연차 차감 없음
- 출장비 정산 항목 포함
- 복명서(귀환 후 보고) 필요 옵션
- 동행자 지정 가능
- 목적지/교통편 등 상세 정보

=== DB 모델 ===

insa_travel_order_detail (출장명령부 상세)
  id, doc_id (FK → insa_approval_doc, unique),
  travel_type ('DOMESTIC'|'OVERSEAS'),
  purpose,                      -- 출장 목적
  destination,                  -- 목적지
  client_company,               -- 방문처 (감정평가 건 등)
  start_at, end_at,             -- 일시 (시간 포함)
  transportation,               -- 교통편 (자가/항공/KTX 등)
  estimated_cost,               -- 예상 경비
  project_code (nullable),      -- 관련 프로젝트 참조
  appraisal_case_no (nullable), -- 감정평가 건번호 (감정평가법인 특화)
  remarks

insa_travel_companion (동행자)
  id, travel_id (FK → insa_travel_order_detail), 
  emp_id (FK)

insa_travel_report (복명서)
  id, travel_id (FK → insa_travel_order_detail, unique),
  report_content,
  actual_cost,                  -- 실제 경비
  receipts_url,                 -- 영수증 파일
  reported_at, doc_id (FK)      -- 복명서도 별도 결재 문서

=== 신청 플로우 ===

1. 출장명령부 기안
   - 출장 종류, 목적, 목적지, 일시, 교통편, 예상 경비 입력
   - 동행자 선택 (여러 명)
   - 감정평가 건 연동 시 건번호 입력
   - 파일 첨부 (견적서 등)

2. 결재 진행
   - 일반 결재선 (팀장 → 부서장 → ...) 또는
   - 해외 출장은 추가 결재선 (임원 포함)
   - 해외 출장 시 doc_type = TRAVEL_OVERSEAS로 구분 가능

3. 최종 승인 시
   - 출장자 본인 + 동행자 전원의 캘린더에 이벤트 자동 생성
   - 이벤트 색상: 출장(빨강)
   - 동행자에게 알림 발송

4. 출장 완료 후
   - 복명서 별도 기안 (doc_type = TRAVEL_REPORT)
   - 또는 기존 출장명령부에 복명 입력 기능
   - 실제 경비 입력 (정산용)
   - HR/재무가 정산 처리

=== API (sync) ===
/api/v1/travel/

- POST /orders                        # 출장명령부 기안 (approval/docs 경유)
- GET  /orders/my
- GET  /orders/team
- GET  /orders/{id}                   # 상세 (결재 이력 + 복명서)

- POST /orders/{id}/report            # 복명서 작성/기안
- GET  /orders/{id}/report

- GET  /orders/by-case/{case_no}      # 감정평가 건별 출장 이력

=== 프론트엔드 ===

frontend/src/components/approval/forms/TravelOrderForm.tsx
  - 출장 종류 라디오 (국내/해외)
  - 목적 textarea
  - 목적지 + 방문처 (감정평가법인 특성상 주소)
  - 일시 RangePicker (시간 포함)
  - 교통편 선택 + 예상 경비 input
  - 동행자 검색/추가 (다중 선택)
  - 감정평가 건번호 연동 (선택)

frontend/src/components/approval/forms/TravelReportForm.tsx
  - 출장 결과 textarea
  - 실제 경비 (항목별)
  - 영수증 파일 업로드
  - 성과/특이사항

frontend/src/pages/travel/
  - MyTravelOrders.tsx
  - TeamTravelOrders.tsx
  - TravelReports.tsx

[사이드바]
전자결재 > 출장
  ├ 출장명령부 신청
  ├ 내 출장 내역
  ├ 복명서 작성
  └ 팀 출장 현황 (팀장)

=== 캘린더 통합 ===
결재 승인 시 calendar_service.create_event_from_approval() 호출:
- 본인 + 동행자 전원에게 이벤트
- 이벤트 제목: "[출장] {목적} - {목적지}"
- event_type = 'TRAVEL'

=== 테스트 ===
pytest:
- 출장 기안 → 결재 → 캘린더 이벤트 생성
- 동행자 이벤트 생성 확인
- 해외 출장 별도 결재선 적용
- 복명서 연동
- 실제 경비 정산 데이터

Vitest:
- TravelOrderForm 동행자 추가/제거
- 국내/해외 토글 시 필드 변경
- 복명서 폼

커버리지 70%+

=== 완료 후 ===
시나리오:
1. 감정평가사가 현장 조사 출장명령부 기안 (감정평가 건번호 연동)
2. 팀장 → 부서장 결재 승인
3. 본인 + 동행자 캘린더에 이벤트 자동 생성
4. 출장 완료 후 복명서 작성 → 실제 경비 입력
5. HR/재무 정산 처리

Git 커밋:
git commit -m "feat: add travel order with companions and calendar sync"
git commit -m "feat: add travel report (complete form) with cost settlement"
git commit -m "feat: link travel orders to appraisal cases"
```

---

## PHASE 17 — 근로계약서 + 전자서명

```
근로계약서 작성 + 사용자 전자서명 + 인사정보 자동 반영 기능을 추가해줘.
최상위 규칙 엄수.

=== 설계 원칙 ===
- 완성된 계약서 PDF에 사용자가 캔버스/터치로 서명
- 서명 완료 시 인사정보(insa_employee)에 자동 반영
- 근로기준법상 3년 보관 의무 준수
- 서명 시 메타데이터(IP, 타임스탬프, User-Agent) 로깅으로 증빙력 확보

=== DB 모델 ===

1. insa_contract_template (계약서 템플릿)
   id, name, version,
   content (HTML/Jinja 템플릿),
   variables (JSON),  -- 치환 가능한 변수 목록
     -- 예: ["name", "birth_date", "address", "hire_date", 
     --      "annual_salary", "position", "dept", "contract_period"]
   is_active, created_by, created_at

2. insa_contract (근로계약서)
   id, template_id (FK), emp_id (FK),
   contract_no (자동 채번),
   contract_type ('REGULAR'|'CONTRACT'|'PART_TIME'|'RENEWAL'),
   
   -- 계약 내용
   period_start, period_end,  -- 계약 기간 (정규직은 end null)
   position, dept_id (FK),
   annual_salary,
   
   -- 개인 정보 (서명 시점 스냅샷)
   emp_name, emp_birth_date, emp_address,
   hire_date,
   
   -- 상태
   status ('DRAFT'|'READY_TO_SIGN'|'SIGNED'|'VOIDED'),
   generated_pdf_url,    -- 서명 전 PDF
   signed_pdf_url,       -- 서명 완료 PDF
   
   -- 감사 정보
   created_by, created_at, signed_at, voided_at, voided_reason

3. insa_contract_signature (서명 기록)
   id, contract_id (FK),
   signer_id (FK → insa_employee),
   signature_image (BLOB 또는 파일 경로, PNG),
   signed_at,
   
   -- 증빙 메타데이터
   ip_address, user_agent, device_info,
   auth_method ('LOGIN_SESSION'|'SMS_OTP'|'EMAIL_OTP'),
   auth_verified_at,
   
   hash_value  -- 서명 이미지 + 메타데이터 SHA256 (무결성 검증용)

=== 계약서 생성 플로우 ===

1. HR이 계약 대상자 선택 + 템플릿 선택
   - 인사정보(insa_employee)에서 변수 자동 채움
   - 연봉 등 수정 가능한 필드 입력
   - 미리보기 → HTML 렌더링

2. PDF 생성
   - weasyprint 또는 puppeteer 등으로 HTML → PDF
   - requirements.txt에 추가

3. 사원에게 서명 요청
   - 알림 발송 (이메일 + 인앱)
   - 전용 서명 페이지 링크

4. 사원 서명
   - 로그인 후 계약서 내용 확인
   - "서명하기" 버튼 → 서명 패드 모달
   - 캔버스에 마우스/터치로 서명
   - 제출 시 메타데이터 수집

5. 서명 완료 처리
   - 서명 이미지 저장
   - 서명이 삽입된 최종 PDF 생성
   - hash_value 계산 및 저장
   - contract.status = SIGNED
   - insa_employee 정보 업데이트 (연봉, 직급, 부서 등)

6. 완료 통보
   - HR에게 완료 알림
   - 본인에게 서명된 PDF 다운로드 링크

=== 인사정보 자동 반영 ===
서명 완료 시 update_employee_from_contract(contract_id) 호출:
- insa_employee에서 반영 대상 필드:
  * name, birth_date, address → 기존과 다르면 경고 후 업데이트
  * hire_date → 최초 계약 시에만 설정
  * annual_salary → 연봉 이력 별도 저장
  * position, dept_id → 발령 이력 별도 저장

인사정보 변경 이력 테이블 (있으면 재사용):
insa_employee_history
  id, emp_id, changed_field, old_value, new_value,
  change_reason, ref_contract_id (FK), changed_at

=== API (sync) ===
/api/v1/contract/

- GET  /templates
- POST /templates                 # admin
- PUT  /templates/{id}
- POST /templates/{id}/preview    # 변수 채워서 미리보기

- GET  /contracts?emp_id=&status=
- POST /contracts                 # HR: 계약서 생성
- GET  /contracts/{id}            # 상세 (내용 + 서명 상태)
- POST /contracts/{id}/request-signature  # 서명 요청 (알림 발송)
- POST /contracts/{id}/sign       # 서명 제출
  body: { signature_image_base64, auth_method? }
- GET  /contracts/{id}/download   # PDF 다운로드 (본인 또는 HR)
- POST /contracts/{id}/void       # 무효화 (HR, 사유 필수)

- GET  /contracts/my              # 내 계약서 목록

=== 서명 패드 컴포넌트 ===

frontend/src/components/signature/SignaturePad.tsx

라이브러리: react-signature-canvas 또는 signature_pad

Props:
  - onSave(dataUrl: string) => void
  - width, height
  - penColor (기본 검정)

UI:
  - 큰 캔버스 (모바일 터치 대응)
  - "지우기" / "다시 그리기" 버튼
  - "서명 완료" 버튼

캔버스 설정:
  - 터치 이벤트 지원 (passive: false)
  - 모바일에서 scroll 방지
  - 저장 시 PNG base64

=== 서명 모달 플로우 ===

frontend/src/pages/contract/SignContract.tsx
1. 계약서 내용 전체 표시 (PDF 임베드 또는 HTML)
2. 하단 "위 내용에 동의합니다" 체크박스
3. "서명하기" 버튼
4. 서명 패드 모달 오픈
5. 서명 후 "확인" → 서버 전송
6. 완료 페이지 (다운로드 링크)

=== 프론트엔드 페이지 ===

frontend/src/pages/contract/
  - MyContracts.tsx          # 내 계약서 목록 + 서명 대기
  - ContractDetail.tsx       # 상세 + 다운로드
  - SignContract.tsx         # 서명 페이지
  - ContractMgmt.tsx         # HR: 계약서 관리
  - ContractTemplateMgmt.tsx # HR: 템플릿 관리
  - CreateContract.tsx       # HR: 계약서 생성

[사이드바]
근로계약
  ├ 내 계약서
  ├ 서명 대기 (뱃지)
  ├ 계약서 관리 (HR)
  └ 계약서 템플릿 (HR)

=== PDF 생성 기술 ===
방안 A: weasyprint (Python, HTML/CSS → PDF)
  장점: 한국어 폰트 잘 렌더링, CSS 조판 쉬움
  단점: wkhtmltopdf처럼 이슈 적지만 설치 필요

방안 B: pdfkit (wkhtmltopdf 래퍼)
  장점: 빠름
  단점: wkhtmltopdf 시스템 설치 필요

방안 C: ReportLab
  장점: 순수 파이썬
  단점: HTML 변환 없음, 직접 레이아웃

추천: weasyprint. requirements.txt에 추가.

PDF에 서명 이미지 삽입:
- 서명 placeholder 영역을 템플릿에 지정
- 서명 완료 후 PIL 또는 pypdf로 이미지 오버레이
- 또는 처음부터 서명 이미지까지 포함해 다시 렌더링

=== 증빙 강화 ===
- 서명 시 사용자 세션 재인증 (비밀번호 재입력 또는 OTP, 선택적)
- IP + User-Agent + 타임스탬프 기록
- 서명 이미지와 메타데이터로 SHA256 해시 생성 → 변조 감지
- PDF에 타임스탬프 + 해시값 워터마크 (선택)

=== 보관 ===
- 파일 경로: `./storage/contracts/{year}/{emp_no}_{contract_no}.pdf`
- 근로기준법 3년 보관 규정 반영
- 자동 삭제 금지 (명시적 void만 가능, 실파일은 유지)

=== 테스트 ===
pytest:
- 템플릿 변수 치환
- PDF 생성 (파일 존재 확인)
- 서명 메타데이터 저장
- hash_value 무결성 검증
- 서명 완료 → 인사정보 업데이트 확인
- 템플릿 없이 계약서 생성 방지
- 서명 대상자만 서명 API 호출 가능 (권한)

Vitest:
- SignaturePad 캔버스 그리기 테스트
- 모바일 터치 이벤트
- 지우기 버튼
- 빈 서명 제출 방지

커버리지 70%+

=== 완료 후 ===
E2E 시나리오:
1. HR이 정규직 계약서 템플릿 등록
2. 신규 입사자 대상 계약서 생성 (이름/생년월일/주소/입사일/연봉 자동 채움)
3. 미리보기 확인 후 서명 요청
4. 사원이 알림 받고 로그인 → 서명 페이지
5. 캔버스에 서명 그리고 제출
6. 메타데이터 (IP/타임스탬프) 저장 확인
7. 서명된 PDF 다운로드
8. insa_employee 정보 자동 업데이트 확인 (연봉 이력 등)
9. HR이 관리 화면에서 서명 상태/메타데이터 확인

Git 커밋:
git commit -m "feat: add contract template with variable substitution"
git commit -m "feat: add contract generation with PDF rendering"
git commit -m "feat: add signature pad (canvas) with mobile touch support"
git commit -m "feat: add signature metadata logging for legal evidence"
git commit -m "feat: auto-update employee info on contract signing"
```

---

## 📊 전체 로드맵 (업데이트)

| PHASE | 내용 | 기반 | 우선순위 |
|---|---|---|---|
| 1~6 | 인사평가 기본 | v3 | **필수** |
| 7~11 | 인사평가 확장 | extensions | 선택 |
| **12** | **전자결재 기반** | — | **★★★★ (이후 모든 결재의 기반)** |
| **13** | **회사 공유 캘린더** | — | ★★★ |
| **14** | **연차 관리** | — | ★★★★ |
| **15** | **근태 전자결재** | 12, 13, 14 | ★★★★ |
| **16** | **출장명령부** | 12, 13 | ★★★ |
| **17** | **근로계약서 + 서명** | 12 | ★★★ |

---

## 🎯 진행 순서 제안

```
[Step 1] 인사평가 기본 (PHASE 1~6) ← 이미 진행 중
    ↓
[Step 2] 전자결재 기반 (PHASE 12) ← 모든 결재의 공통 기반
    ↓
[Step 3] 공유 캘린더 (PHASE 13) ← 휴가/출장 표시 대상
    ↓
[Step 4] 연차 관리 (PHASE 14) ← 휴가 결재의 기반
    ↓
[Step 5] 근태 전자결재 (PHASE 15) ← 가장 많이 쓸 기능
    ↓
[Step 6] 출장명령부 (PHASE 16)
    ↓
[Step 7] 근로계약서 (PHASE 17) ← 신규 입사자 시 유용
    ↓
[Step 8] 인사평가 확장 (PHASE 7~11, 필요 시)
```

---

## 🗂️ 추가될 테이블 요약

| PHASE | 접두사 | 테이블 수 | 주요 테이블 |
|---|---|---|---|
| 12 | `insa_approval_` | 6 | doc_type, line_template, line_step, doc, step_history, attachment |
| 13 | `insa_calendar_` | 3 | calendar, event, event_participant |
| 14 | `insa_leave_` + `insa_holiday` | 5 | type, balance, accrual_rule, transaction + holiday |
| 15 | `insa_leave_request_detail` 등 | 1 | leave_request_detail |
| 16 | `insa_travel_` | 3 | order_detail, companion, report |
| 17 | `insa_contract_` | 3 | template, contract, signature |
| **합계** | | **21개** | 모두 `insa_` 접두사 |

---

## 🚨 주의사항

### 법적 요건
- **연차**: 1년 미만은 월 1일, 1년 이상은 15일+ (실제 법령 반영)
- **근로계약서**: 종료 후 3년 보관, 변조 방지 해시 저장
- **전자서명**: IP/타임스탬프/사용자 인증 로그 필수

### 기술적 주의
- PHASE 12(전자결재)를 먼저 끝내야 15, 16, 17이 매끄러움
- 회계연도 리셋 스케줄러는 중복 실행 방지 (멱등 처리)
- 휴가 일수 계산 시 공휴일 테이블 필요 (음력은 매년 수동)
- PDF 생성은 weasyprint 권장 (한글 잘 됨)
- 서명 캔버스는 모바일 터치 이벤트 대응 필수

### 개인정보
- 계약서에 주민번호 포함 여부 결정 (가능한 생년월일만 쓰는 게 안전)
- 계약서 PDF 접근 권한 엄격 (본인 + HR만)
- 서명 메타데이터는 감사 목적으로만 사용

### 각 PHASE 끝나면
- 반드시 `git commit`
- CLAUDE.md에 모듈 설명 섹션 추가
- 테스트 커버리지 70%+
- 권한 매트릭스 검증

---

## 💡 진행 팁

### Claude Code 실행
```bash
cd D:\AI\INSA
claude
```

### 각 PHASE 프롬프트 붙여넣기 전에
```
PHASE 0 분석 결과를 기반으로 현재 프로젝트 상태를 재확인하고,
이번 PHASE 작업 전에 변경/추가해야 할 사항이 있는지 알려줘.
```

### 막혔을 때
```
현재 insa_ 테이블 목록과 관계도 보여줘
```
```
전자결재 시스템 라우터 중 async def로 된 거 있으면 sync로 바꿔줘
```
```
마지막 변경을 되돌리고 현재 상태 요약해줘
```
