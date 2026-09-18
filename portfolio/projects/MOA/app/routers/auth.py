"""로그인 API — usr 파라미터 없이 접속한 브라우저/EXE의 본인 확인."""

import time

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.common import ApiResponse
from app.services.auth import AuthError, login

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    usr_id: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=100)


@router.post("/login", response_model=ApiResponse)
def post_login(
    request: LoginRequest, db: Session = Depends(get_db)
) -> ApiResponse | JSONResponse:
    try:
        user = login(db, request.usr_id, request.password)
    except AuthError as exc:
        time.sleep(0.5)  # 무차별 대입 속도 제한 (사내망이지만 최소한의 지연)
        response = ApiResponse(
            success=False, code="LOGIN_FAILED", message=str(exc), data=None
        )
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content=response.model_dump(mode="json"),
        )
    return ApiResponse(success=True, code="0000", message="로그인 성공", data=user)
