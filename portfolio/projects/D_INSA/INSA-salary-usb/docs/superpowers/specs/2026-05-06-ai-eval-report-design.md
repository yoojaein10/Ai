# AI 인사평가 리포트 — 설계 문서

- **작성일**: 2026-05-06
- **PHASE**: 18 (가칭)
- **상태**: 설계 승인 대기 → 구현 계획 전환 예정
- **포지셔닝**: AI는 평가자가 아닌 **기존 평가 데이터의 보조 요약 리포트** 생성기. 등급 변경 추천 금지.

---

## 1. 결정사항 요약

| # | 항목 | 결정 |
|---|---|---|
| 1 | LLM 공급자 | 표준 Gemini API + PII 마스킹 |
| 2 | 독자 (1차 출시) | HR_ADMIN / SYSTEM_ADMIN 전용 |
| 3 | 트리거 | 회차 단위 HR 수동 일괄, FastAPI BackgroundTasks + `insa_notification` 완료 알림 |
| 4 | 출력 구조 | 정량 헤더 + 4섹션 자연어 (강점 / 개선 / 코칭 / 면담 가이드) |
| 5 | 저장 정책 | 버전 관리 (append-only, `version` + `is_latest`) |
| 6 | 회차 적격성 | `EvalComprehensive` calculate 완료된 회차만 |
| 7 | 모델 | `gemini-2.5-flash` (env 주입, UI 미노출) |
| 8 | PII 마스킹 | 사번·이름 placeholder + 코멘트 본문 내 등록 인명 정규식 치환. 부서·직급은 원문 유지 |
| 9 | 실행 전략 | 순차 처리, 건별 try/except, 실패 시 `status=FAILED` 행 저장, HR이 수동 재생성 |
| 10 | UI | 단일 페이지 `/eval/ai-report` (Toolbar / Primary 테이블 / Context Panel) |

---

## 2. 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│ FE: AiEvalReportPage.tsx                                    │
│  ─ Toolbar: 회차 select + "일괄 생성" 버튼 + 진행률 표시       │
│  ─ Primary: 직원 테이블 (status, version, generated_at)      │
│  ─ Context Panel: 선택 직원 리포트 (정량 헤더 + 4섹션)         │
└────────────┬────────────────────────────────────────────────┘
             │ React Query
             ▼
┌─────────────────────────────────────────────────────────────┐
│ BE API: /api/v1/eval/ai-reports                             │
│  POST   /generate                          (HR_ADMIN, 일괄) │
│  POST   /generate/{employee_id}            (개별 재생성)     │
│  GET    /                                  (직원별 latest)   │
│  GET    /{id}                              (단건 조회)       │
│  GET    /employees/{employee_id}/history   (버전 이력)       │
│  GET    /employees/{employee_id}/versions/{version}          │
└────────────┬────────────────────────────────────────────────┘
             │ BackgroundTasks (일괄), 동기 (개별)
             ▼
┌─────────────────────────────────────────────────────────────┐
│ Service: ai_eval_report_service                             │
│  ─ build_input(round, emp): perf+comp+multi+SAR 수집        │
│  ─ check_anonymity: response_count<3 → multi 데이터 제외    │
│  ─ mask_pii: 사번/이름 → placeholder + 코멘트 인명 치환     │
│  ─ call_gemini: 4섹션 자연어 생성                           │
│  ─ unmask_pii: 응답에서 placeholder 복원                    │
│  ─ persist: version=prev+1, is_latest 토글, FAILED 처리     │
└────────────┬────────────────────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────────────────────┐
│ External: Gemini API (gemini-2.5-flash, JSON mode)          │
└─────────────────────────────────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────────────────────┐
│ DB: insa_eval_ai_report (신규)                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. 데이터 모델

### 3.1 신규 테이블 `insa_eval_ai_report`

```python
class EvalAiReport(Base):
    __tablename__ = "insa_eval_ai_report"

    id = Column(Integer, primary_key=True, autoincrement=True)
    round_id = Column(Integer, ForeignKey("insa_eval_round.id"), nullable=False, index=True)
    employee_id = Column(Integer, ForeignKey("insa_employee.id"), nullable=False, index=True)

    version = Column(Integer, nullable=False)             # 1부터 증가
    is_latest = Column(Boolean, nullable=False, default=True, index=True)

    status = Column(String(20), nullable=False)            # PENDING | SUCCESS | FAILED
    error_message = Column(Text, nullable=True)            # FAILED 시, 마스킹 후 저장

    # 정량 헤더 (응답 시 즉시 노출, LLM 호출 없이 DB 캐시)
    total_score = Column(Numeric(5, 2), nullable=True)
    final_grade = Column(String(5), nullable=True)
    multi_response_count = Column(Integer, nullable=True)
    multi_included = Column(Boolean, nullable=False, default=False)

    # 4섹션 자연어 (Gemini JSON 응답)
    content_strengths = Column(Text, nullable=True)
    content_improvements = Column(Text, nullable=True)
    content_coaching = Column(Text, nullable=True)
    content_interview_guide = Column(Text, nullable=True)

    # 메타
    model_version = Column(String(50), nullable=False)     # "gemini-2.5-flash"
    prompt_version = Column(String(20), nullable=False)    # "v1.0"
    generated_by = Column(Integer, ForeignKey("insa_user.id"), nullable=False)
    generated_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_eval_ai_report_round_emp_version",
              "round_id", "employee_id", "version", unique=True),
        Index("ix_eval_ai_report_round_emp_latest",
              "round_id", "employee_id", "is_latest"),
    )
```

### 3.2 Alembic 마이그레이션

`backend/alembic/versions/20260506_xxxx_add_eval_ai_report.py` (head 기준 신규 revision).

### 3.3 버전 관리 동작

생성 시:
1. `prev = SELECT WHERE round_id=N AND employee_id=M ORDER BY version DESC LIMIT 1`
2. `prev`가 있으면 `UPDATE prev SET is_latest=False`
3. `INSERT new row` with `version = (prev.version if prev else 0) + 1`, `is_latest=True`

직원별 latest 한 행만이 기본 노출. 히스토리는 별도 endpoint.

---

## 4. API 스펙

전체 prefix: `/api/v1/eval/ai-reports`

| Method | Path | Role | 요청 | 응답 |
|---|---|---|---|---|
| POST | `/generate` | HR/SYS | `{round_id}` | `202 {batch_id, total: N}` 즉시 반환, BackgroundTasks 실행 |
| POST | `/generate/{employee_id}` | HR/SYS | `{round_id}` | `200 EvalAiReportRead` (개별 재생성, 동기 처리) |
| GET | `/` | HR/SYS | `?round_id=N` | `[EvalAiReportListItem]` (latest만) |
| GET | `/{id}` | HR/SYS | — | `EvalAiReportDetail` (4섹션 본문 포함) |
| GET | `/employees/{employee_id}/history` | HR/SYS | `?round_id=N` | 모든 버전 메타 목록 |
| GET | `/employees/{employee_id}/versions/{version}` | HR/SYS | `?round_id=N` | 특정 버전 본문 |

### 4.1 검증 규칙

- 회차 status가 `PLANNED`이거나 `EvalComprehensive` 행이 없으면 → `400 "comprehensive evaluation not completed"`
- 일괄 생성 진행 중인 회차에 동일 호출 → `409 "batch in progress"` (in-memory `set` 락)
- HR_ADMIN / SYSTEM_ADMIN 외 역할 → `403`

### 4.2 GET `/` 응답 구성 규칙

응답 row source는 **`EvalComprehensive`의 모든 직원** + `EvalAiReport`(latest) **left join**.
- 리포트 미생성 직원도 테이블에 표시 (`status=null`로 구분)
- HR이 미생성 직원을 식별해 일괄 또는 개별 생성 가능

```sql
SELECT
  c.emp_id, e.name, e.dept_name, e.job_rank,
  c.total_score, c.final_grade,
  r.id, r.version, r.status, r.generated_at, r.error_message
FROM insa_eval_comprehensive c
LEFT JOIN insa_eval_ai_report r
  ON r.round_id = c.round_id AND r.employee_id = c.emp_id AND r.is_latest = 1
WHERE c.round_id = :round_id
```

### 4.2 알림 트리거

일괄 생성 완료 시 `insa_notification` INSERT:
- recipient = 호출 HR_ADMIN
- message = `"AI 리포트 생성 완료: 성공 N건 / 실패 M건"`
- link = `/eval/ai-report?round_id={round_id}`

---

## 5. 서비스 모듈 구성

```
backend/app/services/
  ai_eval_report_service.py       # 핵심 오케스트레이션
  ai_report/
    __init__.py
    input_builder.py               # DB → 프롬프트 입력 dict
    pii_masker.py                  # 마스킹/언마스킹
    gemini_client.py               # Gemini API 어댑터
    prompts.py                     # 프롬프트 템플릿 v1.0
```

분리 이유:
- `gemini_client`: 외부 의존, 단위 테스트 mock 대상
- `pii_masker`: 순수 함수, 단위 테스트 용이
- `input_builder`: DB 의존하지만 LLM 무관, 결합도 분리

---

## 6. 처리 흐름

### 6.1 단건 생성 `generate_one_report(round_id, employee_id, generated_by)`

```
1. EvalComprehensive 조회
   - 없으면 ValueError("comprehensive not calculated") → 400 / FAILED

2. input_builder.collect(round_id, employee_id)
   ├─ PerfEvalResult 점수·코멘트
   ├─ CompEvalSelf 본인평가 점수·코멘트
   ├─ CompEvalBoss 상사평가 점수·코멘트 (evaluator_id는 placeholder)
   ├─ MultiEvalResult avg_score + response_count
   │   * response_count<3 인 indicator 제외
   │   * 전체<3이면 multi 섹션 통째 제외 (multi_included=False)
   ├─ CompSarRecord 관찰기록 (observer_id placeholder)
   └─ Employee 메타 (부서명·직급명만, 사번/이름 placeholder)

3. pii_masker.mask(input) → masked_input + restore_map
   ├─ 사번 / 이름 → "__INSA_EMP_001__", "__INSA_RATER_A__" 등
   │   (자연어 충돌 방지를 위해 충분히 유니크한 접두어)
   ├─ 코멘트 본문 정규식 치환:
   │     names = SELECT name FROM insa_employee WHERE active
   │     names_sorted_by_len_desc로 긴 이름부터 매칭(substring 충돌 방지)
   │     pattern = r"(" + "|".join(re.escape(n) for n in names_sorted) + r")"
   │     re.sub로 placeholder 치환, restore_map에 (placeholder → original) 등록
   └─ 부서명·직급명은 원문 유지

4. gemini_client.generate(masked_input, prompt_version="v1.0")
   ├─ POST https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent
   ├─ Authorization: Bearer + GEMINI_API_KEY
   ├─ generationConfig.response_mime_type = "application/json"
   ├─ timeout = GEMINI_TIMEOUT_SEC (default 30)
   └─ 응답: { strengths, improvements, coaching, interview_guide }

5. pii_masker.unmask(response, restore_map) → 원본 복원
   * Gemini가 placeholder를 자연어로 변환했을 경우 복원 누락 가능성 존재
   * 단, 입력에 사번·이름이 없었으므로 복원 누락 토큰도 PII 아님 (안전)

6. DB 저장
   ├─ prev = SELECT ... ORDER BY version DESC LIMIT 1
   ├─ UPDATE prev SET is_latest=False (있을 경우)
   └─ INSERT new row, version=prev.version+1, is_latest=True, status=SUCCESS

7. 예외 흐름: try/except로 감싸 status=FAILED + error_message(마스킹된 상태)
   - GeminiError, ValueError, TimeoutError, JSONDecodeError 동일 처리
```

### 6.2 일괄 처리 `generate_batch(round_id, generated_by)`

```
1. 회차 검증: comprehensive 행이 1건 이상 존재
2. 대상 직원 = SELECT DISTINCT emp_id FROM insa_eval_comprehensive WHERE round_id=N
3. in-memory lock에 round_id 등록 (재호출 시 409)
4. for emp_id in 대상:
       try: generate_one_report(round_id, emp_id, generated_by)
       except: 위 7번 흐름으로 FAILED 행 저장 후 다음 직원 (재시도 없음)
5. 완료 후 insa_notification INSERT
6. lock 해제
```

---

## 7. 프롬프트 템플릿 (v1.0)

```python
SYSTEM_PROMPT = """
당신은 한국 기업의 인사평가 보조 분석가입니다.
주어진 평가 데이터를 종합해 HR 담당자가 면담·코칭에 참고할 리포트를 작성합니다.

다음 원칙을 반드시 지키세요:
1. 당신은 평가자가 아니라 데이터 요약·정리 도우미입니다. 등급 변경 추천 금지.
2. 점수의 절대적 우월/열등을 단정하지 말고, 패턴·맥락 중심으로 서술합니다.
3. 다면평가 데이터가 입력에 없으면 다면 관련 언급을 하지 마세요.
4. 모든 출력은 한국어 존댓말. 객관적이고 따뜻한 톤.
5. 개인 식별자(이름·사번)가 입력에 placeholder로 들어와 있으면 그대로 사용합니다.

JSON 스키마로만 응답:
{
  "strengths": "강점 영역 (3~5문장)",
  "improvements": "개선이 필요한 영역 (3~5문장)",
  "coaching": "구체적 코칭 포인트 (3~5문장, 행동 단위)",
  "interview_guide": "1on1 면담 시 활용할 질문·체크포인트 (3~5문장)"
}
"""

USER_PROMPT_TEMPLATE = """
평가 회차: {round_year}년 {round_name}
대상: {employee_placeholder} ({dept_name} / {job_rank})

[정량 점수]
- 성과: {perf_score}
- 역량: {comp_score}
- 다면: {multi_block}
- 종합: {total_score} (등급 {final_grade})

[본인평가 코멘트]
{self_comments}

[상사평가 코멘트]
{boss_comments}

[SAR 관찰기록]
{sar_records}

[다면평가 요약]
{multi_summary}
"""
```

`prompt_version="v1.0"`을 DB에 함께 저장 → 향후 개정 시 어떤 버전으로 생성됐는지 추적.

---

## 8. 마스킹 핵심 보장

1. **다면평가 익명성** (CLAUDE.md CRITICAL): `evaluator_id`는 어떤 단계에서도 입력에 포함되지 않음. `MultiEvalResult.avg_score + response_count`만 사용.
2. `response_count < 3` 검사는 indicator 단위 + 전체 단위 둘 다 적용.
3. 코멘트 본문 마스킹은 정규식 + 긴 이름부터 매칭 (substring 충돌 방지).
4. placeholder 토큰은 `__INSA_EMP_001__` 처럼 일반 한국어와 충돌 가능성이 0에 가까운 형식.
5. `error_message`는 마스킹된 상태로만 DB 저장.

---

## 9. 환경 변수

```bash
# backend/.env
GEMINI_API_KEY=AIza...
GEMINI_MODEL=gemini-2.5-flash
GEMINI_TIMEOUT_SEC=30
GEMINI_DAILY_BUDGET_CALLS=2000   # (옵션, 1차 출시 미강제)
```

`app/core/config.py`의 `Settings`에 추가, 미설정 시 호출 시점에 503 + 명시적 에러 메시지.

---

## 10. 에러 처리 매트릭스

| 시나리오 | 처리 | 사용자 노출 |
|---|---|---|
| `GEMINI_API_KEY` 미설정 | 호출 시점 503 + 로그 | "AI 리포트 서비스 미설정" |
| Gemini 4xx | 직원 단건 status=FAILED, error_message 저장 | 직원 행 빨간 배지 + tooltip |
| Gemini 429 (rate limit) | 동일 처리, 재시도 없음 | "Rate limit, 잠시 후 재시도" |
| Gemini 5xx / timeout | 동일 처리 | "외부 서비스 일시 오류" |
| JSON 파싱 실패 | status=FAILED, 응답 일부(마스킹) error_message | "응답 파싱 실패" |
| `EvalComprehensive` 없는 회차 | 일괄 시작 자체를 400 거부 | "종합평가 calculate 먼저" |
| 일괄 진행 중 동일 호출 | 409 (in-memory `set` 락) | "이미 진행 중인 배치" |
| placeholder 자연어 변환 누락 | unmask는 best-effort, PII 아니므로 안전 | 노출 없음 |

### 10.1 운영 환경 전제

- **1차 출시 가정**: 단일 uvicorn 워커. in-memory lock과 BackgroundTasks 모두 단일 프로세스에서 유효.
- **다중 워커 전환 시 후속 작업**: lock을 DB 기반(예: `insa_eval_ai_batch_lock` 테이블) 또는 Redis로 이전, BackgroundTasks 대신 APScheduler 작업으로 디스패치.
- BackgroundTasks 실행 중 프로세스 재시작 시 진행 중 배치는 중단됨 — 재시작 후 HR이 미완료 직원에 대해 일괄 또는 개별 재생성 호출.

---

## 11. 테스트 전략

### 11.1 단위 테스트 (외부 의존 0)

| 모듈 | 테스트 대상 |
|---|---|
| `pii_masker` | 사번·이름 치환, 코멘트 인명 치환, 긴 이름 우선, 같은 이름 동일 placeholder, unmask 복원 |
| `input_builder` | comprehensive 없으면 ValueError, response_count<3 indicator 제외, multi 전체<3이면 multi_block 제외, observer_id placeholder |
| `prompts` | 템플릿 렌더링 (필수 키 누락 시 ValueError) |

### 11.2 서비스 테스트 (Gemini mock)

| 시나리오 | 검증 |
|---|---|
| Happy path 단건 | DB row INSERT, version=1, is_latest=True, status=SUCCESS |
| 재생성 | prev.is_latest=False, 신규 version=2, 신규 is_latest=True |
| Gemini 4xx | status=FAILED, error_message 저장, prev 행 영향 없음 |
| 일괄 (10명, 7 성공 / 3 실패) | 7건 SUCCESS + 3건 FAILED, 알림 INSERT |
| 진행 중 중복 호출 | 409 |
| comprehensive 없는 회차 | 400 |
| HR_ADMIN 외 역할 | 403 |

### 11.3 API 통합 테스트

위 서비스 케이스를 라우트 단에서 한 번 더, JWT auth 포함.

### 11.4 FE 테스트 (Vitest + RTL)

| 시나리오 | 검증 |
|---|---|
| 회차 선택 → 직원 목록 렌더 | 테이블 행, status 배지 |
| 직원 선택 → Context Panel | 정량 헤더 + 4섹션 본문 |
| "일괄 생성" 클릭 → 진행률 표시 | mutation 호출, polling으로 status 갱신 |
| 실패 직원 행 "재생성" 버튼 | 개별 mutation, status=PENDING → SUCCESS/FAILED |
| HR_ADMIN 외 역할 진입 시도 | 메뉴 미노출 + 라우트 가드 |

### 11.5 다면 익명성 회귀

`backend/tests/test_multi_anonymity.py`에 신규 케이스 2개 추가:
1. AI 리포트 입력 빌드 시 evaluator_id가 어디에도 포함되지 않음
2. response_count<3 indicator는 입력에서 제외됨

### 11.6 커버리지 목표

BE 서비스 80%+ (CLAUDE.md 기준 70% 상회), 익명성 회귀 테스트 100%.

---

## 12. 구현 단계 (PHASE 18)

각 단계 별도 커밋, RED → GREEN → IMPROVE TDD.

| # | 단계 | 산출물 | 의존 | 예상 |
|---|---|---|---|---|
| 1 | DB 모델 + Alembic | `EvalAiReport` 모델, 마이그레이션, `alembic upgrade head` | — | S |
| 2 | `pii_masker` 단위 테스트 + 구현 | 사번·이름 치환, 코멘트 인명 치환, unmask | 1 | S |
| 3 | `input_builder` 테스트 + 구현 | DB 수집, 익명성 보장, multi<3 처리 | 1 | M |
| 4 | `prompts.py` v1.0 템플릿 | system + user 템플릿, 렌더 헬퍼 | — | S |
| 5 | `gemini_client` 어댑터 + mock | httpx, JSON 모드, 4xx/5xx/timeout 분기 | 4 | M |
| 6 | `ai_eval_report_service` 단건 | 단건 generate, version/is_latest, FAILED 저장 | 2-5 | M |
| 7 | 일괄 처리 + BackgroundTasks | for-loop 순차, 알림 INSERT, 동시 호출 lock | 6 | S |
| 8 | API 라우트 + 스키마 + 권한 | 6개 endpoint, HR_ADMIN/SYS 가드 | 7 | M |
| 9 | API 통합 테스트 | happy path, 권한, 검증, 동시 호출 | 8 | M |
| 10 | FE: API 클라이언트 + 훅 | useAiReports, useAiReport, useGenerateBatch, useGenerateOne, useAiReportHistory | 8 | S |
| 11 | FE: `AiEvalReportPage.tsx` | Toolbar + Primary 테이블 + Context Panel + 진행률 | 10 | L |
| 12 | FE: 라우트 + 메뉴 + 권한 가드 | `/eval/ai-report` 라우트 등록(`App.tsx`), `menuRegistry.ts` `eval-comp-final` 그룹 마지막에 추가, role 가드 적용 | 11 | S |
| 13 | FE 테스트 | 페이지 렌더·mutation·권한 | 11 | M |
| 14 | 다면 익명성 회귀 테스트 | `test_multi_anonymity.py`에 케이스 2개 추가 | 6 | S |
| 15 | 문서 업데이트 | `EVAL_MODULE.md` §9 AI 리포트, `.env.example` 업데이트 | 8 | S |

---

### 12.1 메뉴 위치 상세

`frontend/src/shell/menuRegistry.ts`의 `MENU.인사평가.groups[eval-comp-final].items` 배열 마지막에 추가:

```ts
{
  path: "/eval/ai-report",
  label: "AI 리포트",
  icon: "Solution",
  keywords: ["ai", "report", "리포트", "보조"]
}
```

### 12.2 Role 기반 가시성

현재 `MenuLeaf` 타입에 role 필드가 없음 → 둘 중 하나로 처리:

- **선택지 1 (권장)**: `MenuLeaf`에 옵션 필드 `roles?: Role[]` 추가, `SideNav`에서 `useAuth().user.role`로 필터.
  - 장점: 향후 다른 HR 전용 메뉴(예: 등급 조정)도 동일 패턴 재사용 가능.
  - 단점: 타입 변경이 모든 메뉴 정의에 영향. 기존 메뉴는 `roles` 없음 = 모두 노출(하위호환).
- **선택지 2**: `SideNav`에서 path별 하드코딩(`/eval/ai-report`는 HR_ADMIN/SYS만).
  - 장점: 변경 범위 최소.
  - 단점: 메뉴 정의와 가시성 규칙이 분리 → 향후 추적 어려움.

1차 출시는 **선택지 1**로 진행. 라우트 가드(`App.tsx` 또는 별도 `RequireRole` 컴포넌트)는 별도로 적용 — 메뉴 미노출 + 직접 URL 진입 차단 이중 방어.

---

## 13. 1차 출시 후 검토 (out of scope)

| 항목 | 비고 |
|---|---|
| 일일 호출 상한 enforcement | `GEMINI_DAILY_BUDGET_CALLS` 변수만 자리 잡고 실제 차단은 후속 |
| 프롬프트 v2.0 | HR 운영 피드백 수집 후 |
| Vertex AI Enterprise 전환 | 정책 변경 시. `gemini_client`만 교체 가능하게 어댑터 분리 |
| 부서장 / 본인 열람 권한 확장 | 권한 모델 확장 가능하게 둠. 1차는 HR 전용 고정 |
| 리포트 PDF 다운로드 | 요청 들어오면 후속 |
| 등급 조정 사유에 AI 리포트 인용 링크 | `EvalComprehensive.adjusted_reason` 향후 ID 참조로 발전 가능 |

---

## 14. 보안·컴플라이언스 체크리스트

- [x] `GEMINI_API_KEY`는 `.env`에만, 코드 하드코딩 금지 (global rules 보안)
- [x] 외부 호출 시 본인·상사 코멘트 원문은 마스킹 후 전송됨 — `docs/EVAL_MODULE.md`에 명시 (감사 대비)
- [x] 다면평가 익명성 6규칙 + 신규 2케이스 회귀 테스트
- [x] `error_message`는 마스킹된 상태로만 저장 (PII 누출 방지)
- [x] HR_ADMIN / SYSTEM_ADMIN 외 역할 차단 (라우트 + FE 가드 이중)
- [x] `generated_by` + `generated_at`로 audit trail 확보
