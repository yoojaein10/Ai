# 인사평가 모듈 추가 가이드 (INSA 프로젝트 확장) v3

> 대상: `D:\AI\INSA` 기존 프로젝트에 인사평가 기능 추가  
> 스택: FastAPI (sync routes + threadpool) + React 18 + TypeScript + MSSQL  
> 테이블 접두사: `insa_` (CLAUDE.md 규칙 엄수)  
> 인증: JWT Access (header) + Refresh (httpOnly cookie)  
> **주의**: 새 프로젝트가 아닌 기존 `backend/`, `frontend/` 확장 방식

---

## 🏛️ 최상위 규칙 (모든 PHASE 공통)

### CLAUDE.md 핵심 규칙 준수
1. **Backend**: sync routes (`def`, `async def` 금지) + SQLAlchemy + pyodbc
2. **State**: Zustand (client state only) / React Query (server state only)
3. **DB**: 모든 테이블 `insa_` 접두사
4. **Auth**: Access Token은 Authorization header, Refresh Token은 httpOnly cookie
5. **Patterns**: Immutable only (mutation 금지)
6. **Structure**: `schemas/` = Pydantic, `db/` = SQLAlchemy models
7. **Test**: pytest (BE) / Vitest (FE), 커버리지 70%+
8. **Commit**: `<type>: <description>` (feat, fix, refactor, docs, test, chore)

### 각 PHASE 진행 방식
- PHASE 0 분석 결과를 기반으로 작업
- 각 PHASE 끝나면 → 테스트 작성 → 커밋
- 기존 공통 컴포넌트/패턴 최대한 재사용
- 기존 테이블 스키마 수정 금지 (FK 참조만)

---

## 📌 사전 준비

```bash
cd D:\AI\INSA
claude
```

---

## PHASE 0 — 현재 프로젝트 분석 (필수 선행)

> ⚠️ **이 단계 결과를 저한테 공유해주시면 이후 PHASE를 실제 프로젝트에 맞게 다듬어드립니다.**

```
현재 INSA 프로젝트 상태를 철저히 분석해줘. 코드는 수정하지 말고 분석만.

[분석 1: backend/]
1. 폴더 구조 (app/api, app/schemas, app/db, app/services, app/core 등)
2. requirements.txt 의존성 전체
3. alembic 마이그레이션 이력 파일명 목록
4. 현재 정의된 SQLAlchemy 모델 (insa_ 테이블들)
   - 특히 insa_employee, insa_department, insa_position 등 인사 마스터
   - 컬럼명/타입 정확히
5. 현재 API 라우터 엔드포인트 전체 목록 (HTTP method + path)
6. 라우터가 sync인지 async인지 (def vs async def) — CLAUDE.md 규칙 확인
7. 사용자/권한 모델 구조 (Role 값 종류, RBAC 패턴)

[분석 2: 인증 흐름]
1. JWT 발급/검증 구현 위치
2. Access Token이 header로 전달되는 패턴 확인
3. Refresh Token이 httpOnly cookie로 처리되는 방식 확인
4. 권한 체크 deps 함수들 (get_current_user, require_role 등)

[분석 3: frontend/]
1. src/ 폴더 구조
2. package.json 의존성
3. 현재 페이지 목록 (src/pages/ 아래)
4. 공통 컴포넌트 목록 (DataTable, SearchForm, Modal 등 — 있으면 재사용)
5. 사이드바/메뉴 구조 (어디서 정의? 어떻게 추가?)
6. React Router 경로 설정 위치 및 현재 경로 목록
7. Zustand store 파일들 (client state로만 쓰는지)
8. React Query hooks (server state로만 쓰는지)
9. axios 인스턴스 인터셉터 (Refresh cookie 재발급 로직 포함 여부)

[분석 4: 테스트]
1. pytest 설정 + 테스트 파일 패턴
2. Vitest 설정 + 테스트 파일 패턴
3. 현재 커버리지 수준

[분석 5: 프로젝트 관습]
1. Enum 처리 방식 (SQLAlchemy Enum vs VARCHAR + 체크)
2. JSON 컬럼 처리 방식 (MSSQL NVARCHAR(MAX) 기반)
3. Immutable 패턴이 실제 어떻게 구현되어 있는지
4. 네이밍 컨벤션 (snake_case, PascalCase 등)

[결과물]
위 내용을 표/리스트 형식으로 정리. 다음 두 섹션 포함:

A. 재사용 가능한 자산 목록
   - 평가 모듈에서 그대로 쓸 수 있는 컴포넌트/함수/패턴

B. 주의 사항
   - 평가 모듈 추가 시 기존 코드와 충돌 가능성 있는 부분
   - CLAUDE.md 규칙과 기존 구현 간 불일치 (있다면)

절대 파일 수정하지 마. 읽기 + 분석 + 정리만.
```

**결과를 저(Claude)한테 보여주시면 PHASE 1~6을 프로젝트 현황에 맞게 추가 조정해드립니다.**

---

## PHASE 1 — 평가 공통 기반

```
인사평가 도메인의 공통 기반을 추가해줘.
PHASE 0 분석 결과를 기반으로 기존 프로젝트 패턴을 그대로 따를 것.

=== 최상위 규칙 ===
- Backend 라우터: sync routes (def 사용, async def 금지)
- DB 접근: SQLAlchemy + pyodbc, threadpool 활용
- 모든 테이블: insa_ 접두사
- 패턴: Immutable only
- schemas/ = Pydantic, db/ = SQLAlchemy models
- Enum은 프로젝트 기존 방식 따름 (VARCHAR+체크 또는 SQLAlchemy Enum)
- JSON 컬럼도 프로젝트 기존 방식 따름

=== DB 모델 (backend/app/db/) ===
1. insa_eval_round (평가 회차)
   id, year, name, start_date, end_date,
   status ('PLANNED'|'IN_PROGRESS'|'CLOSED'),
   created_at, updated_at

2. insa_eval_schedule (단계별 일정)
   id, round_id (FK → insa_eval_round),
   stage ('TARGET'|'MID'|'FINAL'|'COMPREHENSIVE'),
   start_date, end_date

3. insa_eval_approver (평가자 매핑)
   id, round_id (FK),
   evaluatee_id (FK → insa_employee.id),
   evaluator_id (FK → insa_employee.id),
   eval_type ('PERF'|'COMP'|'MULTI'),
   rater_type ('BOSS'|'PEER'|'SUBORDINATE'),  -- MULTI일 때만
   created_at

4. insa_eval_calibration_group (보정집단)
   id, year, name, created_by, created_at

5. insa_eval_calibration_member
   id, group_id (FK), emp_id (FK → insa_employee.id)

6. insa_eval_setting (평가 기본 설정)
   id, year,
   weight_config (JSON 방식은 기존 패턴 따름),
     -- 예: {perf: 40, comp: 30, multi: 30}
   grade_criteria (JSON 방식은 기존 패턴 따름)
     -- 예: [{grade:'S', min:90, max:100, default_ratio:10}, ...]

=== Alembic 마이그레이션 ===
- 단일 마이그레이션으로 6개 테이블 생성
- 기존 insa_employee FK 관계 확인 후 upgrade
- 마이그레이션 실행 후 테이블 생성 확인

=== Pydantic 스키마 (backend/app/schemas/) ===
PHASE 0에서 확인한 기존 스키마 파일 구조 그대로:
- eval_round.py (Base, Create, Update, Response)
- eval_schedule.py
- eval_approver.py
- eval_calibration.py (group + member 통합)
- eval_setting.py

=== 서비스 (backend/app/services/) ===
기존 services 구조 패턴 따름:
- eval_round_service.py
- eval_approver_service.py
- eval_calibration_service.py
- eval_setting_service.py
모두 Immutable 패턴 (mutation 없이 새 객체 반환)

=== API 라우터 (backend/app/api/) ===
⚠️ 반드시 sync routes (def 사용, async def 절대 금지)

GET    /api/v1/eval/rounds?year=
POST   /api/v1/eval/rounds
PUT    /api/v1/eval/rounds/{id}
PUT    /api/v1/eval/rounds/{id}/close

GET    /api/v1/eval/schedules?round_id=
POST   /api/v1/eval/schedules  (일괄)

GET    /api/v1/eval/approvers?round_id=&eval_type=
POST   /api/v1/eval/approvers  (일괄 매핑)
DELETE /api/v1/eval/approvers/{id}

GET    /api/v1/eval/calibration-groups?year=
POST   /api/v1/eval/calibration-groups
PUT    /api/v1/eval/calibration-groups/{id}
POST   /api/v1/eval/calibration-groups/{id}/members
DELETE /api/v1/eval/calibration-groups/{id}/members/{emp_id}

GET    /api/v1/eval/settings?year=
PUT    /api/v1/eval/settings

=== 권한 ===
관리자(admin) 또는 인사팀(hr)만 접근.
PHASE 0에서 확인한 기존 deps.py 권한 체크 패턴 그대로 활용.

=== 테스트 (backend/tests/) ===
pytest로 각 엔드포인트 + 서비스 테스트:
- eval_round CRUD
- approver 일괄 등록
- calibration group + member 추가/삭제
- setting 업데이트
커버리지 70%+ 목표. 기존 conftest.py 픽스처 활용.

=== 프론트엔드 (frontend/src/) ===

🔸 상태 관리 원칙
- Zustand: UI 상태만 (선택된 회차, 모달 열림 등)
- React Query: 모든 서버 데이터 (fetch/mutate)
- 직접 axios 호출 ❌, 항상 React Query hook으로 감싸기

🔸 API 호출 (frontend/src/api/)
eval.ts 파일 생성:
- 기존 axios 인스턴스 활용
- Refresh cookie 인터셉터는 기존 것 그대로 사용
- fetch 함수만 export (hook은 별도 파일)

🔸 React Query hooks (frontend/src/hooks/eval/)
useRounds, useRoundMutation, useApprovers, useApproverMutation 등
- queryKey는 명확한 구조: ['eval', 'rounds', { year }]
- invalidate 대상 명시

🔸 페이지 (frontend/src/pages/eval/common/)
- RoundMgmt.tsx          # 평가 회차 관리
- ScheduleMgmt.tsx       # 평가 일정
- ApproverMapping.tsx    # 평가자 매핑
- CalibrationGroup.tsx   # 보정집단
- EvalSettings.tsx       # 반영비율/등급기준

🔸 사이드바 메뉴 추가
PHASE 0에서 확인한 메뉴 설정 파일에 추가:
인사평가
  └ 평가 설정
    ├ 평가 회차
    ├ 평가 일정
    ├ 평가자 매핑
    ├ 보정집단
    └ 반영비율/등급

🔸 React Router 경로 추가
/eval/common/rounds, /eval/common/schedules, 등

🔸 Zustand store (frontend/src/store/)
evalUIStore.ts — 선택된 회차 ID 등 UI 상태만

🔸 공통 컴포넌트 재사용
PHASE 0에서 확인한 DataTable, SearchForm, Modal 등 그대로.
없으면 먼저 만들기.

=== Vitest 테스트 (frontend/src/pages/eval/__tests__/) ===
- 회차 목록 렌더링
- 회차 생성 모달 동작
- 평가자 매핑 CRUD
Vitest 커버리지 70%+ 목표.

=== 완료 후 ===
결과 보고:
1. 추가된 테이블 6개 목록
2. 추가된 API 엔드포인트 목록 (sync 확인)
3. 추가된 프론트 라우트 목록
4. 테스트 커버리지 %
5. Git 커밋 명령 제안:
   git add .
   git commit -m "feat: add eval common foundation (round, schedule, approver, calibration, setting)"
```

---

## PHASE 2 — 성과평가 (PERF)

```
성과평가 모듈을 추가해줘.
최상위 규칙(sync routes, insa_ 접두사, Immutable, Zustand UI only, React Query server only) 엄수.

=== DB 모델 ===
insa_perf_kpi
  id, round_id (FK), code, name, measure_type, weight, perspective

insa_perf_target
  id, emp_id (FK), round_id (FK), kpi_id (FK), target_value,
  is_organization, status, weight_percent,
  created_at, updated_at
  status: 'DRAFT'|'SUBMITTED'|'APPROVED'|'REJECTED'

insa_perf_target_mid
  id, target_id (FK), progress_rate, description,
  expected_rate, submitted_at

insa_perf_target_final
  id, target_id (FK), achievement_rate, description,
  self_score, submitted_at

insa_perf_eval_result
  id, emp_id (FK), round_id (FK), evaluator_id (FK),
  score, grade, comment, created_at

=== API (sync routes) ===
GET  /api/v1/eval/perf/kpis?round_id=
POST /api/v1/eval/perf/kpis

GET  /api/v1/eval/perf/targets?emp_id=&round_id=
POST /api/v1/eval/perf/targets
PUT  /api/v1/eval/perf/targets/{id}
PUT  /api/v1/eval/perf/targets/{id}/submit
PUT  /api/v1/eval/perf/targets/{id}/approve
PUT  /api/v1/eval/perf/targets/{id}/reject

POST /api/v1/eval/perf/midterm
GET  /api/v1/eval/perf/midterm?target_id=

POST /api/v1/eval/perf/final
GET  /api/v1/eval/perf/final?target_id=

GET  /api/v1/eval/perf/results?round_id=&dept_id=

=== 권한 ===
- 목표 조회: 본인 + 평가자 + hr/admin
- 승인: insa_eval_approver에 매핑된 평가자만
- 결과 조회: 본인 + 평가라인

=== 프론트엔드 (frontend/src/pages/eval/perf/) ===
- MyEvaluation.tsx      # 내 평가 현황 대시보드
- TargetSetting.tsx     # 목표과제 입력
- MidtermReview.tsx     # 중간점검
- FinalEvaluation.tsx   # 기말실적
- ApprovalInbox.tsx     # 평가자 승인 대기 목록
- TeamStatus.tsx        # 부서별 현황

=== React Query Hooks (frontend/src/hooks/eval/perf/) ===
useMyTargets, useTargetMutation (submit/approve/reject),
useMidterm, useFinal, useApprovalInbox, useTeamStatus

=== Zustand (UI 상태만) ===
evalPerfUIStore: 선택된 target ID, 현재 편집 중인 폼 탭 등

=== 사이드바 추가 ===
인사평가 > 성과평가
  ├ 내 평가 현황
  ├ 목표과제 작성
  ├ 중간점검
  ├ 기말실적
  └ 승인 대기 (평가자)

=== 공통 컴포넌트 재사용/추가 ===
- 기존 DataTable, SearchForm 활용
- ApprovalFlow 컴포넌트가 없으면 추가 (결재 단계 시각화)
- EvalScoreInput 컴포넌트 추가 (슬라이더/라디오/숫자 입력)

=== 테스트 ===
pytest:
- target 상태 전이 (DRAFT → SUBMITTED → APPROVED)
- 권한 분기 (본인/평가자/관리자)
- weight_percent 합계 검증

Vitest:
- MyEvaluation 대시보드 렌더링
- TargetSetting 폼 검증
- ApprovalInbox 승인 액션

커버리지 70%+

=== 완료 후 ===
E2E 시나리오 테스트 결과 보고:
1. 사원 로그인 → 목표 입력 → 제출
2. 팀장 로그인 → ApprovalInbox에서 승인
3. 중간점검 입력
4. 기말실적 입력

Git 커밋:
git commit -m "feat: add perf evaluation module (kpi, target, midterm, final, result)"
```

---

## PHASE 3 — 역량평가 (COMP)

```
역량평가 모듈을 추가해줘.
최상위 규칙 엄수 (sync routes, insa_ 접두사, Immutable, Zustand UI only, React Query server only).

=== DB 모델 ===
insa_comp_indicator
  id, year, code, name, description, weight

insa_comp_behavior
  id, indicator_id (FK), level (1~5), description

insa_comp_eval_self
  id, emp_id (FK), round_id (FK), indicator_id (FK),
  score, comment, submitted_at

insa_comp_eval_boss
  id, evaluatee_id (FK), evaluator_id (FK), round_id (FK),
  indicator_id (FK), score, comment, submitted_at

insa_comp_sar_record
  id, target_emp_id (FK), observer_id (FK), observed_date,
  situation, action, result

=== API (sync routes) ===
GET  /api/v1/eval/comp/indicators?year=
POST /api/v1/eval/comp/indicators

GET  /api/v1/eval/comp/my-eval?round_id=
POST /api/v1/eval/comp/self
POST /api/v1/eval/comp/boss

GET  /api/v1/eval/comp/sar?emp_id=
POST /api/v1/eval/comp/sar

=== 프론트엔드 (frontend/src/pages/eval/comp/) ===
- SelfEvaluation.tsx   # 본인평가 (아코디언 + 슬라이더)
- BossEvaluation.tsx   # 상사평가 (본인평가 참고)
- SarRecords.tsx       # SAR 관찰기록 타임라인

=== React Query Hooks ===
useIndicators, useMyEval, useSelfMutation, useBossMutation,
useSarRecords, useSarMutation

=== 사이드바 ===
인사평가 > 역량평가
  ├ 본인평가
  ├ 상사평가
  └ SAR 관찰기록

=== 테스트 ===
pytest:
- 본인평가 점수 범위 검증 (1~5)
- 상사평가 권한 분기
- SAR 기록 CRUD

Vitest:
- 아코디언 UI 인터랙션
- 본인/상사 평가 폼 제출

커버리지 70%+

=== 완료 후 ===
Git 커밋:
git commit -m "feat: add competency evaluation module (indicator, self, boss, sar)"
```

---

## PHASE 4 — 다면평가 (MULTI, 익명성)

```
다면평가 모듈을 추가해줘. 익명성 처리가 핵심.
최상위 규칙 엄수 (sync routes, insa_ 접두사, Immutable, Zustand UI only, React Query server only).

=== DB 모델 ===
insa_multi_eval_indicator
  id, round_id (FK), name, description, max_score

insa_multi_eval_response
  id, round_id (FK), evaluatee_id (FK),
  rater_type ('BOSS'|'PEER'|'SUBORDINATE'),
  indicator_id (FK), score, comment
  ⚠️ evaluator_id 컬럼 없음 — 완전 익명

insa_multi_eval_response_log
  id, evaluator_id (FK), round_id (FK),
  evaluatee_id (FK), submitted_at
  (제출 여부만 추적, 점수 없음)

insa_multi_eval_result
  id, round_id (FK), evaluatee_id (FK), indicator_id (FK),
  avg_score, response_count

=== 익명성 핵심 로직 ===
response 저장 시:
- insa_multi_eval_response: 점수만 저장 (evaluator_id 절대 없음)
- insa_multi_eval_response_log: 제출 사실만 저장 (점수 없음)
- 두 테이블 간 JOIN으로 역추적 불가능한 구조 (공통 키 없음)

결과 조회 시:
- response_count < 3 → "응답자 부족" 반환 (409 또는 200 + 플래그)
- 평균만 공개, 개별 점수 접근 API 없음

=== API (sync routes) ===
GET  /api/v1/eval/multi/indicators?round_id=
POST /api/v1/eval/multi/indicators

GET  /api/v1/eval/multi/my-targets?round_id=
POST /api/v1/eval/multi/response     # 익명 저장 (내부에서 log 분리 기록)
GET  /api/v1/eval/multi/results/{emp_id}?round_id=
GET  /api/v1/eval/multi/status?round_id=

=== 프론트엔드 (frontend/src/pages/eval/multi/) ===
- MultiEval.tsx          # 내가 평가할 대상자 카드 리스트
- MultiEvalResult.tsx    # 본인의 다면평가 결과 (평균만)
- MultiEvalStatus.tsx    # 관리자: 제출 현황 (익명)

=== React Query Hooks ===
useMyMultiTargets, useMultiResponseMutation, useMultiResult, useMultiStatus

=== 사이드바 ===
인사평가 > 다면평가
  ├ 다면평가 입력
  └ 내 다면평가 결과

=== 테스트 (익명성 검증 필수) ===
pytest (익명성 테스트가 핵심):
- insa_multi_eval_response 테이블 스키마에 evaluator_id 없음 확인
- 응답 저장 후 response 테이블에 evaluator 정보 없는지 확인
- response_log에는 submitted_at만 있고 점수 없는지 확인
- response_count < 3일 때 "응답자 부족" 반환 확인
- 응답자 3명 이상일 때 평균만 반환 확인
- 개별 점수 조회 API 없음 확인

Vitest:
- 대상자 카드 리스트 렌더링
- 연속 평가 모드
- 결과 페이지 (응답자 부족 케이스 포함)

커버리지 70%+

=== 완료 후 ===
익명성 보증 체크리스트:
1. [ ] response 테이블 스키마에 evaluator_id 없음
2. [ ] response_log에 점수 컬럼 없음
3. [ ] response_count < 3 케이스 처리
4. [ ] 개별 점수 조회 API 부재

Git 커밋:
git commit -m "feat: add multi-source evaluation with anonymity (indicator, response, result)"
```

---

## PHASE 5 — 종합평가 + 등급 산출

```
종합평가 모듈을 추가해줘.
최상위 규칙 엄수 (sync routes, insa_ 접두사, Immutable, Zustand UI only, React Query server only).

⚠️ 테이블 접두사: insa_eval_* 사용 (insa_perf_ 아님)
   종합평가는 성과+역량+다면 통합이므로 eval_ 접두사가 의미적으로 맞음.

=== DB 모델 ===
insa_eval_comprehensive
  id, emp_id (FK), round_id (FK),
  perf_score, comp_score, multi_score,
  total_score, original_grade, final_grade,
  is_adjusted, adjusted_by (FK), adjusted_reason,
  calculated_at, adjusted_at

insa_eval_objection
  id, emp_id (FK), round_id (FK), reason,
  status ('PENDING'|'REVIEWED'|'ACCEPTED'|'REJECTED'),
  created_at

insa_eval_objection_review
  id, objection_id (FK), reviewer_id (FK),
  decision, comment, reviewed_at

=== 종합점수 계산 서비스 ===
calculate_comprehensive(round_id) (Immutable):
- insa_eval_setting에서 weight_config 읽기
- 각 사원의 perf/comp/multi 평균 점수 집계
- total = perf × perf_ratio + comp × comp_ratio + multi × multi_ratio
- grade_criteria로 등급 산정 → original_grade
- insa_eval_comprehensive에 저장 (upsert)

=== 보정 로직 ===
- 보정집단별 강제 배분 비율 적용 (옵션)
- 관리자 수동 조정 가능 (final_grade, adjusted_reason 필수)
- 조정 이력 유지 (original_grade vs final_grade 둘 다 보존)

=== API (sync routes) ===
GET  /api/v1/eval/comprehensive?round_id=
POST /api/v1/eval/comprehensive/calculate
PUT  /api/v1/eval/comprehensive/{id}/grade

POST /api/v1/eval/objections
GET  /api/v1/eval/objections?round_id=
PUT  /api/v1/eval/objections/{id}/review

=== 프론트엔드 (frontend/src/pages/eval/comprehensive/) ===
- ComprehensiveList.tsx    # 대상자 목록 + 일괄 계산 버튼
- GradeAdjustment.tsx      # 등급 조정 (인사위원회)
- ObjectionList.tsx        # 이의신청 관리
- MyResult.tsx             # 본인 종합 결과

=== GradeAdjustment.tsx 핵심 UI ===
- 보정집단 드롭다운
- 그룹 내 대상자 테이블 (점수순 정렬)
- 등급 분포 바 차트 (현재 비율 vs 목표 비율)
- 등급 인라인 편집 드롭다운 (S/A/B/C/D)
- 변경 사유 textarea (필수)
- 일괄 저장 버튼

=== React Query Hooks ===
useComprehensiveList, useCalculateComprehensive,
useGradeAdjustmentMutation, useObjections, useObjectionReviewMutation

=== 사이드바 ===
인사평가 > 종합평가
  ├ 종합평가 조회
  ├ 등급 조정 (관리자)
  ├ 이의신청
  └ 내 종합 결과

=== 테스트 ===
pytest:
- 종합점수 계산 로직 (weight 적용)
- 등급 산정 (grade_criteria 경계값)
- 수동 조정 시 adjusted_reason 필수
- 이의신청 상태 전이 (PENDING → REVIEWED → ACCEPTED/REJECTED)

Vitest:
- 등급 분포 차트 렌더링
- 인라인 편집 저장
- 이의신청 폼

커버리지 70%+

=== 완료 후 ===
E2E 시나리오:
1. 계산 → 자동 등급 산정 확인
2. 수동 조정 + 사유 저장
3. 이의신청 → 재심의 플로우

Git 커밋:
git commit -m "feat: add comprehensive evaluation (calculation, grade adjustment, objection)"
```

---

## PHASE 6 — 통합 테스트 + 마무리

```
인사평가 모듈 전체 통합 테스트 + 문서화.

=== 체크리스트 ===

1. 시드 데이터 확장 (backend/scripts/seed_eval.py)
   - 기존 insa_employee 기반
   - 평가 회차 1개 (현재 연도)
   - KPI 5개, 역량지표 10개, 다면지표 5개
   - 평가자 매핑 (조직도 기반)
   - 보정집단 3개

2. E2E 시나리오 테스트 (pytest + Vitest)
   a. 목표 설정 → 제출 → 팀장 승인
   b. 중간점검 → 기말실적 제출
   c. 역량평가 (본인 → 상사)
   d. 다면평가 익명 제출 (3명 이상)
   e. 종합평가 계산 → 등급 조정 → 마감
   f. 이의신청 → 재심의

3. 권한 매트릭스 검증
   | Role    | 평가 설정 | 본인평가 | 승인 | 등급 조정 | 이의신청 재심의 |
   | admin   | ✅       | ✅      | ✅   | ✅       | ✅            |
   | hr      | ✅       | ✅      | -    | ✅       | ✅            |
   | manager | -        | ✅      | ✅   | -        | -             |
   | user    | -        | ✅      | -    | -        | 제출만        |

4. 규칙 준수 최종 감사
   [ ] 모든 라우터가 sync (def, async def 없음)
   [ ] 모든 테이블 insa_ 접두사
   [ ] Immutable 패턴 (서비스 함수에 mutation 없음)
   [ ] Zustand는 UI 상태만
   [ ] React Query는 서버 상태만
   [ ] Access Token은 header, Refresh는 httpOnly cookie

5. 테스트 커버리지
   - Backend: pytest --cov, 70%+
   - Frontend: vitest --coverage, 70%+

6. 문서 업데이트
   - CLAUDE.md에 "인사평가 모듈" 섹션 추가
     (주요 테이블, API 경로, Role별 접근 권한)
   - docs/EVAL_MODULE.md 신규 작성
     (상세 API 레퍼런스, ER 다이어그램, 워크플로 다이어그램)

=== 완료 후 ===
최종 보고:
- 체크리스트 결과 (✅/❌)
- 커버리지 %
- 개선 제안

Git 커밋:
git commit -m "test: add e2e evaluation workflow tests and update docs"
git commit -m "docs: add eval module section to CLAUDE.md and EVAL_MODULE.md"
```

---

## 💡 사용 팁

### 진행 순서
1. **PHASE 0** — 현재 상태 분석 (수정 없음)
2. 분석 결과를 저(Claude)한테 보여주세요
3. PHASE 1~6을 하나씩 진행
4. 각 PHASE 끝나면 **반드시 Git 커밋**

### Git 커밋 규칙 (CLAUDE.md)
```bash
git commit -m "feat: add eval common foundation"
git commit -m "fix: correct target status transition"
git commit -m "refactor: extract approver mapping service"
git commit -m "docs: update api reference"
git commit -m "test: add multi eval anonymity tests"
git commit -m "chore: update alembic migration"
```

### 문제 발생 시 보조 프롬프트
```
현재 라우터 중 async def로 된 게 있으면 찾아서 sync로 바꿔줘
```
```
insa_ 접두사 없는 신규 테이블 있는지 확인해줘
```
```
Zustand store에서 서버 데이터 들어있는 거 있으면 React Query로 옮겨줘
```
```
마지막 변경을 되돌리고 현재 상태 요약해줘
```
```
평가 관련 API 엔드포인트 전체 목록 보여줘
```

---

## 🗺️ 추가될 테이블 요약

| PHASE | 접두사 | 테이블 수 | 주요 테이블 |
|---|---|---|---|
| 1 | `insa_eval_` | 6 | round, schedule, approver, calibration_group, calibration_member, setting |
| 2 | `insa_perf_` | 5 | kpi, target, target_mid, target_final, eval_result |
| 3 | `insa_comp_` | 5 | indicator, behavior, eval_self, eval_boss, sar_record |
| 4 | `insa_multi_` | 4 | indicator, response, response_log, result |
| 5 | `insa_eval_` | 3 | comprehensive, objection, objection_review |
| **합계** | | **23개** | 모두 `insa_` 접두사 |

---

## 🚨 최종 경고

- **PHASE 0 필수 선행**. 건너뛰면 기존 패턴과 충돌 발생 확정.
- `async def` 절대 금지. 모든 라우터 sync.
- `insa_` 접두사 없는 테이블 생성 금지.
- Zustand에 서버 데이터 넣지 말 것.
- React Query로 감싸지 않은 axios 직접 호출 금지.
- Mutation 패턴 금지. 항상 새 객체 반환.
- 각 PHASE 끝나면 `git commit` 필수.
- 테스트 커버리지 70% 미달 시 해당 PHASE 미완료 간주.
