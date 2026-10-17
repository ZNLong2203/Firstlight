"""firstlight-brain: forecasts every pond every 30 s, keeps pond status current and rolls data up."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from ddtrace.trace import tracer
from pymongo import UpdateOne
from pymongo.asynchronous.database import AsyncDatabase

from firstlight.brain.forecast import classify, forecast_pipeline
from firstlight.brain.rollup import hour_rollup, minute_rollup
from firstlight.core.config import get_settings
from firstlight.core.metrics import Metrics
from firstlight.core.mongo import database, make_client

log = logging.getLogger("firstlight.brain")

FORECAST_EVERY_S = 30
FORECAST_WINDOW = timedelta(minutes=12)
NO_RISK_MINUTES = 600  # published instead of "never", so monitors always have a number


async def forecast_once(db: AsyncDatabase[dict[str, Any]], metrics: Metrics, now: datetime) -> dict[str, int]:
    with tracer.trace("brain.forecast", service="firstlight-brain", resource="forecast_pipeline"):
        forecasts = {
            f["_id"]: f async for f in await db.readings.aggregate(forecast_pipeline(now - FORECAST_WINDOW))
        }
    states = [s async for s in db.pond_state.find({}, {"last": 1, "farm": 1, "gateway": 1})]
    updates = []
    counts: dict[str, int] = {}
    for state in states:
        last = state.get("last")
        freshness = (now - last["ts"]).total_seconds() if last else float("inf")
        f = forecasts.get(state["_id"], {})
        minutes = f.get("minutes_to_hypoxia")
        status = classify(last, minutes, freshness)
        counts[status] = counts.get(status, 0) + 1
        updates.append(
            UpdateOne(
                {"_id": state["_id"]},
                {
                    "$set": {
                        "status": status,
                        "freshness_s": round(freshness, 1) if last else None,
                        "forecast": {
                            "at": now,
                            "minutes_to_hypoxia": None if minutes is None else round(minutes, 1),
                            "slope_per_min": round(f.get("slope_per_min", 0.0), 4),
                            "points": f.get("points", 0),
                        },
                    }
                },
            )
        )
        tags = [f"farm:{state.get('farm')}", f"pond:{state['_id']}", f"gateway:{state.get('gateway')}"]
        metrics.gauge(
            "firstlight.pond.minutes_to_hypoxia",
            NO_RISK_MINUTES if minutes is None else min(minutes, NO_RISK_MINUTES),
            tags,
        )
        if last:
            metrics.gauge("firstlight.pond.freshness_seconds", freshness, tags)
    if updates:
        await db.pond_state.bulk_write(updates, ordered=False)
    return counts


async def rollups_due(db: AsyncDatabase[dict[str, Any]], now: datetime, done: dict[str, datetime]) -> None:
    minute = now.replace(second=0, microsecond=0)
    previous_minute = minute - timedelta(minutes=1)
    if now.second >= 15 and done.get("minute") != previous_minute:
        with tracer.trace("brain.rollup", service="firstlight-brain", resource="readings_1m"):
            await (await db.readings.aggregate(minute_rollup(previous_minute, minute))).to_list()
        done["minute"] = previous_minute
    hour = now.replace(minute=0, second=0, microsecond=0)
    previous_hour = hour - timedelta(hours=1)
    if now.minute >= 2 and done.get("hour") != previous_hour:
        with tracer.trace("brain.rollup", service="firstlight-brain", resource="readings_1h"):
            await (await db.readings_1m.aggregate(hour_rollup(previous_hour, hour))).to_list()
        done["hour"] = previous_hour


async def run() -> None:
    settings = get_settings()
    client = make_client(settings)
    db = database(client, settings)
    metrics = Metrics(settings)
    log.info("brain started", extra={"ctx": {"env": settings.dd_env, "every_s": FORECAST_EVERY_S}})
    done: dict[str, datetime] = {}
    next_forecast = 0.0
    loop = asyncio.get_running_loop()
    try:
        while True:
            now = datetime.now(UTC)
            try:
                if loop.time() >= next_forecast:
                    next_forecast = loop.time() + FORECAST_EVERY_S
                    counts = await forecast_once(db, metrics, now)
                    log.info("forecast done", extra={"ctx": {"ponds": counts}})
                await rollups_due(db, now, done)
            except Exception:
                log.exception("brain cycle failed")
            await asyncio.sleep(5)
    finally:
        await client.close()
