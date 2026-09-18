from sqlalchemy.orm import Session

from app.db.models import Employee, EvalRound, PerfEvalResult
from app.schemas.perf_result import PerfResultCreate


def list_results(
    db: Session,
    round_id: int | None = None,
    dept_id: int | None = None,
) -> list[PerfEvalResult]:
    query = db.query(PerfEvalResult)
    if round_id is not None:
        query = query.filter(PerfEvalResult.round_id == round_id)
    if dept_id is not None:
        query = query.join(Employee, Employee.id == PerfEvalResult.emp_id).filter(
            Employee.dept_id == dept_id
        )
    return query.order_by(PerfEvalResult.id.desc()).all()


def list_results_by_emp(db: Session, emp_id: int, round_id: int | None = None) -> list[PerfEvalResult]:
    query = db.query(PerfEvalResult).filter(PerfEvalResult.emp_id == emp_id)
    if round_id is not None:
        query = query.filter(PerfEvalResult.round_id == round_id)
    return query.order_by(PerfEvalResult.id.desc()).all()


def create_result(db: Session, data: PerfResultCreate, evaluator_emp_id: int) -> PerfEvalResult:
    if db.query(EvalRound).filter(EvalRound.id == data.round_id).first() is None:
        raise ValueError(f"EvalRound {data.round_id} not found")
    if db.query(Employee).filter(Employee.id == data.emp_id).first() is None:
        raise ValueError(f"Employee {data.emp_id} not found")

    result = PerfEvalResult(
        emp_id=data.emp_id,
        round_id=data.round_id,
        evaluator_id=evaluator_emp_id,
        score=data.score,
        grade=data.grade,
        comment=data.comment,
    )
    db.add(result)
    db.commit()
    db.refresh(result)
    return result
