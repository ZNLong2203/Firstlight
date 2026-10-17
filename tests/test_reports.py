from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from tests.conftest import DEMO_CODE

from firstlight.brain.reports import build, dawn_report_due, last_night


def test_last_night_is_the_one_that_ended_at_the_latest_dawn() -> None:
    # 08:30 in Vietnam (UTC+7) on 18 October: the night of 17 to 18 October.
    start, end, date = last_night(datetime(2026, 10, 18, 1, 30, tzinfo=UTC), 7)
    assert date == "2026-10-18"
    assert start == datetime(2026, 10, 17, 11, 0, tzinfo=UTC) and end == datetime(
        2026, 10, 17, 23, 0, tzinfo=UTC
    )
    # 05:00 local, before dawn: the night before is the last one that ended.
    assert last_night(datetime(2026, 10, 17, 22, 0, tzinfo=UTC), 7)[2] == "2026-10-17"


async def test_the_dawn_report_counts_the_night_once(api: tuple[httpx.AsyncClient, Any]) -> None:
    client, db = api
    start, end, date = last_night(datetime.now(UTC), 7)
    middle = start + timedelta(hours=6)
    await db.incidents.insert_many(
        [
            {
                "_id": "INC-0001",
                "farm": "BL-01",
                "status": "resolved",
                "opened_at": middle,
                "diagnosis": {"cause": "aerator_failure"},
                "metrics": {"min_do": 4.5},
                "at_risk": {"value_vnd": 900_000_000},
                "timeline": [],
            },
            {
                "_id": "INC-0002",
                "farm": "ST-01",
                "status": "dismissed",
                "opened_at": middle,
                "diagnosis": {"cause": "sensor_fault"},
                "timeline": [],
            },
        ]
    )
    minutes = [
        {
            "_id": {"pond": pond, "minute": middle + timedelta(minutes=m)},
            "farm": pond[:5],
            "minute": middle + timedelta(minutes=m),
            "do_min": do,
        }
        for pond, do in (("BL-01-A3", 3.8), ("ST-01-A2", 4.9))
        for m in range(10)
    ]
    await db.readings_1m.insert_many(minutes)

    reports = await build(db, start, end, date)
    estate = reports[0]["summary"]
    assert estate["incidents"] == 2 and estate["recovered"] == 1 and estate["false_alarms_stopped"] == 1
    assert estate["protected_vnd"] == 900_000_000 and estate["oxygen_safety"] == 0.5
    assert estate["lowest"] == {"pond": "BL-01-A3", "do": 3.8}
    assert "1 báo động giả đã chặn" in reports[0]["message_vi"]
    assert {r["farm"] for r in reports} == {"*", "BL-01", "ST-01"}

    assert await dawn_report_due(db, datetime.now(UTC), 7) is None, "already written for this night"
    latest = (await client.get("/v1/reports/latest")).json()
    assert latest["estate"]["date"] == date and [f["farm"] for f in latest["farms"]] == ["BL-01", "ST-01"]
    run = await client.post("/v1/reports/run", headers={"X-Demo-Code": DEMO_CODE})
    assert run.status_code == 200 and run.json()["estate"]["farm"] == "*"
