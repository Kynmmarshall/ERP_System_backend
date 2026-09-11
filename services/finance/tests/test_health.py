from httpx import ASGITransport, AsyncClient

from app.core.db import database_is_ready
from app.main import app


async def test_healthz_reports_ok_without_dependencies() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "finance"}


async def test_readyz_reports_ready_when_database_reachable(monkeypatch) -> None:
    monkeypatch.setattr("app.main.database_is_ready", lambda: _true())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "service": "finance"}


async def test_readyz_reports_unavailable_when_database_unreachable(monkeypatch) -> None:
    monkeypatch.setattr("app.main.database_is_ready", lambda: _false())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/readyz")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "service": "finance", "reason": "database"}


async def test_database_is_ready_returns_false_when_connection_fails() -> None:
    # No real Postgres is reachable at settings.database_url in a unit-test
    # context, so this exercises the real except-branch, not a mock.
    assert await database_is_ready() is False


async def _true() -> bool:
    return True


async def _false() -> bool:
    return False
