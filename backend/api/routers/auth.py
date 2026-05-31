from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from core.auth.middleware import _get_provider, get_current_user
from core.auth.provider import User

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
    await provider._store_token(token)
    return TokenResponse(access_token=token)


@router.post("/logout")
async def logout(body: dict, user: User = Depends(get_current_user)):
    """Revoke a session token via Redis."""
    token = body.get("token", "")
    if not token:
        raise HTTPException(400, "token required")
    provider = _get_provider()
    await provider.revoke_token(token)
    return {"detail": "logged out"}
