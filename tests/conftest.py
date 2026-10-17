import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

os.environ.setdefault("DD_TRACE_ENABLED", "false")  # no agent in tests; set before ddtrace is imported

import httpx
import pytest
import uvicorn

from firstlight.api.app import app, lifespan
from firstlight.core import config

TOKEN = "test-gateway-token"
DEMO_CODE = "test-demo-code"
WEBHOOK_SECRET = "test-webhook-secret"


@pytest.fixture
async def api(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[tuple[httpx.AsyncClient, Any]]:
    """The API on a throwaway database, dropped afterwards; needs MONGODB_URI."""
    if not os.getenv("MONGODB_URI"):
        pytest.skip("needs a MongoDB (set MONGODB_URI)")
    monkeypatch.setenv("MONGODB_DB", f"firstlight_test_{uuid.uuid4().hex[:8]}")
    monkeypatch.setenv("GATEWAY_TOKEN", TOKEN)
    monkeypatch.setenv("DEMO_CODE", DEMO_CODE)
    monkeypatch.setenv("WEBHOOK_SECRET", WEBHOOK_SECRET)
    config.get_settings.cache_clear()
    try:
        async with lifespan(app):
            db = app.state.db
            transport = httpx.ASGITransport(app=app)
            headers = {"X-Gateway-Token": TOKEN}
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test", headers=headers
            ) as client:
                yield client, db
            await app.state.mongo.drop_database(db.name)
    finally:
        config.get_settings.cache_clear()


@pytest.fixture
async def live_api(api: tuple[httpx.AsyncClient, Any]) -> AsyncIterator[str]:
    """The same app served over a real socket, for streaming clients such as a gateway's command channel."""
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, lifespan="off", log_config=None))
    task = asyncio.create_task(server.serve())
    for _ in range(250):
        if server.started:
            break
        await asyncio.sleep(0.02)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task
