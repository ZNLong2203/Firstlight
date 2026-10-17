import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from tests.conftest import TOKEN

from firstlight.edge.farms import build_farms
from firstlight.edge.gateway import Gateway


def command(gateway: str, pond: str, device: str, **extra: Any) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "gateway": gateway,
        "pond": pond,
        "device": device,
        "action": "aerator.on",
        "incident": "INC-0001",
        "status": "pending",
        "attempts": 0,
        "created_at": now,
        "deliver_by": now + timedelta(minutes=2),
        "expires_at": now + timedelta(days=7),
        **extra,
    }


async def wait_for_status(db: Any, query: dict[str, Any], status: str) -> dict[str, Any]:
    for _ in range(100):
        doc = await db.commands.find_one(query)
        if doc and doc["status"] == status:
            return doc  # type: ignore[no-any-return]
        await asyncio.sleep(0.1)
    raise AssertionError(f"command never reached {status}: {doc}")


async def test_a_gateway_runs_a_command_from_the_bus_and_acknowledges_it(
    api: tuple[httpx.AsyncClient, Any], live_api: str
) -> None:
    _, db = api
    farm = build_farms(1, 4)[0]
    gateway = Gateway(farm)
    pond = farm.ponds[2]
    standby = pond.aerators[-1]
    await db.incidents.insert_one({"_id": "INC-0001", "timeline": []})
    # Created while the gateway was away: delivered from the backlog when it connects.
    early = (await db.commands.insert_one(command(gateway.id, pond.id, standby.id))).inserted_id

    stop = asyncio.Event()
    headers = {"X-Gateway-Token": TOKEN}
    async with httpx.AsyncClient(base_url=live_api, headers=headers) as client:
        listener = asyncio.create_task(gateway.listen(client, stop))
        done = await wait_for_status(db, {"_id": early}, "done")
        assert standby.on and done["result"]["turning"] and done["acked_at"] >= done["created_at"]

        # Created while connected: delivered through the change stream.
        later = (
            await db.commands.insert_one(command(gateway.id, pond.id, standby.id, action="aerator.off"))
        ).inserted_id
        await wait_for_status(db, {"_id": later}, "done")
        assert not standby.on
        stop.set()
        await asyncio.wait_for(listener, timeout=15)

    timeline = (await db.incidents.find_one({"_id": "INC-0001"}))["timeline"]
    assert [entry["kind"] for entry in timeline] == ["action_done", "action_done"]


async def test_acks_are_idempotent_and_scoped_to_their_gateway(api: tuple[httpx.AsyncClient, Any]) -> None:
    client, db = api
    oid = (await db.commands.insert_one(command("GW-BL01-1", "BL-01-A1", "AE-BL-01-A1-S"))).inserted_id
    body = {"gateway": "GW-BL01-1", "status": "done", "executed_at": datetime.now(UTC).isoformat()}
    wrong = await client.post(f"/v1/commands/{oid}/ack", json={**body, "gateway": "GW-ST01-1"})
    assert wrong.status_code == 404
    first = await client.post(f"/v1/commands/{oid}/ack", json=body)
    again = await client.post(f"/v1/commands/{oid}/ack", json={**body, "status": "failed"})
    assert first.json() == {"status": "done", "duplicate": False}
    assert again.json() == {"status": "done", "duplicate": True}
    assert (await client.post("/v1/commands/not-an-id/ack", json=body)).status_code == 404
