"""firstlight-brain: forecasts every pond every 10 s, keeps pond status current and rolls data up."""

import asyncio
import logging
from collections.abc import Awaitable
from datetime import UTC, datetime, timedelta
from typing import Any

from ddtrace.trace import tracer
from pymongo import UpdateOne
from pymongo.asynchronous.database import AsyncDatabase

from firstlight.ai.gemini import Gemini
from firstlight.ai.memory import ensure_search_indexes
from firstlight.brain.ai_worker import AiWorker
from firstlight.brain.forecast import classify, forecast_pipeline
from firstlight.brain.incidents import Policy, incident_cycle
from firstlight.brain.notebooks import NotebookWriter
from firstlight.brain.notifier import Notifier
from firstlight.brain.playbooks import ensure_playbooks
from firstlight.brain.reports import dawn_report_due
from firstlight.brain.rollup import hour_rollup, roll_up_minutes
from firstlight.core.config import get_settings
from firstlight.core.metrics import Metrics
from firstlight.core.mongo import database, make_client
from firstlight.core.telegram import Telegram

log = logging.getLogger("firstlight.brain")

CYCLE_S = 10  # the gateways report every 10 s, so there is nothing new to look at any sooner
FORECAST_WINDOW = timedelta(minutes=12)
NO_RISK_MINUTES = 600  # published instead of "never", so monitors always have a number


async def forecast_once(db: AsyncDatabase[dict[str, Any]], metrics: Metrics, now: datetime) -> dict[str, int]:
    with tracer.trace("brain.forecast", service="firstlight-brain", resource="forecast_pipeline"):
        forecasts = {
            f["_id"]: f async for f in await db.readings.aggregate(forecast_pipeline(now - FORECAST_WINDOW))
        }
    states = [
        s async for s in db.pond_state.find({}, {"last": 1, "farm": 1, "gateway": 1, "sensor_ticket": 1})
    ]
    updates = []
    counts: dict[str, int] = {}
    for state in states:
        last = state.get("last")
        freshness = (now - last["ts"]).total_seconds() if last else float("inf")
        f = forecasts.get(state["_id"], {})
        minutes = f.get("minutes_to_hypoxia")
        status = classify(last, minutes, freshness, sensor_suspect="sensor_ticket" in state)
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
                            "rate_3m": round(f.get("rate_3m") or 0.0, 3),
                        },
                    }
                },
            )
        )
        tags = [f"farm:{state.get('farm')}", f"pond:{state['_id']}", f"gateway:{state.get('gateway')}"]
        # A probe waiting to be cleaned is not believed: its pond is not forecast, so no monitor pages for it.
        published = (
            NO_RISK_MINUTES if minutes is None or "sensor_ticket" in state else min(minutes, NO_RISK_MINUTES)
        )
        metrics.gauge("firstlight.pond.minutes_to_hypoxia", published, tags)
        if last:
            metrics.gauge("firstlight.pond.freshness_seconds", freshness, tags)
    if updates:
        await db.pond_state.bulk_write(updates, ordered=False)
    return counts


async def rollups_due(db: AsyncDatabase[dict[str, Any]], now: datetime, done: dict[str, datetime]) -> None:
    with tracer.trace("brain.rollup", service="firstlight-brain", resource="readings_1m"):
        await roll_up_minutes(db, now)
    hour = now.replace(minute=0, second=0, microsecond=0)
    previous_hour = hour - timedelta(hours=1)
    if now.minute >= 2 and done.get("hour") != previous_hour:
        # Only once the minute rollups have reached the end of that hour, or it would be summed half full.
        last_minute = {"minute": {"$gte": hour - timedelta(minutes=1)}}
        if not await db.readings_1m.find_one(last_minute, {"_id": 1}):
            return
        with tracer.trace("brain.rollup", service="firstlight-brain", resource="readings_1h"):
            await (await db.readings_1m.aggregate(hour_rollup(previous_hour, hour))).to_list()
        done["hour"] = previous_hour


async def step(name: str, work: Awaitable[Any]) -> Any:
    """One part of the cycle. A failure is logged and the cycle goes on, so a bad document in one part
    never stops the others: the forecast, the incidents, the messages, the AI, the notebooks."""
    try:
        return await work
    except Exception:
        log.exception("brain step failed", extra={"ctx": {"step": name}})
        return None


async def dawn_report(
    db: AsyncDatabase[dict[str, Any]], telegram: Telegram, offset_hours: float, now: datetime
) -> None:
    reports = await dawn_report_due(db, now, offset_hours)
    if reports:
        log.info("dawn report written", extra={"ctx": {"date": reports[0]["date"], **reports[0]["summary"]}})
        if telegram.enabled:
            await telegram.send(telegram.chat, reports[0]["message_vi"])


async def run() -> None:
    settings = get_settings()
    client = make_client(settings)
    db = database(client, settings)
    metrics = Metrics(settings)
    policy = Policy(
        recovery_min=settings.recovery_stable_min,
        escalate_after_min=settings.escalate_after_min,
        farm_offset_hours=settings.sim_farm_clock_offset_hours,
    )
    log.info("brain started", extra={"ctx": {"env": settings.dd_env, "every_s": CYCLE_S}})
    await ensure_playbooks(db)
    gemini = Gemini(settings)
    if gemini.enabled:
        await ensure_search_indexes(db)
    ai = AiWorker(db, gemini, metrics)
    telegram = Telegram(settings)
    notifier = Notifier(db, telegram, settings)
    notebooks = NotebookWriter(db, settings)
    done: dict[str, datetime] = {}
    loop = asyncio.get_running_loop()
    cycles = 0
    try:
        while True:
            started = loop.time()
            now = datetime.now(UTC)
            try:
                with tracer.trace("brain.cycle", service="firstlight-brain", resource="cycle"):
                    counts = await step("forecast", forecast_once(db, metrics, now))
                    open_incidents = await step("incidents", incident_cycle(db, metrics, policy, now))
                    await step("rollups", rollups_due(db, now, done))
                await step("notifier", notifier.cycle(now))
                await step(
                    "dawn report", dawn_report(db, telegram, settings.sim_farm_clock_offset_hours, now)
                )
                await step("ai", ai.cycle(now))
                await step("notebooks", notebooks.cycle(now))
                elapsed = round(loop.time() - started, 2)
                metrics.distribution("firstlight.brain.cycle_s", elapsed)
                ctx = {"ponds": counts, "open_incidents": open_incidents, "cycle_s": elapsed}
                if elapsed > CYCLE_S:  # forecasts are now older than the cycle promises
                    log.warning("brain cycle overran", extra={"ctx": ctx})
                elif cycles % 6 == 0:  # a status line every minute is enough
                    log.info("cycle done", extra={"ctx": ctx})
                cycles += 1
            except Exception:
                log.exception("brain cycle failed")
            await asyncio.sleep(max(0.0, CYCLE_S - (loop.time() - started)))
    finally:
        await client.close()
