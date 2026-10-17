"""firstlight-api: HTTP entry point for gateways, the console and Datadog."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import FastAPI, Response

from firstlight import __version__
from firstlight.api.chaos import router as chaos_router
from firstlight.api.commands import CommandHub, watch_commands
from firstlight.api.commands import router as commands_router
from firstlight.api.hooks import router as hooks_router
from firstlight.api.incidents import router as incidents_router
from firstlight.api.ingest import router as ingest_router
from firstlight.api.live import Hub, flush_every_second, watch
from firstlight.api.live import router as live_router
from firstlight.core.config import Settings, get_settings
from firstlight.core.metrics import Metrics
from firstlight.core.mongo import database, make_client
from firstlight.core.schema import ensure_schema
from firstlight.core.telegram import Telegram


async def record_deployment(db: Any, settings: Settings) -> None:
    """Every start of the API is a deployment the brain can line up against an incident."""
    await db.deployments.insert_one(
        {
            "service": "firstlight-api",
            "version": settings.dd_version,
            "started_at": datetime.now(UTC),
            "config": {"ingest_duplicate_check": settings.ingest_duplicate_check},
        }
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.mongo = make_client(settings)
    app.state.db = database(app.state.mongo, settings)
    app.state.metrics = Metrics(settings)
    try:
        await ensure_schema(app.state.db)
        await record_deployment(app.state.db, settings)
    except Exception:
        logging.getLogger("firstlight.api").exception("schema setup failed; /healthz will report it")
    app.state.hub = Hub()
    app.state.commands = CommandHub()
    app.state.telegram = Telegram(settings)
    if (
        app.state.telegram.enabled
        and settings.telegram_webhook_secret
        and settings.public_host != "localhost"
    ):
        await app.state.telegram.set_webhook(
            f"https://{settings.public_host}/v1/hooks/telegram", settings.telegram_webhook_secret
        )
    app.state.edge = httpx.AsyncClient(
        base_url=settings.edge_control_url, timeout=5.0, headers={"X-Gateway-Token": settings.gateway_token}
    )
    tasks = [
        asyncio.create_task(watch(app.state.db, "pond_state", app.state.hub, "ponds")),
        asyncio.create_task(watch(app.state.db, "incidents", app.state.hub, "incidents")),
        asyncio.create_task(flush_every_second(app.state.hub)),
        asyncio.create_task(watch_commands(app.state.db, app.state.commands)),
    ]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await app.state.edge.aclose()
        await app.state.telegram.close()
        await app.state.mongo.close()


app = FastAPI(title="Firstlight API", version=__version__, lifespan=lifespan)
app.include_router(ingest_router)
app.include_router(live_router)
app.include_router(commands_router)
app.include_router(chaos_router)
app.include_router(incidents_router)
app.include_router(hooks_router)


@app.get("/healthz")
@app.get("/v1/healthz")
async def healthz(response: Response) -> dict[str, str]:
    settings = get_settings()
    try:
        await app.state.mongo.admin.command("ping")
        mongo = "ok"
    except Exception:
        mongo = "unreachable"
        response.status_code = 503
    return {"status": "ok" if mongo == "ok" else "degraded", "mongo": mongo, "version": settings.dd_version}
