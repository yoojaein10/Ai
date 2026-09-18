"""API routes for employee sub-tab data (1:1 and 1:N relationships)."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_roles
from app.core.encryption import decrypt, encrypt, mask_account
from app.db.models import (
    EmpAccount,
    EmpAward,
    EmpCareer,
    EmpCertificate,
    EmpDisability,
    EmpDiscipline,
    EmpEducation,
    EmpEvaluation,
    EmpFamily,
    EmpLanguage,
    EmpMilitary,
    EmpPersonal,
    EmpVeteran,
    Employee,
    User,
)
from app.db.session import get_db
from app.schemas.emp_tabs import (
    EmpAccountCreate,
    EmpAccountResponse,
    EmpAwardCreate,
    EmpAwardResponse,
    EmpCareerCreate,
    EmpCareerResponse,
    EmpCertificateCreate,
    EmpCertificateResponse,
    EmpDisabilityCreate,
    EmpDisabilityResponse,
    EmpDisciplineCreate,
    EmpDisciplineResponse,
    EmpEducationCreate,
    EmpEducationResponse,
    EmpEvaluationResponse,
    EmpFamilyCreate,
    EmpFamilyResponse,
    EmpLanguageCreate,
    EmpLanguageResponse,
    EmpMilitaryCreate,
    EmpMilitaryResponse,
    EmpPersonalCreate,
    EmpPersonalResponse,
    EmpVeteranCreate,
    EmpVeteranResponse,
)

router = APIRouter(prefix="/employees/{employee_id}", tags=["employee-tabs"])


def _check_employee(db: Session, employee_id: int) -> Employee:
    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    if emp is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    return emp


# ── 1:1 tabs (personal, military, veteran, disability) ──


def _upsert_one_to_one(db, model_cls, employee_id, data):
    """Create or update a 1:1 sub-record."""
    record = db.query(model_cls).filter(model_cls.employee_id == employee_id).first()
    if record is None:
        record = model_cls(employee_id=employee_id, **data.model_dump())
        db.add(record)
    else:
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(record, field, value)
    db.commit()
    db.refresh(record)
    return record


# ── 신상 ──

@router.get("/personal", response_model=EmpPersonalResponse | None)
def get_personal(employee_id: int, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _check_employee(db, employee_id)
    return db.query(EmpPersonal).filter(EmpPersonal.employee_id == employee_id).first()


@router.put("/personal", response_model=EmpPersonalResponse)
def upsert_personal(
    employee_id: int,
    body: EmpPersonalCreate,
    _: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
    db: Session = Depends(get_db),
):
    _check_employee(db, employee_id)
    return _upsert_one_to_one(db, EmpPersonal, employee_id, body)


# ── 병역 ──

@router.get("/military", response_model=EmpMilitaryResponse | None)
def get_military(employee_id: int, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _check_employee(db, employee_id)
    return db.query(EmpMilitary).filter(EmpMilitary.employee_id == employee_id).first()


@router.put("/military", response_model=EmpMilitaryResponse)
def upsert_military(
    employee_id: int,
    body: EmpMilitaryCreate,
    _: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
    db: Session = Depends(get_db),
):
    _check_employee(db, employee_id)
    return _upsert_one_to_one(db, EmpMilitary, employee_id, body)


# ── 보훈 ──

@router.get("/veteran", response_model=EmpVeteranResponse | None)
def get_veteran(employee_id: int, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _check_employee(db, employee_id)
    return db.query(EmpVeteran).filter(EmpVeteran.employee_id == employee_id).first()


@router.put("/veteran", response_model=EmpVeteranResponse)
def upsert_veteran(
    employee_id: int,
    body: EmpVeteranCreate,
    _: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
    db: Session = Depends(get_db),
):
    _check_employee(db, employee_id)
    return _upsert_one_to_one(db, EmpVeteran, employee_id, body)


# ── 장애 ──

@router.get("/disability", response_model=EmpDisabilityResponse | None)
def get_disability(employee_id: int, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _check_employee(db, employee_id)
    return db.query(EmpDisability).filter(EmpDisability.employee_id == employee_id).first()


@router.put("/disability", response_model=EmpDisabilityResponse)
def upsert_disability(
    employee_id: int,
    body: EmpDisabilityCreate,
    _: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
    db: Session = Depends(get_db),
):
    _check_employee(db, employee_id)
    return _upsert_one_to_one(db, EmpDisability, employee_id, body)


# ── 1:N tabs helper ──


def _list_records(db, model_cls, employee_id):
    _check_employee(db, employee_id)
    return db.query(model_cls).filter(model_cls.employee_id == employee_id).all()


def _create_record(db, model_cls, employee_id, data):
    _check_employee(db, employee_id)
    record = model_cls(employee_id=employee_id, **data.model_dump())
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def _delete_record(db, model_cls, record_id, employee_id):
    record = db.query(model_cls).filter(
        model_cls.id == record_id, model_cls.employee_id == employee_id
    ).first()
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Record not found")
    db.delete(record)
    db.commit()
    return {"deleted": True}


# ── 가족 ──

@router.get("/families", response_model=list[EmpFamilyResponse])
def list_families(employee_id: int, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _list_records(db, EmpFamily, employee_id)


@router.post("/families", response_model=EmpFamilyResponse, status_code=status.HTTP_201_CREATED)
def create_family(
    employee_id: int, body: EmpFamilyCreate,
    _: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")), db: Session = Depends(get_db),
):
    return _create_record(db, EmpFamily, employee_id, body)


@router.delete("/families/{record_id}")
def delete_family(
    employee_id: int, record_id: int,
    _: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")), db: Session = Depends(get_db),
):
    return _delete_record(db, EmpFamily, record_id, employee_id)


# ── 학력 ──

@router.get("/educations", response_model=list[EmpEducationResponse])
def list_educations(employee_id: int, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _list_records(db, EmpEducation, employee_id)


@router.post("/educations", response_model=EmpEducationResponse, status_code=status.HTTP_201_CREATED)
def create_education(
    employee_id: int, body: EmpEducationCreate,
    _: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")), db: Session = Depends(get_db),
):
    return _create_record(db, EmpEducation, employee_id, body)


@router.delete("/educations/{record_id}")
def delete_education(
    employee_id: int, record_id: int,
    _: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")), db: Session = Depends(get_db),
):
    return _delete_record(db, EmpEducation, record_id, employee_id)


# ── 경력 ──

@router.get("/careers", response_model=list[EmpCareerResponse])
def list_careers(employee_id: int, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _list_records(db, EmpCareer, employee_id)


@router.post("/careers", response_model=EmpCareerResponse, status_code=status.HTTP_201_CREATED)
def create_career(
    employee_id: int, body: EmpCareerCreate,
    _: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")), db: Session = Depends(get_db),
):
    return _create_record(db, EmpCareer, employee_id, body)


@router.delete("/careers/{record_id}")
def delete_career(
    employee_id: int, record_id: int,
    _: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")), db: Session = Depends(get_db),
):
    return _delete_record(db, EmpCareer, record_id, employee_id)


# ── 자격 ──

@router.get("/certificates", response_model=list[EmpCertificateResponse])
def list_certificates(employee_id: int, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _list_records(db, EmpCertificate, employee_id)


@router.post("/certificates", response_model=EmpCertificateResponse, status_code=status.HTTP_201_CREATED)
def create_certificate(
    employee_id: int, body: EmpCertificateCreate,
    _: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")), db: Session = Depends(get_db),
):
    return _create_record(db, EmpCertificate, employee_id, body)


@router.delete("/certificates/{record_id}")
def delete_certificate(
    employee_id: int, record_id: int,
    _: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")), db: Session = Depends(get_db),
):
    return _delete_record(db, EmpCertificate, record_id, employee_id)


# ── 어학 ──

@router.get("/languages", response_model=list[EmpLanguageResponse])
def list_languages(employee_id: int, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _list_records(db, EmpLanguage, employee_id)


@router.post("/languages", response_model=EmpLanguageResponse, status_code=status.HTTP_201_CREATED)
def create_language(
    employee_id: int, body: EmpLanguageCreate,
    _: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")), db: Session = Depends(get_db),
):
    return _create_record(db, EmpLanguage, employee_id, body)


@router.delete("/languages/{record_id}")
def delete_language(
    employee_id: int, record_id: int,
    _: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")), db: Session = Depends(get_db),
):
    return _delete_record(db, EmpLanguage, record_id, employee_id)


# ── 포상 ──

@router.get("/awards", response_model=list[EmpAwardResponse])
def list_awards(employee_id: int, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _list_records(db, EmpAward, employee_id)


@router.post("/awards", response_model=EmpAwardResponse, status_code=status.HTTP_201_CREATED)
def create_award(
    employee_id: int, body: EmpAwardCreate,
    _: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")), db: Session = Depends(get_db),
):
    return _create_record(db, EmpAward, employee_id, body)


@router.delete("/awards/{record_id}")
def delete_award(
    employee_id: int, record_id: int,
    _: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")), db: Session = Depends(get_db),
):
    return _delete_record(db, EmpAward, record_id, employee_id)


# ── 징계 ──

@router.get("/disciplines", response_model=list[EmpDisciplineResponse])
def list_disciplines(employee_id: int, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _list_records(db, EmpDiscipline, employee_id)


@router.post("/disciplines", response_model=EmpDisciplineResponse, status_code=status.HTTP_201_CREATED)
def create_discipline(
    employee_id: int, body: EmpDisciplineCreate,
    _: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")), db: Session = Depends(get_db),
):
    return _create_record(db, EmpDiscipline, employee_id, body)


@router.delete("/disciplines/{record_id}")
def delete_discipline(
    employee_id: int, record_id: int,
    _: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")), db: Session = Depends(get_db),
):
    return _delete_record(db, EmpDiscipline, record_id, employee_id)


# ── 평가 (읽기전용) ──

@router.get("/evaluations", response_model=list[EmpEvaluationResponse])
def list_evaluations(employee_id: int, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _list_records(db, EmpEvaluation, employee_id)


# ── 계좌 (AES-256 암호화) ──

@router.get("/accounts", response_model=list[EmpAccountResponse])
def list_accounts(employee_id: int, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _check_employee(db, employee_id)
    records = db.query(EmpAccount).filter(EmpAccount.employee_id == employee_id).all()
    result = []
    for r in records:
        try:
            plain = decrypt(r.account_no_enc)
            masked = mask_account(plain)
        except Exception:
            masked = "****"
        result.append(EmpAccountResponse(
            id=r.id,
            employee_id=r.employee_id,
            bank_name=r.bank_name,
            account_no_masked=masked,
            account_holder=r.account_holder,
        ))
    return result


@router.post("/accounts", response_model=EmpAccountResponse, status_code=status.HTTP_201_CREATED)
def create_account(
    employee_id: int, body: EmpAccountCreate,
    _: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")), db: Session = Depends(get_db),
):
    _check_employee(db, employee_id)
    encrypted = encrypt(body.account_no)
    record = EmpAccount(
        employee_id=employee_id,
        bank_name=body.bank_name,
        account_no_enc=encrypted,
        account_holder=body.account_holder,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return EmpAccountResponse(
        id=record.id,
        employee_id=record.employee_id,
        bank_name=record.bank_name,
        account_no_masked=mask_account(body.account_no),
        account_holder=record.account_holder,
    )


@router.delete("/accounts/{record_id}")
def delete_account(
    employee_id: int, record_id: int,
    _: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")), db: Session = Depends(get_db),
):
    return _delete_record(db, EmpAccount, record_id, employee_id)
