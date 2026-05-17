from core.auth.provider import User


class GitHubOAuthProvider:
    """Activate via AUTH_PROVIDER=github + GITHUB_CLIENT_ID/SECRET env vars."""

    async def authenticate(self, credentials: dict) -> User | None:
        raise NotImplementedError("GitHubOAuthProvider: set AUTH_PROVIDER=github + configure OAuth app")

    async def verify_token(self, token: str) -> User | None:
        raise NotImplementedError

    def login_url(self) -> str:
        return "/auth/github/login"

    def callback_url(self) -> str:
        return "/auth/github/callback"
