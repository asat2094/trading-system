import pytest
from unittest.mock import patch
from core.auth.local import LocalJWTProvider
from core.auth.provider import User


@pytest.mark.asyncio
async def test_local_provider_authenticate_success():
    provider = LocalJWTProvider(
        username="admin",
        password_hash="$2b$12$KIXtmJFMCxJL4v6lEKq9LO9qcIiO.u8t5TH5S8bYcf3fMPi6xKQBm",
        jwt_secret="x" * 32,
        jwt_expiry_hours=24,
    )
    with patch("passlib.context.CryptContext.verify", return_value=True):
        user = await provider.authenticate({"username": "admin", "password": "password"})
    assert user is not None
    assert user.username == "admin"


@pytest.mark.asyncio
async def test_local_provider_authenticate_wrong_password():
    provider = LocalJWTProvider(
        username="admin",
        password_hash="$2b$12$wrong",
        jwt_secret="x" * 32,
        jwt_expiry_hours=24,
    )
    with patch("passlib.context.CryptContext.verify", return_value=False):
        user = await provider.authenticate({"username": "admin", "password": "wrong"})
    assert user is None


@pytest.mark.asyncio
async def test_local_provider_token_roundtrip():
    provider = LocalJWTProvider(
        username="admin",
        password_hash="hash",
        jwt_secret="x" * 32,
        jwt_expiry_hours=24,
    )
    user = User(username="admin")
    token = provider.create_token(user)
    verified = await provider.verify_token(token)
    assert verified is not None
    assert verified.username == "admin"


@pytest.mark.asyncio
async def test_expired_token_rejected():
    provider = LocalJWTProvider(
        username="admin",
        password_hash="hash",
        jwt_secret="x" * 32,
        jwt_expiry_hours=-1,
    )
    user = User(username="admin")
    token = provider.create_token(user)
    verified = await provider.verify_token(token)
    assert verified is None
