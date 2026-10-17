import os

import httpx
import pytest

from firstlight.api.app import app, lifespan


@pytest.mark.skipif(not os.getenv("MONGODB_URI"), reason="needs a MongoDB (set MONGODB_URI)")
async def test_healthz_reports_mongo_ok() -> None:
    async with lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["mongo"] == "ok"


async def test_healthz_is_degraded_without_mongo(monkeypatch: pytest.MonkeyPatch) -> None:
    from firstlight.core import config

    monkeypatch.setenv(
        "MONGODB_URI", "mongodb://127.0.0.1:1/?directConnection=true&serverSelectionTimeoutMS=200"
    )
    config.get_settings.cache_clear()
    try:
        async with lifespan(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/healthz")
    finally:
        config.get_settings.cache_clear()
    assert response.status_code == 503
    assert response.json()["mongo"] == "unreachable"
