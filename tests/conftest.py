import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from firstlight.api.app import app, lifespan
from firstlight.core import config

TOKEN = "test-gateway-token"


@pytest.fixture
async def api(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[tuple[httpx.AsyncClient, Any]]:
    """The API on a throwaway database, dropped afterwards; needs MONGODB_URI."""
    if not os.getenv("MONGODB_URI"):
        pytest.skip("needs a MongoDB (set MONGODB_URI)")
    monkeypatch.setenv("MONGODB_DB", f"firstlight_test_{uuid.uuid4().hex[:8]}")
    monkeypatch.setenv("GATEWAY_TOKEN", TOKEN)
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
