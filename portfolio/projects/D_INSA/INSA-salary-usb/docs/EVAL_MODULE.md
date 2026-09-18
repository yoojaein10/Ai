# 인사평가 모듈 (Evaluation)

INSA HR 시스템의 인사평가 도메인 상세 문서. 5개 PHASE 로 구축됨:
PHASE 1 평가 공통, 2 성과, 3 역량, 4 다면(익명), 5 종합.

---

## 1. 도메인 용어

| 용어 | 영문 | 설명 |
|---|---|---|
| 평가 회차 | Round | 1년 1회 정기 평가 단위 (`insa_eval_round`) |
| 평가 일정 | Schedule | 회차 내 단계별 일정 (TARGET/MID/FINAL/COMPREHENSIVE) |
| 평가자 매핑 | Approver | 누가 누구를 어떤 유형으로 평가하는지 (`insa_eval_approver`) |
| 보정집단 | Calibration Group | 등급 분포 보정 단위 (직급/팀별) |
| 평가 설정 | Setting | 가중치 + 등급 기준 (`insa_eval_setting`, JSON) |
| KPI | Key Performance Indicator | 성과평가 지표 |
| SAR | Situation-Action-Result | 역량 관찰 기록 형식 |
| 다면평가 | Multi-source / 360 | 동료/상사/부하의 익명 평가 |
| 종합평가 | Comprehensive | perf + comp + multi 를 가중치로 합산 |
| 원등급 / 최종등급 | original / final grade | original 보존, final 만 수동 조정 가능 |

---

## 2. ER (테이블 관계)

```
insa_eval_round 1 ── n insa_eval_schedule
                1 ── n insa_eval_approver
                1 ── n insa_perf_kpi
                1 ── n insa_perf_target ── 1 insa_perf_target_mid
                                        ── 1 insa_perf_target_final
                1 ── n insa_perf_eval_result
                1 ── n insa_comp_eval_self
                1 ── n insa_comp_eval_boss
                1 ── n insa_multi_eval_indicator ── n insa_multi_eval_response
                                                 ── n insa_multi_eval_result
                1 ── n insa_multi_eval_response_log    ★ response 와 공통키 없음
                1 ── n insa_eval_comprehensive
                1 ── n insa_eval_objection ── n insa_eval_objection_review

insa_eval_calibration_group ── n insa_eval_calibration_member
insa_eval_setting (year unique)
insa_comp_indicator ── n insa_comp_behavior (5 levels)
insa_comp_sar_record (역량 관찰)
```

★ `insa_multi_eval_response_log`는 (evaluator_id, round_id, evaluatee_id) 만 보유 →
`insa_multi_eval_response`(score, indicator_id 보유, evaluator_id 부재)와 join 불가.

---

## 3. 워크플로

### 3-1. 평가 사이클

```
[관리자] 회차 생성 (PLANNED)
   └→ schedules 4개, KPI/지표 생성
   └→ approver 매핑, 보정집단 구성, setting 저장
   └→ 회차 상태 IN_PROGRESS

[직원] 목표 작성 (DRAFT) → 제출 (SUBMITTED)
[부서장/평가자] 승인 (APPROVED) or 반려 (REJECTED)
[직원] 중간점검 입력 → 기말실적 입력
[직원] 본인평가 (CompEvalSelf)
[평가자] 상사평가 (CompEvalBoss), SAR 관찰기록
[모든 평가자] 다면평가 익명 제출 (PEER/BOSS/SUBORDINATE)

[관리자] /eval/comprehensive/calculate 호출
   ↓
   각 사원별 perf+comp+multi 평균 → 가중치 적용 → 등급 산정
   insa_eval_comprehensive 에 upsert (original_grade=final_grade)

[인사위원회] 등급 수동 조정 (PUT /eval/comprehensive/{id}/grade)
   - final_grade 만 변경, original_grade 보존
   - is_adjusted=True, adjusted_reason 필수

[직원] 결과 확인 → 이의신청 (POST /eval/objections, status=PENDING)
[관리자] 재심의 (PUT /eval/objections/{id}/review)
   - decision: ACCEPTED | REJECTED → status 전이
   - 한 번 ACCEPTED/REJECTED 된 건은 재처리 불가

[관리자] 회차 close (status=CLOSED)
```

### 3-2. 다면평가 익명 제출

```
[평가자] POST /eval/multi/response
   ├→ insa_multi_eval_response_log INSERT (evaluator_id 보관)
   └→ insa_multi_eval_response   INSERT (evaluator_id 없음, score/indicator만)
        ★ 두 테이블에 공통 키 없음 → 누가 무슨 점수 줬는지 추적 불가

[피평가자] GET /eval/multi/results/{emp_id}
   ├→ log 테이블에서 distinct evaluator 수 카운트
   └→ < 3명: insufficient=true (점수 표시 X)
      ≥ 3명: response 평균만 노출
```

### 3-3. 이의신청 상태 전이

```
PENDING ──review:ACCEPTED──> ACCEPTED  (종착)
   │     ──review:REJECTED──> REJECTED  (종착)
   ↓
REVIEWED (예약, 미사용)
```

ACCEPTED/REJECTED 상태에서 추가 review 호출 → 400.

---

## 4. API 레퍼런스

전체 prefix: `/api/v1`

### 평가 공통

| Method | Path | Role | 설명 |
|---|---|---|---|
| GET | `/eval/rounds` | * | 회차 목록 |
| POST | `/eval/rounds` | HR/SYS | 회차 생성 |
| PUT | `/eval/rounds/{id}` | HR/SYS | 회차 수정/상태 변경 |
| GET/POST | `/eval/schedules` | * / HR | 일정 |
| GET/POST/DELETE | `/eval/approvers` | HR/SYS | 평가자 매핑 |
| GET/POST | `/eval/calibration/groups` | HR/SYS | 보정집단 |
| GET/PUT | `/eval/settings/{year}` | HR/SYS | 가중치/등급 설정 |

### 성과평가

| Method | Path | 설명 |
|---|---|---|
| GET/POST | `/eval/perf/kpis` | KPI 마스터 |
| GET/POST/PUT | `/eval/perf/targets` | 목표 작성/제출/승인 |
| GET/POST | `/eval/perf/midterm` | 중간점검 |
| GET/POST | `/eval/perf/final` | 기말실적 |
| GET/POST | `/eval/perf/results` | 평가 결과 |

### 역량평가

| Method | Path | 설명 |
|---|---|---|
| GET/POST | `/eval/comp/indicators` | 역량지표 + 행동지표 |
| GET/POST | `/eval/comp/self` | 본인평가 |
| GET/POST | `/eval/comp/boss` | 상사평가 |
| GET/POST | `/eval/comp/sar` | SAR 관찰기록 |

### 다면평가 (익명)

| Method | Path | 설명 |
|---|---|---|
| GET/POST | `/eval/multi/indicators` | 다면지표 |
| GET | `/eval/multi/my-targets` | 내가 평가할 대상 |
| POST | `/eval/multi/response` | 익명 제출 (per indicator) |
| GET | `/eval/multi/results/{emp_id}` | 본인 또는 관리자 결과 (insufficient<3) |
| GET | `/eval/multi/status` | 제출 현황 (HR/SYS) |

### 종합평가 + 이의신청

| Method | Path | Role | 설명 |
|---|---|---|---|
| GET | `/eval/comprehensive?round_id=` | * | 본인 행만 / 관리자 전체 |
| POST | `/eval/comprehensive/calculate` | HR/SYS | 일괄 계산 |
| PUT | `/eval/comprehensive/{id}/grade` | HR/SYS | 등급 조정 (사유 필수) |
| POST | `/eval/objections` | * | 이의신청 (본인) |
| GET | `/eval/objections?round_id=` | * | 본인 / 관리자 전체 |
| PUT | `/eval/objections/{id}/review` | HR/SYS | 재심의 ACCEPTED/REJECTED |

---

## 5. 주요 비즈니스 규칙

### 5-1. 가중치 합 100 강제

`insa_eval_setting.weight_config`는 `{"perf": N, "comp": M, "multi": K}` JSON.
`N+M+K != 100` 이면 calculate API 가 400 에러 반환.

### 5-2. 등급 산정 경계

`grade_criteria` JSON 배열의 `min`/`max`는 `min <= score < max`.
단, `max == 100` 인 최상위 등급(S)은 `score == 100` 도 포함.

### 5-3. 원등급 보존

`manual_adjust_grade` 호출 시:
- `final_grade` 만 변경
- `original_grade` 는 절대 변경하지 않음
- `is_adjusted=True`, `adjusted_by`, `adjusted_reason`, `adjusted_at` 기록
- `adjusted_reason` 빈 문자열이면 422 (Pydantic) / 400 (서비스)

### 5-4. 재계산 안전성

`calculate_comprehensive` 재실행 시:
- 기존 `is_adjusted=True` 행은 `final_grade` 보존 (재계산 영향 X)
- `is_adjusted=False` 행은 `original_grade=final_grade` 로 갱신

### 5-5. 다면평가 익명성 보장 6 규칙

1. `insa_multi_eval_response`에 `evaluator_id`/`rater_id`/`submitter_id`/`user_id` 등 컬럼 추가 금지
2. `insa_multi_eval_response_log`에 `score`/`indicator_id`/`comment` 컬럼 추가 금지
3. 두 테이블 사이에 공통 join key 추가 금지
4. 개별 evaluator의 점수 조회 API 절대 추가 금지
5. `response_count < 3`이면 무조건 `insufficient=true` (응답자 수 노출도 차단)
6. 서비스 코드에서 `MultiEvalResponse(...)` 생성 시 `evaluator_id` 인자 절대 전달 금지

위 6개 항목은 `tests/test_multi_anonymity.py`로 자동 회귀 검증됨.

---

## 6. 시드 스크립트

```bash
cd backend
python scripts/seed_eval.py            # 시드
python scripts/seed_eval.py --cleanup  # 현재 연도 평가 데이터 정리
```

생성 항목:
- 현재 연도 회차 1개 (status=IN_PROGRESS)
- 4단계 일정 (TARGET/MID/FINAL/COMPREHENSIVE)
- KPI 5개, 역량지표 8개 + 행동지표 5레벨, 다면지표 4개
- 기존 직원 부서별 BOSS/PEER/SUBORDINATE 매핑
- 보정집단 3개 (사원·대리 / 과장·차장 / 부장)
- `insa_eval_setting`: weight 40/30/30, S 90~100 / A 80~90 / B 70~80 / C 60~70 / D 0~60

스크립트는 idempotent: 재실행해도 중복 생성하지 않음.

---

## 7. 테스트 커버리지

평가 모듈 services 측정 결과: **85%** (목표 70%)

```
app\services\comp_boss.py               66%
app\services\comp_indicator.py          95%
app\services\comp_sar.py                83%
app\services\comp_self.py               92%
app\services\eval_approver.py           95%
app\services\eval_calibration.py        95%
app\services\eval_comprehensive.py      87%
app\services\eval_objection.py          90%
app\services\eval_round.py              91%
app\services\eval_setting.py           100%
app\services\multi_indicator.py         85%
app\services\multi_response.py          92%
app\services\multi_result.py            94%
app\services\perf_*.py              71~95%
─────────────────────────────────────────
TOTAL                                   85%
```

127개 테스트 모두 통과 (`pytest tests/`).

---

## 8. 참고

- 백엔드 라우터는 모두 sync (`def`, no `async def`) — FastAPI threadpool 사용
- 프런트엔드는 React Query로만 서버 상태 관리, Zustand에 서버 데이터 저장 금지
- 모든 평가 페이지는 `frontend/src/pages/Eval*.tsx`, `Perf*.tsx`, `Comp*.tsx`, `Multi*.tsx` 플랫 구조
- API 클라이언트는 `frontend/src/api/*.ts`에 hook과 co-locate
