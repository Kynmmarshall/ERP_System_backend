from httpx import ASGITransport, AsyncClient

from app.main import app


async def test_healthz_reports_ok_without_dependencies() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "hr"}


async def test_readyz_reports_ready_when_database_reachable(monkeypatch) -> None:
    monkeypatch.setattr("app.main.database_is_ready", lambda: _true())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "service": "hr"}


async def test_readyz_reports_unavailable_when_database_unreachable(monkeypatch) -> None:
    monkeypatch.setattr("app.main.database_is_ready", lambda: _false())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/readyz")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "service": "hr", "reason": "database"}


# Unlike a purely unit-tested service, this suite requires a real reachable
# Postgres (see tests/test_recruitment.py etc.) so there is no real-
# unreachable-database branch to exercise here without a mock; that branch
# is instead already covered by
# test_readyz_reports_unavailable_when_database_unreachable above.


async def _true() -> bool:
    return True


async def _false() -> bool:
    return False
