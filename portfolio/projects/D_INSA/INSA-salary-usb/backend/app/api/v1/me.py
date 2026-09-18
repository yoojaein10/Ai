from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.schemas.employee import EmployeeResponse

router = APIRouter(prefix="/me", tags=["me"])


@router.get("", response_model=dict)
def get_my_info(current_user: User = Depends(get_current_user)):
    result = {
        "user_id": current_user.id,
        "login_id": current_user.login_id,
        "roles": [ur.role.code for ur in current_user.roles],
    }
    if current_user.employee:
        emp = current_user.employee
        result["employee"] = {
            "id": emp.id,
            "emp_no": emp.emp_no,
            "name_ko": emp.name_ko,
            "department": emp.department.name if emp.department else None,
            "job_rank": emp.job_rank,
            "job_position": emp.job_position,
        }
    return result
