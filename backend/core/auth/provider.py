from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class User:
    username: str
    is_admin: bool = True


@runtime_checkable
class AuthProvider(Protocol):
    async def authenticate(self, credentials: dict) -> User | None: ...
    async def verify_token(self, token: str) -> User | None: ...
    def login_url(self) -> str: ...
    def callback_url(self) -> str: ...
