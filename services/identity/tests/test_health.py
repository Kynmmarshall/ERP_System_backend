from httpx import ASGITransport, AsyncClient

from app.main import app


async def test_healthz_reports_ok_without_dependencies() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "identity"}
