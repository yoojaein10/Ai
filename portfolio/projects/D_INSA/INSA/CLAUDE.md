# INSA - HR Personnel Management System

USTRA HR 대체 인사관리 시스템. FastAPI + React + MSSQL.

## Tech Stack

- **Backend:** FastAPI (Python 3.11+), sync routes + threadpool, SQLAlchemy + pyodbc, Alembic
- **Frontend:** React 18 + TypeScript + Vite, Ant Design, Zustand (client state), React Query (server state)
- **DB:** MSSQL, all tables prefixed `insa_`
- **Auth:** JWT — Access Token (30min, Authorization header) + Refresh Token (7 days, httpOnly cookie)
- **Deploy:** Vercel (FE) + nginx reverse proxy (BE)

## Project Structure

Monorepo: `backend/` + `frontend/`

## Commands

```bash
# Backend
cd backend && pip install -r requirements.txt
uvicorn app.main:app --reload

# Frontend
cd frontend && npm install
npm run dev
```

## Conventions

- Immutable patterns only (no mutation)
- All tables: `insa_` prefix (including system tables)
- Backend: schemas/ = Pydantic, db/ = SQLAlchemy models
- Tests: pytest (BE), Vitest (FE), coverage target 70%+
- Commit format: `<type>: <description>` (feat, fix, refactor, docs, test, chore)

## 인사평가 모듈

상세 문서: [docs/EVAL_MODULE.md](docs/EVAL_MODULE.md)

### 테이블 구성 (총 23개, 모두 `insa_` 접두사)

| 영역 | 접두사 | 개수 | 주요 테이블 |
|---|---|---|---|
| 평가 공통 | `insa_eval_*` | 6 | round, schedule, approver, calibration_group, calibration_member, setting |
| 성과평가 | `insa_perf_*` | 5 | kpi, target, target_mid, target_final, eval_result |
| 역량평가 | `insa_comp_*` | 5 | indicator, behavior, eval_self, eval_boss, sar_record |
| 다면평가 | `insa_multi_*` | 4 | indicator, response, response_log, result |
| 종합평가 | `insa_eval_*` | 3 | comprehensive, objection, objection_review |

### API Prefix

모든 평가 API: `/api/v1/eval/*`
- `/eval/rounds`, `/eval/schedules`, `/eval/approvers`, `/eval/calibration`, `/eval/settings`
- `/eval/perf/*` — KPI, 목표, 중간점검, 기말, 결과
- `/eval/comp/*` — 본인평가, 상사평가, SAR 관찰기록
- `/eval/multi/*` — 다면평가 입력/결과/제출현황 (익명)
- `/eval/comprehensive`, `/eval/objections` — 종합 + 이의신청

### Role 접근 권한

| Role | 평가 설정 | 본인평가 | 승인 | 등급 조정 | 재심의 |
|---|---|---|---|---|---|
| SYSTEM_ADMIN | ✅ | ✅ | ✅ | ✅ | ✅ |
| HR_ADMIN | ✅ | ✅ | - | ✅ | ✅ |
| DEPT_HEAD | - | ✅ | ✅* | - | - |
| EMPLOYEE | - | ✅ | - | - | 제출만 |

\* `insa_eval_approver`에 매핑된 경우만

### 다면평가 익명성 (CRITICAL)

- `insa_multi_eval_response` 테이블에 `evaluator_id` 컬럼이 **존재하지 않음**
- `insa_multi_eval_response_log` 테이블에 `score`/`indicator_id` 컬럼이 **존재하지 않음**
- 두 테이블 사이에 공통 join key가 **없음** — DB 차원에서 역추적 불가
- `response_count < 3`이면 결과 API가 `insufficient=true` 반환 (익명 보호)
- 절대로 evaluator_id를 response 테이블에 추가하지 말 것

---

## Design Context

> 전체 버전: [.impeccable.md](./.impeccable.md). 아래는 핵심 요약 — 모든 UI 작업에 적용.

### Users
- **주 사용자(80% 시간): 인사팀 HR_ADMIN** — 하루 종일 상주. 키보드 중심, 시각적 피로 누적 민감, 한 번의 실수가 법적 리스크.
- 보조: 부서장(평가·결재 집중), 일반 직원(본인 정보·평가 제출 단발성). 연령대 20~60대 — 판독성 중요.
- 맥락: 사무실 데스크톱 1920×1080, 한국어(ko_KR) 단일.

### Brand Personality
**따뜻 · 사람 중심 · 실용** — USTRA식 무미건조한 그룹웨어 톤을 벗어나되, 스타트업 HR SaaS의 캐주얼 과잉도 회피. "정중하지만 차갑지 않은" 지점. 데이터보다 **사람 이름·얼굴**을 먼저 보이게.

### Aesthetic Direction
- **Theme**: 라이트 중립(chroma ≤ 0.003 극미세 웜 틴트 허용). 다크 모드 미지원.
- **Brand Primary**: 현 네이비 `#1a1a2e` 유지 → `oklch(15% 0.04 275)`. 헤더 + Primary 버튼에만.
- **Accent Warm**: `oklch(72% 0.13 75)` 앰버. 아바타·빈 상태·알림 뱃지 **한정**.
- **Typography**: Body/UI = **Wanted Sans Variable**, Display(H1·빈 상태) = **Gowun Dodum**. Pretendard·Noto Sans KR·Spoqa 반사 선택 금지.
- **Density**: AntD `size="small"` 기본, row 32px, `tabular-nums` 숫자. 섹션 간 24~32px 여백.
- **Page Grammar(고정)**: Header(제목+Action) → Toolbar(sticky 필터) → Primary(테이블/폼) → Context Panel. 어느 화면에서도 동일.

### Design Principles (5원칙)
1. **Grammar over Novelty** — 모든 화면 동일 구조 문법. 특별한 화면을 다르게 설계 금지.
2. **Density with Air** — 행·셀은 촘촘히, 섹션 간은 넉넉히.
3. **Warmth in the Seams, Neutrality in the Field** — 면은 중립, 온도는 이음새(아바타·빈 상태·마이크로카피)에만.
4. **Loud Primary, Quiet Destructive** — Primary는 화면당 1회 확실히. 파괴적 액션은 저채도 + 타이핑 확인.
5. **Keyboard ≥ Mouse for Power Users** — 키보드가 마우스보다 빠를 것.

### Absolute Bans (위반 시 재작성)
- 카드·알림에 `border-left: 2px+ solid <any>` 색 스트립.
- 그라디언트 텍스트(`background-clip: text` + gradient). 현재 "Daehwa" 로고가 이에 해당 → 셸 재설계 1순위 제거 대상.
- 퍼플→블루 그라디언트, 네온 액센트, 글래스모피즘 장식.
- 동일 크기 카드 그리드 나열식 대시보드.

### 기술 제약
- **Ant Design 5 유지**. 커스텀은 셸(MainLayout·Header·Sider)과 대시보드 한정. 테이블·폼·모달은 AntD.
- ConfigProvider `theme` 토큰으로 전역 색·radius·fontFamily 재설정.
- WCAG AA 내부 목표(대비 4.5:1, 키보드 네비, `prefers-reduced-motion` 존중).
