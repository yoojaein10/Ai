# HR 인사평가 시스템 - Claude Code 실행 프롬프트

> 사용법: 각 PHASE를 순서대로 Claude Code 터미널에 하나씩 복사-붙여넣기  
> 위치: `D:\AI\INSA`  
> 이전 PHASE 완료 후 다음 PHASE 진행

---

## 📌 사전 준비 (한 번만)

터미널에서 실행:
```bash
cd D:\AI\INSA
claude
```

그 다음 아래 프롬프트를 순서대로 붙여넣으세요.

---

## PHASE 0 — 초기 컨텍스트 설정

```
앞으로 D:\AI\INSA 디렉토리에서 HR 인사평가 시스템을 만들 거야.

[필수 규칙]
- 작업 디렉토리: D:\AI\INSA
- 백엔드: D:\AI\INSA\hr-backend (FastAPI + SQLAlchemy + MSSQL)
- 프론트엔드: D:\AI\INSA\hr-frontend (React 18 + TypeScript + Vite)
- Python 3.11+, Node 20+
- 모든 한글 주석/메시지는 UTF-8
- 매 PHASE 끝나면 "완료" 한 줄과 함께 다음 명령 대기
- 내가 명시하지 않은 기능은 구현하지 말고, 불확실하면 먼저 물어봐
- 파일 생성/수정 시 한 번에 너무 많이 하지 말고 단계별로 진행

[기술 스택 확정]
- 백엔드: FastAPI, SQLAlchemy 2.x, pyodbc, python-jose (JWT), passlib
- DB: MSSQL (localhost\SQLEXPRESS 또는 지정 서버)
- 프론트: React 18 + TypeScript + Vite, Zustand, @tanstack/react-query, @tanstack/react-table, axios, antd
- 라우터: react-router-dom v6

이해했으면 "준비 완료"만 출력하고 다음 지시를 기다려.
```

---

## PHASE 1 — 프로젝트 스켈레톤 생성

```
D:\AI\INSA 아래에 백엔드/프론트엔드 스켈레톤을 만들어줘.

[백엔드: D:\AI\INSA\hr-backend]
hr-backend/
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI 앱 진입점
│   ├── core/
│   │   ├── config.py              # 환경변수, DB URL
│   │   ├── security.py            # JWT, 비밀번호 해시
│   │   └── deps.py                # 의존성 주입 (current_user 등)
│   ├── db/
│   │   ├── base.py                # Base = declarative_base()
│   │   └── session.py             # SessionLocal, get_db()
│   ├── models/                    # SQLAlchemy 모델
│   │   └── __init__.py
│   ├── schemas/                   # Pydantic 스키마
│   │   └── __init__.py
│   ├── services/                  # 비즈니스 로직
│   │   └── __init__.py
│   └── api/v1/
│       ├── __init__.py
│       ├── router.py              # 전체 v1 라우터 모음
│       └── endpoints/
│           ├── __init__.py
│           └── auth.py            # 로그인/토큰 갱신
├── alembic/                       # 마이그레이션
├── alembic.ini
├── .env.example                   # DB_URL, SECRET_KEY, CORS_ORIGINS
├── requirements.txt
└── README.md

[requirements.txt 내용]
fastapi>=0.110
uvicorn[standard]>=0.27
sqlalchemy>=2.0
pyodbc>=5.0
alembic>=1.13
python-jose[cryptography]>=3.3
passlib[bcrypt]>=1.7
python-multipart>=0.0.9
pydantic-settings>=2.2

[프론트엔드: D:\AI\INSA\hr-frontend]
- Vite + React + TypeScript 템플릿으로 생성 (npm create vite@latest)
- 추가 설치: antd, @ant-design/icons, axios, zustand, 
  @tanstack/react-query, @tanstack/react-table,
  react-router-dom, dayjs
- src/ 아래 구조:
  src/
  ├── main.tsx
  ├── App.tsx
  ├── api/
  │   ├── client.ts               # axios 인스턴스 + 인터셉터
  │   └── auth.ts
  ├── components/
  │   ├── Layout/                 # GNB + LNB 레이아웃
  │   ├── DataTable/
  │   └── SearchForm/
  ├── pages/
  │   ├── Login.tsx
  │   └── Dashboard.tsx
  ├── hooks/
  ├── store/
  │   └── authStore.ts            # Zustand
  ├── routes/
  │   └── index.tsx               # 라우터 설정
  └── types/

[작업 순서]
1. 백엔드 폴더 구조 생성 + 빈 파일
2. requirements.txt, .env.example, main.py 최소 구현
3. 프론트엔드 Vite 프로젝트 생성
4. 패키지 설치
5. 백엔드 실행 테스트 (uvicorn app.main:app --reload) + 프론트 실행 테스트 (npm run dev)

각 단계마다 확인하고 넘어가. 오류 나면 멈춰.
```

---

## PHASE 2 — MSSQL 연결 + JWT 인증

```
백엔드에 MSSQL 연결과 JWT 인증을 구현해줘.

[환경변수 .env]
DATABASE_URL=mssql+pyodbc://@localhost\SQLEXPRESS/HR_INSA?driver=ODBC+Driver+17+for+SQL+Server&trusted_connection=yes
SECRET_KEY=<랜덤 32자>
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7
CORS_ORIGINS=http://localhost:5173

[구현 파일]
1. app/core/config.py
   - Pydantic BaseSettings로 .env 읽기

2. app/db/session.py
   - engine = create_engine(settings.DATABASE_URL)
   - SessionLocal, get_db() 제너레이터

3. app/core/security.py
   - hash_password, verify_password (passlib)
   - create_access_token, create_refresh_token
   - decode_token

4. app/models/user.py
   - users 테이블: id, username, password_hash, emp_id(FK), 
     role, is_active, created_at
   - emp_id는 나중에 hr_employee와 연결

5. app/schemas/auth.py
   - LoginRequest, TokenResponse, UserInfo

6. app/api/v1/endpoints/auth.py
   POST /auth/login      # username + password → access + refresh
   POST /auth/refresh    # refresh token → 새 access
   GET  /auth/me         # 현재 사용자 정보

7. app/core/deps.py
   - get_current_user 의존성

8. app/main.py
   - CORS 미들웨어
   - v1 라우터 include

[테스트]
- 테스트용 사용자 시드 스크립트: scripts/create_admin.py
  (admin/admin123 계정 생성)
- curl로 로그인 → /auth/me 호출까지 확인

완료되면 MSSQL 연결 상태와 /auth/login 응답 예시를 보여줘.
```

---

## PHASE 3 — 프론트 로그인 + 레이아웃

```
프론트엔드 로그인 흐름과 공통 레이아웃을 구현해줘.

[작업 내용]
1. src/api/client.ts
   - axios 인스턴스 (baseURL: http://localhost:8000/api/v1)
   - 요청 인터셉터: Authorization Bearer 토큰 자동 추가
   - 응답 인터셉터: 401 시 refresh 토큰으로 재발급 시도
   - 재발급 실패 시 로그아웃 + /login 이동

2. src/store/authStore.ts (Zustand)
   - accessToken, refreshToken, user
   - login(), logout(), setTokens()
   - localStorage persist

3. src/pages/Login.tsx
   - Ant Design Form 사용
   - 로그인 성공 시 /dashboard로 이동

4. src/components/Layout/
   - AppLayout.tsx: GNB(상단) + LNB(좌측) + Content
   - GNB: 로고, 대메뉴 탭, 알림, 프로필 드롭다운(로그아웃)
   - LNB: 메뉴 트리 + 즐겨찾기 (일단 하드코딩, 나중에 API 연동)
   - 반응형: 1280px 이하에서 LNB 아이콘 모드

5. src/routes/index.tsx
   - react-router-dom v6
   - PrivateRoute 래퍼 (미로그인 시 /login으로)
   - /login, /dashboard, / (redirect)

6. src/pages/Dashboard.tsx
   - 간단한 "안녕하세요, {user.name}님" 표시

[스타일]
- Ant Design 기본 테마
- 사이드바 너비 240px, 헤더 높이 56px
- 컨텐츠 영역 패딩 24px

완료되면 로그인 → 대시보드 진입까지 브라우저로 확인한 뒤 알려줘.
```

---

## PHASE 4 — 인사공통관리 (평가 기반)

```
인사공통관리 모듈을 구현해줘. 평가 모듈의 기반이 되는 부분이야.

[DB 모델 - app/models/]
1. hr_employee.py (HrEmployee)
   id, emp_no(사번), name, name_hanja, name_en, gender, birth_date,
   hire_date, workplace, work_location, dept_id(FK), 
   position_id(FK), title, job_group, emp_status, resign_date

2. hr_department.py (HrDepartment)
   id, dept_code, dept_name, parent_id(self FK), manager_emp_id,
   org_level, sort_order, is_active

3. hr_position.py (HrPosition)
   id, code, name, position_type(직급/직책/직군), sort_order

4. hr_eval_schedule.py (HrEvalSchedule)
   id, year, name, stage(목표/중간/기말/종합), 
   start_date, end_date, status

5. hr_calibration_group.py (HrCalibrationGroup)
   id, name, year, created_by, members(관계 테이블)

6. hr_eval_setting.py (HrEvalSetting)
   id, year, grade_criteria(JSON), weight_config(JSON)

[Alembic 마이그레이션]
- alembic revision --autogenerate -m "hr common tables"
- alembic upgrade head

[API - app/api/v1/endpoints/]
employees.py:
  GET    /employees?dept_id=&keyword=&page=&size=
  GET    /employees/{id}
  POST   /employees
  PUT    /employees/{id}
  DELETE /employees/{id}

departments.py:
  GET    /departments/tree          # 트리 구조 반환
  GET    /departments/{id}
  POST   /departments
  PUT    /departments/{id}

positions.py:
  GET    /positions?type=
  POST   /positions
  PUT    /positions/{id}

eval-schedules.py:
  GET    /eval-schedules?year=
  POST   /eval-schedules
  PUT    /eval-schedules/{id}

calibration-groups.py:
  GET    /calibration-groups?year=
  POST   /calibration-groups
  PUT    /calibration-groups/{id}

[시드 데이터 스크립트 - scripts/seed_hr.py]
- 부서: 경영지원부 / 감정평가1부 / 감정평가2부 / IT팀
- 직급: 사원/대리/과장/차장/부장/이사
- 직책: 팀원/팀장/본부장
- 샘플 사원 10명

[프론트엔드 - src/pages/common/]
EmployeeList.tsx:
  좌측 조직도 트리 + 우측 사원 목록 (Split 레이아웃)
  검색: 사번/성명, 페이징
  행 클릭 시 상세 모달

DepartmentTree.tsx:
  Ant Design Tree 컴포넌트 활용
  CRUD 버튼

CodeMgmt.tsx:
  직급/직책/직군 탭으로 구분, 인라인 편집

완료되면 조직도와 사원 목록이 보이는 화면 스크린샷 흐름을 설명해줘.
```

---

## PHASE 5 — 공통 컴포넌트

```
여러 평가 모듈에서 재사용할 공통 컴포넌트를 만들어줘.

[src/components/DataTable/index.tsx]
Props:
  columns: ColumnDef[]
  data: any[]
  onRowClick?: (row) => void
  pagination?: { page, size, total, onChange }
  searchable?: boolean
  exportExcel?: boolean
  rowSelection?: boolean

구현:
  - @tanstack/react-table 기반
  - 정렬, 필터, 페이징
  - 체크박스 선택
  - 엑셀 다운로드 (xlsx 라이브러리)

[src/components/SearchForm/index.tsx]
Props:
  fields: FieldConfig[]  (type: text|select|date|dateRange|checkbox)
  onSearch: (values) => void
  onReset: () => void

구현:
  - Ant Design Form
  - 검색/초기화 버튼 우측 정렬
  - 필드 유형별 자동 렌더링

[src/components/ApprovalFlow/index.tsx]
Props:
  steps: { name, role, status, date?, comment? }[]

구현:
  - 가로 스텝퍼
  - status: 대기(회색)/승인(초록)/반려(빨강)/진행중(파랑)
  - 각 단계 클릭 시 상세 툴팁

[src/components/EvalScoreInput/index.tsx]
Props:
  min, max, value, onChange
  mode: 'slider' | 'radio' | 'number'

구현:
  - mode별 다른 UI
  - 라벨 표시 (미흡/보통/우수 등)

[src/components/GradeBadge/index.tsx]
Props:
  grade: 'S' | 'A' | 'B' | 'C' | 'D'
  size?: 'sm' | 'md' | 'lg'

구현:
  - 등급별 색상:
    S: 골드, A: 초록, B: 파랑, C: 주황, D: 빨강
  - 원형 또는 각진 뱃지

각 컴포넌트는 Storybook 없이 간단한 example 페이지(/test/components)에서 확인 가능하게.

완료되면 /test/components에서 보이는 목록을 알려줘.
```

---

## PHASE 6 — 성과평가 사이클

```
성과평가 모듈을 구현해줘. 목표→중간→기말 사이클이 핵심.

[DB 모델]
perf_eval_round: id, year, name, start_date, end_date, status
perf_kpi: id, round_id, code, name, measure_type, weight, perspective
perf_target: id, emp_id, round_id, kpi_id, target_value, 
             is_organization, status, created_at
  status: DRAFT | SUBMITTED | APPROVED | REJECTED
perf_target_mid: id, target_id, progress_rate, description, 
                 expected_rate, submitted_at
perf_target_final: id, target_id, achievement_rate, description, 
                   self_score, submitted_at
perf_eval_result: id, emp_id, round_id, evaluator_id, score, 
                  grade, comment
perf_eval_approver: id, evaluatee_id, evaluator_id, eval_type

[API]
GET  /perf/rounds
POST /perf/rounds                  # 회차 생성 (관리자)
GET  /perf/kpis?round_id=
POST /perf/kpis

GET  /perf/targets?emp_id=&round_id=
POST /perf/targets
PUT  /perf/targets/{id}
PUT  /perf/targets/{id}/submit     # 상태 변경: DRAFT → SUBMITTED
PUT  /perf/targets/{id}/approve    # SUBMITTED → APPROVED (평가자만)
PUT  /perf/targets/{id}/reject

POST /perf/midterm                 # 중간점검 입력
GET  /perf/midterm?target_id=

POST /perf/final                   # 기말실적 입력
GET  /perf/final?target_id=

GET  /perf/results?round_id=&dept_id=

[권한 체크]
- 목표과제 조회: 본인 + 직속상사 + 인사팀
- 승인: 평가자(직속상사)만
- 결과 조회: 본인 + 평가라인

[프론트엔드 페이지]
src/pages/perf/
├── MyEvaluation.tsx          # 내 평가 현황 대시보드
├── TargetSetting.tsx         # 목표과제 입력 폼
├── MidtermReview.tsx         # 중간점검
├── FinalEvaluation.tsx       # 기말평가
├── ApprovalInbox.tsx         # 평가자: 승인 대기 목록
└── TeamStatus.tsx            # 부서별 현황 (평가자용)

[MyEvaluation.tsx 구성]
- 상단: 현재 회차 정보 + 단계 표시 (ApprovalFlow 컴포넌트)
- 진행률 카드: 목표 N개, 중간점검 M개 완료, 기말 K개
- 내 목표과제 테이블 (DataTable)
- "목표 추가" 버튼 → TargetSetting 모달

[TargetSetting.tsx]
- KPI 드롭다운 (round_id로 필터)
- 목표값 입력
- 가중치 입력 (총합 100% 검증)
- 조직/개인 구분 라디오
- 임시저장 / 제출 버튼

[MidtermReview.tsx]
- 목표과제별 진척률 슬라이더 (0~100%)
- 실적 내용 textarea
- 예상 달성률 자동 계산 표시

완료되면 샘플 데이터로 목표 입력 → 제출 → 승인 시나리오가 돌아가는지 확인해서 알려줘.
```

---

## PHASE 7 — 역량평가

```
역량평가 모듈을 구현해줘.

[DB 모델]
comp_indicator: id, year, code, name, description, weight
comp_behavior: id, indicator_id, level (1~5), description
comp_eval_mapping: id, evaluatee_id, evaluator_id, round_id, eval_type
  eval_type: SELF | BOSS
comp_eval_self: id, emp_id, round_id, indicator_id, score, comment, 
                submitted_at
comp_eval_boss: id, evaluatee_id, evaluator_id, round_id, 
                indicator_id, score, comment, submitted_at
comp_sar_record: id, target_emp_id, observer_id, observed_date, 
                 situation, action, result

[API]
GET  /comp/indicators?year=
GET  /comp/behaviors?indicator_id=
GET  /comp/my-eval?round_id=         # 내가 해야 할 평가 (본인/상사)
POST /comp/self                       # 본인평가 일괄 제출
POST /comp/boss                       # 상사평가 일괄 제출
GET  /comp/sar?emp_id=
POST /comp/sar

[프론트엔드]
src/pages/comp/
├── SelfEvaluation.tsx       # 본인평가 입력
├── BossEvaluation.tsx       # 상사평가 (본인평가 참고 표시)
├── SarRecords.tsx           # SAR 관찰기록 타임라인
└── CompStatus.tsx           # 평가 현황

[SelfEvaluation.tsx 구성]
- 역량 지표 아코디언 리스트
- 각 지표 펼치면 행동지표 5단계 표시
- 1~5 라디오 또는 EvalScoreInput 컴포넌트
- 코멘트 textarea
- 하단 제출 버튼

[BossEvaluation.tsx]
- 좌측: 평가 대상자 카드 리스트
- 우측: 선택된 대상자의 본인평가 결과 + 상사평가 입력 폼

완료되면 역량평가 흐름 테스트 결과 알려줘.
```

---

## PHASE 8 — 다면평가 (익명성)

```
다면평가 모듈을 구현해줘. 익명성 처리가 핵심.

[DB 모델]
multi_eval_group: id, round_id, evaluatee_id
multi_eval_member: id, group_id, evaluator_id, 
                   rater_type (BOSS|PEER|SUBORDINATE)
multi_eval_indicator: id, round_id, name, description, max_score
multi_eval_response: id, round_id, evaluatee_id, 
                     rater_type, indicator_id, score, comment
  ⚠️ evaluator_id는 저장하지 않음 (완전 익명)
multi_eval_response_log: id, evaluator_id, round_id, 
                         evaluatee_id, submitted_at
  (제출 여부 추적용, 점수와는 분리)
multi_eval_result: id, round_id, evaluatee_id, indicator_id, 
                   avg_score, response_count

[API]
GET  /multi-eval/my-targets?round_id=
POST /multi-eval/response              # 응답 저장 (익명)
GET  /multi-eval/results/{emp_id}?round_id=
GET  /multi-eval/status?round_id=      # 제출 현황

[익명성 로직]
- response 저장 시: evaluator_id는 response_log에만, 
  response 테이블에는 rater_type만 저장
- 결과 조회 시:
  - 응답자 수 < 3명이면 "응답자 부족" 반환
  - 평균 점수만 공개, 개별 점수 불가

[프론트엔드]
src/pages/multi/
├── MultiEval.tsx            # 내가 평가할 대상자
├── MultiEvalResult.tsx      # 내 다면평가 결과 (본인)
└── MultiEvalStatus.tsx      # 관리자: 제출 현황

[MultiEval.tsx]
- 대상자 카드 리스트 (이름, 소속, 관계: 상사/동료/부하)
- 카드 클릭 → 평가 입력 화면
- 일괄 평가 모드: 다음 대상자로 이어서 평가

완료되면 익명성이 보장되는지 확인(evaluator_id가 response에 없는지) 해서 알려줘.
```

---

## PHASE 9 — 종합평가 + 등급 산출

```
종합평가 모듈을 구현해줘. 반영비율 계산 + 보정 + 이의신청.

[DB 모델]
perf_weight: id, year, perf_ratio, comp_ratio, multi_ratio
perf_grade_criteria: id, year, grade, min_score, max_score, 
                     default_ratio  (예: S등급은 10%)
perf_comprehensive: id, emp_id, round_id, 
                    perf_score, comp_score, multi_score,
                    total_score, original_grade, final_grade, 
                    is_adjusted, adjusted_by, adjusted_reason
perf_objection: id, emp_id, round_id, reason, status, created_at
  status: PENDING | REVIEWED | ACCEPTED | REJECTED
perf_objection_review: id, objection_id, reviewer_id, 
                       decision, comment, reviewed_at

[종합점수 로직]
total = (perf_score × perf_ratio) 
      + (comp_score × comp_ratio) 
      + (multi_score × multi_ratio)

[등급 기준 (기본값)]
S: 90점 이상 / A: 80~89 / B: 70~79 / C: 60~69 / D: 60 미만
(관리자가 변경 가능)

[보정 로직]
- 보정집단 내 강제 배분 적용 옵션
- 예: S 10% / A 20% / B 40% / C 20% / D 10%
- 인사위원회 심의 후 수동 조정 가능
- 조정 이력 저장 (original_grade vs final_grade)

[API]
GET  /perf/comprehensive?round_id=
POST /perf/comprehensive/calculate    # 일괄 계산 (관리자)
PUT  /perf/comprehensive/{id}/grade   # 수동 조정
POST /perf/objections
PUT  /perf/objections/{id}/review
GET  /perf/weight?year=
PUT  /perf/weight                     # 반영비율 설정
GET  /perf/grade-criteria?year=
PUT  /perf/grade-criteria

[프론트엔드]
src/pages/comprehensive/
├── WeightConfig.tsx          # 반영비율 설정
├── ComprehensiveList.tsx     # 종합평가 대상자 목록 (계산 버튼)
├── GradeAdjustment.tsx       # 등급 수동 조정 (인사위원회)
├── ObjectionList.tsx         # 이의신청 목록
└── MyResult.tsx              # 본인의 종합 결과

[GradeAdjustment.tsx 핵심]
- 보정집단 드롭다운
- 그룹 내 대상자 테이블 (점수순 정렬)
- 등급 분포 바 차트 (현재 vs 목표)
- 등급 인라인 편집 (S/A/B/C/D 드롭다운)
- 변경 사유 입력 필수

완료되면 계산 → 조정 → 마감 플로우 테스트 결과 알려줘.
```

---

## PHASE 10 — 통합 테스트 + 마무리

```
전체 시스템 통합 테스트 + 배포 준비.

[체크리스트]
1. 시드 데이터 전체 생성 스크립트
   - scripts/seed_all.py
   - 회사, 부서, 사원 20명, 평가 회차 1개, KPI/역량지표, 평가자 매핑

2. E2E 시나리오 테스트
   - 로그인 → 내 평가 현황 확인
   - 목표 설정 → 제출 → 상사 승인
   - 중간점검 제출 → 기말실적 제출
   - 역량평가 (본인 → 상사)
   - 다면평가 익명 제출
   - 종합평가 계산 → 등급 조정 → 마감
   - 이의신청 → 재심의

3. API 문서화
   - FastAPI 자동 Swagger (/docs)
   - README에 주요 엔드포인트 정리

4. 권한 매트릭스 정리
   - 일반사원 / 평가자(팀장) / 인사팀 / 관리자

5. 배포 설정
   - 백엔드: Dockerfile + docker-compose.yml
   - 프론트: vite build → Vercel 배포 설정

6. 운영 문서
   - docs/DEPLOY.md
   - docs/USER_GUIDE.md

완료되면 체크리스트 결과와 다음 개선 제안을 알려줘.
```

---

## 💡 사용 팁

### Claude Code 실행 시
```bash
cd D:\AI\INSA
claude
```

### PHASE 진행 중 막히면
- 오류 메시지 복사해서 "이 오류 수정해줘" 요청
- 파일 위치 잊었으면 "지금까지 만든 파일 구조 보여줘"
- 되돌리고 싶으면 git 활용 (PHASE 1 끝나면 `git init` 필수)

### Git 초기화 추천 시점
PHASE 1 완료 직후:
```bash
cd D:\AI\INSA
git init
git add .
git commit -m "phase 1: project skeleton"
```

각 PHASE 완료마다 커밋하면 안전.

### 자주 쓰는 보조 프롬프트
```
지금까지 만든 파일 구조 보여줘
```
```
DB 테이블 현황 보여줘 (Alembic 이력 포함)
```
```
이 API를 Postman 컬렉션으로 내보내줘
```
```
TypeScript 타입 에러 다 잡아줘
```

---

## 🚨 주의사항

- **MSSQL 연결 문자열**은 환경에 따라 수정 필요
- **Windows에서 pyodbc** 설치 시 ODBC Driver 17 별도 설치
- **프론트 패키지 설치**가 오래 걸릴 수 있음 (npm install)
- PHASE 4 이후부터는 DB 마이그레이션이 누적되므로 순서 지키기
- 각 PHASE 끝나고 반드시 커밋
