import random
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from pymongo.errors import WriteError

from firstlight.edge.farms import build_farms
from firstlight.edge.gateway import Gateway

FARM = build_farms(1, 4)[0]


def batch(gateway: Gateway, ts: datetime) -> dict[str, Any]:
    gateway.collect(ts, random.Random(gateway.seq))
    return {**gateway.buffer.pop(), "sent_at": ts.isoformat()}


async def test_schema_is_time_series_with_ttl_and_validated_devices(
    api: tuple[httpx.AsyncClient, Any],
) -> None:
    _, db = api
    info = {c["name"]: c for c in await (await db.list_collections()).to_list()}
    assert info["readings"]["type"] == "timeseries"
    assert info["readings"]["options"]["expireAfterSeconds"] == 14 * 86_400
    assert info["readings"]["options"]["timeseries"]["metaField"] == "meta"
    with pytest.raises(WriteError):
        await db.devices.insert_one({"_id": "AE-bad", "type": "aerator", "farm": "BL-01"})


async def test_manifest_registers_devices_and_seeds_pond_state(api: tuple[httpx.AsyncClient, Any]) -> None:
    client, db = api
    response = await client.put(
        f"/v1/gateways/{FARM.gateway}/manifest", json=FARM.manifest().model_dump(mode="json")
    )
    assert response.status_code == 200
    aerators = sum(len(p.aerators) for p in FARM.ponds)
    assert await db.devices.count_documents({"type": "aerator"}) == aerators
    gateway = await db.devices.find_one({"_id": FARM.gateway})
    assert gateway["location"]["type"] == "Point"
    pond = await db.pond_state.find_one({"_id": FARM.ponds[0].id})
    assert pond["standby"] == [a.id for a in FARM.ponds[0].aerators if a.standby]


async def test_ingest_stores_once_and_never_rewinds_pond_state(api: tuple[httpx.AsyncClient, Any]) -> None:
    client, db = api
    gateway = Gateway(FARM)
    now = datetime.now(UTC).replace(microsecond=0)

    fresh = batch(gateway, now)
    first = await client.post("/v1/ingest", json=fresh)
    assert first.json() == {"stored": 4, "duplicate": False}
    again = await client.post("/v1/ingest", json=fresh)
    assert again.json() == {"stored": 0, "duplicate": True}
    assert await db.readings.count_documents({}) == 4

    late = batch(gateway, now - timedelta(minutes=5))  # backlog arriving after newer data
    assert (await client.post("/v1/ingest", json=late)).json()["stored"] == 4
    state = await db.pond_state.find_one({"_id": FARM.ponds[0].id})
    assert state["last"]["ts"].replace(tzinfo=UTC) == now
    assert await db.readings.count_documents({"meta.pond": FARM.ponds[0].id}) == 2


async def test_ingest_rejects_a_wrong_token(api: tuple[httpx.AsyncClient, Any]) -> None:
    client, _ = api
    response = await client.post(
        "/v1/ingest", json=batch(Gateway(FARM), datetime.now(UTC)), headers={"X-Gateway-Token": "nope"}
    )
    assert response.status_code == 401
