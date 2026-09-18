# PHASE 18-15 Leader Plan

**작성**: 2026-05-28
**작성자**: phase-leader (오케스트레이터 직접 분해)
**규모 판정**: 소규모 → 풀팀 호출 생략, fe-engineer + qa-reviewer 부분 활성화 가능

## Phase 0 컨텍스트 확인 결과

- `_workspace/18-15/` — 없었음, 방금 생성
- 마지막 commit: `4448e66 docs: AI 리포트 §9 + .env.example 업데이트 (PHASE 18-14)`
- 브랜치: `phase-18-ai-eval-report` (main 대비 17 commits ahead, push 미실시)
- 메모리(`session_resume_20260507.md`)는 21일 전 작성 — 신뢰도 보정 필요

## 메모리 기준 남은 작업 (4건) — 검증 결과

| # | 작업 | 메모리 기준 상태 | 2026-05-28 검증 | 결론 |
|---|------|---------------|----------------|-----|
| 1 | UX 1줄 수정 (`EvalAiReportPage.tsx` 버튼 라벨 상태 분기) | 미완 | **이미 완료** — `EvalAiReportPage.tsx:118`에 `{row.report_id == null ? "생성" : "재생성"}` 적용됨. PHASE 18-11/12 commit 시점에 함께 반영된 것으로 추정 | ✅ DONE |
| 2 | alembic stamp + upgrade head | DB가 `20260430_0001`에 멈춤, `20260501_0001`이 `insa_approval_reference 이미 존재`로 막힘 → `alembic stamp 20260502_0001` 후 upgrade | DB 접근 불가 — **사용자만 가능** | ⏳ 사용자 |
| 3 | 브라우저 E2E 8 시나리오 (HR_ADMIN 일괄 생성, 열람, 권한, 알림 등) | 미완 | 브라우저 접근 불가 — **사용자만 가능** | ⏳ 사용자 |
| 4 | main 머지 + push | 사용자 명시 동의 필요 | 미동의 + uncommitted 67개 파일 미정리 → **블로커** | ⏳ 블록됨 |

## 신규 발견: uncommitted 67개 파일 (블로커)

```
git diff --stat (working tree) → 69 files, +4599 / -372 lines
```

영역:
- **backend** (30+ files): 라우터·서비스·스키마 다수, requirements.txt 포함
- **frontend** (30+ files): 페이지·셸·store 다수, package.json 포함
- **CLAUDE.md, .gitignore**: 방금 하네스 구성으로 내가 수정한 변경

이 변경은 PHASE 18(AI 평가 리포트)의 17 committed 변경과 **완전히 별개**다. 누군가가(또는 이전 세션에서) 다른 PHASE/리팩토링 작업을 working tree에 남겨두고 commit 안 한 상태.

**판단**: 이 67개 파일을 모르는 상태로 PHASE 18-15 머지를 진행하면 안 된다. 의도하지 않은 코드가 main에 같이 들어가거나, 분실될 위험.

## 활성화 에이전트

소규모 + 블로커 상태이므로 풀팀 호출 안 함:

- **phase-leader (현재)**: 상황 분석 + 사용자 보고
- **be-engineer**: 호출 안 함 (BE 코드 변경 없음, 다만 uncommitted 파일 판정에 의견 필요할 수 있음)
- **fe-engineer**: 호출 안 함 (UX 1줄 이미 완료, FE 추가 변경 없음)
- **qa-reviewer**: 머지 직전 회귀 검증 1회만 호출 예정 (uncommitted 정리 후)
- **doc-syncer**: 호출 안 함 (PHASE 18 문서는 18-14에서 이미 갱신됨)
- **domain-researcher**: 호출 안 함 (리서치 불필요)

## 사용자에게 확인 필요한 사항

1. **uncommitted 67개 파일**의 의도:
   - (A) PHASE 18 외 다른 진행 중인 작업이다 → 별도 브랜치로 분리
   - (B) 의도하지 않은 변경이라 폐기해도 된다 → `git stash` or `git checkout --`
   - (C) PHASE 18에 포함시켜 같이 머지하고 싶다 → 그러면 PHASE 18 범위 재정의 필요

2. **alembic 이슈**: 사용자가 이미 DB stamp+upgrade를 수동으로 했을 수도 있음. 현재 DB 상태를 LLM이 알 수 없음.

3. **머지 시점**: 67개 파일 정리 + alembic + E2E 끝난 뒤 진행. 지금은 머지 보류.

## 다음 액션

1. 위 3개 질문에 대한 사용자 답변 수신
2. 답변에 따라:
   - 67개 파일 처리 (분리 / 폐기 / 포함 중 선택)
   - alembic / E2E 사용자 직접 수행 결과 확인
   - 모두 OK 시 qa-reviewer 호출 → 회귀 + 디자인 절대 금지 점검 → main 머지 동의 받기
