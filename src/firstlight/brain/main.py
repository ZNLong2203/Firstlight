"""firstlight-brain: forecasting, evidence, playbooks and verification (from 17 Oct)."""

import asyncio
import logging

from firstlight.core.config import get_settings

log = logging.getLogger("firstlight.brain")


async def run() -> None:
    settings = get_settings()
    log.info("brain started", extra={"ctx": {"env": settings.dd_env}})
    await asyncio.Event().wait()  # idle until the loop lands on 17 Oct
