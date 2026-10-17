"""firstlight-api: HTTP entry point for gateways, the console and Datadog."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response

from firstlight import __version__
from firstlight.core.config import get_settings
from firstlight.core.mongo import make_client


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.mongo = make_client(settings)
    try:
        yield
    finally:
        await app.state.mongo.close()


app = FastAPI(title="Firstlight API", version=__version__, lifespan=lifespan)


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
