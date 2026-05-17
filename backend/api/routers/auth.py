from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from core.auth.middleware import _get_provider

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest):
    provider = _get_provider()
    user = await provider.authenticate({"username": req.username, "password": req.password})
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = provider.create_token(user)
    return TokenResponse(access_token=token)
