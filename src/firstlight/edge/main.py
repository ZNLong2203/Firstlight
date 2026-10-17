"""firstlight-edge: the pond and gateway simulator (from 17 Oct)."""

import asyncio
import logging

from firstlight.core.config import get_settings

log = logging.getLogger("firstlight.edge")


async def run() -> None:
    settings = get_settings()
    ponds = settings.sim_farms * settings.sim_ponds_per_farm
    log.info("edge started", extra={"ctx": {"ponds": ponds, "api": settings.firstlight_api_url}})
    await asyncio.Event().wait()  # idle until the loop lands on 17 Oct
