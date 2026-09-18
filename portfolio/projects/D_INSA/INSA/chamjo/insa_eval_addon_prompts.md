# 인사평가 모듈 추가 가이드 (기존 INSA 프로젝트 확장)

> 대상: `D:\AI\INSA` 기존 프로젝트에 인사평가 기능 추가  
> 스택: FastAPI + React 18 + TypeScript + MSSQL (기존 유지)  
> 테이블 접두사: `insa_` (CLAUDE.md 규칙 준수)  
> **주의**: 새 프로젝트가 아니라 기존 `backend/`, `frontend/`에 얹는 방식

---

## 🏛️ 확장 방침

### 기존 프로젝트 구조 존중
- 폴더: `backend/`, `frontend/` 그대로 사용
- Tech Stack: CLAUDE.md에 명시된 것 그대로
- 테이블: 모두 `insa_` 접두사
- 컨벤션: Immutable patterns, schemas/=Pydantic, db/=SQLAlchemy

### 평가 모듈 추가 원칙
- 기존 인사 테이블(`insa_employee` 등)을 FK로 참조
- 평가 관련 테이블은 `insa_eval_*`, `insa_perf_*`, `insa_comp_*`, `insa_multi_*` 접두사
- 기존 레이아웃/공통 컴포넌트 최대한 재사용
- 사이드바에 "인사평가" 대메뉴 추가

---

## 📌 사전 준비

```bash
cd D:\AI\INSA
claude
```

---

## PHASE 0 — 현재 프로젝트 분석 (필수!)

> ⚠️ 반드시 이 단계부터 하세요. 이후 PHASE는 분석 결과에 맞춰 조정됩니다.

```
현재 프로젝트 상태를 분석해줘. 아직 코드는 수정하지 마.

[분석 항목]
1. backend/ 구조
   - 현재 폴더 구조 (app/api, app/schemas, app/db, app/services 등)
   - 구현된 주요 모듈 목록
   - 사용 중인 라우터/엔드포인트
   - requirements.txt 의존성
   - alembic 마이그레이션 이력

2. frontend/ 구조
   - src/ 폴더 구조
   - 구현된 페이지 목록
   - 공통 컴포넌트 (DataTable, Layout 등이 이미 있는지)
   - 라우팅 설정 (react-router 경로)
   - package.json 의존성
   - 사이드바/메뉴 구조

3. DB 현황
   - 현재 정의된 SQLAlchemy 모델 (insa_ 테이블들)
   - 특히 insa_employee, insa_department, insa_position 같은 
     인사 마스터 테이블의 컬럼 구조
   - 사용자/권한 테이블 구조

4. 인증 체계
   - JWT 구현 방식
   - Role 정의 (admin, hr, manager, user 등)
   - 권한 체크 패턴 (deps.py 등)

5. 재사용 가능한 공통 컴포넌트
   - DataTable, SearchForm, Modal 등 이미 만든 것
   - API client 인터셉터

[결과 정리]
- 현재 상태 요약 (표 형식)
- 인사평가 모듈 추가 시 활용할 수 있는 기존 자산 목록
- 충돌 가능성 있는 부분 경고

결과만 정리해서 보여주고 수정은 하지 마.
```

**이 분석 결과를 저한테 보여주시면 PHASE 1~N을 프로젝트 현황에 맞게 맞춤 조정해드릴게요.**

---

## PHASE 1 — 평가 도메인 공통 기반

> 기존 인사 테이블(`insa_employee` 등)이 있다는 전제. 없으면 선행 필요.

```
인사평가 도메인의 공통 기반을 구현해줘.
기존 backend/ 구조를 그대로 따르고, 테이블은 insa_ 접두사 사용.

[DB 모델 - backend/app/db/ 아래 적절한 위치]
1. insa_eval_round (평가 회차)
   id, year, name, start_date, end_date,
   status ('PLANNED'|'IN_PROGRESS'|'CLOSED'),
   created_at, updated_at

2. insa_eval_schedule (평가 단계별 일정)
   id, round_id (FK), 
   stage ('TARGET'|'MID'|'FINAL'|'COMPREHENSIVE'),
   start_date, end_date

3. insa_eval_approver (평가자 매핑)
   id, round_id, 
   evaluatee_id (FK → insa_employee.id),
   evaluator_id (FK → insa_employee.id),
   eval_type ('PERF'|'COMP'|'MULTI'),
   rater_type ('BOSS'|'PEER'|'SUBORDINATE')  -- MULTI일 때만
   created_at

4. insa_eval_calibration_group (보정집단)
   id, year, name, created_by, created_at

5. insa_eval_calibration_member
   id, group_id (FK), emp_id (FK)

6. insa_eval_setting (평가 기본설정)
   id, year, 
   weight_config JSON,   -- {perf: 40, comp: 30, multi: 30}
   grade_criteria JSON   -- [{grade:'S', min:90, max:100, default_ratio:10}, ...]

[Alembic]
- 새 마이그레이션 생성
- 기존 insa_employee FK 관계 확인 후 upgrade

[Pydantic 스키마 - backend/app/schemas/]
기존 스키마 파일 구조에 맞춰서:
eval_round.py, eval_schedule.py, eval_approver.py,
calibration_group.py, eval_setting.py

[서비스 - backend/app/services/]
eval_common_service.py 또는 모듈별 분리
(기존 services/ 구조 패턴 따를 것)

[API 라우터]
기존 backend/app/api 구조에 맞춰 eval 관련 라우터 추가:
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

[권한]
관리자(admin) 또는 인사팀(hr) Role만 이 엔드포인트 접근 가능.
기존 deps.py의 권한 체크 패턴 그대로 활용.

[Immutable 원칙]
CLAUDE.md에 명시된 대로 mutation 없이 구현.

[프론트엔드 - frontend/src/pages/ 아래 eval/ 생성]
기존 페이지 구조 패턴 따라서:
src/pages/eval/
├── common/
│   ├── RoundMgmt.tsx          # 평가 회차 관리
│   ├── ScheduleMgmt.tsx        # 평가 일정
│   ├── ApproverMapping.tsx     # 평가자 매핑
│   ├── CalibrationGroup.tsx    # 보정집단
│   └── EvalSettings.tsx        # 반영비율/등급기준

[사이드바 메뉴 추가]
기존 메뉴 설정 파일에 "인사평가" 대메뉴 추가:
인사평가
  └ 평가 설정
    ├ 평가 회차
    ├ 평가 일정
    ├ 평가자 매핑
    ├ 보정집단
    └ 반영비율/등급

[API 호출 - frontend/src/api/]
eval.ts 파일 생성 (기존 axios 인스턴스 활용)

[테스트]
pytest로 서비스/API 테스트 (기존 테스트 패턴 따름)

완료되면:
1. 추가된 테이블 목록
2. 추가된 API 엔드포인트
3. 추가된 프론트 라우트
정리해서 알려줘.
```

---

## PHASE 2 — 성과평가 (PERF)

```
성과평가 모듈을 추가해줘. 기존 스타일과 규칙 준수.

[DB 모델]
insa_perf_kpi: id, round_id, code, name, measure_type, weight, perspective
insa_perf_target: id, emp_id, round_id, kpi_id, target_value,
                  is_organization, status, weight_percent,
                  created_at, updated_at
  status: 'DRAFT'|'SUBMITTED'|'APPROVED'|'REJECTED'
insa_perf_target_mid: id, target_id, progress_rate, description,
                      expected_rate, submitted_at
insa_perf_target_final: id, target_id, achievement_rate, description,
                        self_score, submitted_at
insa_perf_eval_result: id, emp_id, round_id, evaluator_id,
                       score, grade, comment, created_at

[API]
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

[권한]
- 목표 조회: 본인 + 평가자 + hr/admin
- 승인: insa_eval_approver 매핑된 평가자만
- 결과 조회: 본인 + 평가라인

[프론트엔드 - frontend/src/pages/eval/perf/]
MyEvaluation.tsx      # 내 평가 현황 (ApprovalFlow 사용)
TargetSetting.tsx     # 목표과제 입력
MidtermReview.tsx     # 중간점검
FinalEvaluation.tsx   # 기말실적
ApprovalInbox.tsx     # 평가자 승인 대기 목록
TeamStatus.tsx        # 부서별 현황

[사이드바 추가]
인사평가 > 성과평가
  ├ 내 평가 현황
  ├ 목표과제 작성
  ├ 중간점검
  ├ 기말실적
  └ 승인 대기 (평가자)

[컴포넌트 재사용]
DataTable, SearchForm, ApprovalFlow 등 기존 공통 컴포넌트 활용.
없으면 먼저 만들기.

완료되면 사원 로그인 → 목표 입력 → 팀장 승인 E2E 시나리오 
테스트 결과 알려줘.
```

---

## PHASE 3 — 역량평가 (COMP)

```
역량평가 모듈을 추가해줘.

[DB 모델]
insa_comp_indicator: id, year, code, name, description, weight
insa_comp_behavior: id, indicator_id, level (1~5), description
insa_comp_eval_self: id, emp_id, round_id, indicator_id,
                     score, comment, submitted_at
insa_comp_eval_boss: id, evaluatee_id, evaluator_id, round_id,
                     indicator_id, score, comment, submitted_at
insa_comp_sar_record: id, target_emp_id, observer_id, observed_date,
                      situation, action, result

[API]
GET  /api/v1/eval/comp/indicators?year=
POST /api/v1/eval/comp/indicators

GET  /api/v1/eval/comp/my-eval?round_id=
POST /api/v1/eval/comp/self
POST /api/v1/eval/comp/boss

GET  /api/v1/eval/comp/sar?emp_id=
POST /api/v1/eval/comp/sar

[프론트엔드 - frontend/src/pages/eval/comp/]
SelfEvaluation.tsx   # 본인평가 (아코디언 + 슬라이더)
BossEvaluation.tsx   # 상사평가 (본인평가 참고)
SarRecords.tsx       # SAR 관찰기록 타임라인

[사이드바]
인사평가 > 역량평가
  ├ 본인평가
  ├ 상사평가
  └ SAR 관찰기록

완료되면 본인→상사 평가 플로우 테스트 결과 알려줘.
```

---

## PHASE 4 — 다면평가 (MULTI, 익명성)

```
다면평가 모듈을 추가해줘. 익명성 처리가 핵심.

[DB 모델]
insa_multi_eval_indicator: id, round_id, name, description, max_score

insa_multi_eval_response: id, round_id, evaluatee_id,
                          rater_type, indicator_id, score, comment
  ⚠️ evaluator_id 저장 안 함 (완전 익명)

insa_multi_eval_response_log: id, evaluator_id, round_id,
                              evaluatee_id, submitted_at
  (제출 여부만 추적, 점수와 분리)

insa_multi_eval_result: id, round_id, evaluatee_id, indicator_id,
                        avg_score, response_count

[익명성 로직 (중요)]
- response 저장 시:
  * insa_multi_eval_response: 점수만 (evaluator_id 없음)
  * insa_multi_eval_response_log: 제출 사실만 (점수 없음)
- 결과 조회 시:
  * response_count < 3 → "응답자 부족" 반환
  * 평균만 공개, 개별 점수 접근 불가
- 두 테이블 조인으로 역추적 불가능한 구조

[API]
GET  /api/v1/eval/multi/indicators?round_id=
POST /api/v1/eval/multi/indicators

GET  /api/v1/eval/multi/my-targets?round_id=
POST /api/v1/eval/multi/response
GET  /api/v1/eval/multi/results/{emp_id}?round_id=
GET  /api/v1/eval/multi/status?round_id=

[프론트엔드 - frontend/src/pages/eval/multi/]
MultiEval.tsx        # 내가 평가할 대상자 카드 리스트
MultiEvalResult.tsx  # 본인의 다면평가 결과
MultiEvalStatus.tsx  # 관리자: 제출 현황

[사이드바]
인사평가 > 다면평가
  ├ 다면평가 입력
  └ 내 다면평가 결과

완료되면:
1. response 테이블 스키마에 evaluator_id 없음 확인
2. 3명 미만일 때 "응답자 부족" 반환 확인
알려줘.
```

---

## PHASE 5 — 종합평가 + 등급 산출

```
종합평가 모듈을 추가해줘.

[DB 모델]
insa_perf_comprehensive: id, emp_id, round_id,
                         perf_score, comp_score, multi_score,
                         total_score, original_grade, final_grade,
                         is_adjusted, adjusted_by, adjusted_reason,
                         calculated_at, adjusted_at

insa_perf_objection: id, emp_id, round_id, reason,
                     status ('PENDING'|'REVIEWED'|'ACCEPTED'|'REJECTED'),
                     created_at

insa_perf_objection_review: id, objection_id, reviewer_id,
                            decision, comment, reviewed_at

[종합점수 계산 서비스]
calculate_comprehensive(round_id):
- insa_eval_setting에서 weight_config 읽기
- 각 사원의 perf/comp/multi 평균 계산
- total = perf*ratio + comp*ratio + multi*ratio
- grade_criteria로 등급 산정 → original_grade 저장

[보정 로직]
- 보정집단별 강제 배분 비율 적용 옵션
- 관리자 수동 조정 가능 (final_grade, adjusted_reason)
- 조정 이력 유지 (original vs final)

[API]
GET  /api/v1/eval/comprehensive?round_id=
POST /api/v1/eval/comprehensive/calculate
PUT  /api/v1/eval/comprehensive/{id}/grade

POST /api/v1/eval/objections
GET  /api/v1/eval/objections?round_id=
PUT  /api/v1/eval/objections/{id}/review

[프론트엔드 - frontend/src/pages/eval/comprehensive/]
ComprehensiveList.tsx    # 대상자 + 계산 버튼
GradeAdjustment.tsx      # 등급 조정 (인사위원회)
ObjectionList.tsx        # 이의신청
MyResult.tsx             # 본인 종합 결과

[GradeAdjustment.tsx 핵심]
- 보정집단 드롭다운
- 그룹 내 대상자 테이블 (점수순)
- 등급 분포 바 차트 (현재 vs 목표)
- 등급 인라인 편집
- 변경 사유 필수
- 일괄 저장

[사이드바]
인사평가 > 종합평가
  ├ 종합평가 조회
  ├ 등급 조정 (관리자)
  ├ 이의신청
  └ 내 종합 결과

완료되면 계산→조정→이의신청 E2E 테스트 결과 알려줘.
```

---

## PHASE 6 — 통합 테스트 + 마무리

```
인사평가 모듈 전체 통합 테스트.

[체크리스트]
1. 시드 데이터 확장
   - 기존 insa_employee에 맞춰 평가 시드 추가
   - 평가 회차 1개, KPI 5개, 역량지표 10개, 다면지표 5개
   - 평가자 매핑, 보정집단 3개

2. E2E 시나리오 테스트 (pytest + Vitest)
   a. 목표 설정 → 제출 → 팀장 승인
   b. 중간점검 → 기말실적 제출
   c. 역량평가 (본인 → 상사)
   d. 다면평가 익명 제출 (3명 이상)
   e. 종합평가 계산 → 등급 조정 → 마감
   f. 이의신청 → 재심의

3. 권한 매트릭스 검증
   | Role   | 설정 | 본인평가 | 승인 | 조정 |
   | admin  | ✅   | ✅      | ✅   | ✅  |
   | hr     | ✅   | ✅      | -    | ✅  |
   | manager| -    | ✅      | ✅   | -   |
   | user   | -    | ✅      | -    | -   |

4. 테스트 커버리지 70%+ 확인
   - Backend: pytest --cov
   - Frontend: vitest --coverage

5. 문서 업데이트
   - CLAUDE.md에 평가 모듈 섹션 추가
   - docs/EVAL_MODULE.md 작성 (API 레퍼런스)

완료되면 체크리스트 결과 + 개선 제안 알려줘.
```

---

## 💡 사용 팁

### 시작 순서
1. **PHASE 0 먼저** (현재 상태 분석) - 필수!
2. 분석 결과를 저한테 보여주세요
3. 그 결과에 맞춰 PHASE 1 이후 프롬프트 미세조정
4. PHASE별로 하나씩 붙여넣기 + Git 커밋

### Git 커밋 메시지 (CLAUDE.md 규칙)
```bash
git commit -m "feat: add eval round and approver models"
git commit -m "feat: add perf evaluation module"
git commit -m "feat: add multi-source evaluation with anonymity"
```

### 문제 생기면
```
마지막 변경을 되돌리고 현재 상태 요약해줘
```
```
현재 eval 관련 API 엔드포인트 전체 목록 보여줘
```
```
insa_ 접두사로 시작하는 테이블 중 평가 관련만 보여줘
```

---

## 🚨 주의사항

- **PHASE 0 먼저 실행**하고 그 결과를 공유해주세요. 그래야 이후 PHASE가 정확히 맞아요.
- 기존 테이블 스키마를 **함부로 수정 금지** (FK만 참조)
- 기존 공통 컴포넌트(DataTable 등)가 이미 있으면 **재사용**, 다시 만들지 말 것
- CLAUDE.md의 Immutable, `insa_` 접두사 규칙 엄수
- 매 PHASE 끝나고 커밋

---

## 📋 PHASE 요약

| PHASE | 내용 | DB 추가 |
|---|---|---|
| 0 | **현재 상태 분석** (수정 X) | - |
| 1 | 평가 공통 (회차/일정/평가자/보정집단/설정) | insa_eval_* (6개) |
| 2 | 성과평가 | insa_perf_* (5개) |
| 3 | 역량평가 | insa_comp_* (5개) |
| 4 | 다면평가 | insa_multi_* (4개) |
| 5 | 종합평가 | insa_perf_comprehensive, _objection* (3개) |
| 6 | 통합 테스트 | - |

총 **23개 신규 테이블**, 모두 `insa_` 접두사.
