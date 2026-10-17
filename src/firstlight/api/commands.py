"""The command bus: commands are documents in MongoDB, delivered to gateways through a change stream.

One change stream on `commands` feeds every connected gateway's channel, so the number of streams
does not grow with the fleet. A gateway that connects first receives everything it has not yet
acknowledged, which also covers commands created while it or the API was down.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pymongo import ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase

from firstlight.api.ingest import require_gateway_token
from firstlight.api.live import HEARTBEAT_S, sse
from firstlight.core.metrics import Metrics
from firstlight.core.models import CommandAck

router = APIRouter(prefix="/v1")
log = logging.getLogger("firstlight.api.commands")

UNACKED = ("pending", "sent")


def wire(command: dict[str, Any]) -> dict[str, Any]:
    """What a gateway needs to run a command, and nothing else."""
    return {
        "id": str(command["_id"]),
        "action": command["action"],
        "pond": command.get("pond"),
        "device": command.get("device"),
        "incident": command.get("incident"),
    }


class CommandHub:
    """The gateways connected to this API process, each with its own queue of commands."""

    def __init__(self) -> None:
        self._channels: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}

    def connect(self, gateway: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        self._channels.setdefault(gateway, set()).add(queue)
        return queue

    def disconnect(self, gateway: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        channels = self._channels.get(gateway, set())
        channels.discard(queue)
        if not channels:
            self._channels.pop(gateway, None)

    def connected(self, gateway: str) -> bool:
        return gateway in self._channels

    @property
    def gateways(self) -> int:
        return len(self._channels)

    def offer(self, command: dict[str, Any]) -> None:
        for queue in self._channels.get(command["gateway"], set()):
            try:
                queue.put_nowait(command)
            except asyncio.QueueFull:
                log.warning("command channel full", extra={"ctx": {"gateway": command["gateway"]}})


async def watch_commands(db: AsyncDatabase[dict[str, Any]], hub: CommandHub) -> None:
    """New commands, and commands set back to pending for a retry, go to their gateway's channel."""
    token: Any = None
    pipeline = [
        {
            "$match": {
                "$or": [
                    {"operationType": "insert"},
                    {"operationType": "update", "updateDescription.updatedFields.status": "pending"},
                ]
            }
        }
    ]
    while True:
        try:
            async with await db.commands.watch(
                pipeline, full_document="updateLookup", resume_after=token
            ) as stream:
                async for change in stream:
                    token = stream.resume_token
                    command = change.get("fullDocument")
                    if command and command.get("status") == "pending":
                        hub.offer(command)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("commands change stream failed; restarting")
            await asyncio.sleep(2)


@router.get("/gateways/{gateway_id}/commands", dependencies=[Depends(require_gateway_token)])
async def command_channel(gateway_id: str, request: Request) -> StreamingResponse:
    db = request.app.state.db
    hub: CommandHub = request.app.state.commands

    async def deliver(command: dict[str, Any]) -> str:
        await db.commands.update_one(
            {"_id": command["_id"], "status": "pending"},
            {"$set": {"status": "sent", "sent_at": datetime.now(UTC)}},
        )
        return sse("command", wire(command))

    async def events() -> AsyncIterator[str]:
        queue = hub.connect(gateway_id)  # before the backlog query, so nothing falls in between
        try:
            backlog = db.commands.find(
                {"gateway": gateway_id, "status": {"$in": UNACKED}, "deliver_by": {"$gt": datetime.now(UTC)}}
            ).sort("created_at", 1)
            async for command in backlog:
                yield await deliver(command)
            while not await request.is_disconnected():
                try:
                    command = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_S)
                except TimeoutError:
                    yield sse("tick", {"at": datetime.now(UTC)})
                    continue
                yield await deliver(command)
        finally:
            hub.disconnect(gateway_id, queue)

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return StreamingResponse(events(), media_type="text/event-stream", headers=headers)


@router.post("/commands/{command_id}/ack", dependencies=[Depends(require_gateway_token)])
async def acknowledge(command_id: str, ack: CommandAck, request: Request) -> dict[str, Any]:
    """Idempotent: a repeated ack returns the stored outcome and changes nothing."""
    db = request.app.state.db
    metrics: Metrics = request.app.state.metrics
    try:
        oid = ObjectId(command_id)
    except InvalidId as exc:
        raise HTTPException(status_code=404, detail="no such command") from exc
    now = datetime.now(UTC)
    command = await db.commands.find_one_and_update(
        {"_id": oid, "gateway": ack.gateway, "status": {"$in": UNACKED}},
        {
            "$set": {
                "status": ack.status,
                "acked_at": now,
                "executed_at": ack.executed_at,
                "result": ack.detail,
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    if command is None:
        existing = await db.commands.find_one({"_id": oid, "gateway": ack.gateway})
        if existing is None:
            raise HTTPException(status_code=404, detail="no such command")
        return {"status": existing["status"], "duplicate": True}

    latency_ms = (now - command["created_at"]).total_seconds() * 1000
    tags = [f"action:{command['action']}", f"gateway:{ack.gateway}", f"status:{ack.status}"]
    metrics.distribution("firstlight.command.ack_latency_ms", latency_ms, tags)
    if command.get("incident"):
        await db.incidents.update_one(
            {"_id": command["incident"]},
            {
                "$push": {
                    "timeline": {
                        "t": now,
                        "kind": "action_done" if ack.status == "done" else "action_failed",
                        "action": command["action"],
                        "device": command.get("device"),
                        "command": command["_id"],
                        "latency_ms": round(latency_ms),
                        "detail": ack.detail,
                    }
                }
            },
        )
    return {"status": command["status"], "duplicate": False}
