"""인사평가 모듈 시드 스크립트 (idempotent).

현재 연도 평가 회차 1개 (status=IN_PROGRESS), 4단계 일정,
KPI 5개, 역량지표 8개 + 행동지표 5레벨, 다면지표 4개,
기존 직원 7명 기준 평가자 매핑(BOSS/PEER/SUBORDINATE),
보정집단 3개(직급별), insa_eval_setting (weight 40/30/30, S/A/B/C/D 등급).

실행:
    python scripts/seed_eval.py
    python scripts/seed_eval.py --cleanup
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy.orm import Session

from app.db.models import (
    CompBehavior,
    CompIndicator,
    Employee,
    EvalApprover,
    EvalCalibrationGroup,
    EvalCalibrationMember,
    EvalRound,
    EvalSchedule,
    EvalSetting,
    MultiEvalIndicator,
    PerfKpi,
    User,
)
from app.db.session import SessionLocal

CURRENT_YEAR = date.today().year
ROUND_NAME = f"{CURRENT_YEAR}년 정기평가"

KPI_SAMPLES = [
    ("매출 달성", "재무", 30),
    ("프로젝트 납기 준수", "내부", 25),
    ("품질 지표", "내부", 20),
    ("후배 양성", "학습", 15),
    ("자기 개발", "학습", 10),
]

COMP_INDICATORS = [
    ("LEADERSHIP", "리더십", "팀을 동기부여하고 방향을 제시"),
    ("COLLAB", "협업", "타 부서/동료와 효과적으로 협력"),
    ("EXECUTION", "실행력", "계획을 구체적 결과물로 만들어냄"),
    ("INNOVATION", "혁신", "기존 방식을 개선하고 새로운 시도"),
    ("CUSTOMER", "고객지향", "내·외부 고객 관점에서 사고"),
    ("EXPERTISE", "전문성", "직무 지식과 기술의 깊이"),
    ("COMMUNICATION", "커뮤니케이션", "명확하고 효과적인 의사 전달"),
    ("OWNERSHIP", "주인의식", "결과에 책임을 지고 끝까지 완수"),
]

BEHAVIOR_BY_LEVEL = {
    1: "기대 수준에 미달, 지속적 지도 필요",
    2: "기본 수준만 수행, 자율성 부족",
    3: "기대 수준 충족, 일관된 수행",
    4: "기대 수준 초과, 동료에게 모범",
    5: "탁월, 조직 전체에 영향",
}

MULTI_INDICATORS = [
    ("협업 태도", "동료와의 협력 자세"),
    ("커뮤니케이션", "명확한 의사 표현과 경청"),
    ("책임감", "맡은 일을 끝까지 완수"),
    ("성장 가능성", "학습과 발전에 대한 의지"),
]

WEIGHT_CONFIG = {"perf": 40, "comp": 30, "multi": 30}
GRADE_CRITERIA = [
    {"grade": "S", "min": 90, "max": 100, "default_ratio": 10},
    {"grade": "A", "min": 80, "max": 90, "default_ratio": 20},
    {"grade": "B", "min": 70, "max": 80, "default_ratio": 40},
    {"grade": "C", "min": 60, "max": 70, "default_ratio": 20},
    {"grade": "D", "min": 0, "max": 60, "default_ratio": 10},
]


def _get_or_create_round(db: Session) -> EvalRound:
    r = (
        db.query(EvalRound)
        .filter(EvalRound.year == CURRENT_YEAR, EvalRound.name == ROUND_NAME)
        .first()
    )
    if r is not None:
        return r
    r = EvalRound(
        year=CURRENT_YEAR,
        name=ROUND_NAME,
        start_date=date(CURRENT_YEAR, 1, 1),
        end_date=date(CURRENT_YEAR, 12, 31),
        status="IN_PROGRESS",
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    print(f"[round] created id={r.id}")
    return r


def _seed_schedules(db: Session, round_id: int) -> None:
    if db.query(EvalSchedule).filter(EvalSchedule.round_id == round_id).first():
        print("[schedules] skip (exists)")
        return
    stages = [
        ("TARGET", date(CURRENT_YEAR, 1, 1), date(CURRENT_YEAR, 2, 28)),
        ("MID", date(CURRENT_YEAR, 6, 1), date(CURRENT_YEAR, 7, 31)),
        ("FINAL", date(CURRENT_YEAR, 11, 1), date(CURRENT_YEAR, 12, 15)),
        ("COMPREHENSIVE", date(CURRENT_YEAR, 12, 16), date(CURRENT_YEAR, 12, 31)),
    ]
    for stage, s, e in stages:
        db.add(EvalSchedule(round_id=round_id, stage=stage, start_date=s, end_date=e))
    db.commit()
    print(f"[schedules] created {len(stages)}")


def _seed_kpis(db: Session, round_id: int) -> None:
    if db.query(PerfKpi).filter(PerfKpi.round_id == round_id).first():
        print("[kpi] skip (exists)")
        return
    for idx, (name, perspective, weight) in enumerate(KPI_SAMPLES, start=1):
        db.add(
            PerfKpi(
                round_id=round_id,
                code=f"KPI{idx:02d}",
                name=name,
                weight=weight,
                perspective=perspective,
                measure_type="혼합",
            )
        )
    db.commit()
    print(f"[kpi] created {len(KPI_SAMPLES)}")


def _seed_comp_indicators(db: Session) -> None:
    existing = {
        i.code
        for i in db.query(CompIndicator).filter(CompIndicator.year == CURRENT_YEAR).all()
    }
    created_inds = 0
    created_behaviors = 0
    for code, name, desc in COMP_INDICATORS:
        if code in existing:
            continue
        ind = CompIndicator(
            year=CURRENT_YEAR, code=code, name=name, description=desc, weight=12.5
        )
        db.add(ind)
        db.flush()
        created_inds += 1
        for level, behavior in BEHAVIOR_BY_LEVEL.items():
            db.add(
                CompBehavior(indicator_id=ind.id, level=level, description=behavior)
            )
            created_behaviors += 1
    db.commit()
    print(f"[comp] indicators +{created_inds}, behaviors +{created_behaviors}")


def _seed_multi_indicators(db: Session, round_id: int) -> None:
    existing = {
        i.name
        for i in db.query(MultiEvalIndicator)
        .filter(MultiEvalIndicator.round_id == round_id)
        .all()
    }
    created = 0
    for name, desc in MULTI_INDICATORS:
        if name in existing:
            continue
        db.add(
            MultiEvalIndicator(
                round_id=round_id, name=name, description=desc, max_score=5
            )
        )
        created += 1
    db.commit()
    print(f"[multi] indicators +{created}")


def _seed_setting(db: Session) -> None:
    s = db.query(EvalSetting).filter(EvalSetting.year == CURRENT_YEAR).first()
    if s is None:
        db.add(
            EvalSetting(
                year=CURRENT_YEAR,
                weight_config=json.dumps(WEIGHT_CONFIG),
                grade_criteria=json.dumps(GRADE_CRITERIA),
            )
        )
        db.commit()
        print(f"[setting] created year={CURRENT_YEAR}")
    else:
        s.weight_config = json.dumps(WEIGHT_CONFIG)
        s.grade_criteria = json.dumps(GRADE_CRITERIA)
        db.commit()
        print(f"[setting] updated year={CURRENT_YEAR}")


def _seed_approvers(db: Session, round_id: int) -> int:
    """기존 직원을 활용하여 BOSS/PEER/SUBORDINATE 매핑.

    - 부서별로 첫 번째 사원을 BOSS 로 간주
    - 같은 부서의 다른 사원은 PEER (cross)
    - BOSS → 본인 부서원을 SUBORDINATE 로 평가
    - PERF/COMP 매핑도 함께 생성 (BOSS → 부서원)
    """
    if db.query(EvalApprover).filter(EvalApprover.round_id == round_id).first():
        print("[approvers] skip (exists)")
        return 0

    employees = db.query(Employee).filter(Employee.emp_status == "재직").all()
    by_dept: dict[int | None, list[Employee]] = {}
    for e in employees:
        by_dept.setdefault(e.dept_id, []).append(e)

    created = 0
    for dept_id, members in by_dept.items():
        if dept_id is None or not members:
            continue
        boss = members[0]
        others = members[1:]

        # PERF/COMP: BOSS → 부서원
        for sub in others:
            for et in ("PERF", "COMP"):
                db.add(
                    EvalApprover(
                        round_id=round_id,
                        evaluatee_id=sub.id,
                        evaluator_id=boss.id,
                        eval_type=et,
                    )
                )
                created += 1

        # MULTI: 부서원 ↔ 부서원 (PEER), BOSS → 부서원 (SUBORDINATE 가 BOSS 평가),
        # 부서원 → BOSS (BOSS 평가 by 부원)
        for evaluatee in members:
            for evaluator in members:
                if evaluatee.id == evaluator.id:
                    continue
                rater = (
                    "BOSS"
                    if evaluator.id == boss.id
                    else (
                        "SUBORDINATE" if evaluatee.id == boss.id else "PEER"
                    )
                )
                db.add(
                    EvalApprover(
                        round_id=round_id,
                        evaluatee_id=evaluatee.id,
                        evaluator_id=evaluator.id,
                        eval_type="MULTI",
                        rater_type=rater,
                    )
                )
                created += 1
    db.commit()
    print(f"[approvers] created {created}")
    return created


def _seed_calibration(db: Session) -> None:
    if (
        db.query(EvalCalibrationGroup)
        .filter(EvalCalibrationGroup.year == CURRENT_YEAR)
        .first()
    ):
        print("[calibration] skip (exists)")
        return

    creator = db.query(User).filter(User.login_id == "admin").first()
    if creator is None:
        print("[calibration] skip (admin user not found)")
        return

    groups_by_rank = {"사원/대리": ["사원", "대리"], "과장/차장": ["과장", "차장"], "부장": ["부장"]}
    employees = db.query(Employee).filter(Employee.emp_status == "재직").all()

    for name, ranks in groups_by_rank.items():
        g = EvalCalibrationGroup(year=CURRENT_YEAR, name=name, created_by=creator.id)
        db.add(g)
        db.flush()
        members = [e for e in employees if e.job_rank in ranks]
        for emp in members:
            db.add(EvalCalibrationMember(group_id=g.id, emp_id=emp.id))
        print(f"[calibration] group '{name}' members={len(members)}")
    db.commit()


def seed() -> None:
    db = SessionLocal()
    try:
        r = _get_or_create_round(db)
        _seed_schedules(db, r.id)
        _seed_kpis(db, r.id)
        _seed_comp_indicators(db)
        _seed_multi_indicators(db, r.id)
        _seed_setting(db)
        _seed_approvers(db, r.id)
        _seed_calibration(db)
        print("\n✓ eval seed complete")
    finally:
        db.close()


def cleanup() -> None:
    """현재 연도 회차 + 종속 데이터 + setting + calibration 삭제."""
    db = SessionLocal()
    try:
        rounds = (
            db.query(EvalRound).filter(EvalRound.year == CURRENT_YEAR).all()
        )
        for r in rounds:
            db.query(EvalApprover).filter(EvalApprover.round_id == r.id).delete()
            db.query(EvalSchedule).filter(EvalSchedule.round_id == r.id).delete()
            db.query(MultiEvalIndicator).filter(
                MultiEvalIndicator.round_id == r.id
            ).delete()
            db.query(PerfKpi).filter(PerfKpi.round_id == r.id).delete()
            db.delete(r)
        db.query(EvalSetting).filter(EvalSetting.year == CURRENT_YEAR).delete()
        # comp 지표/행동지표 (cascade)
        comp_inds = (
            db.query(CompIndicator).filter(CompIndicator.year == CURRENT_YEAR).all()
        )
        for ind in comp_inds:
            db.query(CompBehavior).filter(CompBehavior.indicator_id == ind.id).delete()
            db.delete(ind)
        # calibration
        cal_groups = (
            db.query(EvalCalibrationGroup)
            .filter(EvalCalibrationGroup.year == CURRENT_YEAR)
            .all()
        )
        for g in cal_groups:
            db.query(EvalCalibrationMember).filter(
                EvalCalibrationMember.group_id == g.id
            ).delete()
            db.delete(g)
        db.commit()
        print(f"✓ cleanup complete (year={CURRENT_YEAR})")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cleanup", action="store_true")
    args = parser.parse_args()
    if args.cleanup:
        cleanup()
    else:
        seed()
