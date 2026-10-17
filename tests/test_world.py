import random
from datetime import UTC, datetime

import httpx
import pytest

from firstlight.core.models import FaultRequest
from firstlight.edge.control import control_app
from firstlight.edge.farms import build_farms
from firstlight.edge.gateway import Gateway
from firstlight.edge.world import UnknownTarget, World

NOW = datetime.now(UTC)


def make_world() -> World:
    farms = build_farms(2, 4)
    return World(farms, [Gateway(farm) for farm in farms])


def settle(world: World, minutes: int, rng: random.Random) -> None:
    for _ in range(minutes):
        for farm in world.farms.values():
            farm.step(2.0, 60, rng)


def test_aerator_trip_fails_the_largest_running_aerator_and_clearing_repairs_it() -> None:
    world = make_world()
    pond = world.ponds["BL-01-A3"]
    view = world.apply(FaultRequest(id="CH-1", kind="aerator_trip", pond=pond.id), NOW)
    main = max((a for a in pond.aerators if not a.standby), key=lambda a: a.kla)
    assert view.device == main.id and main.failed
    assert (view.farm, view.gateway) == ("BL-01", "GW-BL01-1")
    assert world.apply(FaultRequest(id="CH-1", kind="aerator_trip", pond=pond.id), NOW) == view

    pond.aerators[-1].on = True  # Firstlight started the standby meanwhile
    world.clear("CH-1")
    assert not main.failed and not pond.aerators[-1].on and world.faults == []


def test_fouling_builds_up_over_minutes_and_cleaning_resets_it() -> None:
    world = make_world()
    rng = random.Random(1)
    pond = world.ponds["BL-01-A1"]
    settle(world, 300, rng)
    world.apply(FaultRequest(id="CH-2", kind="probe_fouling", pond=pond.id), NOW)
    settle(world, 2, rng)
    two_minutes = pond.probe.read(pond.do, rng)[0]
    settle(world, 4, rng)
    assert pond.probe.read(pond.do, rng)[0] < two_minutes < pond.do
    assert pond.do > 4.0, "the water itself is fine"
    world.clear("CH-2")
    assert pond.probe.fouling == 0.0


def test_power_outage_stops_every_aerator_on_the_farm_until_the_generator_runs() -> None:
    world = make_world()
    rng = random.Random(2)
    world.apply(FaultRequest(id="CH-3", kind="power_outage", farm="BL-01"), NOW)
    settle(world, 1, rng)
    assert all(not p.powered and p.kla == 0 for p in world.farms["BL-01"].ponds)
    assert all(p.powered for p in world.farms["ST-01"].ponds)
    world.farms["BL-01"].generator_running = True
    settle(world, 1, rng)
    assert all(p.powered for p in world.farms["BL-01"].ponds)


def test_gateway_offline_and_unknown_targets() -> None:
    world = make_world()
    view = world.apply(FaultRequest(id="CH-4", kind="gateway_offline", gateway="GW-ST01-1"), NOW)
    assert view.farm == "ST-01" and not world.gateways["GW-ST01-1"].online
    world.clear("CH-4")
    assert world.gateways["GW-ST01-1"].online
    with pytest.raises(UnknownTarget):
        world.apply(FaultRequest(id="CH-5", kind="aerator_trip", pond="XX-99-A1"), NOW)
    with pytest.raises(UnknownTarget):
        world.apply(FaultRequest(id="CH-6", kind="probe_fouling", farm="BL-01"), NOW)


async def test_control_port_injects_and_clears_with_the_token() -> None:
    world = make_world()
    transport = httpx.ASGITransport(app=control_app(world, "secret"))
    async with httpx.AsyncClient(transport=transport, base_url="http://edge") as client:
        body = {"id": "CH-7", "kind": "aerator_trip", "pond": "BL-01-A2"}
        assert (await client.post("/faults", json=body)).status_code == 401
        headers = {"X-Gateway-Token": "secret"}
        injected = await client.post("/faults", json=body, headers=headers)
        assert injected.status_code == 200 and injected.json()["device"].startswith("AE-BL-01-A2-")
        missing = await client.post("/faults", json={**body, "id": "CH-8", "pond": "nope"}, headers=headers)
        assert missing.status_code == 404
        assert [f["id"] for f in (await client.get("/faults", headers=headers)).json()] == ["CH-7"]
        assert (await client.delete("/faults/CH-7", headers=headers)).status_code == 200
        assert (await client.delete("/faults/CH-7", headers=headers)).status_code == 404
