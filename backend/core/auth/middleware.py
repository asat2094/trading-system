from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from core.auth.provider import User

_bearer = HTTPBearer(auto_error=False)


def _get_provider():
    from core.config import settings
    if settings.AUTH_PROVIDER == "local":
        from core.auth.local import LocalJWTProvider
        return LocalJWTProvider(
            username=settings.ADMIN_USERNAME,
            password_hash=settings.ADMIN_PASSWORD_HASH,
            jwt_secret=settings.JWT_SECRET,
            jwt_expiry_hours=settings.JWT_EXPIRY_HOURS,
        )
    raise ValueError(f"Unknown AUTH_PROVIDER: {settings.AUTH_PROVIDER!r}")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    provider = _get_provider()
    user = await provider.verify_token(credentials.credentials)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    return user
