# AI 인사평가 리포트 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** HR_ADMIN이 회차 단위로 평가 데이터를 종합한 AI 보조 리포트를 생성·열람할 수 있는 기능을 구현한다.

**Architecture:** FastAPI 신규 라우트 `/api/v1/eval/ai-reports` + 신규 서비스 `ai_eval_report_service` + 신규 테이블 `insa_eval_ai_report`. 외부 Gemini 2.5 Flash API를 PII 마스킹 후 호출, JSON 응답을 4섹션으로 분해 저장. FE는 단일 페이지 `/eval/ai-report` (Toolbar/Primary/Context Panel).

**Tech Stack:** FastAPI(sync) · SQLAlchemy · Alembic · pyodbc/MSSQL · httpx · Pydantic v2 · React 18 + TypeScript + Vite · Ant Design 5 · React Query · Vitest + RTL · pytest.

**Spec:** `docs/superpowers/specs/2026-05-06-ai-eval-report-design.md`

---

## File Structure

### Backend (신규/수정)

```
backend/
├ alembic/versions/
│  └ 20260506_0001_eval_ai_report.py            (신규) 테이블 생성
├ app/
│  ├ core/
│  │  └ config.py                                (수정) GEMINI_* 설정 추가
│  ├ db/
│  │  └ models.py                                (수정) EvalAiReport 모델 추가
│  ├ schemas/
│  │  └ eval_ai_report.py                        (신규) Pydantic 스키마
│  ├ services/
│  │  ├ ai_eval_report_service.py                (신규) 오케스트레이션
│  │  └ ai_report/
│  │     ├ __init__.py                           (신규)
│  │     ├ input_builder.py                      (신규) DB → 입력 dict
│  │     ├ pii_masker.py                         (신규) 마스킹/언마스킹
│  │     ├ gemini_client.py                      (신규) Gemini API 어댑터
│  │     └ prompts.py                            (신규) v1.0 템플릿
│  └ api/v1/
│     ├ ai_eval_report.py                       (신규) 6 endpoints
│     └ router.py                                (수정) include_router
└ tests/
   ├ test_ai_report_pii_masker.py                (신규)
   ├ test_ai_report_input_builder.py             (신규)
   ├ test_ai_report_gemini_client.py             (신규)
   ├ test_ai_eval_report_service.py              (신규)
   ├ test_ai_eval_report_api.py                  (신규)
   └ test_multi_anonymity.py                     (수정) AI 리포트 케이스 2개 추가
```

### Frontend (신규/수정)

```
frontend/
└ src/
   ├ api/
   │  └ aiReport.ts                              (신규) hooks + axios
   ├ pages/
   │  └ eval/
   │     └ AiEvalReportPage.tsx                  (신규) 단일 페이지
   ├ App.tsx                                     (수정) /eval/ai-report 라우트
   └ shell/
      ├ menuRegistry.ts                          (수정) MenuLeaf.roles 필드 + 메뉴 항목
      └ SideNav.tsx                              (수정) role 필터
```

### Docs

```
docs/
└ EVAL_MODULE.md                                 (수정) §9 AI 리포트 추가
backend/.env.example                             (수정 또는 신규) GEMINI_* 변수
```

---

## Task 1: DB 모델 + Alembic 마이그레이션

**Files:**
- Modify: `backend/app/db/models.py` (파일 끝에 추가)
- Create: `backend/alembic/versions/20260506_0001_eval_ai_report.py`

- [ ] **Step 1: SQLAlchemy 모델 추가**

`backend/app/db/models.py` 파일 맨 끝에 추가:

```python
# ── AI Evaluation Report (PHASE 18) ──────────────


class EvalAiReport(Base):
    __tablename__ = "insa_eval_ai_report"

    id = Column(Integer, primary_key=True, autoincrement=True)
    round_id = Column(Integer, ForeignKey("insa_eval_round.id"), nullable=False, index=True)
    employee_id = Column(Integer, ForeignKey("insa_employee.id"), nullable=False, index=True)

    version = Column(Integer, nullable=False)
    is_latest = Column(Boolean, nullable=False, default=True, index=True)

    status = Column(String(20), nullable=False)  # PENDING|SUCCESS|FAILED
    error_message = Column(Text, nullable=True)

    total_score = Column(Numeric(5, 2), nullable=True)
    final_grade = Column(String(5), nullable=True)
    multi_response_count = Column(Integer, nullable=True)
    multi_included = Column(Boolean, nullable=False, default=False)

    content_strengths = Column(Text, nullable=True)
    content_improvements = Column(Text, nullable=True)
    content_coaching = Column(Text, nullable=True)
    content_interview_guide = Column(Text, nullable=True)

    model_version = Column(String(50), nullable=False)
    prompt_version = Column(String(20), nullable=False)
    generated_by = Column(Integer, ForeignKey("insa_user.id"), nullable=False)
    generated_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index(
            "ix_eval_ai_report_round_emp_version",
            "round_id", "employee_id", "version",
            unique=True,
        ),
        Index(
            "ix_eval_ai_report_round_emp_latest",
            "round_id", "employee_id", "is_latest",
        ),
    )
```

- [ ] **Step 2: Alembic 마이그레이션 작성**

`backend/alembic/versions/20260506_0001_eval_ai_report.py`:

```python
"""add insa_eval_ai_report table

PHASE 18 AI 인사평가 리포트 — append-only 버전 관리.

Revision ID: 20260506_0001
Revises: 20260502_0001
Create Date: 2026-05-06
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260506_0001"
down_revision: Union[str, None] = "20260502_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "insa_eval_ai_report",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("round_id", sa.Integer(), sa.ForeignKey("insa_eval_round.id"), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("insa_employee.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("is_latest", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("total_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("final_grade", sa.String(5), nullable=True),
        sa.Column("multi_response_count", sa.Integer(), nullable=True),
        sa.Column("multi_included", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("content_strengths", sa.Text(), nullable=True),
        sa.Column("content_improvements", sa.Text(), nullable=True),
        sa.Column("content_coaching", sa.Text(), nullable=True),
        sa.Column("content_interview_guide", sa.Text(), nullable=True),
        sa.Column("model_version", sa.String(50), nullable=False),
        sa.Column("prompt_version", sa.String(20), nullable=False),
        sa.Column("generated_by", sa.Integer(), sa.ForeignKey("insa_user.id"), nullable=False),
        sa.Column("generated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_eval_ai_report_round_id",
        "insa_eval_ai_report",
        ["round_id"],
    )
    op.create_index(
        "ix_eval_ai_report_employee_id",
        "insa_eval_ai_report",
        ["employee_id"],
    )
    op.create_index(
        "ix_eval_ai_report_is_latest",
        "insa_eval_ai_report",
        ["is_latest"],
    )
    op.create_index(
        "ix_eval_ai_report_round_emp_version",
        "insa_eval_ai_report",
        ["round_id", "employee_id", "version"],
        unique=True,
    )
    op.create_index(
        "ix_eval_ai_report_round_emp_latest",
        "insa_eval_ai_report",
        ["round_id", "employee_id", "is_latest"],
    )


def downgrade() -> None:
    op.drop_index("ix_eval_ai_report_round_emp_latest", table_name="insa_eval_ai_report")
    op.drop_index("ix_eval_ai_report_round_emp_version", table_name="insa_eval_ai_report")
    op.drop_index("ix_eval_ai_report_is_latest", table_name="insa_eval_ai_report")
    op.drop_index("ix_eval_ai_report_employee_id", table_name="insa_eval_ai_report")
    op.drop_index("ix_eval_ai_report_round_id", table_name="insa_eval_ai_report")
    op.drop_table("insa_eval_ai_report")
```

- [ ] **Step 3: 마이그레이션 적용 (개발 DB)**

```bash
cd backend && alembic upgrade head
```

Expected: `Running upgrade 20260502_0001 -> 20260506_0001, add insa_eval_ai_report table`

- [ ] **Step 4: 테스트 SQLite에서 모델 import 검증**

```bash
cd backend && python -c "from app.db.models import EvalAiReport; print(EvalAiReport.__tablename__)"
```

Expected: `insa_eval_ai_report`

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/20260506_0001_eval_ai_report.py
git commit -m "feat: add insa_eval_ai_report table + alembic migration (PHASE 18-1)"
```

---

## Task 2: PII Masker 단위 테스트 + 구현

**Files:**
- Create: `backend/app/services/ai_report/__init__.py`
- Create: `backend/app/services/ai_report/pii_masker.py`
- Create: `backend/tests/test_ai_report_pii_masker.py`

- [ ] **Step 1: 빈 패키지 마커 생성**

`backend/app/services/ai_report/__init__.py`:

```python
```

(빈 파일)

- [ ] **Step 2: 실패 테스트 작성**

`backend/tests/test_ai_report_pii_masker.py`:

```python
from app.services.ai_report.pii_masker import PiiMasker


def test_mask_employee_id_and_name():
    masker = PiiMasker(employee_names=["홍길동", "김철수"])
    masked, restore = masker.mask_identifier(emp_id=1, name="홍길동", role="employee")
    assert masked == "__INSA_EMP_001__"
    assert restore[masked] == "홍길동(E001)"


def test_mask_rater_uses_separate_namespace():
    masker = PiiMasker(employee_names=["홍길동", "김철수"])
    masker.mask_identifier(emp_id=1, name="홍길동", role="employee")
    masked_rater, _ = masker.mask_identifier(emp_id=2, name="김철수", role="rater")
    assert masked_rater.startswith("__INSA_RATER_")
    assert masked_rater != "__INSA_EMP_002__"


def test_mask_comment_replaces_employee_names():
    masker = PiiMasker(employee_names=["홍길동", "김철수", "박영희"])
    text = "홍길동 사원과 김철수 대리가 협업했습니다"
    masked, restore = masker.mask_text(text)
    assert "홍길동" not in masked
    assert "김철수" not in masked
    assert "협업" in masked
    # 복원 시 원문 회복
    assert masker.unmask(masked, restore) == text


def test_long_names_match_first():
    """이름이 substring으로 충돌하면 긴 이름부터 매칭."""
    masker = PiiMasker(employee_names=["김철수", "김철"])
    masked, _ = masker.mask_text("김철수 사원")
    # "김철"이 먼저 매칭되면 안 됨
    assert "수 사원" not in masked


def test_same_name_returns_same_placeholder():
    masker = PiiMasker(employee_names=["홍길동"])
    masked1, restore = masker.mask_text("홍길동 사원")
    masked2, _ = masker.mask_text("홍길동 사원의 보고서", existing_restore=restore)
    # 두 번째 호출에서도 같은 placeholder
    placeholder1 = masked1.replace(" 사원", "")
    placeholder2 = masked2.replace(" 사원의 보고서", "")
    assert placeholder1 == placeholder2


def test_unmask_handles_missing_placeholder_gracefully():
    """Gemini가 placeholder를 자연어로 변환 시 best-effort로 처리."""
    masker = PiiMasker(employee_names=["홍길동"])
    restore = {"__INSA_EMP_001__": "홍길동(E001)"}
    text = "직원분의 강점은..."  # placeholder 없음
    assert masker.unmask(text, restore) == text
```

- [ ] **Step 3: 테스트 실행 — 실패 확인**

```bash
cd backend && python -m pytest tests/test_ai_report_pii_masker.py -v
```

Expected: ImportError or ModuleNotFoundError (`pii_masker` not exist).

- [ ] **Step 4: 구현**

`backend/app/services/ai_report/pii_masker.py`:

```python
"""PII 마스킹 / 언마스킹 — Gemini 호출 전후 변환.

마스킹 대상:
- 직원 식별자(사번 + 이름) → `__INSA_EMP_NNN__` / `__INSA_RATER_NNN__`
- 코멘트 본문 내 등록 직원 이름 → 식별자와 동일 placeholder

부서명·직급명은 원문 유지 (코칭 품질 위해).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal


RestoreMap = dict[str, str]
Role = Literal["employee", "rater"]


@dataclass
class PiiMasker:
    employee_names: list[str]
    _emp_counter: int = 0
    _rater_counter: int = 0
    _emp_id_to_placeholder: dict[tuple[Role, int], str] = field(default_factory=dict)
    _name_to_placeholder: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # 긴 이름부터 매칭하기 위해 정렬 (substring 충돌 방지)
        self._sorted_names = sorted(set(self.employee_names), key=len, reverse=True)

    def mask_identifier(
        self,
        emp_id: int,
        name: str,
        role: Role,
    ) -> tuple[str, RestoreMap]:
        key = (role, emp_id)
        if key in self._emp_id_to_placeholder:
            placeholder = self._emp_id_to_placeholder[key]
        else:
            if role == "employee":
                self._emp_counter += 1
                placeholder = f"__INSA_EMP_{self._emp_counter:03d}__"
            else:
                self._rater_counter += 1
                placeholder = f"__INSA_RATER_{self._rater_counter:03d}__"
            self._emp_id_to_placeholder[key] = placeholder
            self._name_to_placeholder[name] = placeholder
        restore = {placeholder: f"{name}(E{emp_id:03d})"}
        return placeholder, restore

    def mask_text(
        self,
        text: str | None,
        existing_restore: RestoreMap | None = None,
    ) -> tuple[str, RestoreMap]:
        if not text:
            return text or "", existing_restore or {}
        restore: RestoreMap = dict(existing_restore or {})
        masked = text
        for name in self._sorted_names:
            if name not in masked:
                continue
            if name in self._name_to_placeholder:
                placeholder = self._name_to_placeholder[name]
            else:
                self._emp_counter += 1
                placeholder = f"__INSA_EMP_{self._emp_counter:03d}__"
                self._name_to_placeholder[name] = placeholder
            masked = masked.replace(name, placeholder)
            restore[placeholder] = name
        return masked, restore

    @staticmethod
    def unmask(text: str, restore: RestoreMap) -> str:
        if not text:
            return text or ""
        result = text
        # 복원도 긴 placeholder부터 (안전성)
        for placeholder in sorted(restore.keys(), key=len, reverse=True):
            result = result.replace(placeholder, restore[placeholder])
        return result
```

- [ ] **Step 5: 테스트 재실행 — 통과 확인**

```bash
cd backend && python -m pytest tests/test_ai_report_pii_masker.py -v
```

Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/ai_report/__init__.py \
        backend/app/services/ai_report/pii_masker.py \
        backend/tests/test_ai_report_pii_masker.py
git commit -m "feat: add ai_report.pii_masker with employee name masking (PHASE 18-2)"
```

---

## Task 3: Input Builder 단위 테스트 + 구현

**Files:**
- Create: `backend/app/services/ai_report/input_builder.py`
- Create: `backend/tests/test_ai_report_input_builder.py`

- [ ] **Step 1: 실패 테스트 작성**

`backend/tests/test_ai_report_input_builder.py`:

```python
from decimal import Decimal

import pytest

from app.db.models import (
    CompEvalBoss,
    CompEvalSelf,
    CompIndicator,
    CompSarRecord,
    Department,
    Employee,
    EvalComprehensive,
    EvalRound,
    JobRank,
    MultiEvalIndicator,
    MultiEvalResult,
    PerfEvalResult,
)
from app.services.ai_report.input_builder import build_input


def _seed_round(db, year=2026):
    rnd = EvalRound(year=year, name=f"{year}년 정기평가", status="IN_PROGRESS")
    db.add(rnd)
    db.flush()
    return rnd


def _seed_employee(db, name="홍길동"):
    dept = Department(name="개발팀", code="DEV")
    rank = JobRank(name="과장", level=3)
    db.add_all([dept, rank])
    db.flush()
    emp = Employee(
        emp_no=f"E{name}",
        name=name,
        dept_id=dept.id,
        job_rank_id=rank.id,
    )
    db.add(emp)
    db.flush()
    return emp, dept, rank


def test_build_input_raises_when_comprehensive_missing(db_session):
    rnd = _seed_round(db_session)
    emp, *_ = _seed_employee(db_session)
    with pytest.raises(ValueError, match="comprehensive not calculated"):
        build_input(db_session, round_id=rnd.id, employee_id=emp.id)


def test_build_input_returns_quantitative_header(db_session):
    rnd = _seed_round(db_session)
    emp, dept, rank = _seed_employee(db_session)
    db_session.add(EvalComprehensive(
        round_id=rnd.id, emp_id=emp.id,
        perf_score=Decimal("85"), comp_score=Decimal("80"), multi_score=Decimal("75"),
        total_score=Decimal("82"), original_grade="A", final_grade="A",
        is_adjusted=False,
    ))
    db_session.commit()

    result = build_input(db_session, round_id=rnd.id, employee_id=emp.id)
    assert result["header"]["total_score"] == Decimal("82")
    assert result["header"]["final_grade"] == "A"
    assert result["header"]["dept_name"] == "개발팀"
    assert result["header"]["job_rank"] == "과장"


def test_multi_excluded_when_response_count_lt_3(db_session):
    rnd = _seed_round(db_session)
    emp, *_ = _seed_employee(db_session)
    db_session.add(EvalComprehensive(
        round_id=rnd.id, emp_id=emp.id, total_score=Decimal("70"),
        original_grade="B", final_grade="B", is_adjusted=False,
    ))
    ind = MultiEvalIndicator(round_id=rnd.id, name="협업", weight=Decimal("100"))
    db_session.add(ind)
    db_session.flush()
    db_session.add(MultiEvalResult(
        round_id=rnd.id, evaluatee_id=emp.id, indicator_id=ind.id,
        avg_score=Decimal("4.0"), response_count=2,  # < 3
    ))
    db_session.commit()

    result = build_input(db_session, round_id=rnd.id, employee_id=emp.id)
    assert result["header"]["multi_included"] is False
    assert result["multi_summary"] == []


def test_multi_included_when_response_count_ge_3(db_session):
    rnd = _seed_round(db_session)
    emp, *_ = _seed_employee(db_session)
    db_session.add(EvalComprehensive(
        round_id=rnd.id, emp_id=emp.id, total_score=Decimal("70"),
        original_grade="B", final_grade="B", is_adjusted=False,
    ))
    ind = MultiEvalIndicator(round_id=rnd.id, name="협업", weight=Decimal("100"))
    db_session.add(ind)
    db_session.flush()
    db_session.add(MultiEvalResult(
        round_id=rnd.id, evaluatee_id=emp.id, indicator_id=ind.id,
        avg_score=Decimal("4.0"), response_count=4,
    ))
    db_session.commit()

    result = build_input(db_session, round_id=rnd.id, employee_id=emp.id)
    assert result["header"]["multi_included"] is True
    assert result["header"]["multi_response_count"] == 4
    assert len(result["multi_summary"]) == 1
    assert result["multi_summary"][0]["indicator"] == "협업"


def test_partial_indicator_lt_3_excluded(db_session):
    """전체 응답 수>=3이지만 일부 indicator만 <3이면 그 indicator만 제외."""
    rnd = _seed_round(db_session)
    emp, *_ = _seed_employee(db_session)
    db_session.add(EvalComprehensive(
        round_id=rnd.id, emp_id=emp.id, total_score=Decimal("70"),
        original_grade="B", final_grade="B", is_adjusted=False,
    ))
    ind1 = MultiEvalIndicator(round_id=rnd.id, name="협업", weight=Decimal("50"))
    ind2 = MultiEvalIndicator(round_id=rnd.id, name="리더십", weight=Decimal("50"))
    db_session.add_all([ind1, ind2])
    db_session.flush()
    db_session.add_all([
        MultiEvalResult(round_id=rnd.id, evaluatee_id=emp.id, indicator_id=ind1.id,
                        avg_score=Decimal("4.0"), response_count=5),
        MultiEvalResult(round_id=rnd.id, evaluatee_id=emp.id, indicator_id=ind2.id,
                        avg_score=Decimal("3.0"), response_count=2),  # 제외 대상
    ])
    db_session.commit()

    result = build_input(db_session, round_id=rnd.id, employee_id=emp.id)
    indicators = [m["indicator"] for m in result["multi_summary"]]
    assert "협업" in indicators
    assert "리더십" not in indicators
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

```bash
cd backend && python -m pytest tests/test_ai_report_input_builder.py -v
```

Expected: ImportError on `app.services.ai_report.input_builder`.

- [ ] **Step 3: 구현**

`backend/app/services/ai_report/input_builder.py`:

```python
"""DB → 프롬프트 입력 dict 변환.

수집 항목:
- EvalComprehensive (정량 헤더)
- PerfEvalResult, CompEvalSelf, CompEvalBoss (점수+코멘트)
- MultiEvalResult (avg_score + response_count, response_count<3 indicator 제외)
- CompSarRecord (관찰기록)
- Employee + Department + JobRank (메타)

다면평가 익명성 보장:
- evaluator_id는 어떤 단계에서도 입력에 포함되지 않음
- response_count<3 indicator 제외, 전체<3이면 multi 통째로 제외
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import (
    CompEvalBoss,
    CompEvalSelf,
    CompIndicator,
    CompSarRecord,
    Department,
    Employee,
    EvalComprehensive,
    EvalRound,
    JobRank,
    MultiEvalIndicator,
    MultiEvalResult,
    PerfEvalResult,
)


def build_input(db: Session, round_id: int, employee_id: int) -> dict[str, Any]:
    comp = (
        db.query(EvalComprehensive)
        .filter(EvalComprehensive.round_id == round_id, EvalComprehensive.emp_id == employee_id)
        .first()
    )
    if comp is None:
        raise ValueError(f"comprehensive not calculated for round={round_id}, emp={employee_id}")

    rnd = db.query(EvalRound).filter(EvalRound.id == round_id).first()
    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    dept = db.query(Department).filter(Department.id == emp.dept_id).first() if emp.dept_id else None
    rank = db.query(JobRank).filter(JobRank.id == emp.job_rank_id).first() if emp.job_rank_id else None

    multi_results = (
        db.query(MultiEvalResult, MultiEvalIndicator.name)
        .join(MultiEvalIndicator, MultiEvalResult.indicator_id == MultiEvalIndicator.id)
        .filter(
            MultiEvalResult.round_id == round_id,
            MultiEvalResult.evaluatee_id == employee_id,
        )
        .all()
    )
    multi_summary = [
        {
            "indicator": indicator_name,
            "avg_score": r.avg_score,
            "response_count": r.response_count,
        }
        for r, indicator_name in multi_results
        if r.response_count >= 3
    ]
    total_responses = sum(r.response_count for r, _ in multi_results)
    multi_included = bool(multi_summary) and total_responses >= 3
    if not multi_included:
        multi_summary = []

    perf_results = (
        db.query(PerfEvalResult)
        .filter(PerfEvalResult.round_id == round_id, PerfEvalResult.emp_id == employee_id)
        .all()
    )
    self_evals = (
        db.query(CompEvalSelf, CompIndicator.name)
        .join(CompIndicator, CompEvalSelf.indicator_id == CompIndicator.id)
        .filter(CompEvalSelf.round_id == round_id, CompEvalSelf.emp_id == employee_id)
        .all()
    )
    boss_evals = (
        db.query(CompEvalBoss, CompIndicator.name)
        .join(CompIndicator, CompEvalBoss.indicator_id == CompIndicator.id)
        .filter(CompEvalBoss.round_id == round_id, CompEvalBoss.evaluatee_id == employee_id)
        .all()
    )
    sars = (
        db.query(CompSarRecord)
        .filter(CompSarRecord.target_emp_id == employee_id)
        .all()
    )

    return {
        "round": {"year": rnd.year, "name": rnd.name},
        "employee": {
            "emp_id": emp.id,
            "name": emp.name,
            "emp_no": emp.emp_no,
        },
        "header": {
            "perf_score": comp.perf_score,
            "comp_score": comp.comp_score,
            "multi_score": comp.multi_score,
            "total_score": comp.total_score,
            "final_grade": comp.final_grade,
            "dept_name": dept.name if dept else "",
            "job_rank": rank.name if rank else "",
            "multi_response_count": total_responses,
            "multi_included": multi_included,
        },
        "perf_results": [
            {"score": p.score, "grade": p.grade, "comment": p.comment, "evaluator_id": p.evaluator_id}
            for p in perf_results
        ],
        "self_evals": [
            {"indicator": ind, "score": s.score, "comment": s.comment}
            for s, ind in self_evals
        ],
        "boss_evals": [
            {"indicator": ind, "score": b.score, "comment": b.comment, "evaluator_id": b.evaluator_id}
            for b, ind in boss_evals
        ],
        "multi_summary": multi_summary,
        "sars": [
            {"date": s.observed_date, "situation": s.situation, "action": s.action,
             "result": s.result, "observer_id": s.observer_id}
            for s in sars
        ],
    }
```

- [ ] **Step 4: 테스트 재실행 — 통과 확인**

```bash
cd backend && python -m pytest tests/test_ai_report_input_builder.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ai_report/input_builder.py \
        backend/tests/test_ai_report_input_builder.py
git commit -m "feat: add ai_report.input_builder with multi anonymity guard (PHASE 18-3)"
```

---

## Task 4: 프롬프트 템플릿 v1.0

**Files:**
- Create: `backend/app/services/ai_report/prompts.py`

- [ ] **Step 1: 템플릿 작성**

`backend/app/services/ai_report/prompts.py`:

```python
"""Gemini 프롬프트 템플릿 v1.0."""
from __future__ import annotations

from typing import Any

PROMPT_VERSION = "v1.0"

SYSTEM_PROMPT = """당신은 한국 기업의 인사평가 보조 분석가입니다.
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


def render_user_prompt(masked_input: dict[str, Any]) -> str:
    h = masked_input["header"]
    multi_block = (
        f"평균 {h['multi_score']} (응답 {h['multi_response_count']}명)"
        if h["multi_included"]
        else "(데이터 부족으로 제외)"
    )
    self_comments = "\n".join(
        f"- [{e['indicator']}] {e['score']}/5: {e.get('comment') or '(코멘트 없음)'}"
        for e in masked_input["self_evals"]
    ) or "(없음)"
    boss_comments = "\n".join(
        f"- [{e['indicator']}] {e['score']}/5 by {e['evaluator_placeholder']}: {e.get('comment') or '(코멘트 없음)'}"
        for e in masked_input["boss_evals"]
    ) or "(없음)"
    sar_records = "\n".join(
        f"- {s['date']} (관찰자 {s['observer_placeholder']}): "
        f"S={s.get('situation') or ''} / A={s.get('action') or ''} / R={s.get('result') or ''}"
        for s in masked_input["sars"]
    ) or "(없음)"
    multi_summary = "\n".join(
        f"- [{m['indicator']}] 평균 {m['avg_score']}/5 (응답 {m['response_count']}명)"
        for m in masked_input["multi_summary"]
    ) or "(없음)"

    return f"""평가 회차: {masked_input['round']['year']}년 {masked_input['round']['name']}
대상: {masked_input['employee_placeholder']} ({h['dept_name']} / {h['job_rank']})

[정량 점수]
- 성과: {h['perf_score']}
- 역량: {h['comp_score']}
- 다면: {multi_block}
- 종합: {h['total_score']} (등급 {h['final_grade']})

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

- [ ] **Step 2: smoke test**

```bash
cd backend && python -c "
from app.services.ai_report.prompts import render_user_prompt, SYSTEM_PROMPT, PROMPT_VERSION
fake = {
    'round': {'year': 2026, 'name': '정기'},
    'employee_placeholder': '__INSA_EMP_001__',
    'header': {
        'perf_score': 85, 'comp_score': 80, 'multi_score': 75,
        'total_score': 82, 'final_grade': 'A',
        'dept_name': '개발팀', 'job_rank': '과장',
        'multi_response_count': 5, 'multi_included': True,
    },
    'self_evals': [], 'boss_evals': [], 'sars': [], 'multi_summary': [],
}
print(render_user_prompt(fake))
print('PROMPT_VERSION =', PROMPT_VERSION)
"
```

Expected: 한국어 프롬프트 출력 + `PROMPT_VERSION = v1.0`.

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/ai_report/prompts.py
git commit -m "feat: add ai_report.prompts v1.0 template (PHASE 18-4)"
```

---

## Task 5: Gemini 어댑터 + 단위 테스트

**Files:**
- Modify: `backend/app/core/config.py`
- Create: `backend/app/services/ai_report/gemini_client.py`
- Create: `backend/tests/test_ai_report_gemini_client.py`
- Modify: `backend/requirements.txt` (httpx는 이미 있음, 별도 추가 없음)

- [ ] **Step 1: Settings에 Gemini 설정 추가**

`backend/app/core/config.py`의 `Settings` 클래스 안에 (SCHEDULER 섹션 뒤에) 추가:

```python
    # Gemini API (PHASE 18: AI 평가 리포트)
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"
    GEMINI_TIMEOUT_SEC: int = 30
    GEMINI_DAILY_BUDGET_CALLS: int = 2000  # 안전장치, 1차 출시 미강제
```

- [ ] **Step 2: 실패 테스트 작성**

`backend/tests/test_ai_report_gemini_client.py`:

```python
import json

import httpx
import pytest

from app.services.ai_report.gemini_client import (
    GeminiClient,
    GeminiConfigError,
    GeminiError,
)


def _success_response_json() -> dict:
    return {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": json.dumps(
                                {
                                    "strengths": "성실함",
                                    "improvements": "발표 스킬",
                                    "coaching": "주 1회 발표 연습",
                                    "interview_guide": "최근 도전 경험을 묻기",
                                },
                                ensure_ascii=False,
                            )
                        }
                    ]
                }
            }
        ]
    }


def test_generate_returns_parsed_json(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_success_response_json())

    transport = httpx.MockTransport(handler)
    client = GeminiClient(api_key="REDACTED_CONFIGURE_LOCALLY", model="gemini-2.5-flash", timeout=10, transport=transport)
    result = client.generate(system_prompt="sys", user_prompt="user")
    assert result["strengths"] == "성실함"
    assert result["coaching"].startswith("주 1회")


def test_generate_raises_config_error_when_api_key_missing():
    with pytest.raises(GeminiConfigError):
        GeminiClient(api_key="", model="gemini-2.5-flash", timeout=10)


def test_generate_raises_on_4xx(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "bad request"}})

    transport = httpx.MockTransport(handler)
    client = GeminiClient(api_key="REDACTED_CONFIGURE_LOCALLY", model="gemini-2.5-flash", timeout=10, transport=transport)
    with pytest.raises(GeminiError, match="400"):
        client.generate(system_prompt="sys", user_prompt="user")


def test_generate_raises_on_5xx(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": {"message": "service unavailable"}})

    transport = httpx.MockTransport(handler)
    client = GeminiClient(api_key="REDACTED_CONFIGURE_LOCALLY", model="gemini-2.5-flash", timeout=10, transport=transport)
    with pytest.raises(GeminiError, match="503"):
        client.generate(system_prompt="sys", user_prompt="user")


def test_generate_raises_on_invalid_json(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": "not json"}]}}
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    client = GeminiClient(api_key="REDACTED_CONFIGURE_LOCALLY", model="gemini-2.5-flash", timeout=10, transport=transport)
    with pytest.raises(GeminiError, match="JSON"):
        client.generate(system_prompt="sys", user_prompt="user")
```

- [ ] **Step 3: 테스트 실행 — 실패 확인**

```bash
cd backend && python -m pytest tests/test_ai_report_gemini_client.py -v
```

Expected: ImportError on `gemini_client`.

- [ ] **Step 4: 어댑터 구현**

`backend/app/services/ai_report/gemini_client.py`:

```python
"""Gemini API 어댑터 — 표준 generativelanguage REST.

JSON 모드 응답 강제, 4xx/5xx/timeout/JSON 파싱 실패 → GeminiError로 통일.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx


class GeminiError(Exception):
    """Gemini 호출 실패 (4xx, 5xx, timeout, JSON 파싱 실패 등)."""


class GeminiConfigError(Exception):
    """API 키 미설정 등 환경 오류."""


_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


@dataclass
class GeminiClient:
    api_key: str
    model: str = "gemini-2.5-flash"
    timeout: int = 30
    transport: httpx.BaseTransport | None = None  # 테스트용 주입

    def __post_init__(self) -> None:
        if not self.api_key:
            raise GeminiConfigError("GEMINI_API_KEY is not configured")

    def generate(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        url = f"{_BASE_URL}/{self.model}:generateContent"
        params = {"key": self.api_key}
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {"response_mime_type": "application/json"},
        }
        try:
            with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
                resp = client.post(url, params=params, json=payload)
        except httpx.TimeoutException as e:
            raise GeminiError(f"timeout: {e}") from e
        except httpx.HTTPError as e:
            raise GeminiError(f"http error: {e}") from e

        if resp.status_code >= 400:
            raise GeminiError(f"{resp.status_code}: {resp.text[:300]}")

        try:
            data = resp.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text)
        except (KeyError, IndexError, ValueError, json.JSONDecodeError) as e:
            raise GeminiError(f"JSON parse failed: {e}") from e
```

- [ ] **Step 5: 테스트 재실행 — 통과 확인**

```bash
cd backend && python -m pytest tests/test_ai_report_gemini_client.py -v
```

Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/config.py \
        backend/app/services/ai_report/gemini_client.py \
        backend/tests/test_ai_report_gemini_client.py
git commit -m "feat: add Gemini API adapter + config (PHASE 18-5)"
```

---

## Task 6: 단건 생성 서비스 + 테스트

**Files:**
- Create: `backend/app/services/ai_eval_report_service.py`
- Create: `backend/tests/test_ai_eval_report_service.py`

- [ ] **Step 1: 실패 테스트 작성**

`backend/tests/test_ai_eval_report_service.py`:

```python
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.db.models import (
    Department,
    Employee,
    EvalAiReport,
    EvalComprehensive,
    EvalRound,
    JobRank,
    Role,
    User,
    UserRole,
)
from app.services.ai_eval_report_service import (
    BatchInProgressError,
    generate_one_report,
    list_reports_for_round,
)
from app.services.ai_report.gemini_client import GeminiError


@pytest.fixture
def hr_user(db_session):
    role = Role(code="HR_ADMIN", name="인사")
    db_session.add(role)
    db_session.flush()
    user = User(login_id="hr1", password_hash="x", is_active=True)
    db_session.add(user)
    db_session.flush()
    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    db_session.commit()
    return user


@pytest.fixture
def round_with_comp(db_session):
    rnd = EvalRound(year=2026, name="정기", status="IN_PROGRESS")
    db_session.add(rnd)
    db_session.flush()
    dept = Department(name="개발팀", code="DEV")
    rank = JobRank(name="과장", level=3)
    db_session.add_all([dept, rank])
    db_session.flush()
    emp = Employee(emp_no="E001", name="홍길동", dept_id=dept.id, job_rank_id=rank.id)
    db_session.add(emp)
    db_session.flush()
    db_session.add(EvalComprehensive(
        round_id=rnd.id, emp_id=emp.id,
        perf_score=Decimal("85"), comp_score=Decimal("80"), multi_score=Decimal("75"),
        total_score=Decimal("82"), original_grade="A", final_grade="A", is_adjusted=False,
    ))
    db_session.commit()
    return rnd, emp


def _fake_gemini_response():
    return {
        "strengths": "성실함과 책임감",
        "improvements": "발표 스킬",
        "coaching": "주 1회 발표 연습",
        "interview_guide": "최근 도전 사례 질문",
    }


def test_generate_one_report_happy_path(db_session, hr_user, round_with_comp):
    rnd, emp = round_with_comp
    with patch("app.services.ai_eval_report_service._call_gemini", return_value=_fake_gemini_response()):
        report = generate_one_report(db_session, rnd.id, emp.id, generated_by=hr_user.id)
    assert report.status == "SUCCESS"
    assert report.version == 1
    assert report.is_latest is True
    assert report.content_strengths == "성실함과 책임감"
    assert report.total_score == Decimal("82")
    assert report.final_grade == "A"


def test_regenerate_creates_new_version_and_demotes_prev(db_session, hr_user, round_with_comp):
    rnd, emp = round_with_comp
    with patch("app.services.ai_eval_report_service._call_gemini", return_value=_fake_gemini_response()):
        v1 = generate_one_report(db_session, rnd.id, emp.id, generated_by=hr_user.id)
        v2 = generate_one_report(db_session, rnd.id, emp.id, generated_by=hr_user.id)

    db_session.refresh(v1)
    assert v1.is_latest is False
    assert v2.version == 2
    assert v2.is_latest is True


def test_gemini_error_persists_failed_row(db_session, hr_user, round_with_comp):
    rnd, emp = round_with_comp
    with patch(
        "app.services.ai_eval_report_service._call_gemini",
        side_effect=GeminiError("503: service unavailable"),
    ):
        report = generate_one_report(db_session, rnd.id, emp.id, generated_by=hr_user.id)
    assert report.status == "FAILED"
    assert "503" in report.error_message
    assert report.content_strengths is None


def test_comprehensive_missing_raises_value_error(db_session, hr_user):
    rnd = EvalRound(year=2026, name="정기", status="IN_PROGRESS")
    db_session.add(rnd)
    db_session.flush()
    emp = Employee(emp_no="E999", name="유령")
    db_session.add(emp)
    db_session.commit()
    with pytest.raises(ValueError, match="comprehensive"):
        generate_one_report(db_session, rnd.id, emp.id, generated_by=hr_user.id)


def test_list_reports_left_joins_comprehensive(db_session, hr_user, round_with_comp):
    """리포트 미생성 직원도 응답에 포함."""
    rnd, emp = round_with_comp
    rows = list_reports_for_round(db_session, rnd.id)
    assert len(rows) == 1
    assert rows[0]["employee_id"] == emp.id
    assert rows[0]["status"] is None  # 미생성

    with patch("app.services.ai_eval_report_service._call_gemini", return_value=_fake_gemini_response()):
        generate_one_report(db_session, rnd.id, emp.id, generated_by=hr_user.id)
    rows = list_reports_for_round(db_session, rnd.id)
    assert rows[0]["status"] == "SUCCESS"
    assert rows[0]["version"] == 1
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

```bash
cd backend && python -m pytest tests/test_ai_eval_report_service.py -v
```

Expected: ImportError on `app.services.ai_eval_report_service`.

- [ ] **Step 3: 서비스 구현**

`backend/app/services/ai_eval_report_service.py`:

```python
"""AI 평가 리포트 오케스트레이션.

흐름:
1. EvalComprehensive 검증
2. input_builder.build_input
3. PiiMasker로 입력 마스킹
4. Gemini 호출
5. 응답 unmask
6. 버전 관리하며 EvalAiReport INSERT
실패 시 status=FAILED 행 저장.
"""
from __future__ import annotations

import json
import logging
from threading import Lock
from typing import Any

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import (
    Employee,
    EvalAiReport,
    EvalComprehensive,
)
from app.services.ai_report.gemini_client import GeminiClient, GeminiError
from app.services.ai_report.input_builder import build_input
from app.services.ai_report.pii_masker import PiiMasker
from app.services.ai_report.prompts import PROMPT_VERSION, SYSTEM_PROMPT, render_user_prompt

logger = logging.getLogger(__name__)


class BatchInProgressError(Exception):
    """동일 round에 진행 중인 배치가 있을 때."""


_batch_locks: set[int] = set()
_lock_mutex = Lock()


def _call_gemini(system_prompt: str, user_prompt: str) -> dict[str, Any]:
    """Gemini 호출 (테스트에서 monkeypatch 대상)."""
    client = GeminiClient(
        api_key=settings.GEMINI_API_KEY,
        model=settings.GEMINI_MODEL,
        timeout=settings.GEMINI_TIMEOUT_SEC,
    )
    return client.generate(system_prompt=system_prompt, user_prompt=user_prompt)


def _mask_input(
    input_data: dict[str, Any],
    employee_id_to_name: dict[int, str],
) -> tuple[dict[str, Any], dict[str, str]]:
    """입력 dict의 PII 마스킹.

    employee_id_to_name: 모든 직원의 id→name 매핑 (evaluator/observer 식별용).
    """
    masker = PiiMasker(employee_names=list(employee_id_to_name.values()))
    restore: dict[str, str] = {}

    emp = input_data["employee"]
    emp_placeholder, r = masker.mask_identifier(emp["emp_id"], emp["name"], "employee")
    restore.update(r)

    masked_self = []
    for e in input_data["self_evals"]:
        c, r = masker.mask_text(e.get("comment"), existing_restore=restore)
        restore.update(r)
        masked_self.append({**e, "comment": c})

    masked_boss = []
    for e in input_data["boss_evals"]:
        evaluator_id = e["evaluator_id"]
        evaluator_name = employee_id_to_name.get(evaluator_id, f"평가자_{evaluator_id}")
        rater_placeholder, r = masker.mask_identifier(evaluator_id, evaluator_name, "rater")
        restore.update(r)
        c, r = masker.mask_text(e.get("comment"), existing_restore=restore)
        restore.update(r)
        masked_boss.append({**e, "evaluator_placeholder": rater_placeholder, "comment": c})

    masked_sars = []
    for s in input_data["sars"]:
        observer_id = s["observer_id"]
        observer_name = employee_id_to_name.get(observer_id, f"관찰자_{observer_id}")
        observer_placeholder, r = masker.mask_identifier(observer_id, observer_name, "rater")
        restore.update(r)
        masked_situation, r1 = masker.mask_text(s.get("situation"), existing_restore=restore)
        restore.update(r1)
        masked_action, r2 = masker.mask_text(s.get("action"), existing_restore=restore)
        restore.update(r2)
        masked_result, r3 = masker.mask_text(s.get("result"), existing_restore=restore)
        restore.update(r3)
        masked_sars.append({
            **s,
            "observer_placeholder": observer_placeholder,
            "situation": masked_situation,
            "action": masked_action,
            "result": masked_result,
        })

    masked = {
        **input_data,
        "employee_placeholder": emp_placeholder,
        "self_evals": masked_self,
        "boss_evals": masked_boss,
        "sars": masked_sars,
    }
    return masked, restore


def _unmask_response(response: dict[str, Any], restore: dict[str, str]) -> dict[str, Any]:
    return {k: PiiMasker.unmask(v, restore) if isinstance(v, str) else v for k, v in response.items()}


def _employee_id_to_name(db: Session) -> dict[int, str]:
    rows = db.query(Employee.id, Employee.name).filter(Employee.name.isnot(None)).all()
    return {r.id: r.name for r in rows}


def _next_version(db: Session, round_id: int, employee_id: int) -> tuple[int, EvalAiReport | None]:
    prev = (
        db.query(EvalAiReport)
        .filter(EvalAiReport.round_id == round_id, EvalAiReport.employee_id == employee_id)
        .order_by(desc(EvalAiReport.version))
        .first()
    )
    return ((prev.version + 1) if prev else 1), prev


def generate_one_report(
    db: Session,
    round_id: int,
    employee_id: int,
    generated_by: int,
) -> EvalAiReport:
    # 1) 입력 빌드 (comprehensive 없으면 ValueError)
    input_data = build_input(db, round_id=round_id, employee_id=employee_id)

    next_version, prev = _next_version(db, round_id, employee_id)

    try:
        # 2) 마스킹
        masked, restore = _mask_input(input_data, _employee_id_to_name(db))
        # 3) Gemini 호출
        user_prompt = render_user_prompt(masked)
        raw_response = _call_gemini(SYSTEM_PROMPT, user_prompt)
        # 4) 언마스킹
        response = _unmask_response(raw_response, restore)

        if prev is not None:
            prev.is_latest = False
            db.add(prev)

        report = EvalAiReport(
            round_id=round_id,
            employee_id=employee_id,
            version=next_version,
            is_latest=True,
            status="SUCCESS",
            total_score=input_data["header"]["total_score"],
            final_grade=input_data["header"]["final_grade"],
            multi_response_count=input_data["header"]["multi_response_count"],
            multi_included=input_data["header"]["multi_included"],
            content_strengths=response.get("strengths"),
            content_improvements=response.get("improvements"),
            content_coaching=response.get("coaching"),
            content_interview_guide=response.get("interview_guide"),
            model_version=settings.GEMINI_MODEL,
            prompt_version=PROMPT_VERSION,
            generated_by=generated_by,
        )
        db.add(report)
        db.commit()
        db.refresh(report)
        logger.info("ai_report_generated", extra={"round_id": round_id, "emp_id": employee_id, "version": next_version})
        return report
    except (GeminiError, ValueError) as e:
        # FAILED 행도 버전 차감 없이 다음 version으로 저장
        if prev is not None:
            prev.is_latest = False
            db.add(prev)
        report = EvalAiReport(
            round_id=round_id,
            employee_id=employee_id,
            version=next_version,
            is_latest=True,
            status="FAILED",
            error_message=str(e)[:500],
            total_score=input_data["header"]["total_score"],
            final_grade=input_data["header"]["final_grade"],
            multi_response_count=input_data["header"]["multi_response_count"],
            multi_included=input_data["header"]["multi_included"],
            model_version=settings.GEMINI_MODEL,
            prompt_version=PROMPT_VERSION,
            generated_by=generated_by,
        )
        db.add(report)
        db.commit()
        db.refresh(report)
        logger.warning("ai_report_failed", extra={"round_id": round_id, "emp_id": employee_id, "error": str(e)})
        return report


def list_reports_for_round(db: Session, round_id: int) -> list[dict[str, Any]]:
    """EvalComprehensive를 기준으로 left join하여 미생성 직원도 포함."""
    rows = (
        db.query(
            EvalComprehensive.emp_id,
            EvalComprehensive.total_score,
            EvalComprehensive.final_grade,
            Employee.name,
            EvalAiReport.id,
            EvalAiReport.version,
            EvalAiReport.status,
            EvalAiReport.generated_at,
            EvalAiReport.error_message,
        )
        .join(Employee, Employee.id == EvalComprehensive.emp_id)
        .outerjoin(
            EvalAiReport,
            (EvalAiReport.round_id == EvalComprehensive.round_id)
            & (EvalAiReport.employee_id == EvalComprehensive.emp_id)
            & (EvalAiReport.is_latest == True),  # noqa: E712
        )
        .filter(EvalComprehensive.round_id == round_id)
        .all()
    )
    return [
        {
            "employee_id": r.emp_id,
            "employee_name": r.name,
            "total_score": r.total_score,
            "final_grade": r.final_grade,
            "report_id": r.id,
            "version": r.version,
            "status": r.status,
            "generated_at": r.generated_at,
            "error_message": r.error_message,
        }
        for r in rows
    ]
```

- [ ] **Step 4: 테스트 재실행 — 통과 확인**

```bash
cd backend && python -m pytest tests/test_ai_eval_report_service.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ai_eval_report_service.py \
        backend/tests/test_ai_eval_report_service.py
git commit -m "feat: ai_eval_report_service single-report generate + list (PHASE 18-6)"
```

---

## Task 7: 일괄 처리 + Lock + 알림

**Files:**
- Modify: `backend/app/services/ai_eval_report_service.py` (배치 함수 추가)
- Modify: `backend/tests/test_ai_eval_report_service.py` (배치 테스트 추가)

- [ ] **Step 1: 실패 테스트 추가**

`backend/tests/test_ai_eval_report_service.py` 파일 끝에 추가:

```python
from app.db.models import Notification


def test_generate_batch_processes_all_employees(db_session, hr_user, round_with_comp):
    rnd, emp = round_with_comp
    # 두 번째 직원 추가
    emp2 = Employee(emp_no="E002", name="김철수", dept_id=emp.dept_id, job_rank_id=emp.job_rank_id)
    db_session.add(emp2)
    db_session.flush()
    db_session.add(EvalComprehensive(
        round_id=rnd.id, emp_id=emp2.id,
        total_score=Decimal("70"), original_grade="B", final_grade="B", is_adjusted=False,
    ))
    db_session.commit()

    from app.services.ai_eval_report_service import generate_batch

    with patch("app.services.ai_eval_report_service._call_gemini", return_value=_fake_gemini_response()):
        summary = generate_batch(db_session, rnd.id, generated_by=hr_user.id)
    assert summary["total"] == 2
    assert summary["success"] == 2
    assert summary["failed"] == 0


def test_generate_batch_records_failures(db_session, hr_user, round_with_comp):
    rnd, emp = round_with_comp
    from app.services.ai_eval_report_service import generate_batch

    with patch(
        "app.services.ai_eval_report_service._call_gemini",
        side_effect=GeminiError("400: bad request"),
    ):
        summary = generate_batch(db_session, rnd.id, generated_by=hr_user.id)
    assert summary["failed"] == 1
    assert summary["success"] == 0


def test_generate_batch_creates_notification(db_session, hr_user, round_with_comp):
    rnd, _ = round_with_comp
    from app.services.ai_eval_report_service import generate_batch

    with patch("app.services.ai_eval_report_service._call_gemini", return_value=_fake_gemini_response()):
        generate_batch(db_session, rnd.id, generated_by=hr_user.id)
    notif = db_session.query(Notification).filter(Notification.user_id == hr_user.id).first()
    assert notif is not None
    assert "AI 리포트 생성" in notif.message


def test_generate_batch_409_when_in_progress(db_session, hr_user, round_with_comp):
    rnd, _ = round_with_comp
    from app.services.ai_eval_report_service import _batch_locks, generate_batch

    _batch_locks.add(rnd.id)
    try:
        with pytest.raises(BatchInProgressError):
            generate_batch(db_session, rnd.id, generated_by=hr_user.id)
    finally:
        _batch_locks.discard(rnd.id)


def test_generate_batch_400_when_no_comprehensive(db_session, hr_user):
    from app.services.ai_eval_report_service import generate_batch

    rnd = EvalRound(year=2026, name="빈회차", status="IN_PROGRESS")
    db_session.add(rnd)
    db_session.commit()
    with pytest.raises(ValueError, match="no comprehensive"):
        generate_batch(db_session, rnd.id, generated_by=hr_user.id)
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

```bash
cd backend && python -m pytest tests/test_ai_eval_report_service.py -v
```

Expected: ImportError on `generate_batch`.

- [ ] **Step 3: 배치 함수 + 알림 추가**

`backend/app/services/ai_eval_report_service.py` 끝에 추가:

```python
def generate_batch(db: Session, round_id: int, generated_by: int) -> dict[str, int]:
    """회차 내 전 직원에 대해 순차적으로 리포트 생성."""
    from app.db.models import Notification  # local to avoid circular

    # 1) 회차 검증: comprehensive 행 1개 이상
    comp_count = (
        db.query(EvalComprehensive)
        .filter(EvalComprehensive.round_id == round_id)
        .count()
    )
    if comp_count == 0:
        raise ValueError("no comprehensive evaluation for this round")

    # 2) Lock 획득
    with _lock_mutex:
        if round_id in _batch_locks:
            raise BatchInProgressError(f"batch already in progress for round {round_id}")
        _batch_locks.add(round_id)

    try:
        emp_ids = [
            r.emp_id for r in
            db.query(EvalComprehensive.emp_id)
              .filter(EvalComprehensive.round_id == round_id)
              .distinct()
              .all()
        ]
        success = 0
        failed = 0
        for emp_id in emp_ids:
            try:
                report = generate_one_report(db, round_id, emp_id, generated_by=generated_by)
                if report.status == "SUCCESS":
                    success += 1
                else:
                    failed += 1
            except ValueError:
                failed += 1

        # 3) 알림 INSERT
        notif = Notification(
            user_id=generated_by,
            kind="AI_REPORT_BATCH_DONE",
            message=f"AI 리포트 생성 완료: 성공 {success}건 / 실패 {failed}건",
            link=f"/eval/ai-report?round_id={round_id}",
            is_read=False,
        )
        db.add(notif)
        db.commit()

        return {"total": len(emp_ids), "success": success, "failed": failed, "round_id": round_id}
    finally:
        with _lock_mutex:
            _batch_locks.discard(round_id)
```

> **참고**: `Notification` 모델의 실제 필드(`user_id`, `kind`, `message`, `link`, `is_read`)는 `backend/app/db/models.py`의 정의와 일치하는지 import 직전에 확인. 다르면 (예: recipient_id, content) 정의에 맞춰 인자 이름만 교체.

- [ ] **Step 4: 테스트 재실행 — 통과 확인**

```bash
cd backend && python -m pytest tests/test_ai_eval_report_service.py -v
```

Expected: 모든 케이스(이전 5 + 신규 5) PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ai_eval_report_service.py \
        backend/tests/test_ai_eval_report_service.py
git commit -m "feat: ai_eval_report batch with lock + notification (PHASE 18-7)"
```

---

## Task 8: API 라우트 + Pydantic 스키마

**Files:**
- Create: `backend/app/schemas/eval_ai_report.py`
- Create: `backend/app/api/v1/ai_eval_report.py`
- Modify: `backend/app/api/v1/router.py`
- Create: `backend/tests/test_ai_eval_report_api.py`

- [ ] **Step 1: 스키마 작성**

`backend/app/schemas/eval_ai_report.py`:

```python
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class GenerateRequest(BaseModel):
    round_id: int


class GenerateBatchResponse(BaseModel):
    round_id: int
    total: int
    success: int
    failed: int


class AiReportListItem(BaseModel):
    employee_id: int
    employee_name: str | None
    total_score: Decimal | None
    final_grade: str | None
    report_id: int | None
    version: int | None
    status: str | None  # None = 미생성
    generated_at: datetime | None
    error_message: str | None


class AiReportDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    round_id: int
    employee_id: int
    version: int
    is_latest: bool
    status: str
    error_message: str | None
    total_score: Decimal | None
    final_grade: str | None
    multi_response_count: int | None
    multi_included: bool
    content_strengths: str | None
    content_improvements: str | None
    content_coaching: str | None
    content_interview_guide: str | None
    model_version: str
    prompt_version: str
    generated_by: int
    generated_at: datetime


class AiReportHistoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    version: int
    is_latest: bool
    status: str
    generated_by: int
    generated_at: datetime
    model_version: str
    prompt_version: str
```

- [ ] **Step 2: 실패 테스트 작성**

`backend/tests/test_ai_eval_report_api.py`:

```python
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.db.models import (
    Department,
    Employee,
    EvalComprehensive,
    EvalRound,
    JobRank,
)


@pytest.fixture
def round_emp_comp(db_session, admin_user):
    rnd = EvalRound(year=2026, name="정기", status="IN_PROGRESS")
    db_session.add(rnd)
    db_session.flush()
    dept = Department(name="개발팀", code="DEV")
    rank = JobRank(name="과장", level=3)
    db_session.add_all([dept, rank])
    db_session.flush()
    emp = Employee(emp_no="E001", name="홍길동", dept_id=dept.id, job_rank_id=rank.id)
    db_session.add(emp)
    db_session.flush()
    db_session.add(EvalComprehensive(
        round_id=rnd.id, emp_id=emp.id, total_score=Decimal("82"),
        original_grade="A", final_grade="A", is_adjusted=False,
    ))
    db_session.commit()
    return rnd, emp


def _fake_response():
    return {
        "strengths": "성실함",
        "improvements": "발표 스킬",
        "coaching": "주1 발표",
        "interview_guide": "최근 도전 질문",
    }


def test_post_generate_returns_summary(client, auth_headers, round_emp_comp):
    rnd, _ = round_emp_comp
    with patch("app.services.ai_eval_report_service._call_gemini", return_value=_fake_response()):
        resp = client.post(
            "/api/v1/eval/ai-reports/generate",
            json={"round_id": rnd.id},
            headers=auth_headers,
        )
    assert resp.status_code == 202
    body = resp.json()
    assert body["round_id"] == rnd.id
    assert body["total"] == 1
    assert body["success"] == 1


def test_post_generate_400_when_no_comprehensive(client, auth_headers, db_session):
    rnd = EvalRound(year=2026, name="빈", status="IN_PROGRESS")
    db_session.add(rnd)
    db_session.commit()
    resp = client.post(
        "/api/v1/eval/ai-reports/generate",
        json={"round_id": rnd.id},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_post_generate_403_for_non_admin(client, db_session):
    from app.core.security import create_access_token
    from app.db.models import Role, User, UserRole
    role = Role(code="EMPLOYEE", name="직원")
    db_session.add(role)
    db_session.flush()
    user = User(login_id="emp", password_hash="x", is_active=True)
    db_session.add(user)
    db_session.flush()
    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    db_session.commit()
    token = create_access_token(str(user.id), extra={"roles": ["EMPLOYEE"]})

    resp = client.post(
        "/api/v1/eval/ai-reports/generate",
        json={"round_id": 1},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_get_list_returns_left_joined_rows(client, auth_headers, round_emp_comp):
    rnd, _ = round_emp_comp
    resp = client.get(
        f"/api/v1/eval/ai-reports?round_id={rnd.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["status"] is None  # 미생성


def test_post_generate_individual(client, auth_headers, round_emp_comp):
    rnd, emp = round_emp_comp
    with patch("app.services.ai_eval_report_service._call_gemini", return_value=_fake_response()):
        resp = client.post(
            f"/api/v1/eval/ai-reports/generate/{emp.id}",
            json={"round_id": rnd.id},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "SUCCESS"
    assert body["version"] == 1


def test_get_history_returns_versions(client, auth_headers, round_emp_comp):
    rnd, emp = round_emp_comp
    with patch("app.services.ai_eval_report_service._call_gemini", return_value=_fake_response()):
        client.post(f"/api/v1/eval/ai-reports/generate/{emp.id}",
                    json={"round_id": rnd.id}, headers=auth_headers)
        client.post(f"/api/v1/eval/ai-reports/generate/{emp.id}",
                    json={"round_id": rnd.id}, headers=auth_headers)
    resp = client.get(
        f"/api/v1/eval/ai-reports/employees/{emp.id}/history?round_id={rnd.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    versions = resp.json()
    assert len(versions) == 2
    assert versions[0]["version"] == 2  # 최신부터
    assert versions[0]["is_latest"] is True
    assert versions[1]["is_latest"] is False
```

- [ ] **Step 3: 라우트 작성**

`backend/app/api/v1/ai_eval_report.py`:

```python
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_roles
from app.db.models import EvalAiReport, User
from app.db.session import get_db
from app.schemas.eval_ai_report import (
    AiReportDetail,
    AiReportHistoryItem,
    AiReportListItem,
    GenerateBatchResponse,
    GenerateRequest,
)
from app.services.ai_eval_report_service import (
    BatchInProgressError,
    generate_batch,
    generate_one_report,
    list_reports_for_round,
)

router = APIRouter(prefix="/eval/ai-reports", tags=["eval-ai-report"])


@router.post(
    "/generate",
    response_model=GenerateBatchResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def generate_batch_route(
    payload: GenerateRequest,
    current_user: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
    db: Session = Depends(get_db),
):
    try:
        summary = generate_batch(db, payload.round_id, generated_by=current_user.id)
    except BatchInProgressError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return GenerateBatchResponse(**summary)


@router.post("/generate/{employee_id}", response_model=AiReportDetail)
def generate_one_route(
    employee_id: int,
    payload: GenerateRequest,
    current_user: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
    db: Session = Depends(get_db),
):
    try:
        report = generate_one_report(
            db, payload.round_id, employee_id, generated_by=current_user.id
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return AiReportDetail.model_validate(report)


@router.get("", response_model=list[AiReportListItem])
def list_route(
    round_id: int = Query(...),
    _: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
    db: Session = Depends(get_db),
):
    return list_reports_for_round(db, round_id)


@router.get("/{report_id}", response_model=AiReportDetail)
def detail_route(
    report_id: int,
    _: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
    db: Session = Depends(get_db),
):
    report = db.query(EvalAiReport).filter(EvalAiReport.id == report_id).first()
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="report not found")
    return AiReportDetail.model_validate(report)


@router.get(
    "/employees/{employee_id}/history",
    response_model=list[AiReportHistoryItem],
)
def history_route(
    employee_id: int,
    round_id: int = Query(...),
    _: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(EvalAiReport)
        .filter(
            EvalAiReport.round_id == round_id,
            EvalAiReport.employee_id == employee_id,
        )
        .order_by(desc(EvalAiReport.version))
        .all()
    )
    return [AiReportHistoryItem.model_validate(r) for r in rows]


@router.get(
    "/employees/{employee_id}/versions/{version}",
    response_model=AiReportDetail,
)
def version_detail_route(
    employee_id: int,
    version: int,
    round_id: int = Query(...),
    _: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
    db: Session = Depends(get_db),
):
    report = (
        db.query(EvalAiReport)
        .filter(
            EvalAiReport.round_id == round_id,
            EvalAiReport.employee_id == employee_id,
            EvalAiReport.version == version,
        )
        .first()
    )
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="version not found")
    return AiReportDetail.model_validate(report)
```

- [ ] **Step 4: router.py에 등록**

`backend/app/api/v1/router.py`에 import + include:

```python
from app.api.v1.ai_eval_report import router as ai_eval_report_router
# ...
api_router.include_router(ai_eval_report_router)
```

- [ ] **Step 5: 테스트 실행 — 통과 확인**

```bash
cd backend && python -m pytest tests/test_ai_eval_report_api.py -v
```

Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/eval_ai_report.py \
        backend/app/api/v1/ai_eval_report.py \
        backend/app/api/v1/router.py \
        backend/tests/test_ai_eval_report_api.py
git commit -m "feat: ai_eval_report API routes + schemas (PHASE 18-8)"
```

---

## Task 9: 다면 익명성 회귀 테스트 케이스 추가

**Files:**
- Modify: `backend/tests/test_multi_anonymity.py`

- [ ] **Step 1: 케이스 2개 추가**

`backend/tests/test_multi_anonymity.py` 파일 끝에 추가:

```python
def test_ai_report_input_excludes_evaluator_id():
    """입력 빌드 결과에 어떤 evaluator_id 키도 들어가지 않음 (다면 익명성)."""
    import json
    from app.services.ai_report.input_builder import build_input  # noqa: F401

    # build_input이 반환하는 dict에 'evaluator_id' 키가 multi 관련 어디에도 없는지
    # 정적으로 검증: input_builder.py 소스에 multi 쪽 evaluator_id 참조 없음
    src = open("app/services/ai_report/input_builder.py", encoding="utf-8").read()
    assert "MultiEvalResponseLog" not in src, "log 테이블은 ID만 보유 — 입력에 포함 금지"
    # multi_summary는 indicator/avg_score/response_count만 가짐
    assert "evaluator_id" not in src.split("multi_summary")[1].split("perf_results")[0]


def test_ai_report_excludes_indicator_with_response_count_lt_3(db_session):
    """response_count<3인 indicator는 build_input 결과의 multi_summary에서 제외."""
    from decimal import Decimal
    from app.db.models import (
        Department, Employee, EvalComprehensive, EvalRound,
        JobRank, MultiEvalIndicator, MultiEvalResult,
    )
    from app.services.ai_report.input_builder import build_input

    rnd = EvalRound(year=2026, name="정기", status="IN_PROGRESS")
    db_session.add(rnd)
    db_session.flush()
    dept = Department(name="DEV", code="D"); rank = JobRank(name="대리", level=2)
    db_session.add_all([dept, rank]); db_session.flush()
    emp = Employee(emp_no="E1", name="A", dept_id=dept.id, job_rank_id=rank.id)
    db_session.add(emp); db_session.flush()
    db_session.add(EvalComprehensive(
        round_id=rnd.id, emp_id=emp.id, total_score=Decimal("70"),
        original_grade="B", final_grade="B", is_adjusted=False,
    ))
    ind = MultiEvalIndicator(round_id=rnd.id, name="협업", weight=Decimal("100"))
    db_session.add(ind); db_session.flush()
    db_session.add(MultiEvalResult(
        round_id=rnd.id, evaluatee_id=emp.id, indicator_id=ind.id,
        avg_score=Decimal("4"), response_count=2,
    ))
    db_session.commit()

    result = build_input(db_session, round_id=rnd.id, employee_id=emp.id)
    assert result["multi_summary"] == []
    assert result["header"]["multi_included"] is False
```

- [ ] **Step 2: 테스트 실행**

```bash
cd backend && python -m pytest tests/test_multi_anonymity.py -v
```

Expected: 기존 케이스 + 신규 2개 PASS.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_multi_anonymity.py
git commit -m "test: AI 리포트 다면 익명성 회귀 케이스 2개 추가 (PHASE 18-9)"
```

---

## Task 10: FE API 클라이언트 + 훅

**Files:**
- Create: `frontend/src/api/aiReport.ts`

- [ ] **Step 1: API 클라이언트 + 훅 작성**

`frontend/src/api/aiReport.ts`:

```typescript
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { axios } from "./client";

export type AiReportListItem = {
  employee_id: number;
  employee_name: string | null;
  total_score: string | null;
  final_grade: string | null;
  report_id: number | null;
  version: number | null;
  status: "PENDING" | "SUCCESS" | "FAILED" | null;
  generated_at: string | null;
  error_message: string | null;
};

export type AiReportDetail = {
  id: number;
  round_id: number;
  employee_id: number;
  version: number;
  is_latest: boolean;
  status: "PENDING" | "SUCCESS" | "FAILED";
  error_message: string | null;
  total_score: string | null;
  final_grade: string | null;
  multi_response_count: number | null;
  multi_included: boolean;
  content_strengths: string | null;
  content_improvements: string | null;
  content_coaching: string | null;
  content_interview_guide: string | null;
  model_version: string;
  prompt_version: string;
  generated_by: number;
  generated_at: string;
};

export type AiReportHistoryItem = {
  id: number;
  version: number;
  is_latest: boolean;
  status: "PENDING" | "SUCCESS" | "FAILED";
  generated_by: number;
  generated_at: string;
  model_version: string;
  prompt_version: string;
};

export type GenerateBatchResponse = {
  round_id: number;
  total: number;
  success: number;
  failed: number;
};

const BASE = "/api/v1/eval/ai-reports";

export function useAiReports(roundId: number | null) {
  return useQuery({
    queryKey: ["ai-reports", roundId],
    queryFn: async () => {
      const { data } = await axios.get<AiReportListItem[]>(`${BASE}?round_id=${roundId}`);
      return data;
    },
    enabled: roundId != null,
  });
}

export function useAiReportDetail(reportId: number | null) {
  return useQuery({
    queryKey: ["ai-report", reportId],
    queryFn: async () => {
      const { data } = await axios.get<AiReportDetail>(`${BASE}/${reportId}`);
      return data;
    },
    enabled: reportId != null,
  });
}

export function useAiReportHistory(roundId: number | null, employeeId: number | null) {
  return useQuery({
    queryKey: ["ai-report-history", roundId, employeeId],
    queryFn: async () => {
      const { data } = await axios.get<AiReportHistoryItem[]>(
        `${BASE}/employees/${employeeId}/history?round_id=${roundId}`,
      );
      return data;
    },
    enabled: roundId != null && employeeId != null,
  });
}

export function useGenerateBatch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (roundId: number) => {
      const { data } = await axios.post<GenerateBatchResponse>(`${BASE}/generate`, {
        round_id: roundId,
      });
      return data;
    },
    onSuccess: (_, roundId) => {
      qc.invalidateQueries({ queryKey: ["ai-reports", roundId] });
    },
  });
}

export function useGenerateOne() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (params: { roundId: number; employeeId: number }) => {
      const { data } = await axios.post<AiReportDetail>(
        `${BASE}/generate/${params.employeeId}`,
        { round_id: params.roundId },
      );
      return data;
    },
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: ["ai-reports", vars.roundId] });
      qc.invalidateQueries({ queryKey: ["ai-report-history", vars.roundId, vars.employeeId] });
    },
  });
}
```

- [ ] **Step 2: 타입 체크**

```bash
cd frontend && npx tsc --noEmit
```

Expected: errors 0.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/aiReport.ts
git commit -m "feat(fe): aiReport API hooks (PHASE 18-10)"
```

---

## Task 11: FE 단일 페이지 `/eval/ai-report`

**Files:**
- Create: `frontend/src/pages/eval/AiEvalReportPage.tsx`

- [ ] **Step 1: 페이지 컴포넌트 작성**

`frontend/src/pages/eval/AiEvalReportPage.tsx`:

```tsx
import { useMemo, useState } from "react";
import { Alert, Badge, Button, Card, Descriptions, Modal, Select, Space, Table, Typography, message } from "antd";
import { useEvalRounds } from "../../api/evalRound";
import {
  useAiReportDetail,
  useAiReports,
  useGenerateBatch,
  useGenerateOne,
} from "../../api/aiReport";

const { Title, Paragraph } = Typography;

export default function AiEvalReportPage() {
  const [roundId, setRoundId] = useState<number | null>(null);
  const [selectedEmpId, setSelectedEmpId] = useState<number | null>(null);
  const [selectedReportId, setSelectedReportId] = useState<number | null>(null);

  const roundsQuery = useEvalRounds();
  const reportsQuery = useAiReports(roundId);
  const detailQuery = useAiReportDetail(selectedReportId);
  const batchMutation = useGenerateBatch();
  const oneMutation = useGenerateOne();

  const onBatch = () => {
    if (roundId == null) return;
    Modal.confirm({
      title: "회차 전체 직원에 대해 AI 리포트를 생성합니다",
      content: "외부 LLM(Gemini) 호출이 발생합니다. 진행할까요?",
      okText: "생성",
      cancelText: "취소",
      onOk: async () => {
        try {
          const summary = await batchMutation.mutateAsync(roundId);
          message.success(`완료: 성공 ${summary.success}건 / 실패 ${summary.failed}건`);
        } catch (e: unknown) {
          message.error(e instanceof Error ? e.message : "생성 실패");
        }
      },
    });
  };

  const columns = useMemo(
    () => [
      { title: "직원", dataIndex: "employee_name", key: "employee_name" },
      { title: "종합 점수", dataIndex: "total_score", key: "total_score" },
      { title: "등급", dataIndex: "final_grade", key: "final_grade" },
      {
        title: "버전", dataIndex: "version", key: "version",
        render: (v: number | null) => (v == null ? "-" : `v${v}`),
      },
      {
        title: "상태",
        dataIndex: "status",
        key: "status",
        render: (s: string | null) => {
          if (s == null) return <Badge status="default" text="미생성" />;
          if (s === "SUCCESS") return <Badge status="success" text="완료" />;
          if (s === "FAILED") return <Badge status="error" text="실패" />;
          return <Badge status="processing" text="진행중" />;
        },
      },
      {
        title: "액션",
        key: "actions",
        render: (_: unknown, row: { employee_id: number; report_id: number | null }) => (
          <Space>
            {row.report_id && (
              <Button size="small" onClick={() => {
                setSelectedEmpId(row.employee_id);
                setSelectedReportId(row.report_id);
              }}>열람</Button>
            )}
            <Button
              size="small"
              loading={oneMutation.isPending}
              onClick={async () => {
                if (roundId == null) return;
                await oneMutation.mutateAsync({ roundId, employeeId: row.employee_id });
                message.success("생성 완료");
              }}
            >재생성</Button>
          </Space>
        ),
      },
    ],
    [oneMutation, roundId],
  );

  const detail = detailQuery.data;

  return (
    <div style={{ padding: 24 }}>
      <Title level={3}>AI 인사평가 리포트</Title>

      <Card size="small" style={{ marginBottom: 16 }}>
        <Space>
          <Select
            style={{ minWidth: 240 }}
            placeholder="회차 선택"
            options={(roundsQuery.data ?? []).map((r) => ({
              value: r.id,
              label: `${r.year}년 ${r.name}`,
            }))}
            value={roundId ?? undefined}
            onChange={(v) => { setRoundId(v); setSelectedReportId(null); }}
          />
          <Button
            type="primary"
            disabled={roundId == null}
            loading={batchMutation.isPending}
            onClick={onBatch}
          >회차 일괄 생성</Button>
        </Space>
      </Card>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <Card size="small" title="직원 목록">
          <Table
            rowKey="employee_id"
            size="small"
            loading={reportsQuery.isLoading}
            dataSource={reportsQuery.data ?? []}
            columns={columns}
            pagination={{ pageSize: 20 }}
          />
        </Card>

        <Card size="small" title={detail ? `리포트 v${detail.version}` : "리포트"}>
          {!detail && <Paragraph type="secondary">왼쪽 테이블에서 "열람"을 누르세요.</Paragraph>}
          {detail && detail.status === "FAILED" && (
            <Alert
              type="error"
              message="생성 실패"
              description={detail.error_message}
              showIcon
            />
          )}
          {detail && detail.status === "SUCCESS" && (
            <Space direction="vertical" style={{ width: "100%" }}>
              <Descriptions size="small" column={2} bordered>
                <Descriptions.Item label="종합 점수">{detail.total_score}</Descriptions.Item>
                <Descriptions.Item label="등급">{detail.final_grade}</Descriptions.Item>
                <Descriptions.Item label="다면 응답">{detail.multi_response_count ?? "-"}</Descriptions.Item>
                <Descriptions.Item label="다면 포함">{detail.multi_included ? "Y" : "N"}</Descriptions.Item>
                <Descriptions.Item label="모델">{detail.model_version}</Descriptions.Item>
                <Descriptions.Item label="프롬프트">{detail.prompt_version}</Descriptions.Item>
              </Descriptions>
              <Card size="small" type="inner" title="강점">
                <Paragraph>{detail.content_strengths}</Paragraph>
              </Card>
              <Card size="small" type="inner" title="개선 영역">
                <Paragraph>{detail.content_improvements}</Paragraph>
              </Card>
              <Card size="small" type="inner" title="코칭 포인트">
                <Paragraph>{detail.content_coaching}</Paragraph>
              </Card>
              <Card size="small" type="inner" title="면담 가이드">
                <Paragraph>{detail.content_interview_guide}</Paragraph>
              </Card>
            </Space>
          )}
        </Card>
      </div>
    </div>
  );
}
```

> **참고**: 위 페이지가 사용하는 `useEvalRounds` 훅이 `frontend/src/api/evalRound.ts`(또는 유사) 위치에 이미 존재한다고 가정. 만약 import 경로가 다르면 (`../../api/evalRounds` 등) 실제 파일에 맞춰 수정.

- [ ] **Step 2: 타입 체크**

```bash
cd frontend && npx tsc --noEmit
```

Expected: errors 0 (단, `useEvalRounds` import 경로 미확인 시 실패할 수 있음 — 이때 실제 회차 hook 파일을 grep으로 찾아 import 경로 교체).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/eval/AiEvalReportPage.tsx
git commit -m "feat(fe): AiEvalReportPage component (PHASE 18-11)"
```

---

## Task 12: 라우트 + 메뉴 + Role 가드

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/shell/menuRegistry.ts`
- Modify: `frontend/src/shell/SideNav.tsx`

- [ ] **Step 1: `App.tsx`에 lazy 라우트 추가**

`frontend/src/App.tsx`에서 기존 lazy import 블록을 찾아 추가:

```tsx
const AiEvalReportPage = lazy(() => import("./pages/eval/AiEvalReportPage"));
```

`<Routes>` 안에 추가 (인사평가 라우트들 근처):

```tsx
<Route path="/eval/ai-report" element={<AiEvalReportPage />} />
```

- [ ] **Step 2: menuRegistry에 `roles` 필드 추가**

`frontend/src/shell/menuRegistry.ts`의 `MenuLeaf` 타입 수정:

```ts
export type Role = "SYSTEM_ADMIN" | "HR_ADMIN" | "DEPT_HEAD" | "EMPLOYEE";

export type MenuLeaf = {
  path: string;
  label: string;
  icon?: string;
  keywords?: string[];
  /** 노출 가능한 role 목록. 미지정 시 모두 노출 (하위호환). */
  roles?: Role[];
};
```

같은 파일 `eval-comp-final` 그룹 items 배열 마지막에 추가:

```ts
{
  path: "/eval/ai-report",
  label: "AI 리포트",
  icon: "Solution",
  keywords: ["ai", "report", "리포트", "보조"],
  roles: ["SYSTEM_ADMIN", "HR_ADMIN"],
},
```

- [ ] **Step 3: SideNav에 role 필터 추가**

`frontend/src/shell/SideNav.tsx`에서 메뉴 렌더링 시 사용자 role과 비교 (구체 변경은 기존 SideNav 구조에 따름).

핵심 패턴:

```ts
import { useAuth } from "../store/auth";  // 기존 훅

const userRoles = useAuth().user?.roles ?? [];
const visibleItems = group.items.filter(
  (item) => !item.roles || item.roles.some((r) => userRoles.includes(r)),
);
```

- [ ] **Step 4: 타입 체크 + 빌드 검증**

```bash
cd frontend && npx tsc --noEmit && npm run build
```

Expected: errors 0, build success.

- [ ] **Step 5: 브라우저 검증**

1. BE 재시작: `cd backend && uvicorn app.main:app --reload`
2. FE 시작: `cd frontend && npm run dev`
3. HR_ADMIN으로 로그인 → 인사평가 → 종합평가 그룹에 "AI 리포트" 노출 확인
4. EMPLOYEE로 로그인 → "AI 리포트" 메뉴 미노출 확인
5. EMPLOYEE 상태에서 직접 `/eval/ai-report` 접속 → API 403 확인

- [ ] **Step 6: Commit**

```bash
git add frontend/src/App.tsx \
        frontend/src/shell/menuRegistry.ts \
        frontend/src/shell/SideNav.tsx
git commit -m "feat(fe): /eval/ai-report route + menu with role guard (PHASE 18-12)"
```

---

## Task 13: FE 페이지 테스트 (Vitest + RTL)

**Files:**
- Create: `frontend/src/pages/eval/__tests__/AiEvalReportPage.test.tsx`

- [ ] **Step 1: 테스트 작성**

`frontend/src/pages/eval/__tests__/AiEvalReportPage.test.tsx`:

```tsx
import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import AiEvalReportPage from "../AiEvalReportPage";

vi.mock("../../../api/evalRound", () => ({
  useEvalRounds: () => ({
    data: [{ id: 1, year: 2026, name: "정기" }],
    isLoading: false,
  }),
}));

const mockReports = vi.hoisted(() => ({
  list: [
    {
      employee_id: 10, employee_name: "홍길동",
      total_score: "82", final_grade: "A",
      report_id: null, version: null, status: null,
      generated_at: null, error_message: null,
    },
  ],
}));

vi.mock("../../../api/aiReport", () => ({
  useAiReports: () => ({ data: mockReports.list, isLoading: false }),
  useAiReportDetail: () => ({ data: undefined }),
  useGenerateBatch: () => ({ mutateAsync: vi.fn().mockResolvedValue({ success: 1, failed: 0 }), isPending: false }),
  useGenerateOne: () => ({ mutateAsync: vi.fn().mockResolvedValue({}), isPending: false }),
}));

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AiEvalReportPage />
    </QueryClientProvider>,
  );
}

describe("AiEvalReportPage", () => {
  it("회차 선택 후 직원 목록을 렌더한다", async () => {
    renderPage();
    const select = screen.getByRole("combobox");
    await userEvent.click(select);
    await userEvent.click(await screen.findByText("2026년 정기"));
    await waitFor(() => {
      expect(screen.getByText("홍길동")).toBeInTheDocument();
      expect(screen.getByText("미생성")).toBeInTheDocument();
    });
  });

  it("일괄 생성 버튼 클릭 시 confirm 모달이 뜬다", async () => {
    renderPage();
    const select = screen.getByRole("combobox");
    await userEvent.click(select);
    await userEvent.click(await screen.findByText("2026년 정기"));
    await userEvent.click(screen.getByRole("button", { name: /회차 일괄 생성/ }));
    expect(await screen.findByText(/외부 LLM/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: 테스트 실행**

```bash
cd frontend && npx vitest run src/pages/eval/__tests__/AiEvalReportPage.test.tsx
```

Expected: 2 passed.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/eval/__tests__/AiEvalReportPage.test.tsx
git commit -m "test(fe): AiEvalReportPage rendering + batch confirm (PHASE 18-13)"
```

---

## Task 14: 문서 업데이트 + .env.example

**Files:**
- Modify: `docs/EVAL_MODULE.md`
- Modify or Create: `backend/.env.example`

- [ ] **Step 1: EVAL_MODULE.md에 §9 추가**

`docs/EVAL_MODULE.md` 파일 끝에 추가:

```markdown
---

## 9. AI 인사평가 리포트 (PHASE 18)

Gemini 2.5 Flash로 생성하는 HR 보조 리포트. 평가자가 아닌 **데이터 요약** 포지션.

### 테이블

| 테이블 | 역할 |
|---|---|
| `insa_eval_ai_report` | 회차×직원×버전 단위 리포트 (append-only, `is_latest` 플래그) |

### API

| Method | Path | Role | 설명 |
|---|---|---|---|
| POST | `/eval/ai-reports/generate` | HR/SYS | 회차 일괄 생성 (BackgroundTasks) |
| POST | `/eval/ai-reports/generate/{employee_id}` | HR/SYS | 개별 재생성 (동기) |
| GET | `/eval/ai-reports?round_id=N` | HR/SYS | latest 목록 (left join — 미생성 직원 포함) |
| GET | `/eval/ai-reports/{id}` | HR/SYS | 단건 조회 |
| GET | `/eval/ai-reports/employees/{emp_id}/history?round_id=N` | HR/SYS | 버전 이력 |
| GET | `/eval/ai-reports/employees/{emp_id}/versions/{v}?round_id=N` | HR/SYS | 특정 버전 |

### 보안

- 모든 외부 호출은 PII 마스킹(사번·이름·코멘트 인명) 후 송신.
- 다면평가 익명성: `MultiEvalResult.response_count<3` 인 indicator는 입력에서 제외.
- 리포트 열람·생성 모두 HR_ADMIN/SYSTEM_ADMIN 전용 (라우트 + FE 메뉴 이중 가드).
- `error_message`는 마스킹된 상태로만 저장.

### 환경변수

```
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.5-flash
GEMINI_TIMEOUT_SEC=30
GEMINI_DAILY_BUDGET_CALLS=2000  # 미강제, 추후 도입
```
```

- [ ] **Step 2: .env.example 업데이트 또는 생성**

`backend/.env.example`이 있으면 끝에 추가, 없으면 신규:

```bash
# Gemini API (PHASE 18)
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash
GEMINI_TIMEOUT_SEC=30
GEMINI_DAILY_BUDGET_CALLS=2000
```

- [ ] **Step 3: 전체 회귀 테스트**

```bash
cd backend && python -m pytest -q
```

Expected: all pass (기존 + PHASE 18 신규 다 통과).

```bash
cd frontend && npx tsc --noEmit && npx vitest run
```

Expected: type 에러 0, 테스트 all pass.

- [ ] **Step 4: Commit**

```bash
git add docs/EVAL_MODULE.md backend/.env.example
git commit -m "docs: AI 리포트 §9 + .env.example 업데이트 (PHASE 18-14)"
```

---

## Task 15: E2E 검증 (수동)

**Files:** (변경 없음 — 수동 검증)

- [ ] **Step 1: 백엔드 재시작**

```bash
cd backend && uvicorn app.main:app --reload
```

- [ ] **Step 2: 프론트 시작**

```bash
cd frontend && npm run dev
```

- [ ] **Step 3: HR_ADMIN으로 로그인 → 인사평가 → 종합평가 → AI 리포트**

- [ ] **Step 4: 회차 선택 → "회차 일괄 생성" 클릭 → 확인 모달 → 생성 진행**

성공 시 메시지: `"완료: 성공 N건 / 실패 M건"`. 직원 행 status 배지 갱신.

- [ ] **Step 5: 직원 행 "열람" 클릭 → 우측 패널에 4섹션 + 정량 헤더 노출**

- [ ] **Step 6: "재생성" 클릭 → 새 버전 생성, version 컬럼 +1 확인**

- [ ] **Step 7: 종합평가 미완료 회차 선택 시 "회차 일괄 생성" → 400 에러 안내 확인**

- [ ] **Step 8: EMPLOYEE 계정으로 재로그인 → 메뉴에 "AI 리포트" 미노출 확인**

- [ ] **Step 9: EMPLOYEE 상태 직접 URL 접속 시 API 403 확인**

- [ ] **Step 10: 알림 벨 → "AI 리포트 생성 완료" 알림 표시 확인**

E2E 결과 정상이면 PHASE 18 완료. 이상 있으면 해당 단계로 돌아가 수정 후 재검증.

---

## 완료 후 체크리스트

- [ ] 모든 단계 커밋 완료
- [ ] BE 회귀 테스트 PASS
- [ ] FE 타입 + 테스트 PASS
- [ ] 다면 익명성 회귀 케이스 추가됨
- [ ] HR_ADMIN/SYS만 메뉴/API 접근 가능
- [ ] `.env.example`에 Gemini 변수 명시
- [ ] `docs/EVAL_MODULE.md` §9 업데이트
- [ ] 브라우저 E2E 시나리오 8개 모두 통과
