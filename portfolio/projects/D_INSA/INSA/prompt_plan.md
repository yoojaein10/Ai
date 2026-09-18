# PHASE 15 (셸 재설계) 구현 계획: MainLayout + PageShell + 디자인 토큰

> 확정일: 2026-04-20
> 참고: `D:\AI\INSA\CLAUDE.md` Design Context, `.impeccable.md`

## 요구사항 재진술
현재 셸(Header/Sider/PageShell)을 새 디자인 토큰으로 전면 재구축. 그라디언트 "Daehwa" 로고 제거(Absolute Ban 위반). Wanted Sans Variable + Gowun Dodum 폰트 체계 적용. AntD ConfigProvider theme + CSS vars로 oklch 기반 토큰 주입. 모든 페이지가 "Header → Toolbar → Primary → Context Panel" grammar를 따르도록 정렬.

## 설계 원칙 (CLAUDE.md Design Context 준수)
1. **Grammar over Novelty** — 모든 화면 동일 구조 문법
2. **Density with Air** — row 32px, 섹션 간 24-32px
3. **Warmth in the Seams** — 면은 중립, 온도는 아바타·빈 상태·마이크로카피에만
4. **Loud Primary, Quiet Destructive** — Primary 버튼 네이비, 파괴적 액션은 저채도 + 타이핑 확인
5. **Keyboard ≥ Mouse** — 단축키, 포커스 링, Tab 순서 정비

## 구현 단계 (6 커밋)

### 15-A 디자인 토큰 인프라 (2-3h)
- `src/theme/tokens.ts` — AntD theme 객체
  - `colorPrimary: oklch(15% 0.04 275)` → hex 변환
  - `colorWarning` / accent = `oklch(72% 0.13 75)` 앰버
  - `borderRadius: 6`, `controlHeightSM: 32`
  - `fontFamily: "Wanted Sans Variable", sans-serif`
  - `fontFeatureSettings: "tnum"` (숫자 tabular)
- `src/theme/variables.css` — CSS 커스텀 프로퍼티
  - `--color-*` / `--space-*` (4,8,12,16,24,32,48) / `--elevation-*`
  - 극미세 웜 틴트 적용한 neutrals (chroma ≤ 0.003)
- `index.html` — Wanted Sans / Gowun Dodum preconnect + preload
- `src/index.css` — body font 교체, `font-variant-numeric: tabular-nums`, 기존 Pretendard import 제거
- `App.tsx` — `<ConfigProvider theme={tokens}>` 주입

### 15-B Header + SideNav 재구축 (3-4h)
- `shell/Header.tsx` 재작성
  - 그라디언트 "Daehwa" 제거 → 솔리드 워드마크(텍스트)
  - GNB Tabs (현재 active GNB 강조) + 프로필 Dropdown + NotificationBell
  - 48px 높이, 하단 border `--color-border-subtle`
- `shell/SideNav.tsx` 재작성
  - menuRegistry.ts 기반, collapsed 상태 Zustand persist(localStorage)
  - 현재 경로 하이라이트 (네이비 bar가 아닌 배경 틴트)
  - 접힘 시 아이콘만 표시, 펼침 240px
- `shell/MainLayout.tsx` — AntD `<Layout>` 구조 정비, outlet 영역 배경 surface

### 15-C PageShell 표준화 (2-3h)
- `shell/PageShell.tsx` 재작성
  - slots: `title`, `subtitle`, `actions`, `toolbar` (sticky), `children`, `contextPanel`
  - Heading = Gowun Dodum 24px, subtitle 14px neutral
  - Toolbar sticky top, background surface + 하단 1px border, padding 12px
  - contextPanel = 우측 320px (>=1440px) / 하단 접힘 (<1440px)
  - 기본 max-width 1600px + 좌우 auto margin

### 15-D 브랜드/로그인 정비 (1h)
- 그라디언트 로고 완전 제거 (Header + Favicon + Login 페이지)
- 로그인 페이지에 신규 토큰 적용, 버튼·입력 스타일 AntD 기본 + 테마 적용

### 15-E 기존 페이지 리그리드 (3-5h)
- PageShell 사용하지 않는 페이지 전수 점검
- 위반 수정 대상:
  - 카드 중첩 (nested Card)
  - border-left 2px+ 색 스트립
  - 중앙 정렬 본문 텍스트
  - 동일 크기 카드 그리드식 대시보드
- 주요 점검 영역: HR (`/hr/*`), 근태 (`/att/*`), 교육/복리후생, 인사평가 (`/eval/*`), 전자결재 (`/approval/*`, `/travel/*`), 캘린더, 문서함, 통계, 관리

### 15-F QA + 커밋 분리 (2-3h)
- 대비 AA 자동검사 (axe-core 또는 수동)
- Tab 키보드 네비 / 포커스 링 확인
- `prefers-reduced-motion` 존중
- 주요 페이지 시각 회귀 스크린샷 (폰트 교체 영향)
- 커밋 분리:
  1. `feat: design tokens (oklch) + font switch (Wanted Sans + Gowun Dodum)`
  2. `feat: rebuild Header + SideNav with new tokens`
  3. `feat: standardize PageShell grammar`
  4. `chore: remove gradient Daehwa logo + relight login`
  5. `refactor: align existing pages to PageShell grammar`
  6. `test: a11y + visual regression sanity`

## 주요 파일
- **신규**: `src/theme/tokens.ts`, `src/theme/variables.css`
- **재작성**: `src/shell/MainLayout.tsx`, `src/shell/Header.tsx`, `src/shell/SideNav.tsx`, `src/shell/PageShell.tsx`
- **수정**: `src/App.tsx`, `index.html`, `src/index.css`, 로그인 페이지, PageShell 사용 페이지 전수 점검

## 리스크
| 리스크 | 수준 | 대응 |
|---|---|---|
| 전역 폰트 교체로 폭/행높이 변경 → 테이블/폼 시각 회귀 | HIGH | 주요 화면 스냅샷 비교, 좁은 컬럼 우선 점검 |
| Wanted Sans / Gowun Dodum 라이선스·self-host 전략 | MEDIUM | 공식 CDN 우선 + 라이선스 확인. fallback 폰트 스택 견고히 |
| ConfigProvider theme 변경 시 AntD Button/Table/Form/Modal 스타일 전수 재검증 | MEDIUM | 대표 페이지 1개씩 샘플링, primary 변경으로 인한 hover/active 상태 확인 |
| Gowun Dodum 한글 커버리지/자간 문제 | LOW | Display(H1/빈 상태)에만 제한, 본문은 Wanted Sans |
| Sider collapsed 상태 localStorage 충돌 | LOW | 기존 store 네임스페이스 확인 |

## 복잡도: MEDIUM-HIGH (~13-20h) · 6 커밋

---

## 이전 계획

# PHASE 16 구현 계획: 출장명령부 + 복명서 (전자결재 + 캘린더 자동 반영)

> 확정일: 2026-04-20
> 참고 스펙: `chamjo/insa_hr_operations_prompts12~16.md` (741~881행)

## 요구사항 재진술
출장명령부를 전자결재 문서로 기안. 최종 승인 시 본인+동행자 전원 캘린더에 이벤트 자동 생성. 출장 종료 후 복명서(별도 결재문서)로 실제 경비·보고 내용 정산. 연차 차감 없음(업무 연장).

## 의존성 (완료)
- PHASE 12 — `approval_service.approve_step/reject_step/recall_doc` + `doc_hooks` dispatcher
- PHASE 13 — `CalendarEvent.source_type/source_ref` + `calendar_service.create_event_from_approval`
- PHASE 15 — `doc_hooks/leave_hook.py` 패턴, `init_db.py` doc_type+LineTemplate seed

## 새 테이블 (3)
- `insa_travel_order_detail` — doc_id FK unique, travel_type(DOMESTIC/OVERSEAS), purpose, destination, client_company, start_at/end_at(datetime), transportation, estimated_cost, project_code, appraisal_case_no(감정평가법인 특화), remarks
- `insa_travel_companion` — travel_id FK, emp_id FK, unique(travel_id, emp_id)
- `insa_travel_report` — travel_id FK unique, doc_id FK(복명서 결재), report_content, actual_cost, receipts_url, reported_at

## 새 doc_type (2)
- TRAVEL_ORDER + 기본 결재선 (팀장 → 부서장)
- TRAVEL_REPORT

## 구현 단계 (7 커밋)

### 16-A DB 모델 + 마이그레이션 + 시드 (2h)
- 모델 3개, Alembic revision, init_db seed(doc_type 2 + LineTemplate 2)

### 16-B 서비스 + 스키마 (2h)
- `schemas/travel_order.py`, `services/travel_order_service.py`
- create_draft/submit/cancel/list_my/list_team/get_detail

### 16-C 결재 훅 (1.5h)
- `doc_hooks/travel_hook.py` on_approved → 본인+동행자 캘린더 이벤트 생성(event_type=TRAVEL, all_day=False 시간범위)
- dispatcher에 TRAVEL_ORDER 등록
- calendar_service: 다중 owner 이벤트 멱등 생성 (source_type, source_ref, owner_id 유니크)

### 16-D 복명서 서비스 + 훅 (1.5h)
- `services/travel_report_service.py` + `doc_hooks` TRAVEL_REPORT 등록
- 승인 시 travel_report.reported_at 확정

### 16-E API 라우트 (1h)
- `/api/v1/travel/orders` (POST/GET my/team/{id})
- `/orders/{id}/report` POST/GET
- `/orders/by-case/{case_no}` GET

### 16-F 프론트엔드 (3h)
- api/travelOrder.ts, api/travelReport.ts
- pages/travel/: TravelOrderPage(폼), MyTravelOrdersPage, TeamTravelOrdersPage, TravelReportPage
- App.tsx 라우트 + menuRegistry 전자결재>출장 그룹

### 16-G 테스트 + 커밋 분리 (2h)
- test_travel_order_service, test_travel_order_api, test_travel_hook(동행자 이벤트 생성 검증)
- 커버리지 70%+

완료: 2026-04-20. 6 커밋. 519 backend 테스트 pass. 4 travel 페이지 + 2 API client 추가.

---

## 더 이전 계획

# PHASE 15 (근태 전자결재) 구현 계획

휴가 신청 → 결재 → 연차 자동 차감 + 캘린더 자동 이벤트. `insa_holiday` + `insa_leave_request_detail` + `doc_hooks/leave_hook.py`. 완료: 2026-04-20.

---

# PHASE 14 구현 계획: 연차 관리

`insa_leave_type/balance/accrual_rule/transaction` + APScheduler 월차·연간 리셋. 완료: 2026-04-20.

---

# PHASE 13 구현 계획: 회사 공유 캘린더

3 테이블 + 12 API + 4 페이지. FullCalendar. 완료: 2026-04-20.
