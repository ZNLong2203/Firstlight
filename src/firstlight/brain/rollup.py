"""Data lifecycle: raw readings → 1-minute rollups → 1-hour rollups, each with its own retention.

The minute rollups are a time series collection, like the readings: as a regular collection they took
149 bytes a row on disk, and 180 days of them outweighed everything else. `$merge` cannot write into a
time series collection, so the brain inserts each minute's rows itself. It rolls up every complete
minute after the newest one it has, oldest first, so a brain that was down catches up instead of
leaving a hole.
"""

from datetime import datetime, timedelta
from typing import Any

from pymongo.asynchronous.database import AsyncDatabase

Db = AsyncDatabase[dict[str, Any]]
SETTLE = timedelta(seconds=15)  # a minute is complete once its last batch has had time to land
CATCH_UP = timedelta(hours=1)  # at most this much history per cycle, so a long catch-up never stalls one
RAW_KEPT = timedelta(days=14)  # the readings' own retention: nothing older can be rolled up


def _minute(ts: datetime) -> datetime:
    return ts.replace(second=0, microsecond=0)


def minute_rollup(start: datetime, end: datetime) -> list[dict[str, Any]]:
    """One row per pond per minute for raw readings in [start, end), shaped for readings_1m."""
    return [
        {"$match": {"ts": {"$gte": start, "$lt": end}}},
        {
            "$group": {
                "_id": {"pond": "$meta.pond", "minute": {"$dateTrunc": {"date": "$ts", "unit": "minute"}}},
                "farm": {"$first": "$meta.farm"},
                "gateway": {"$first": "$meta.gateway"},
                "do_avg": {"$avg": "$do"},
                "do_min": {"$min": "$do"},
                "do_max": {"$max": "$do"},
                "temp": {"$avg": "$temp"},
                "ph": {"$avg": "$ph"},
                "n": {"$sum": 1},
            }
        },
        {
            "$project": {
                "_id": 0,
                "minute": "$_id.minute",
                "meta": {"pond": "$_id.pond", "farm": "$farm", "gateway": "$gateway"},
                "do_avg": {"$round": ["$do_avg", 3]},
                "do_min": 1,
                "do_max": 1,
                "temp": {"$round": ["$temp", 2]},
                "ph": {"$round": ["$ph", 3]},
                "n": 1,
            }
        },
    ]


async def roll_up_minutes(db: Db, now: datetime) -> int:
    """Insert the rollups of the complete minutes after the newest one stored. Returns the rows written."""
    complete = _minute(now - SETTLE)
    newest = await db.readings_1m.find_one({}, {"minute": 1}, sort=[("minute", -1)])
    since = newest["minute"] + timedelta(minutes=1) if newest else complete - RAW_KEPT
    # Start at the first reading, so a stretch with no data at all is skipped rather than retried.
    first = await db.readings.find_one(
        {"ts": {"$gte": max(since, complete - RAW_KEPT), "$lt": complete}}, {"ts": 1}, sort=[("ts", 1)]
    )
    if first is None:
        return 0
    start = _minute(first["ts"])
    end = min(complete, start + CATCH_UP)
    rows = await (await db.readings.aggregate(minute_rollup(start, end))).to_list()
    if rows:
        await db.readings_1m.insert_many(rows, ordered=False)
    return len(rows)


def hour_rollup(start: datetime, end: datetime) -> list[dict[str, Any]]:
    """Aggregate readings_1m in [start, end) into readings_1h, kept indefinitely."""
    return [
        {"$match": {"minute": {"$gte": start, "$lt": end}}},
        {
            "$group": {
                "_id": {"pond": "$meta.pond", "hour": {"$dateTrunc": {"date": "$minute", "unit": "hour"}}},
                "farm": {"$first": "$meta.farm"},
                "do_avg": {"$avg": "$do_avg"},
                "do_min": {"$min": "$do_min"},
                "do_max": {"$max": "$do_max"},
                "safe_minutes": {"$sum": {"$cond": [{"$gte": ["$do_min", 4.0]}, 1, 0]}},
                "minutes": {"$sum": 1},
            }
        },
        {"$set": {"hour": "$_id.hour", "do_avg": {"$round": ["$do_avg", 3]}}},
        {
            "$merge": {
                "into": "readings_1h",
                "on": "_id",
                "whenMatched": "replace",
                "whenNotMatched": "insert",
            }
        },
    ]
