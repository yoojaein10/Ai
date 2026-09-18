"""임시 테스트용 시드 스크립트.

tenter(ACSDB) + APW_IW_SCHEDULE(apworksdw)에서 이름/사번을 뽑아
INSA Employee 테이블에 stub 레코드를 채워넣는다.

- tenter.e_idno → emp_no (숫자)
- SCHEDULE.name 중 tenter에 없는 이름 → 'APW' + 4자리 일련번호로 emp_no 생성
- 전부 'TEST_SEED' 부서에 배치
- workplace='TEST_SEED' 마커로 cleanup 가능

실행: python scripts/seed_from_external.py [--cleanup]
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

# scripts/ 에서 실행해도 app.* 을 찾을 수 있도록 루트 추가
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import text

from app.db.models import Department, Employee
from app.db.session import (
    ApworksSessionLocal,
    AttendanceSessionLocal,
    SessionLocal,
)

_SEED_MARKER = "TEST_SEED"
_SEED_DEPT_CODE = "TEST_SEED"
_SEED_DEPT_NAME = "테스트(임시)"


def _ensure_seed_dept(db) -> int:
    dept = db.query(Department).filter(Department.code == _SEED_DEPT_CODE).first()
    if dept:
        return dept.id
    dept = Department(code=_SEED_DEPT_CODE, name=_SEED_DEPT_NAME, is_active=True)
    db.add(dept)
    db.commit()
    db.refresh(dept)
    return dept.id


def _collect_tenter_names() -> dict[str, str]:
    """tenter 최근 90일에서 (name → emp_no) 매핑."""
    att = AttendanceSessionLocal()
    try:
        rows = att.execute(
            text(
                """
                SELECT e_idno, e_name
                FROM tenter
                WHERE e_id <> -1
                  AND e_idno IS NOT NULL
                  AND e_idno <> ''
                  AND e_name IS NOT NULL
                  AND e_name <> ''
                  AND e_date >= CONVERT(varchar(8), DATEADD(day, -90, GETDATE()), 112)
                GROUP BY e_idno, e_name
                """
            )
        ).all()
    finally:
        att.close()

    result: dict[str, str] = {}
    for emp_no, name in rows:
        name = (name or "").strip()
        emp_no = (emp_no or "").strip()
        if not name or not emp_no:
            continue
        # 같은 이름에 여러 사번이 있으면 첫 번째만 사용
        result.setdefault(name, emp_no)
    return result


def _collect_schedule_names() -> set[str]:
    apw = ApworksSessionLocal()
    try:
        rows = apw.execute(
            text(
                """
                SELECT DISTINCT name FROM APW_IW_SCHEDULE
                WHERE [date] >= DATEADD(day, -90, GETDATE())
                UNION
                SELECT DISTINCT Name FROM APW_IW_DAYCULJANG
                WHERE CulDate >= DATEADD(day, -90, GETDATE())
                """
            )
        ).all()
    finally:
        apw.close()

    return {(r[0] or "").strip() for r in rows if r[0] and (r[0] or "").strip()}


def seed() -> None:
    tenter_map = _collect_tenter_names()
    schedule_names = _collect_schedule_names()
    all_names = set(tenter_map.keys()) | schedule_names
    print(f"tenter names: {len(tenter_map)}, schedule-only: {len(schedule_names - set(tenter_map))}")

    db = SessionLocal()
    try:
        dept_id = _ensure_seed_dept(db)

        existing_emp_nos = {
            e[0] for e in db.query(Employee.emp_no).all()
        }
        existing_names = {
            e[0] for e in db.query(Employee.name_ko).all()
        }

        apw_seq = 1

        def _next_apw_emp_no() -> str:
            nonlocal apw_seq
            while True:
                candidate = f"APW{apw_seq:04d}"
                apw_seq += 1
                if candidate not in existing_emp_nos:
                    return candidate

        created = 0
        skipped = 0
        for name in sorted(all_names):
            if name in existing_names:
                skipped += 1
                continue

            emp_no = tenter_map.get(name)
            if not emp_no or emp_no in existing_emp_nos:
                emp_no = _next_apw_emp_no()

            emp = Employee(
                emp_no=emp_no,
                name_ko=name,
                hire_date=date(2020, 1, 1),
                dept_id=dept_id,
                workplace=_SEED_MARKER,
                emp_status="재직",
                emp_type="정규직",
            )
            db.add(emp)
            existing_emp_nos.add(emp_no)
            existing_names.add(name)
            created += 1

        db.commit()
        print(f"created: {created}, skipped (already exists): {skipped}")
    finally:
        db.close()


def cleanup() -> None:
    db = SessionLocal()
    try:
        count = (
            db.query(Employee).filter(Employee.workplace == _SEED_MARKER).count()
        )
        db.query(Employee).filter(Employee.workplace == _SEED_MARKER).delete(
            synchronize_session=False
        )
        dept = db.query(Department).filter(Department.code == _SEED_DEPT_CODE).first()
        if dept:
            db.delete(dept)
        db.commit()
        print(f"deleted employees: {count}, dept removed: {'yes' if dept else 'no'}")
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
