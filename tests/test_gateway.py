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
