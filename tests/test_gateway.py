import asyncio
import json
import random
from datetime import UTC, datetime

import httpx

from firstlight.edge.farms import build_farms
from firstlight.edge.gateway import Gateway


def make_client(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler, base_url="http://api")


async def test_gateway_stores_and_forwards_in_order() -> None:
    sent: list[str] = []
    fail = {"on": True}

    def handle(request: httpx.Request) -> httpx.Response:
        if fail["on"]:
            return httpx.Response(503)
        sent.append(request.read().decode())
        return httpx.Response(200, json={"stored": 4})

    gateway = Gateway(build_farms(1, 4)[0])
    rng = random.Random(1)
    async with make_client(httpx.MockTransport(handle)) as client:
        for _ in range(3):
            gateway.collect(datetime.now(UTC), rng)
            await gateway.flush(client)
        assert len(gateway.buffer) == 3 and not sent
        fail["on"] = False
        await gateway.flush(client)
    assert not gateway.buffer and len(sent) == 3
    assert [f":{n:08d}" in body for n, body in zip((1, 2, 3), sent, strict=True)] == [True, True, True]


async def test_offline_gateway_keeps_everything_and_batch_ids_survive_restart() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise AssertionError("an offline gateway must not send")

    farm = build_farms(1, 4)[0]
    gateway = Gateway(farm)
    gateway.online = False
    async with make_client(httpx.MockTransport(handle)) as client:
        gateway.collect(datetime.now(UTC), random.Random(2))
        await gateway.flush(client)
    assert len(gateway.buffer) == 1
    restarted = Gateway(farm)
    restarted.collect(datetime.now(UTC), random.Random(3))
    assert gateway.buffer[0]["batch_id"] != restarted.buffer[0]["batch_id"]


def test_commands_run_once_and_turn_the_standby_on() -> None:
    farm = build_farms(1, 4)[0]
    gateway = Gateway(farm)
    pond = farm.ponds[0]
    standby = pond.aerators[-1]
    command = {"id": "c1", "action": "aerator.on", "pond": pond.id, "device": standby.id}
    first = gateway.execute(command)
    assert first["status"] == "done" and standby.on and first["detail"]["turning"]
    standby.on = False
    assert gateway.execute(command) == first and not standby.on, "a repeated command is not run again"
    unknown = gateway.execute({"id": "c2", "action": "aerator.on", "pond": pond.id, "device": "AE-x"})
    assert unknown["status"] == "failed"
    assert gateway.execute({"id": "c3", "action": "generator.start"})["detail"] == {"generator": True}


def test_failsafe_starts_the_standby_only_without_the_cloud() -> None:
    farm = build_farms(1, 4)[0]
    gateway = Gateway(farm)
    pond = farm.ponds[1]
    pond.probe.stuck_at = 3.1  # the gateway only knows what the probe says
    rng = random.Random(4)
    gateway.collect(datetime.now(UTC), rng)
    assert not pond.aerators[-1].on, "the cloud is reachable, so it decides"

    gateway.online = False
    gateway.collect(datetime.now(UTC), rng)
    gateway.collect(datetime.now(UTC), rng)
    assert pond.aerators[-1].on
    events = gateway.buffer[1]["events"]
    expected = [("failsafe", pond.id, pond.aerators[-1].id)]
    assert [(e["kind"], e["pond"], e["device"]) for e in events] == expected
    assert gateway.buffer[2]["events"] == [], "an event is reported once"


async def test_command_channel_executes_and_acknowledges() -> None:
    farm = build_farms(1, 4)[0]
    gateway = Gateway(farm)
    pond = farm.ponds[2]
    standby = pond.aerators[-1]
    command = {"id": "c9", "action": "aerator.on", "pond": pond.id, "device": standby.id}
    acks: list[dict[str, object]] = []
    stop = asyncio.Event()

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            body = f"event: tick\ndata: {{}}\n\nevent: command\ndata: {json.dumps(command)}\n\n"
            return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
        acks.append({"path": request.url.path, **json.loads(request.read())})
        stop.set()
        return httpx.Response(200, json={"status": "done"})

    async with make_client(httpx.MockTransport(handle)) as client:
        await asyncio.wait_for(gateway.listen(client, stop), timeout=5)
    assert standby.on
    assert acks[0]["path"] == "/v1/commands/c9/ack" and acks[0]["status"] == "done"
    assert acks[0]["gateway"] == gateway.id
