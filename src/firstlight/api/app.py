"""firstlight-api: HTTP entry point for gateways, the console and Datadog."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response

from firstlight import __version__
from firstlight.api.ingest import router as ingest_router
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
    try:
        yield
    finally:
        await app.state.mongo.close()


app = FastAPI(title="Firstlight API", version=__version__, lifespan=lifespan)
app.include_router(ingest_router)


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
