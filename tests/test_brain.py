from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from firstlight.brain.forecast import classify, forecast_pipeline
from firstlight.brain.main import forecast_once
from firstlight.brain.rollup import minute_rollup
from firstlight.core.config import get_settings
from firstlight.core.metrics import Metrics

NOW = datetime.now(UTC).replace(microsecond=0)


def readings(pond: str, start_do: float, per_minute: float, minutes: int = 12) -> list[dict[str, Any]]:
    out = []
    for i in range(minutes * 6):
        ts = NOW - timedelta(seconds=10 * (minutes * 6 - 1 - i))
        out.append(
            {
                "ts": ts,
                "meta": {"farm": "BL-01", "pond": pond, "gateway": "GW-BL01-1"},
                "do": round(start_do + per_minute * i / 6, 3),
                "temp": 28.0,
                "ph": 7.9,
            }
        )
    return out


def test_classify_covers_every_status() -> None:
    last = {"do": 5.0, "aerators_on": 3, "aerators_running": 3}
    assert classify(last, None, 5) == "ok"
    assert classify(last, 45, 5) == "watch"
    assert classify({**last, "aerators_running": 2}, None, 5) == "watch"
    assert classify(last, 20, 5) == "alert"
    assert classify({**last, "do": 2.8}, None, 5) == "alert"
    assert classify(last, None, 120) == "blind"
    assert classify(None, None, float("inf")) == "blind"


async def test_forecast_pipeline_finds_the_falling_pond(api: tuple[httpx.AsyncClient, Any]) -> None:
    _, db = api
    await db.readings.insert_many(
        readings("flat", 5.0, 0.0) + readings("falling", 5.0, -0.05) + readings("rising", 4.0, 0.03)
    )
    result = {
        r["_id"]: r async for r in await db.readings.aggregate(forecast_pipeline(NOW - timedelta(minutes=12)))
    }
    falling = result["falling"]
    expected = (falling["do"] - 3.0) / 0.05
    assert falling["slope_per_min"] == pytest.approx(-0.05, rel=0.02)
    assert falling["minutes_to_hypoxia"] == pytest.approx(expected, rel=0.05)
    assert result["flat"]["minutes_to_hypoxia"] is None
    assert result["rising"]["minutes_to_hypoxia"] is None


async def test_minute_rollup_is_correct_and_idempotent(api: tuple[httpx.AsyncClient, Any]) -> None:
    _, db = api
    start = (NOW - timedelta(minutes=3)).replace(second=0)
    docs = [
        {
            "ts": start + timedelta(seconds=10 * i),
            "meta": {"farm": "BL-01", "pond": "p1", "gateway": "g"},
            "do": 4.0 + i * 0.1,
            "temp": 28.0,
            "ph": 7.9,
        }
        for i in range(6)
    ]
    await db.readings.insert_many(docs)
    for _ in range(2):
        await (await db.readings.aggregate(minute_rollup(start, start + timedelta(minutes=1)))).to_list()
    rows = await db.readings_1m.find({}).to_list()
    assert len(rows) == 1
    assert rows[0]["n"] == 6 and rows[0]["do_min"] == 4.0 and rows[0]["do_max"] == pytest.approx(4.5)
    assert rows[0]["do_avg"] == pytest.approx(4.25)


async def test_forecast_once_writes_status_and_forecast(api: tuple[httpx.AsyncClient, Any]) -> None:
    _, db = api
    await db.readings.insert_many(readings("BL-01-A3", 4.8, -0.06))
    await db.pond_state.insert_many(
        [
            {
                "_id": "BL-01-A3",
                "farm": "BL-01",
                "gateway": "GW-BL01-1",
                "last": {"ts": NOW, "do": 4.15, "aerators_on": 2, "aerators_running": 1},
            },
            {
                "_id": "BL-01-A4",
                "farm": "BL-01",
                "gateway": "GW-BL01-1",
                "last": {
                    "ts": NOW - timedelta(minutes=5),
                    "do": 5.0,
                    "aerators_on": 2,
                    "aerators_running": 2,
                },
            },
        ]
    )
    counts = await forecast_once(db, Metrics(get_settings()), NOW)
    a3 = await db.pond_state.find_one({"_id": "BL-01-A3"})
    a4 = await db.pond_state.find_one({"_id": "BL-01-A4"})
    assert a3["status"] == "alert" and 0 < a3["forecast"]["minutes_to_hypoxia"] < 30
    assert a4["status"] == "blind" and a4["freshness_s"] == pytest.approx(300, abs=1)
    assert counts == {"alert": 1, "blind": 1}


async def test_forecast_restarts_when_an_aerator_stops(api: tuple[httpx.AsyncClient, Any]) -> None:
    """Ten flat minutes with three aerators, then one stops and DO falls: the slope must be the new one."""
    _, db = api
    docs = []
    for i in range(72):
        ts = NOW - timedelta(seconds=10 * (71 - i))
        after = i >= 60  # the last two minutes
        aer = [{"id": f"a{k}", "on": True, "amp": 0.0 if after and k == 0 else 6.0} for k in range(3)]
        do = 5.0 - (0.05 * (i - 60) / 6 if after else 0.0)
        docs.append({"ts": ts, "meta": {"farm": "BL-01", "pond": "p", "gateway": "g"}, "do": do, "aer": aer})
    await db.readings.insert_many(docs)
    result = await (await db.readings.aggregate(forecast_pipeline(NOW - timedelta(minutes=12)))).to_list()
    assert result[0]["slope_per_min"] == pytest.approx(-0.05, rel=0.05)
    assert result[0]["points"] == 12 and 30 < result[0]["minutes_to_hypoxia"] < 45
    assert result[0]["rate_3m"] == pytest.approx(-0.05, rel=0.1)
