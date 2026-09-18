"""Schemas for employee sub-tab data (personal, military, family, education, etc.)."""

from datetime import date

from pydantic import BaseModel


# ── 신상 (Personal) ──

class EmpPersonalBase(BaseModel):
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    emergency_contact: str | None = None
    emergency_phone: str | None = None


class EmpPersonalCreate(EmpPersonalBase):
    pass


class EmpPersonalResponse(EmpPersonalBase):
    id: int
    employee_id: int
    model_config = {"from_attributes": True}


# ── 병역 (Military) ──

class EmpMilitaryBase(BaseModel):
    branch: str | None = None
    rank: str | None = None
    service_start: date | None = None
    service_end: date | None = None
    exemption_reason: str | None = None


class EmpMilitaryCreate(EmpMilitaryBase):
    pass


class EmpMilitaryResponse(EmpMilitaryBase):
    id: int
    employee_id: int
    model_config = {"from_attributes": True}


# ── 보훈 (Veteran) ──

class EmpVeteranBase(BaseModel):
    veteran_no: str | None = None
    veteran_type: str | None = None
    veteran_grade: str | None = None


class EmpVeteranCreate(EmpVeteranBase):
    pass


class EmpVeteranResponse(EmpVeteranBase):
    id: int
    employee_id: int
    model_config = {"from_attributes": True}


# ── 장애 (Disability) ──

class EmpDisabilityBase(BaseModel):
    disability_type: str | None = None
    disability_grade: str | None = None
    registered_at: date | None = None


class EmpDisabilityCreate(EmpDisabilityBase):
    pass


class EmpDisabilityResponse(EmpDisabilityBase):
    id: int
    employee_id: int
    model_config = {"from_attributes": True}


# ── 가족 (Family) ──

class EmpFamilyBase(BaseModel):
    relation: str
    name: str
    birth_date: date | None = None
    is_cohabiting: bool = True


class EmpFamilyCreate(EmpFamilyBase):
    pass


class EmpFamilyResponse(EmpFamilyBase):
    id: int
    employee_id: int
    model_config = {"from_attributes": True}


# ── 학력 (Education) ──

class EmpEducationBase(BaseModel):
    school_name: str
    degree: str | None = None
    major: str | None = None
    graduation_year: int | None = None


class EmpEducationCreate(EmpEducationBase):
    pass


class EmpEducationResponse(EmpEducationBase):
    id: int
    employee_id: int
    model_config = {"from_attributes": True}


# ── 경력 (Career) ──

class EmpCareerBase(BaseModel):
    company_name: str
    position: str | None = None
    start_date: date | None = None
    end_date: date | None = None


class EmpCareerCreate(EmpCareerBase):
    pass


class EmpCareerResponse(EmpCareerBase):
    id: int
    employee_id: int
    model_config = {"from_attributes": True}


# ── 자격 (Certificate) ──

class EmpCertificateBase(BaseModel):
    cert_name: str
    issuer: str | None = None
    acquired_at: date | None = None


class EmpCertificateCreate(EmpCertificateBase):
    pass


class EmpCertificateResponse(EmpCertificateBase):
    id: int
    employee_id: int
    model_config = {"from_attributes": True}


# ── 어학 (Language) ──

class EmpLanguageBase(BaseModel):
    language: str
    test_name: str | None = None
    score: str | None = None
    acquired_at: date | None = None


class EmpLanguageCreate(EmpLanguageBase):
    pass


class EmpLanguageResponse(EmpLanguageBase):
    id: int
    employee_id: int
    model_config = {"from_attributes": True}


# ── 포상 (Award) ──

class EmpAwardBase(BaseModel):
    award_name: str
    award_date: date | None = None
    description: str | None = None


class EmpAwardCreate(EmpAwardBase):
    pass


class EmpAwardResponse(EmpAwardBase):
    id: int
    employee_id: int
    model_config = {"from_attributes": True}


# ── 징계 (Discipline) ──

class EmpDisciplineBase(BaseModel):
    discipline_type: str
    discipline_date: date | None = None
    reason: str | None = None


class EmpDisciplineCreate(EmpDisciplineBase):
    pass


class EmpDisciplineResponse(EmpDisciplineBase):
    id: int
    employee_id: int
    model_config = {"from_attributes": True}


# ── 평가 (Evaluation) — 읽기전용 ──

class EmpEvaluationResponse(BaseModel):
    id: int
    employee_id: int
    eval_year: int
    eval_grade: str | None = None
    score: int | None = None
    model_config = {"from_attributes": True}


# ── 계좌 (Account) ──

class EmpAccountBase(BaseModel):
    bank_name: str
    account_no: str  # plaintext in request, encrypted in DB
    account_holder: str


class EmpAccountCreate(EmpAccountBase):
    pass


class EmpAccountResponse(BaseModel):
    id: int
    employee_id: int
    bank_name: str
    account_no_masked: str  # ****1234 format
    account_holder: str
    model_config = {"from_attributes": True}
