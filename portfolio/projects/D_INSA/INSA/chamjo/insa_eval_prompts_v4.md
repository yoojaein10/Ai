# 인사평가 모듈 추가 가이드 (INSA 프로젝트 현 상태 반영판) v4

> 대상: `D:\AI\INSA` 기존 프로젝트에 인사평가 기능 추가
> 스택: FastAPI (sync routes + threadpool) + React 18 + TypeScript + MSSQL
> 테이블 접두사: `insa_` (CLAUDE.md 규칙 엄수)
> 인증: JWT Access (Authorization header) + Refresh (httpOnly cookie)
> **v3와 차이**: PHASE 0 결과를 먼저 반영 → 실제 `backend/`, `frontend/` 구조/패턴에 맞춤

---

## 🔍 PHASE 0 결과 요약 (2026-04-17 기준)

아래 사실을 전제로 PHASE 1~6이 작성됨. 프로젝트가 바뀌었으면 각 PHASE 적용 전 재확인 필요.

### Backend 현황

| 항목 | 실제 상태 |
|---|---|
| 폴더 구조 | `app/{api/v1, schemas, services, db, core}` |
| 라우터 | **모두 sync (`def`)**, `async def` 없음 ✅ |
| DB 마이그레이션 | **Alembic 미사용** (`alembic/versions/` 비어있음) |
| 스키마 생성 | `app/db/init_db.py`에서 `Base.metadata.create_all()` |
| 모델 파일 | `app/db/models.py` **단일 파일**에 모든 모델 집약 |
| Pydantic 스키마 | `app/schemas/{entity}.py` — 엔티티별 파일 분리 |
| 서비스 | `app/services/{entity}.py` — 함수형 (클래스 X) |
| Immutable 패턴 | ⚠️ **실제 코드는 ORM 모델 mutation함** (`appointment.py`에서 `employee.dept_id = ...`). CLAUDE.md의 "Immutable only"는 **비즈니스 로직 딕셔너리/리스트 레벨**에만 적용. ORM transaction 내부의 필드 재할당은 허용됨 |
| 권한 체크 | `app/core/deps.py`: `get_current_user`, `require_roles(*role_codes)` |
| Role 코드 | **`SYSTEM_ADMIN`, `HR_ADMIN`, `DEPT_HEAD`, `EMPLOYEE`** (admin/hr/manager/user 아님!) |
| JWT | `app/core/security.py` — access(header) + refresh(cookie) |
| 암호화 | `app/core/encryption.py` — AES-256 (계좌번호 등 민감필드) |
| 의존성 | fastapi 0.115, sqlalchemy 2.0, pyodbc 5.2, alembic 1.15 (패키지만 설치, 미사용), pydantic 2.11, pytest 8.3, openpyxl(엑셀) |

### Frontend 현황

| 항목 | 실제 상태 |
|---|---|
| 폴더 구조 | `src/{pages, components, api, hooks, store, assets}` |
| `pages/` | **플랫 구조** (서브폴더 없음). `EmployeeListPage.tsx` 식 단일 파일 |
| `api/*.ts` | **fetch + React Query hook이 한 파일에 공존** (예: `employees.ts`에 `useEmployees`, `useCreateEmployee` 정의) |
| `hooks/` | **비어 있음** — 현재 프로젝트는 api 파일에 hook을 co-locate. 새 모듈도 동일 패턴 따름 |
| `store/` | `auth.ts`만 존재 (accessToken, loginId) |
| `axios client` | `api/client.ts` — refresh cookie 인터셉터 내장 (재사용 가능) |
| Routing | `App.tsx`에 **모든 경로를 인라인 정의**. 라우트 파일 분리 X |
| 레이아웃 | `components/MainLayout.tsx` — **GNB(상단) + 동적 Sidebar** |
| GNB 항목 | `인사`, `근태`, `교육`, `복리후생`, `문서함`, `통계`, `관리` |
| 경로 prefix 매핑 | `/hr → 인사`, `/att → 근태`, `/edu → 교육`, `/benefit → 복리후생`, `/doc → 문서함`, `/stat → 통계`, `/admin → 관리` |
| 공통 컴포넌트 | `MainLayout`, `PlaceholderPage`, `ChangeRequestModal`, `CreateEmployeeModal`, `tabs/` — **DataTable/SearchForm 같은 추상화 없음**. Ant Design `Table`, `Form`, `Modal`을 **직접 사용**. |
| Ant Design | antd 5.25, @ant-design/icons 5.6 |
| 상태관리 | Zustand 5.0 (UI), React Query 5.74 (서버) |
| 테스트 | Vitest 3.1 (devDeps 있지만 **실제 테스트 파일 미확인**) |

### 🚨 기존 `insa_emp_evaluation` 충돌 주의

`app/db/models.py:327`에 이미 단순 평가 테이블 존재:

```python
class EmpEvaluation(Base):
    __tablename__ = "insa_emp_evaluation"
    id, employee_id, eval_year, eval_grade, score
```

→ 신규 모듈은 **`insa_eval_*`, `insa_perf_*`, `insa_comp_*`, `insa_multi_*`** 접두사로 분리. 기존 `insa_emp_evaluation`는 **건드리지 않음** (다른 화면에서 참조 중일 수 있음). PHASE 5 종합평가 완료 후 `insa_emp_evaluation`에 최종 등급을 sync하는 로직 추가 여부는 별도 결정.

### 재사용 자산 요약

- `api/client.ts`: axios + refresh cookie 인터셉터 → 그대로 import
- `core/deps.py`: `require_roles("SYSTEM_ADMIN", "HR_ADMIN")` 패턴 → 그대로 사용
- `core/encryption.py`: 민감정보 암호화 필요 시 재사용
- `MainLayout.tsx`의 `sidebarByGnb`, `gnbDefaultPath`, `pathPrefixToGnb` → 인사평가 GNB 항목 추가만 하면 됨
- Ant Design `Table`, `Form`, `Modal`, `Descriptions`, `Tabs` → 직접 사용

---

## 🏛️ 최상위 규칙 (모든 PHASE 공통)

### 필수 준수

1. **Backend 라우터**: sync (`def`), `async def` 절대 금지
2. **DB 테이블**: 모두 `insa_` 접두사
3. **스키마 생성**: `app/db/init_db.py`의 `create_all()` 방식 유지. **Alembic 마이그레이션 작성 금지** (프로젝트에서 미사용). 새 모델은 `models.py`에 추가만 하면 `create_all()`이 처리
4. **Role 코드**: `SYSTEM_ADMIN`, `HR_ADMIN`, `DEPT_HEAD`, `EMPLOYEE` 정확히 사용
5. **Pydantic 스키마**: `app/schemas/{entity}.py` — Base/Create/Update/Response 패턴
6. **서비스 함수형 구조**: 클래스 만들지 말고 함수로 작성 (`app/services/{entity}.py`)
7. **Frontend api 파일**: `api/{domain}.ts`에 **fetch + React Query hook 동시에** 작성 (기존 `api/employees.ts` 패턴 따름). `hooks/` 폴더 쓰지 말 것
8. **Frontend 페이지**: `pages/`에 **플랫 구조**로 `EvalXxxPage.tsx` 명명. 서브폴더 만들지 말 것
9. **axios**: `api/client.ts` import, 직접 인스턴스 만들지 말 것
10. **Zustand**: UI 상태만 (선택된 회차 ID 등)
11. **React Query**: 서버 상태 전용, queryKey는 `['eval', 'domain', { params }]` 배열 형식

### 각 PHASE 진행 방식

- PHASE 순서대로 진행, 각 PHASE 끝나면 **Git 커밋**
- 기존 테이블/컬럼 스키마 수정 금지
- 기존 페이지/api 수정 최소화 (`App.tsx`, `MainLayout.tsx`는 항목 추가만)
- 테스트 커버리지 70%+ (백엔드 pytest, 프론트 vitest)

---

## 📌 사전 준비

```bash
cd D:\AI\INSA
claude
```

---

## PHASE 1 — 평가 공통 기반

```
인사평가 도메인의 공통 기반을 추가해줘.
CLAUDE.md + PHASE 0 요약(insa_eval_prompts_v4.md 상단)을 전제로 작업.

=== 최상위 규칙 (재확인) ===
- sync routes (def), async def 금지
- Alembic 미사용. app/db/models.py에 모델 추가 + init_db.py create_all() 방식
- Role 코드: SYSTEM_ADMIN, HR_ADMIN, DEPT_HEAD, EMPLOYEE
- Frontend: api/{domain}.ts 하나에 fetch + useQuery/useMutation 동시 작성
- Pages는 pages/ 플랫 구조에 EvalXxxPage.tsx
- MainLayout.tsx에 GNB "인사평가" 추가

=== DB 모델 (backend/app/db/models.py에 append) ===
파일 말미 "# ── Evaluation Tables ──" 섹션 추가하고 6개 모델 작성:

1. EvalRound → insa_eval_round
   id, year(Integer), name(String 100),
   start_date(Date), end_date(Date),
   status(String 20, default 'PLANNED') -- PLANNED|IN_PROGRESS|CLOSED
   created_at, updated_at

2. EvalSchedule → insa_eval_schedule
   id, round_id(FK insa_eval_round),
   stage(String 20), -- TARGET|MID|FINAL|COMPREHENSIVE
   start_date, end_date

3. EvalApprover → insa_eval_approver
   id, round_id(FK),
   evaluatee_id(FK insa_employee.id),
   evaluator_id(FK insa_employee.id),
   eval_type(String 10), -- PERF|COMP|MULTI
   rater_type(String 20, nullable), -- MULTI일 때만: BOSS|PEER|SUBORDINATE
   created_at

4. EvalCalibrationGroup → insa_eval_calibration_group
   id, year, name(String 100),
   created_by(FK insa_user.id),
   created_at

5. EvalCalibrationMember → insa_eval_calibration_member
   id, group_id(FK),
   emp_id(FK insa_employee.id)

6. EvalSetting → insa_eval_setting
   id, year(unique),
   weight_config(Text)  -- JSON 직렬화 문자열 저장 (MSSQL NVARCHAR(MAX))
   grade_criteria(Text) -- 예: '[{"grade":"S","min":90,"max":100,"default_ratio":10}]'
   -- 서비스에서 json.loads/dumps로 처리. MSSQL JSON 함수 X.

⚠️ 기존 EmpEvaluation(insa_emp_evaluation) 건드리지 말 것. 별개 유지.

=== DB 스키마 적용 ===
Alembic 미사용이므로:
1. 개발: uvicorn 재기동 시 init_db.py → create_all()로 자동 생성
2. 운영 적용 방법은 기존 init_db.py 호출 흐름 따름
3. 마이그레이션 파일 만들지 말 것

=== Pydantic 스키마 (backend/app/schemas/) ===
기존 파일 패턴 그대로 (app/schemas/employee.py 참고):

- eval_round.py        (EvalRoundBase/Create/Update/Response)
- eval_schedule.py     (일괄 등록용 List 포함)
- eval_approver.py     (단건 + 일괄)
- eval_calibration.py  (GroupBase + MemberBase 통합)
- eval_setting.py      (weight_config/grade_criteria은 dict/list 타입으로 노출, 서비스 레이어에서 json 직렬화)

=== 서비스 (backend/app/services/) ===
기존 app/services/appointment.py 패턴 따름 (함수형, Session 주입):

- eval_round.py          (create, list_by_year, update, close)
- eval_approver.py       (bulk_upsert, list_by_round, delete)
- eval_calibration.py    (group CRUD + member add/remove)
- eval_setting.py        (upsert_by_year, get_by_year + json 직렬화)

=== API 라우터 (backend/app/api/v1/) ===
⚠️ 반드시 sync (def). 기존 appointments.py 패턴 따름.

파일: eval_rounds.py, eval_schedules.py, eval_approvers.py,
      eval_calibration.py, eval_settings.py

GET    /api/v1/eval/rounds?year=
POST   /api/v1/eval/rounds
PUT    /api/v1/eval/rounds/{id}
PUT    /api/v1/eval/rounds/{id}/close

GET    /api/v1/eval/schedules?round_id=
POST   /api/v1/eval/schedules  (일괄)

GET    /api/v1/eval/approvers?round_id=&eval_type=
POST   /api/v1/eval/approvers  (일괄 매핑, List[EvalApproverCreate])
DELETE /api/v1/eval/approvers/{id}

GET    /api/v1/eval/calibration-groups?year=
POST   /api/v1/eval/calibration-groups
PUT    /api/v1/eval/calibration-groups/{id}
POST   /api/v1/eval/calibration-groups/{id}/members
DELETE /api/v1/eval/calibration-groups/{id}/members/{emp_id}

GET    /api/v1/eval/settings?year=
PUT    /api/v1/eval/settings   (upsert)

권한: SYSTEM_ADMIN, HR_ADMIN만 쓰기/수정. 조회는 get_current_user만.
require_roles("SYSTEM_ADMIN", "HR_ADMIN") 사용.

=== 라우터 등록 ===
app/api/v1/router.py에 5개 router include 추가.

=== 테스트 (backend/tests/) ===
기존 tests/ 구조 따름 (없으면 conftest.py 먼저). pytest:
- test_eval_rounds.py: CRUD + close 상태 전이
- test_eval_approvers.py: 일괄 upsert, duplicate 처리
- test_eval_calibration.py: group+member CRUD
- test_eval_settings.py: json weight_config upsert
커버리지 70%+. SYSTEM_ADMIN/HR_ADMIN/EMPLOYEE 권한 분기 포함.

=== 프론트엔드 (frontend/src/) ===

🔸 api 파일 (api/eval.ts 단일 파일로 통합 OR 5개 분리)
기존 api/employees.ts 패턴 그대로:
- fetch 함수 + useXxx hook을 같은 파일에 공존
- apiClient (api/client.ts)를 import
- queryKey: ['eval', 'rounds', { year }], ['eval', 'approvers', { round_id, eval_type }] 등

권장: api/evalRounds.ts, api/evalApprovers.ts, api/evalCalibration.ts,
      api/evalSettings.ts 파일 분리 (파일당 ~150줄 유지)

🔸 페이지 (frontend/src/pages/ - 플랫)
- EvalRoundPage.tsx          # 평가 회차 관리
- EvalSchedulePage.tsx       # 평가 일정
- EvalApproverPage.tsx       # 평가자 매핑
- EvalCalibrationPage.tsx    # 보정집단
- EvalSettingPage.tsx        # 반영비율/등급기준
Ant Design Table/Form/Modal 직접 사용. 공통 컴포넌트 추상화 만들지 말 것.

🔸 App.tsx 라우트 추가 (인라인)
/eval/rounds, /eval/schedules, /eval/approvers,
/eval/calibration, /eval/settings

🔸 MainLayout.tsx 수정 (항목 추가만)
- GnbKey 타입에 "인사평가" 추가
- gnbItems 배열에 "인사평가" 추가 (위치: "복리후생"과 "문서함" 사이)
- sidebarByGnb에 "인사평가" 키 추가:
  {
    key: "eval-common",
    label: "평가 설정",
    type: "group",
    children: [
      { key: "/eval/rounds", label: "평가 회차", icon: <FileTextOutlined /> },
      { key: "/eval/schedules", label: "평가 일정", icon: <ClockCircleOutlined /> },
      { key: "/eval/approvers", label: "평가자 매핑", icon: <TeamOutlined /> },
      { key: "/eval/calibration", label: "보정집단", icon: <TeamOutlined /> },
      { key: "/eval/settings", label: "반영비율/등급", icon: <SettingOutlined /> },
    ],
  }
- gnbDefaultPath에 "인사평가": "/eval/rounds"
- pathPrefixToGnb에 { prefix: "/eval", gnb: "인사평가" }

🔸 Zustand store 추가
frontend/src/store/evalUI.ts — selectedRoundId 등 UI 상태만
(서버 데이터는 React Query로만)

=== Vitest 테스트 (frontend/src/pages/__tests__/ 또는 각 파일 옆) ===
- EvalRoundPage 렌더링 + 생성 모달
- EvalApproverPage 일괄 등록
- API fetch mock + React Query 동작
커버리지 70%+.

=== 완료 후 보고 ===
1. models.py에 추가된 모델 6개 클래스명
2. 추가된 API 엔드포인트 목록 (sync 재확인)
3. App.tsx 추가 라우트 5개
4. MainLayout 수정 라인 요약
5. pytest / vitest 실행 결과 (pass/fail 수, 커버리지)
6. git commit 제안:
   git add backend/app/db/models.py backend/app/schemas/eval_*.py \
           backend/app/services/eval_*.py backend/app/api/v1/eval_*.py \
           backend/app/api/v1/router.py \
           frontend/src/api/eval*.ts frontend/src/pages/Eval*Page.tsx \
           frontend/src/App.tsx frontend/src/components/MainLayout.tsx \
           frontend/src/store/evalUI.ts
   git commit -m "feat: add eval common foundation (round, schedule, approver, calibration, setting)"
```

---

## PHASE 2 — 성과평가 (PERF)

```
성과평가 모듈 추가. CLAUDE.md + v4 PHASE 0 요약 + 최상위 규칙 전제.
PHASE 1이 완료된 상태.

=== DB 모델 (models.py append) ===
- PerfKpi → insa_perf_kpi
  id, round_id(FK), code(String 50), name(String 200),
  measure_type(String 30), weight(Numeric(5,2)), perspective(String 30)

- PerfTarget → insa_perf_target
  id, emp_id(FK insa_employee.id), round_id(FK),
  kpi_id(FK insa_perf_kpi.id, nullable),
  target_value(Text), is_organization(Boolean default False),
  status(String 20 default 'DRAFT'), -- DRAFT|SUBMITTED|APPROVED|REJECTED
  weight_percent(Numeric(5,2)),
  created_at, updated_at

- PerfTargetMid → insa_perf_target_mid
  id, target_id(FK), progress_rate(Numeric(5,2)),
  description(Text), expected_rate(Numeric(5,2)),
  submitted_at(DateTime)

- PerfTargetFinal → insa_perf_target_final
  id, target_id(FK), achievement_rate(Numeric(5,2)),
  description(Text), self_score(Numeric(5,2)),
  submitted_at

- PerfEvalResult → insa_perf_eval_result
  id, emp_id(FK), round_id(FK), evaluator_id(FK insa_employee.id),
  score(Numeric(5,2)), grade(String 5), comment(Text),
  created_at

=== Pydantic 스키마 ===
- perf_kpi.py
- perf_target.py (Create/Update/StatusTransition/Response)
- perf_midterm.py
- perf_final.py
- perf_result.py

=== 서비스 ===
- perf_kpi.py (CRUD)
- perf_target.py
  - create/update/submit/approve/reject (상태 전이 검증)
  - weight_percent 합계 검증 (한 사원 × 회차 기준 ≤ 100)
- perf_midterm.py / perf_final.py (upsert)
- perf_result.py (조회 + 평가자 기록)

=== API (sync routes, app/api/v1/) ===
파일: perf_kpis.py, perf_targets.py, perf_midterm.py, perf_final.py, perf_results.py

GET  /api/v1/eval/perf/kpis?round_id=
POST /api/v1/eval/perf/kpis  (SYSTEM_ADMIN/HR_ADMIN)

GET  /api/v1/eval/perf/targets?emp_id=&round_id=
POST /api/v1/eval/perf/targets         (본인)
PUT  /api/v1/eval/perf/targets/{id}    (본인, status=DRAFT)
PUT  /api/v1/eval/perf/targets/{id}/submit  (본인)
PUT  /api/v1/eval/perf/targets/{id}/approve (evaluator — insa_eval_approver로 검증)
PUT  /api/v1/eval/perf/targets/{id}/reject  (evaluator)

POST /api/v1/eval/perf/midterm
GET  /api/v1/eval/perf/midterm?target_id=

POST /api/v1/eval/perf/final
GET  /api/v1/eval/perf/final?target_id=

GET  /api/v1/eval/perf/results?round_id=&dept_id=

권한:
- 목표 조회: 본인 | insa_eval_approver의 evaluator_id 일치 | HR_ADMIN/SYSTEM_ADMIN
- 승인/반려: insa_eval_approver(eval_type='PERF') 매핑된 평가자 전용
- 결과 조회: 본인 + 평가라인 + HR_ADMIN/SYSTEM_ADMIN

router.py에 5개 include 추가.

=== 프론트엔드 ===

🔸 api/ (fetch + hook 공존)
- api/perfKpi.ts
- api/perfTarget.ts     (useTargets, useTargetMutation { create, update, submit, approve, reject })
- api/perfMidterm.ts
- api/perfFinal.ts
- api/perfResult.ts

queryKey 예시:
['eval', 'perf', 'targets', { emp_id, round_id }]
['eval', 'perf', 'results', { round_id, dept_id }]

🔸 페이지 (pages/ 플랫)
- PerfMyDashboardPage.tsx     # 내 평가 현황
- PerfTargetSettingPage.tsx   # 목표과제 입력
- PerfMidtermPage.tsx         # 중간점검
- PerfFinalPage.tsx           # 기말실적
- PerfApprovalInboxPage.tsx   # 평가자 승인 대기
- PerfTeamStatusPage.tsx      # 부서별 현황

🔸 App.tsx 라우트 추가
/eval/perf/dashboard, /eval/perf/target, /eval/perf/midterm,
/eval/perf/final, /eval/perf/approval, /eval/perf/team

🔸 MainLayout.tsx sidebarByGnb["인사평가"]에 group 추가
{
  key: "eval-perf",
  label: "성과평가",
  type: "group",
  children: [
    { key: "/eval/perf/dashboard", label: "내 평가 현황", ... },
    { key: "/eval/perf/target", label: "목표과제 작성", ... },
    { key: "/eval/perf/midterm", label: "중간점검", ... },
    { key: "/eval/perf/final", label: "기말실적", ... },
    { key: "/eval/perf/approval", label: "승인 대기", ... },
  ]
}

🔸 공통 UI 컴포넌트 (필요 시)
- components/ApprovalFlowBar.tsx (결재 단계 시각화)
- components/EvalScoreInput.tsx (슬라이더/숫자)
만들고 pages에서 재사용. 과도한 추상화 금지.

🔸 Zustand store/evalUI.ts에 선택 target ID 등 추가

=== 테스트 ===
pytest:
- target 상태 전이 DRAFT→SUBMITTED→APPROVED
- weight_percent 합계 검증
- 권한 분기 (본인/evaluator/HR_ADMIN) 각각
- midterm/final upsert

vitest:
- PerfMyDashboard 렌더링
- PerfTargetSettingPage 폼 submit
- PerfApprovalInboxPage 승인 액션 mutation

커버리지 70%+.

=== 완료 후 ===
E2E 시나리오 수동 테스트 보고:
1. EMPLOYEE 로그인 → 목표 입력 → 제출
2. DEPT_HEAD(또는 매핑된 evaluator) 로그인 → ApprovalInbox 승인
3. 중간점검 → 기말실적

git commit -m "feat: add perf evaluation module (kpi, target, midterm, final, result)"
```

---

## PHASE 3 — 역량평가 (COMP)

```
역량평가 모듈 추가. v4 전제 유지.

=== DB 모델 (models.py append) ===
- CompIndicator → insa_comp_indicator
  id, year, code(String 50), name(String 200),
  description(Text), weight(Numeric(5,2))

- CompBehavior → insa_comp_behavior
  id, indicator_id(FK), level(Integer 1~5), description(Text)

- CompEvalSelf → insa_comp_eval_self
  id, emp_id(FK), round_id(FK), indicator_id(FK),
  score(Integer 1~5), comment(Text), submitted_at

- CompEvalBoss → insa_comp_eval_boss
  id, evaluatee_id(FK), evaluator_id(FK), round_id(FK),
  indicator_id(FK), score(Integer 1~5), comment(Text),
  submitted_at

- CompSarRecord → insa_comp_sar_record
  id, target_emp_id(FK), observer_id(FK), observed_date(Date),
  situation(Text), action(Text), result(Text)

=== Pydantic 스키마 ===
- comp_indicator.py (behavior 포함)
- comp_self.py
- comp_boss.py
- comp_sar.py

=== 서비스 ===
- comp_indicator.py
- comp_self.py (upsert by (emp, round, indicator))
- comp_boss.py (upsert by (evaluatee, evaluator, round, indicator))
- comp_sar.py (CRUD)

점수 범위 검증: 1 ≤ score ≤ 5 (Pydantic validator)

=== API (sync) ===
GET  /api/v1/eval/comp/indicators?year=
POST /api/v1/eval/comp/indicators   (HR_ADMIN/SYSTEM_ADMIN)

GET  /api/v1/eval/comp/my-eval?round_id=   (본인)
POST /api/v1/eval/comp/self   (본인 일괄 제출)
POST /api/v1/eval/comp/boss   (evaluator — insa_eval_approver eval_type='COMP' 매핑자)

GET  /api/v1/eval/comp/sar?emp_id=
POST /api/v1/eval/comp/sar   (observer_id=current_user.employee_id)

router.py include 추가.

=== 프론트엔드 ===

🔸 api/
- api/compIndicator.ts
- api/compMyEval.ts (self 제출 + self 조회 포함)
- api/compBoss.ts
- api/compSar.ts

🔸 페이지
- CompSelfPage.tsx       # 본인평가 (Ant Collapse + InputNumber/Radio.Group)
- CompBossPage.tsx       # 상사평가 (본인평가 참고값 표시)
- CompSarPage.tsx        # SAR 타임라인 (Ant Timeline)

🔸 App.tsx 라우트 추가
/eval/comp/self, /eval/comp/boss, /eval/comp/sar

🔸 MainLayout sidebarByGnb["인사평가"]에 group 추가
{
  key: "eval-comp",
  label: "역량평가",
  type: "group",
  children: [
    { key: "/eval/comp/self", label: "본인평가", ... },
    { key: "/eval/comp/boss", label: "상사평가", ... },
    { key: "/eval/comp/sar", label: "SAR 관찰기록", ... },
  ]
}

=== 테스트 ===
pytest:
- 점수 범위 검증 (0, 6 → 422)
- 상사평가 권한 분기 (매핑 안 된 유저 → 403)
- SAR CRUD

vitest:
- Collapse 펼침/접힘
- InputNumber submit mutation

커버리지 70%+.

git commit -m "feat: add competency evaluation module (indicator, self, boss, sar)"
```

---

## PHASE 4 — 다면평가 (MULTI, 익명성 핵심)

```
다면평가 모듈 추가. 익명성 보장이 최우선.
v4 전제 유지.

=== DB 모델 (models.py append) ===
- MultiEvalIndicator → insa_multi_eval_indicator
  id, round_id(FK), name(String 200),
  description(Text), max_score(Integer default 5)

- MultiEvalResponse → insa_multi_eval_response
  id, round_id(FK), evaluatee_id(FK),
  rater_type(String 20), -- BOSS|PEER|SUBORDINATE
  indicator_id(FK), score(Numeric(5,2)), comment(Text, nullable)
  ⚠️ evaluator_id 컬럼 절대 없음 — 스키마 자체에서 익명

- MultiEvalResponseLog → insa_multi_eval_response_log
  id, evaluator_id(FK), round_id(FK),
  evaluatee_id(FK), submitted_at(DateTime)
  (제출 여부만 추적. 점수/지표 ID 없음. response 테이블과 공통 키 없음)

- MultiEvalResult → insa_multi_eval_result
  id, round_id(FK), evaluatee_id(FK), indicator_id(FK),
  avg_score(Numeric(5,2)), response_count(Integer)

=== 익명성 아키텍처 핵심 ===
서비스 `submit_multi_response`:
1. 트랜잭션 시작
2. insa_multi_eval_response_log에 (evaluator_id, round_id, evaluatee_id, now) 저장
3. 각 indicator별 insa_multi_eval_response에 (round_id, evaluatee_id, rater_type, indicator_id, score, comment) 저장 — **evaluator_id는 절대 전달하지 않음**
4. 커밋

결과 조회 `get_multi_result`:
- response_count < 3 → 익명 보호를 위해 "응답자 부족" 반환 (200 + flag 권장)
- 평균만 반환, 개별 점수 조회 API 자체를 만들지 않음

=== Pydantic 스키마 ===
- multi_indicator.py
- multi_response.py (Submit: List[indicator_id + score + comment] + evaluatee_id + rater_type)
- multi_result.py

=== 서비스 ===
- multi_indicator.py
- multi_response.py (submit, list_targets_for_me)
- multi_result.py (calculate_result, get_result_for_emp)

=== API (sync) ===
GET  /api/v1/eval/multi/indicators?round_id=
POST /api/v1/eval/multi/indicators   (HR_ADMIN/SYSTEM_ADMIN)

GET  /api/v1/eval/multi/my-targets?round_id=  -- 내가 평가할 대상자
POST /api/v1/eval/multi/response              -- 익명 저장
GET  /api/v1/eval/multi/results/{emp_id}?round_id=  -- 본인만 or HR_ADMIN
GET  /api/v1/eval/multi/status?round_id=      -- 관리자: 제출률 (이름 없이)

router.py include 추가.

=== 프론트엔드 ===

🔸 api/
- api/multiIndicator.ts
- api/multiResponse.ts  (useMyTargets, useSubmitResponse)
- api/multiResult.ts

🔸 페이지
- MultiEvalPage.tsx       # 평가 대상자 카드 + 연속 입력 플로우
- MultiResultPage.tsx     # 내 다면평가 결과 (평균만)
- MultiStatusPage.tsx     # 관리자: 제출률 대시보드

🔸 App.tsx 라우트
/eval/multi/input, /eval/multi/result, /eval/multi/status

🔸 MainLayout sidebar group 추가
{
  key: "eval-multi",
  label: "다면평가",
  type: "group",
  children: [
    { key: "/eval/multi/input", label: "다면평가 입력", ... },
    { key: "/eval/multi/result", label: "내 다면평가 결과", ... },
    { key: "/eval/multi/status", label: "제출 현황", ... }, -- 관리자만 노출 제어
  ]
}

=== 테스트 (익명성 검증 필수) ===
pytest:
- insa_multi_eval_response 테이블 컬럼 목록에 evaluator_id 없음 (introspection)
- insa_multi_eval_response_log 컬럼에 점수/지표 컬럼 없음
- 응답 저장 후 response 테이블 row에 evaluator 추적 가능 컬럼 없음
- response_count < 3일 때 result API가 응답자 부족 플래그 반환
- response_count >= 3일 때 평균만 반환
- 개별 점수 조회 API 엔드포인트 부재 확인 (router inspection)

vitest:
- MultiEvalPage 카드 리스트 + 연속 입력
- MultiResultPage 응답자 부족 케이스

커버리지 70%+.

=== 완료 후 익명성 체크리스트 ===
[ ] response 스키마에 evaluator_id 컬럼 없음
[ ] response_log에 score/indicator_id 컬럼 없음
[ ] 두 테이블 간 공통 키 없음 (JOIN 역추적 불가)
[ ] response_count < 3 응답 보호
[ ] 개별 점수 조회 API 부재
[ ] 서비스 레이어에서도 evaluator_id를 response에 넣는 코드 없음 (grep 검증)

git commit -m "feat: add multi-source evaluation with anonymity (indicator, response, result)"
```

---

## PHASE 5 — 종합평가 + 등급 산출

```
종합평가 모듈 추가. v4 전제 유지.

⚠️ 접두사: insa_eval_* (insa_perf_ 아님). 종합은 perf+comp+multi 통합이므로 eval_이 의미적으로 맞음.

=== DB 모델 (models.py append) ===
- EvalComprehensive → insa_eval_comprehensive
  id, emp_id(FK), round_id(FK),
  perf_score(Numeric(5,2)), comp_score(Numeric(5,2)), multi_score(Numeric(5,2)),
  total_score(Numeric(5,2)),
  original_grade(String 5), final_grade(String 5),
  is_adjusted(Boolean default False),
  adjusted_by(FK insa_user.id, nullable),
  adjusted_reason(Text, nullable),
  calculated_at(DateTime), adjusted_at(DateTime, nullable)

- EvalObjection → insa_eval_objection
  id, emp_id(FK), round_id(FK), reason(Text),
  status(String 20 default 'PENDING'), -- PENDING|REVIEWED|ACCEPTED|REJECTED
  created_at

- EvalObjectionReview → insa_eval_objection_review
  id, objection_id(FK), reviewer_id(FK insa_user.id),
  decision(String 20), comment(Text),
  reviewed_at

=== 종합점수 계산 서비스 (services/eval_comprehensive.py) ===
calculate_comprehensive(db, round_id):
1. insa_eval_setting.weight_config 읽기 (json.loads)
2. 대상 사원 목록 (해당 회차 insa_eval_approver에 등장한 evaluatee_id distinct)
3. 각 사원별:
   - perf: insa_perf_eval_result의 score 평균
   - comp: insa_comp_eval_boss score 평균 (self는 참고용, 종합엔 boss 사용)
   - multi: insa_multi_eval_result.avg_score 평균
4. total = perf × w_perf + comp × w_comp + multi × w_multi (weight 합=100 전제)
5. grade_criteria로 original_grade 산정
6. insa_eval_comprehensive upsert (기존 행 있으면 update, 없으면 insert)

calibrate_by_group(db, group_id, target_distribution):
- 옵션 로직. 그룹 내 분포 비율에 맞춰 final_grade 조정 가능 (관리자 검토용)

manual_adjust_grade(db, comp_id, new_grade, reason, adjusted_by):
- final_grade, is_adjusted=True, adjusted_by, adjusted_reason, adjusted_at 저장
- original_grade는 절대 변경하지 않음 (보존)

=== Pydantic 스키마 ===
- eval_comprehensive.py (Calculate request/Response/GradeAdjust)
- eval_objection.py (Create/Review/Response)

=== API (sync) ===
GET  /api/v1/eval/comprehensive?round_id=       (HR_ADMIN/SYSTEM_ADMIN, 본인은 자기 행만)
POST /api/v1/eval/comprehensive/calculate       (HR_ADMIN/SYSTEM_ADMIN)
PUT  /api/v1/eval/comprehensive/{id}/grade      (HR_ADMIN/SYSTEM_ADMIN, adjusted_reason 필수)

POST /api/v1/eval/objections                    (본인)
GET  /api/v1/eval/objections?round_id=          (관리자: 전체, 본인: 자기 것)
PUT  /api/v1/eval/objections/{id}/review        (HR_ADMIN/SYSTEM_ADMIN)

router.py include 추가.

=== 프론트엔드 ===

🔸 api/
- api/evalComprehensive.ts (useList, useCalculate, useGradeAdjust)
- api/evalObjection.ts

🔸 페이지
- EvalComprehensiveListPage.tsx    # 대상자 목록 + 일괄 계산
- EvalGradeAdjustmentPage.tsx      # 등급 조정 (인사위원회)
- EvalObjectionListPage.tsx        # 이의신청 관리
- EvalMyResultPage.tsx             # 본인 종합 결과

🔸 EvalGradeAdjustmentPage 핵심 UI
- Select: 보정집단
- Table: 그룹 내 대상자 (점수 desc)
- Ant Statistic + Progress: 현재 등급 분포 vs 목표 분포
- Table 컬럼에 Select: 등급 인라인 편집 (S/A/B/C/D)
- TextArea: 변경 사유 (필수)
- Button: 일괄 저장 (mutation으로 PUT /{id}/grade 반복 호출 or bulk endpoint)

🔸 App.tsx 라우트
/eval/comprehensive, /eval/comprehensive/adjust,
/eval/objection, /eval/my-result

🔸 MainLayout sidebar group 추가
{
  key: "eval-comp-final",
  label: "종합평가",
  type: "group",
  children: [
    { key: "/eval/comprehensive", label: "종합평가 조회", ... },
    { key: "/eval/comprehensive/adjust", label: "등급 조정", ... },
    { key: "/eval/objection", label: "이의신청", ... },
    { key: "/eval/my-result", label: "내 종합 결과", ... },
  ]
}

=== 테스트 ===
pytest:
- calculate_comprehensive: weight 정합 (합 != 100 → 검증 실패 or 정규화 정책 명시)
- grade_criteria 경계값 (min/max inclusive/exclusive)
- manual_adjust_grade: adjusted_reason 없으면 400
- original_grade 보존 (adjust 후에도 unchanged)
- 이의신청 상태 전이

vitest:
- 등급 분포 차트
- 인라인 편집 mutation + 사유 필수 검증
- 이의신청 폼

커버리지 70%+.

=== 완료 후 E2E 시나리오 ===
1. 회차 close 전 상태 → calculate → 자동 등급 산정 확인
2. 수동 조정 + 사유 저장 → original/final 둘 다 조회 가능
3. EMPLOYEE가 이의신청 → HR_ADMIN 재심의 → ACCEPTED/REJECTED

git commit -m "feat: add comprehensive evaluation (calculation, grade adjustment, objection)"
```

---

## PHASE 6 — 통합 테스트 + 마무리

```
인사평가 모듈 전체 통합 검증 + 문서화.

=== 체크리스트 ===

1. 시드 데이터 스크립트 (backend/scripts/seed_eval.py)
   - init_db.py와 분리. 직접 실행 가능한 스크립트.
   - 현재 연도 평가 회차 1개 (status=IN_PROGRESS)
   - 4단계 일정
   - KPI 5개 (샘플)
   - 역량지표 8개 + 행동지표 각 5레벨
   - 다면지표 4개
   - 기존 7명 직원 기준 평가자 매핑:
     - BOSS: dept_id 기반 팀장
     - PEER: 같은 부서 동료
     - SUBORDINATE: 팀장의 부서원
   - 보정집단 3개 (직급별)
   - insa_eval_setting: weight={perf:40, comp:30, multi:30},
     grade S:90-100/A:80-90/B:70-80/C:60-70/D:<60, default_ratio 10/20/40/20/10

2. E2E 시나리오 수동 테스트
   a. EMPLOYEE 로그인 → 목표 입력 → 제출
   b. DEPT_HEAD 로그인 → ApprovalInbox 승인
   c. 중간점검 → 기말실적 제출
   d. 본인평가 → 상사평가 완료
   e. 다면평가 3명 이상 익명 제출
   f. HR_ADMIN: calculate → 등급 확인 → 수동 조정 → 회차 close
   g. 이의신청 → 재심의 플로우

3. 권한 매트릭스 검증
   | Role          | 평가 설정 | 본인평가 | 승인 | 등급 조정 | 재심의 |
   |---------------|----------|---------|------|----------|--------|
   | SYSTEM_ADMIN  | ✅       | ✅      | ✅   | ✅       | ✅     |
   | HR_ADMIN      | ✅       | ✅      | -    | ✅       | ✅     |
   | DEPT_HEAD     | -        | ✅      | ✅*  | -        | -      |
   | EMPLOYEE      | -        | ✅      | -    | -        | 제출만 |
   * insa_eval_approver에 매핑된 경우만

4. CLAUDE.md 규칙 감사
   [ ] 모든 평가 라우터 sync (grep 'async def' backend/app/api/v1/eval*)
   [ ] 모든 테이블 insa_ 접두사
   [ ] Zustand에 서버 데이터 없음
   [ ] React Query 없이 직접 axios 호출 없음 (grep 'axios' frontend/src/pages/Eval*)
   [ ] Alembic 파일 신규 생성 없음
   [ ] Role 코드 오타 없음 (SYSTEM_ADMIN, HR_ADMIN, DEPT_HEAD, EMPLOYEE)

5. 테스트 커버리지
   - cd backend && pytest --cov=app tests/ (70%+)
   - cd frontend && npm run test -- --coverage (70%+)
   - 실제 출력으로 증빙 (숫자 복사)

6. 문서 업데이트
   - CLAUDE.md에 "인사평가 모듈" 섹션 추가:
     - 23개 테이블 요약표
     - API 경로 prefix (/api/v1/eval/*)
     - Role별 접근 권한 요약
     - 익명성 보장 원칙 (다면평가)
   - docs/EVAL_MODULE.md 신규 작성:
     - 도메인 용어 사전
     - ER 다이어그램 (텍스트 or mermaid)
     - 워크플로 다이어그램 (상태 전이 포함)
     - API 전체 레퍼런스

=== 완료 후 최종 보고 ===
- 체크리스트 결과 (✅/❌)
- pytest/vitest 커버리지 숫자
- 추가된 테이블 총 N개, 엔드포인트 총 N개, 페이지 총 N개
- 개선 제안 (성능/UX)

Git 커밋:
git commit -m "test: add e2e evaluation workflow tests and seed script"
git commit -m "docs: add eval module section to CLAUDE.md and EVAL_MODULE.md"
```

---

## 💡 사용 팁

### 진행 순서

1. **이 문서 상단 PHASE 0 요약**을 읽고 현 프로젝트와 일치하는지 재확인 (달라졌으면 이 문서 업데이트)
2. PHASE 1~6 순서대로 진행
3. 각 PHASE 끝나면 **반드시 Git 커밋** (테스트 통과 + 커버리지 확인 후)
4. `models.py`는 단일 파일이므로 **append만**. 기존 모델 수정 금지.

### 문제 발생 시 보조 프롬프트

```
추가된 평가 라우터 중 async def가 있으면 sync로 바꿔줘
```
```
insa_ 접두사 없는 신규 테이블 있으면 찾아서 보고해줘
```
```
frontend/src/pages/Eval*.tsx 중 React Query 없이 axios 직접 호출하는 곳 찾아줘
```
```
insa_multi_eval_response 테이블의 컬럼 목록 조회해서 evaluator_id 없는지 확인해줘
```
```
마지막 변경 되돌리고 현재 상태 요약해줘
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

기존 `insa_emp_evaluation`은 별개로 유지.

---

## 🚨 최종 경고 (v3와 달라진 지점 포함)

- **Alembic 마이그레이션 생성 금지** — 프로젝트가 `create_all()` 사용 중
- `async def` 절대 금지 — 모든 라우터 sync
- `insa_` 접두사 없는 테이블 생성 금지
- Role 코드 정확히: `SYSTEM_ADMIN`, `HR_ADMIN`, `DEPT_HEAD`, `EMPLOYEE`
- Frontend `hooks/` 폴더 쓰지 말 것 — `api/*.ts`에 co-locate
- Frontend `pages/` 플랫 구조 유지 — 서브폴더 만들지 말 것
- `DataTable`/`SearchForm` 같은 추상 컴포넌트 만들지 말 것 — 기존 프로젝트는 Ant Design 직접 사용
- Zustand에 서버 데이터 금지, React Query로만
- `models.py` append만, 기존 모델 수정 금지
- 각 PHASE 끝나면 `git commit` 필수
- 테스트 커버리지 70% 미달 시 해당 PHASE 미완료로 간주
- 다면평가 익명성: 체크리스트 6개 항목 전부 ✅ 아니면 PHASE 4 미완료
