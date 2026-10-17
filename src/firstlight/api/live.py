"""Live view for the console: pond list, pond history, and server-sent events from a change stream."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pymongo.asynchronous.database import AsyncDatabase

from firstlight import __version__
from firstlight.core.config import get_settings

router = APIRouter(prefix="/v1")
log = logging.getLogger("firstlight.api.live")

POND_FIELDS = ("farm", "gateway", "status", "last", "forecast", "freshness_s", "area_m2")
PROJECTION = dict.fromkeys(POND_FIELDS, 1)
RECONNECT = "reconnect"  # queued for a console that fell behind: its stream ends and it starts over
HEARTBEAT_S = 15


def _default(value: Any) -> str:
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=UTC)).isoformat()
    raise TypeError(f"not serialisable: {type(value).__name__}")


def sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=_default, separators=(',', ':'))}\n\n"


def project(doc: dict[str, Any]) -> dict[str, Any]:
    return {"_id": doc["_id"], **{key: doc.get(key) for key in POND_FIELDS}}


class Hub:
    """Fans pond updates out to every connected console, coalesced to one message per second."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[str]] = set()
        self._pending: dict[str, dict[str, Any]] = {}

    @property
    def subscribers(self) -> int:
        return len(self._subscribers)

    def subscribe(self) -> asyncio.Queue[str]:
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=50)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[str]) -> None:
        self._subscribers.discard(queue)

    def offer(self, pond: dict[str, Any]) -> None:
        self._pending[pond["_id"]] = pond  # only the latest state of each pond matters

    def flush(self) -> None:
        if not self._pending:
            return
        message = sse("ponds", list(self._pending.values()))
        self._pending.clear()
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                # A console that stopped reading is dropped. Its backlog is stale, so it is replaced by
                # one instruction to end the stream; EventSource then reconnects and gets a fresh snapshot.
                self._subscribers.discard(queue)
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(RECONNECT)


async def watch_pond_state(db: AsyncDatabase[dict[str, Any]], hub: Hub) -> None:
    """pond_state change stream → hub. Restarts from the last resume token after any error."""
    token: Any = None
    pipeline = [{"$match": {"operationType": {"$in": ["insert", "update", "replace"]}}}]
    while True:
        try:
            async with await db.pond_state.watch(
                pipeline, full_document="updateLookup", resume_after=token
            ) as stream:
                async for change in stream:
                    token = stream.resume_token
                    if doc := change.get("fullDocument"):
                        hub.offer(project(doc))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("pond_state change stream failed; restarting")
            await asyncio.sleep(2)


async def flush_every_second(hub: Hub) -> None:
    while True:
        await asyncio.sleep(1)
        hub.flush()


@router.get("/meta")
async def meta() -> dict[str, Any]:
    settings = get_settings()
    return {
        "version": settings.dd_version or __version__,
        "env": settings.dd_env,
        "farm_clock_offset_hours": settings.sim_farm_clock_offset_hours,
    }


@router.get("/ponds")
async def ponds(request: Request) -> list[dict[str, Any]]:
    db = request.app.state.db
    return [project(p) async for p in db.pond_state.find({}, PROJECTION).sort("_id", 1)]


@router.get("/ponds/{pond_id}")
async def pond(pond_id: str, request: Request) -> dict[str, Any]:
    db = request.app.state.db
    state = await db.pond_state.find_one({"_id": pond_id})
    if state is None:
        raise HTTPException(status_code=404, detail="no such pond")
    devices = await db.devices.find({"pond": pond_id}, {"updated_at": 0}).sort("_id", 1).to_list()
    return {**state, "devices": devices}


@router.get("/ponds/{pond_id}/history")
async def history(
    pond_id: str, request: Request, minutes: int = Query(120, ge=5, le=1440)
) -> list[dict[str, Any]]:
    """Raw 10 s readings for short windows, 1-minute rollups beyond three hours."""
    db = request.app.state.db
    since = datetime.now(UTC) - timedelta(minutes=minutes)
    if minutes <= 180:
        running = {"$size": {"$filter": {"input": "$aer", "cond": {"$gte": ["$$this.amp", 0.5]}}}}
        pipeline: list[dict[str, Any]] = [
            {"$match": {"meta.pond": pond_id, "ts": {"$gte": since}}},
            {"$sort": {"ts": 1}},
            {"$project": {"_id": 0, "ts": 1, "do": 1, "temp": 1, "ph": 1, "running": running}},
        ]
        return [r async for r in await db.readings.aggregate(pipeline)]
    rows = db.readings_1m.find(
        {"_id.pond": pond_id, "_id.minute": {"$gte": since}},
        {"_id": 0, "ts": "$minute", "do": "$do_avg", "do_min": 1, "do_max": 1, "temp": 1, "ph": 1},
    ).sort("_id.minute", 1)
    return [r async for r in rows]


@router.get("/stream")
async def stream(request: Request) -> StreamingResponse:
    hub: Hub = request.app.state.hub
    db = request.app.state.db

    async def events() -> AsyncIterator[str]:
        queue = hub.subscribe()
        try:
            snapshot = [project(p) async for p in db.pond_state.find({}, PROJECTION).sort("_id", 1)]
            yield "retry: 2000\n" + sse("snapshot", snapshot)
            while not await request.is_disconnected():
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_S)
                except TimeoutError:
                    # A named event, not a comment, so the console can tell a quiet stream from a dead one.
                    yield sse("tick", {"at": datetime.now(UTC)})
                    continue
                if message == RECONNECT:
                    return
                yield message
        finally:
            hub.unsubscribe(queue)

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return StreamingResponse(events(), media_type="text/event-stream", headers=headers)
