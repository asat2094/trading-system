import pytest
from httpx import AsyncClient, ASGITransport
from api.main import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.mark.asyncio
async def test_health_returns_200(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_protected_route_requires_auth(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/scanner/run")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_returns_token(app):
    import os
    os.environ["ADMIN_USERNAME"] = "admin"
    os.environ["ADMIN_PASSWORD_HASH"] = "$2b$12$placeholder"
    os.environ["JWT_SECRET"] = "x" * 32
    from unittest.mock import patch, AsyncMock
    from core.auth.provider import User
    with patch("core.auth.local.LocalJWTProvider.authenticate", new_callable=AsyncMock,
               return_value=User(username="admin")):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/auth/login", json={"username": "admin", "password": "pass"})
    assert resp.status_code == 200
    assert "access_token" in resp.json()
