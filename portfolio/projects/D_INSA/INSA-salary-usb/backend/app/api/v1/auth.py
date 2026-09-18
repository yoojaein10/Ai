from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from app.db.models import User
from app.db.session import get_db
from app.schemas.auth import LoginRequest, LoginResponse, TokenRefreshResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.login_id == body.login_id).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is deactivated")

    role_codes = [ur.role.code for ur in user.roles]
    access_token = create_access_token(str(user.id), extra={"roles": role_codes})
    refresh_token = create_refresh_token(str(user.id))

    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        path="/api/v1/auth",
    )

    return LoginResponse(
        access_token=access_token,
        user_id=user.id,
        login_id=user.login_id,
        roles=role_codes,
    )


@router.post("/refresh", response_model=TokenRefreshResponse)
def refresh(refresh_token: str | None = Cookie(default=None), db: Session = Depends(get_db)):
    if refresh_token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token")

    try:
        payload = decode_token(refresh_token)
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")

    user_id = payload.get("sub")
    user = db.query(User).filter(User.id == int(user_id), User.is_active == True).first()  # noqa: E712
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    role_codes = [ur.role.code for ur in user.roles]
    access_token = create_access_token(str(user.id), extra={"roles": role_codes})
    return TokenRefreshResponse(access_token=access_token)


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(key="refresh_token", path="/api/v1/auth")
    return {"message": "Logged out"}
