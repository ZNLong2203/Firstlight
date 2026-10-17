"""firstlight-edge: simulated farms and their gateways, posting to the API in real time."""

import asyncio
import logging
import random
import time
from datetime import UTC, datetime, timedelta

import httpx

from firstlight.core.config import get_settings
from firstlight.edge.farms import Farm, build_farms
from firstlight.edge.gateway import Gateway

log = logging.getLogger("firstlight.edge")


def farm_hour(now: datetime, offset_hours: float) -> float:
    """Hour of day on the farm clock. Timestamps stay real; only the physics follows this clock."""
    local = now + timedelta(hours=offset_hours)
    return local.hour + local.minute / 60 + local.second / 3600


def warm_up(farms: list[Farm], now: datetime, offset_hours: float, rng: random.Random) -> None:
    """Run six simulated hours so every pond starts from a realistic oxygen level for this time of day."""
    for minutes_ago in range(360, 0, -1):
        hour = farm_hour(now - timedelta(minutes=minutes_ago), offset_hours)
        for farm in farms:
            for pond in farm.ponds:
                pond.step(hour, 60, rng)


async def announce(client: httpx.AsyncClient, farm: Farm) -> None:
    manifest = farm.manifest().model_dump(mode="json")
    for attempt in range(60):
        try:
            response = await client.put(f"/v1/gateways/{farm.gateway}/manifest", json=manifest)
            if response.status_code < 300:
                return
            log.warning(
                "manifest rejected",
                extra={"ctx": {"gateway": farm.gateway, "status_code": response.status_code}},
            )
        except httpx.HTTPError as exc:
            log.warning(
                "api not reachable yet",
                extra={"ctx": {"gateway": farm.gateway, "reason": type(exc).__name__}},
            )
        await asyncio.sleep(min(2 + attempt, 15))


async def run() -> None:
    settings = get_settings()
    rng = random.Random(7)
    farms = build_farms(settings.sim_farms, settings.sim_ponds_per_farm)
    gateways = [Gateway(farm) for farm in farms]
    offset = settings.sim_farm_clock_offset_hours
    warm_up(farms, datetime.now(UTC), offset, rng)
    log.info(
        "edge started",
        extra={
            "ctx": {
                "farms": len(farms),
                "ponds": sum(len(f.ponds) for f in farms),
                "api": settings.firstlight_api_url,
            }
        },
    )

    limits = httpx.Limits(max_connections=20, max_keepalive_connections=20)
    headers = {"X-Gateway-Token": settings.gateway_token}
    async with httpx.AsyncClient(
        base_url=settings.firstlight_api_url, timeout=5.0, limits=limits, headers=headers
    ) as client:
        await asyncio.gather(*(announce(client, farm) for farm in farms))
        log.info("manifests announced", extra={"ctx": {"gateways": len(gateways)}})

        last = time.monotonic()
        while True:
            started = time.monotonic()
            now = datetime.now(UTC)
            hour = farm_hour(now, offset)
            dt = min(started - last, 60.0)
            last = started
            for farm in farms:
                for pond in farm.ponds:
                    pond.step(hour, dt, rng)
            for gateway in gateways:
                gateway.collect(now, rng)
            await asyncio.gather(*(gateway.flush(client) for gateway in gateways))
            await asyncio.sleep(max(0.0, settings.sim_batch_seconds - (time.monotonic() - started)))
