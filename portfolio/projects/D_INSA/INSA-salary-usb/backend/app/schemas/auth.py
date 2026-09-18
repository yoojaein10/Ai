from pydantic import BaseModel


class LoginRequest(BaseModel):
    login_id: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    login_id: str
    roles: list[str]


class TokenRefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
