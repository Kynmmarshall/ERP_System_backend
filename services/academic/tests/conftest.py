import asyncio
import sys

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

# asyncpg's connection-close/cancel path is incompatible with Windows'
# default ProactorEventLoop. Only affects local Windows test runs; Linux
# (Docker, Jenkins, the VPS) is unaffected.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

