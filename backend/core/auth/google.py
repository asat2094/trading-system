from core.auth.provider import User


class GoogleOAuthProvider:
    """Activate via AUTH_PROVIDER=google + GOOGLE_CLIENT_ID/SECRET env vars."""

    async def authenticate(self, credentials: dict) -> User | None:
        raise NotImplementedError("GoogleOAuthProvider: set AUTH_PROVIDER=google + configure OAuth app")

    async def verify_token(self, token: str) -> User | None:
        raise NotImplementedError

    def login_url(self) -> str:
        return "/auth/google/login"

    def callback_url(self) -> str:
        return "/auth/google/callback"
