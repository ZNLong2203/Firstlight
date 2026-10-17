"""Data lifecycle: raw readings → 1-minute rollups → 1-hour rollups, each with its own retention."""

from datetime import datetime
from typing import Any


def minute_rollup(start: datetime, end: datetime) -> list[dict[str, Any]]:
    """Aggregate raw readings in [start, end) into readings_1m. Re-running a window replaces it."""
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
            "$set": {
                "minute": "$_id.minute",
                "do_avg": {"$round": ["$do_avg", 3]},
                "temp": {"$round": ["$temp", 2]},
                "ph": {"$round": ["$ph", 3]},
            }
        },
        {
            "$merge": {
                "into": "readings_1m",
                "on": "_id",
                "whenMatched": "replace",
                "whenNotMatched": "insert",
            }
        },
    ]


def hour_rollup(start: datetime, end: datetime) -> list[dict[str, Any]]:
    """Aggregate readings_1m in [start, end) into readings_1h, kept indefinitely."""
    return [
        {"$match": {"minute": {"$gte": start, "$lt": end}}},
        {
            "$group": {
                "_id": {"pond": "$_id.pond", "hour": {"$dateTrunc": {"date": "$minute", "unit": "hour"}}},
                "farm": {"$first": "$farm"},
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
