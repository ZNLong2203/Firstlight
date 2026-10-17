"""firstlight-api: HTTP entry point for gateways, the console and Datadog."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response

from firstlight import __version__
from firstlight.api.ingest import router as ingest_router
from firstlight.api.live import Hub, flush_every_second, watch_pond_state
from firstlight.api.live import router as live_router
from firstlight.core.config import get_settings
from firstlight.core.metrics import Metrics
from firstlight.core.mongo import database, make_client
from firstlight.core.schema import ensure_schema


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.mongo = make_client(settings)
    app.state.db = database(app.state.mongo, settings)
    app.state.metrics = Metrics(settings)
    try:
        await ensure_schema(app.state.db)
    except Exception:
        logging.getLogger("firstlight.api").exception("schema setup failed; /healthz will report it")
    app.state.hub = Hub()
    tasks = [
        asyncio.create_task(watch_pond_state(app.state.db, app.state.hub)),
        asyncio.create_task(flush_every_second(app.state.hub)),
    ]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await app.state.mongo.close()


app = FastAPI(title="Firstlight API", version=__version__, lifespan=lifespan)
app.include_router(ingest_router)
app.include_router(live_router)


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
