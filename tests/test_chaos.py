import random
from datetime import UTC, datetime
from typing import Any

import httpx
from tests.conftest import DEMO_CODE, TOKEN

from firstlight.api.app import app
from firstlight.edge.control import control_app
from firstlight.edge.farms import build_farms
from firstlight.edge.gateway import Gateway
from firstlight.edge.world import World

DEMO = {"X-Demo-Code": DEMO_CODE}


async def test_chaos_panel_breaks_the_world_and_keeps_the_ground_truth(
    api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, db = api
    farms = build_farms(2, 4)
    world = World(farms, [Gateway(farm) for farm in farms])
    app.state.edge = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=control_app(world, TOKEN)),
        base_url="http://edge",
        headers={"X-Gateway-Token": TOKEN},
    )

    assert (
        await client.post("/v1/chaos", json={"kind": "aerator_trip", "pond": "BL-01-A3"})
    ).status_code == 403
    tripped = (
        await client.post("/v1/chaos", json={"kind": "aerator_trip", "pond": "BL-01-A3"}, headers=DEMO)
    ).json()
    assert tripped["status"] == "active" and tripped["gateway"] == "GW-BL01-1"
    aerator = next(a for a in world.ponds["BL-01-A3"].aerators if a.id == tripped["device"])
    assert aerator.failed

    missing = await client.post("/v1/chaos", json={"kind": "aerator_trip", "pond": "XX-01-A1"}, headers=DEMO)
    assert missing.status_code == 404 and await db.chaos.count_documents({}) == 1

    cleared = (await client.delete(f"/v1/chaos/{tripped['_id']}", headers=DEMO)).json()
    assert cleared["status"] == "cleared" and not aerator.failed

    offline = (
        await client.post("/v1/chaos", json={"kind": "gateway_offline", "gateway": "GW-ST01-1"}, headers=DEMO)
    ).json()
    world.clear(offline["_id"])  # as if the simulator restarted and forgot it
    listed = (await client.get("/v1/chaos", headers=DEMO)).json()
    assert [(f["_id"], f["status"]) for f in listed if f["_id"] == offline["_id"]] == [
        (offline["_id"], "cleared")
    ]


async def test_gateway_events_are_stored_once(api: tuple[httpx.AsyncClient, Any]) -> None:
    client, db = api
    farm = build_farms(1, 4)[0]
    gateway = Gateway(farm)
    gateway.online = False
    farm.ponds[0].probe.stuck_at = 3.0
    gateway.collect(datetime.now(UTC), random.Random(1))
    batch = {**gateway.buffer[0], "sent_at": datetime.now(UTC).isoformat()}
    for _ in range(2):
        assert (await client.post("/v1/ingest", json=batch)).status_code == 200
    events = await db.events.find({}).to_list()
    assert [(e["kind"], e["pond"]) for e in events] == [("failsafe", farm.ponds[0].id)]
