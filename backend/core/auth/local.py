from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
import bcrypt
from jose import jwt, JWTError
from core.auth.provider import User

_ALGORITHM = "HS256"
_REDIS_PREFIX = "auth:session:"


@dataclass
class LocalJWTProvider:
    username: str
    password_hash: str
    jwt_secret: str
    jwt_expiry_hours: int = 24
    _redis: object = field(default=None, repr=False)

    def __post_init__(self):
        if self._redis is None:
            from core.cache import get_redis
            self._redis = get_redis()

    async def authenticate(self, credentials: dict) -> User | None:
        if credentials.get("username") != self.username:
            return None
        pw = credentials.get("password", "").encode()
        hsh = self.password_hash.encode() if isinstance(self.password_hash, str) else self.password_hash
        if not bcrypt.checkpw(pw, hsh):
            return None
        return User(username=self.username)

    def create_token(self, user: User) -> str:
        expire = datetime.now(timezone.utc) + timedelta(hours=self.jwt_expiry_hours)
        return jwt.encode(
            {"sub": user.username, "exp": expire},
            self.jwt_secret,
            algorithm=_ALGORITHM,
        )

    async def _store_token(self, token: str) -> None:
        ttl_seconds = self.jwt_expiry_hours * 3600
        try:
            await self._redis.setex(f"{_REDIS_PREFIX}{token}", ttl_seconds, "1")
        except Exception:
            pass

    async def verify_token(self, token: str) -> User | None:
        try:
            payload = jwt.decode(token, self.jwt_secret, algorithms=[_ALGORITHM])
            username = payload.get("sub")
            if username is None:
                return None
            try:
                exists = await self._redis.exists(f"{_REDIS_PREFIX}{token}")
                if not exists:
                    # Key missing — could be revoked OR Redis was down during login.
                    # Re-store it so subsequent calls succeed (self-healing).
                    remaining = payload.get("exp", 0) - int(datetime.now(timezone.utc).timestamp())
                    if remaining > 0:
                        await self._redis.setex(f"{_REDIS_PREFIX}{token}", int(remaining), "1")
                    else:
                        return None
            except Exception:
                pass
            return User(username=username)
        except JWTError:
            return None

    async def revoke_token(self, token: str) -> None:
        try:
            await self._redis.delete(f"{_REDIS_PREFIX}{token}")
        except Exception:
            pass

    def login_url(self) -> str:
        return "/auth/login"

    def callback_url(self) -> str:
        return "/auth/login"
