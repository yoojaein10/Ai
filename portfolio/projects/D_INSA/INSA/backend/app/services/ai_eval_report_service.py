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


def _employee_id_to_name(db: Session) -> dict[int, str]:
    rows = db.query(Employee.id, Employee.name_ko).filter(Employee.name_ko.isnot(None)).all()
    return {r.id: r.name_ko for r in rows}


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
        masked, restore = _mask_input(input_data, _employee_id_to_name(db))
        user_prompt = render_user_prompt(masked)
        raw_response = _call_gemini(SYSTEM_PROMPT, user_prompt)
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
            type="AI_REPORT_BATCH_DONE",
            title="AI 리포트 일괄 생성 완료",
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


def list_reports_for_round(db: Session, round_id: int) -> list[dict[str, Any]]:
    """EvalComprehensive를 기준으로 left join하여 미생성 직원도 포함."""
    rows = (
        db.query(
            EvalComprehensive.emp_id,
            EvalComprehensive.total_score,
            EvalComprehensive.final_grade,
            Employee.name_ko,
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
            "employee_name": r.name_ko,
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
