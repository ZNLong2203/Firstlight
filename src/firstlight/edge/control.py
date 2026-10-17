"""The simulator's control port: the API injects and clears chaos faults here. Not exposed publicly."""

import hmac
from datetime import UTC, datetime

from fastapi import Depends, FastAPI, Header, HTTPException

from firstlight.core.models import FaultRequest, FaultView
from firstlight.edge.world import UnknownTarget, World


def control_app(world: World, token: str) -> FastAPI:
    app = FastAPI(title="Firstlight simulator control", docs_url=None, redoc_url=None, openapi_url=None)

    def authorised(x_gateway_token: str = Header(default="")) -> None:
        if not token or not hmac.compare_digest(x_gateway_token.encode(), token.encode()):
            raise HTTPException(status_code=401, detail="invalid token")

    @app.get("/faults", dependencies=[Depends(authorised)])
    async def faults() -> list[FaultView]:
        return world.faults

    @app.post("/faults", dependencies=[Depends(authorised)])
    async def inject(request: FaultRequest) -> FaultView:
        try:
            return world.apply(request, datetime.now(UTC))
        except UnknownTarget as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.delete("/faults/{fault_id}", dependencies=[Depends(authorised)])
    async def clear(fault_id: str) -> FaultView:
        view = world.clear(fault_id)
        if view is None:
            raise HTTPException(status_code=404, detail="no such fault")
        return view

    return app
