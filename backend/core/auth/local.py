from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
import bcrypt
from jose import jwt, JWTError
from core.auth.provider import User

_ALGORITHM = "HS256"


@dataclass
class LocalJWTProvider:
    username: str
    password_hash: str
    jwt_secret: str
    jwt_expiry_hours: int = 24

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

    async def verify_token(self, token: str) -> User | None:
        try:
            payload = jwt.decode(token, self.jwt_secret, algorithms=[_ALGORITHM])
            username = payload.get("sub")
            if username is None:
                return None
            return User(username=username)
        except JWTError:
            return None

    def login_url(self) -> str:
        return "/auth/login"

    def callback_url(self) -> str:
        return "/auth/login"
