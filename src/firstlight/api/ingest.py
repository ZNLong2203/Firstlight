"""Gateway endpoints: device manifests and telemetry batches."""

import hmac
from datetime import UTC, datetime
from typing import Any

from ddtrace.trace import tracer
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pymongo import ReplaceOne, UpdateOne
from pymongo.errors import BulkWriteError, DuplicateKeyError

from firstlight.core.config import get_settings
from firstlight.core.metrics import Metrics
from firstlight.core.models import GatewayBatch, GatewayManifest, PondReading

router = APIRouter(prefix="/v1")


def require_gateway_token(x_gateway_token: str = Header(default="")) -> None:
    expected = get_settings().gateway_token
    if not expected or not hmac.compare_digest(x_gateway_token.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="invalid gateway token")


def _tag_span(**tags: str) -> None:
    span = tracer.current_root_span()
    if span is not None:
        for key, value in tags.items():
            span.set_tag(key, value)


@router.put("/gateways/{gateway_id}/manifest", dependencies=[Depends(require_gateway_token)])
async def put_manifest(gateway_id: str, manifest: GatewayManifest, request: Request) -> dict[str, int]:
    if manifest.gateway != gateway_id:
        raise HTTPException(status_code=422, detail="gateway id in path and body differ")
    _tag_span(gateway=gateway_id, farm=manifest.farm)
    db = request.app.state.db
    now = datetime.now(UTC)
    base = {"farm": manifest.farm, "gateway": manifest.gateway, "updated_at": now}
    devices: list[ReplaceOne[dict[str, Any]]] = [
        ReplaceOne(
            {"_id": manifest.gateway},
            {
                "_id": manifest.gateway,
                "type": "gateway",
                "province": manifest.province,
                "location": {"type": "Point", "coordinates": [manifest.lon, manifest.lat]},
                **base,
            },
            upsert=True,
        )
    ]
    for pond in manifest.ponds:
        for aerator in pond.aerators:
            devices.append(
                ReplaceOne(
                    {"_id": aerator.id},
                    {
                        "_id": aerator.id,
                        "type": "aerator",
                        "pond": pond.id,
                        "aerator": {"kw": aerator.kw, "standby": aerator.standby},
                        **base,
                    },
                    upsert=True,
                )
            )
        devices.append(
            ReplaceOne(
                {"_id": pond.probe.id},
                {
                    "_id": pond.probe.id,
                    "type": "do_probe",
                    "pond": pond.id,
                    "probe": {"model": pond.probe.model},
                    **base,
                },
                upsert=True,
            )
        )
    await db.devices.bulk_write(devices, ordered=False)
    await db.pond_state.bulk_write(
        [
            UpdateOne(
                {"_id": pond.id},
                {
                    "$set": {
                        "farm": manifest.farm,
                        "gateway": manifest.gateway,
                        "area_m2": pond.area_m2,
                        "aerators": [a.id for a in pond.aerators if not a.standby],
                        "standby": [a.id for a in pond.aerators if a.standby],
                        "probe": pond.probe.id,
                    },
                    "$setOnInsert": {"status": "ok"},
                },
                upsert=True,
            )
            for pond in manifest.ponds
        ],
        ordered=False,
    )
    return {"devices": len(devices), "ponds": len(manifest.ponds)}


def _reading_doc(r: PondReading, batch: GatewayBatch) -> dict[str, Any]:
    return {
        "ts": r.ts,
        "meta": {"farm": r.farm, "pond": r.pond, "gateway": batch.gateway},
        "do": r.do,
        "temp": r.temp,
        "ph": r.ph,
        "aer": [a.model_dump() for a in r.aer],
        "probe": r.probe.model_dump(),
        "batch": batch.batch_id,
    }


def _pond_state_update(r: PondReading, gateway: str) -> list[dict[str, Any]]:
    """Pipeline update: replace `last` only if this reading is newer, so late backlog never rewinds."""
    last = {
        "ts": r.ts,
        "do": r.do,
        "temp": r.temp,
        "ph": r.ph,
        "aerators_on": sum(1 for a in r.aer if a.on),
        "aerators_running": sum(1 for a in r.aer if a.amp >= 0.5),
        "aer": [{"id": a.id, "on": a.on, "amp": a.amp} for a in r.aer],
        "probe_q": r.probe.q,
    }
    newer = {"$or": [{"$eq": [{"$type": "$last.ts"}, "missing"]}, {"$lt": ["$last.ts", r.ts]}]}
    return [
        {
            "$set": {
                "farm": {"$literal": r.farm},
                "gateway": {"$literal": gateway},
                "last": {"$cond": [newer, {"$literal": last}, "$last"]},
                "updated_at": "$$NOW",
            }
        }
    ]


async def _store_events(db: Any, batch: GatewayBatch, received: datetime) -> None:
    """What the gateway did on its own (the failsafe). Ids come from the batch, so a retry adds nothing."""
    docs = [
        {
            "_id": f"{batch.batch_id}:{i}",
            "ts": e.ts,
            "gateway": batch.gateway,
            "pond": e.pond,
            "kind": e.kind,
            "device": e.device,
            "detail": e.detail,
            "received_at": received,
        }
        for i, e in enumerate(batch.events)
    ]
    try:
        await db.events.insert_many(docs, ordered=False)
    except BulkWriteError as exc:
        if any(error.get("code") != 11000 for error in exc.details.get("writeErrors", [])):
            raise


@router.post("/ingest", dependencies=[Depends(require_gateway_token)])
async def ingest(batch: GatewayBatch, request: Request) -> dict[str, Any]:
    db = request.app.state.db
    metrics: Metrics = request.app.state.metrics
    received = datetime.now(UTC)
    _tag_span(gateway=batch.gateway, batch_id=batch.batch_id)

    # Time series collections cannot hold a unique index, so the batch id is claimed here first.
    try:
        await db.ingest_batches.insert_one(
            {
                "_id": batch.batch_id,
                "gateway": batch.gateway,
                "received_at": received,
                "n": len(batch.readings),
            }
        )
    except DuplicateKeyError:
        metrics.count("firstlight.ingest.duplicates", 1, [f"gateway:{batch.gateway}"])
        return {"stored": 0, "duplicate": True}

    try:
        if batch.events:
            await _store_events(db, batch, received)
        await db.readings.insert_many([_reading_doc(r, batch) for r in batch.readings], ordered=False)
    except Exception:
        await db.ingest_batches.delete_one({"_id": batch.batch_id})  # release the claim so the retry lands
        raise

    latest: dict[str, PondReading] = {}
    for r in batch.readings:
        if r.pond not in latest or r.ts > latest[r.pond].ts:
            latest[r.pond] = r
    await db.pond_state.bulk_write(
        [
            UpdateOne({"_id": r.pond}, _pond_state_update(r, batch.gateway), upsert=True)
            for r in latest.values()
        ],
        ordered=False,
    )

    for r in latest.values():
        tags = [f"farm:{r.farm}", f"pond:{r.pond}", f"gateway:{batch.gateway}"]
        metrics.gauge("firstlight.pond.do", r.do, tags)
        metrics.gauge("firstlight.pond.temp", r.temp, tags)
        metrics.gauge("firstlight.pond.ph", r.ph, tags)
        metrics.gauge("firstlight.pond.aerators_off", sum(1 for a in r.aer if a.on and a.amp < 0.5), tags)
    oldest = min(r.ts for r in batch.readings)
    metrics.count("firstlight.ingest.readings", len(batch.readings), [f"gateway:{batch.gateway}"])
    metrics.distribution(
        "firstlight.ingest.lag_seconds", (received - oldest).total_seconds(), [f"gateway:{batch.gateway}"]
    )
    return {"stored": len(batch.readings), "duplicate": False}
