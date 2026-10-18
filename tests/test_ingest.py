import random
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from pymongo.errors import WriteError

from firstlight.core import config
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


async def test_a_pond_left_out_of_the_manifest_is_retired(api: tuple[httpx.AsyncClient, Any]) -> None:
    """Otherwise a pond taken out of service would look silent, and blind, forever."""
    client, db = api
    url = f"/v1/gateways/{FARM.gateway}/manifest"
    full = FARM.manifest()
    assert (await client.put(url, json=full.model_dump(mode="json"))).status_code == 200
    smaller = full.model_copy(update={"ponds": full.ponds[:2]})
    assert (await client.put(url, json=smaller.model_dump(mode="json"))).status_code == 200
    kept = {p.id for p in smaller.ponds}
    assert {s["_id"] async for s in db.pond_state.find({"gateway": FARM.gateway})} == kept
    assert {d["pond"] async for d in db.devices.find({"type": {"$ne": "gateway"}})} == kept
    assert await db.devices.find_one({"_id": FARM.gateway}) is not None


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


async def test_release_1_4_finds_duplicates_by_gateway_and_sequence(
    api: tuple[httpx.AsyncClient, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = api
    monkeypatch.setenv("INGEST_DUPLICATE_CHECK", "fields")
    config.get_settings.cache_clear()
    gateway = Gateway(FARM)
    first = batch(gateway, datetime.now(UTC))
    assert (await client.post("/v1/ingest", json=first)).json()["stored"] == 4
    resent = {**first, "batch_id": first["batch_id"] + "-again"}  # same gateway and sequence number
    assert (await client.post("/v1/ingest", json=resent)).json() == {"stored": 0, "duplicate": True}
    claim = await db.ingest_batches.find_one({"_id": first["batch_id"]})
    assert claim["seq"] == first["seq"]


async def test_every_api_start_is_recorded_as_a_deployment(api: tuple[httpx.AsyncClient, Any]) -> None:
    _, db = api
    deployment = await db.deployments.find_one({"service": "firstlight-api"})
    assert deployment["version"] == config.get_settings().dd_version
    assert deployment["config"] == {"ingest_duplicate_check": "id"}
