import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from firstlight.api.app import app
from firstlight.api.live import RECONNECT, Hub
from firstlight.brain.reports import current_night


def test_hub_coalesces_and_drops_stuck_consoles() -> None:
    hub = Hub()
    fast, stuck = hub.subscribe(), hub.subscribe()
    for _ in range(50):
        stuck.put_nowait("x")  # a console that stopped reading
    hub.offer({"_id": "A1", "status": "ok"})
    hub.offer({"_id": "A1", "status": "watch"})
    hub.offer({"_id": "A2", "status": "ok"})
    hub.flush()
    event, data = fast.get_nowait().split("\n")[:2]
    items = json.loads(data.removeprefix("data: "))
    assert event == "event: ponds"
    assert {p["_id"]: p["status"] for p in items} == {"A1": "watch", "A2": "ok"}
    assert hub.subscribers == 1
    assert stuck.qsize() == 1 and stuck.get_nowait() == RECONNECT


async def test_change_stream_reaches_subscribers(api: tuple[httpx.AsyncClient, Any]) -> None:
    _, db = api
    queue = app.state.hub.subscribe()
    await asyncio.sleep(1)  # let the change stream open
    await db.pond_state.update_one(
        {"_id": "BL-01-A3"}, {"$set": {"farm": "BL-01", "status": "alert"}}, upsert=True
    )
    message = await asyncio.wait_for(queue.get(), timeout=10)
    assert '"BL-01-A3"' in message and '"alert"' in message


async def test_ponds_and_history(api: tuple[httpx.AsyncClient, Any]) -> None:
    client, db = api
    now = datetime.now(UTC).replace(microsecond=0)
    await db.pond_state.insert_one({"_id": "BL-01-A1", "farm": "BL-01", "status": "ok", "last": {"ts": now}})
    await db.readings.insert_many(
        [
            {
                "ts": now - timedelta(seconds=10 * i),
                "meta": {"farm": "BL-01", "pond": "BL-01-A1", "gateway": "g"},
                "do": 5.0,
                "temp": 28.0,
                "ph": 7.9,
                "aer": [{"id": "a", "on": True, "amp": 6.0}, {"id": "b", "on": True, "amp": 0.0}],
            }
            for i in range(12)
        ]
    )
    ponds = (await client.get("/v1/ponds")).json()
    assert [p["_id"] for p in ponds] == ["BL-01-A1"] and ponds[0]["status"] == "ok"
    rows = (await client.get("/v1/ponds/BL-01-A1/history?minutes=30")).json()
    assert len(rows) == 12 and rows[0]["ts"] < rows[-1]["ts"] and rows[0]["running"] == 1
    # Longer spans come from the minute rollups.
    await db.readings_1m.insert_many(
        [
            {
                "minute": now.replace(second=0) - timedelta(minutes=m),
                "meta": {"farm": "BL-01", "pond": "BL-01-A1", "gateway": "g"},
                "do_avg": 5.0 - m / 100,
                "do_min": 4.9,
                "do_max": 5.1,
            }
            for m in (300, 200, 100)
        ]
    )
    rows = (await client.get("/v1/ponds/BL-01-A1/history?minutes=600")).json()
    assert [r["do"] for r in rows] == [2.0, 3.0, 4.0] and rows[0]["ts"] < rows[-1]["ts"]
    assert (await client.get("/v1/ponds/nope")).status_code == 404
    assert (await client.get("/v1/meta")).json()["farm_clock_offset_hours"] == 7.0


async def test_the_night_curve_steps_through_the_minute_rollups(api: tuple[httpx.AsyncClient, Any]) -> None:
    client, db = api
    start, end = current_night(datetime.now(UTC), 7.0)
    await db.readings_1m.insert_many(
        [
            {
                "minute": start + timedelta(minutes=m),
                "meta": {"farm": "BL-01", "pond": pond, "gateway": "g"},
                "do_avg": do,
                "do_min": do - 0.2,
            }
            for m in (0, 5, 12)
            for pond, do in (("BL-01-A1", 5.0), ("BL-01-A2", 4.0))
        ]
    )
    body = (await client.get("/v1/night")).json()
    assert datetime.fromisoformat(body["start"]) == start and datetime.fromisoformat(body["end"]) == end
    first, second = body["buckets"]  # minutes 0 and 5 share the first ten minutes; 12 starts the next
    assert first["min"] == 3.8 and first["p10"] == 4.0 and 4.0 <= first["median"] <= 5.0
    assert datetime.fromisoformat(second["t"]) == start + timedelta(minutes=10)


def test_hub_sends_each_kind_as_its_own_event() -> None:
    hub = Hub()
    queue = hub.subscribe()
    hub.offer({"_id": "A1", "status": "ok"})
    hub.offer({"_id": "INC-0001", "status": "mitigating"}, "incidents")
    hub.flush()
    events = sorted(queue.get_nowait().split("\n")[0] for _ in range(2))
    assert events == ["event: incidents", "event: ponds"]
