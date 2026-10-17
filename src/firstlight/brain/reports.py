"""The dawn report: at 06:00 on the farm clock, what the night held, for the estate and for each farm.

"Sleep through the night, read the report in the morning." One document per farm per night in `reports`
(unique on farm and date), plus one for the whole estate under farm "*". Numbers come from the
incidents of the night and the one-minute rollups, so the report can be rebuilt at any time.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from pymongo import ReplaceOne
from pymongo.asynchronous.database import AsyncDatabase

from firstlight.brain.forecast import HYPOXIA_MGL, SAFE_MGL

Doc = dict[str, Any]
NIGHT_HOURS = 12
DAWN_HOUR = 6
READY_AFTER = timedelta(minutes=5)  # let the last minute rollups land first
POND_CAUSES = ("aerator_failure", "power_outage")


def last_night(now: datetime, offset_hours: float) -> tuple[datetime, datetime, str]:
    """The most recent night that has ended: its start and end in UTC, and the date of its dawn."""
    offset = timedelta(hours=offset_hours)
    local = now + offset
    dawn = local.replace(hour=DAWN_HOUR, minute=0, second=0, microsecond=0)
    if local < dawn:
        dawn -= timedelta(days=1)
    return dawn - timedelta(hours=NIGHT_HOURS) - offset, dawn - offset, dawn.date().isoformat()


def pond_minutes_pipeline(start: datetime, end: datetime) -> list[Doc]:
    """For each pond over the night: its lowest DO, and how many minutes it spent under 4 mg/L."""
    return [
        {"$match": {"minute": {"$gte": start, "$lt": end}}},
        {
            "$group": {
                "_id": "$_id.pond",
                "farm": {"$first": "$farm"},
                "min_do": {"$min": "$do_min"},
                "below_safe": {"$sum": {"$cond": [{"$lt": ["$do_min", SAFE_MGL]}, 1, 0]}},
                "minutes": {"$sum": 1},
            }
        },
    ]


def _summary(incidents: list[Doc], ponds: list[Doc]) -> Doc:
    causes: dict[str, int] = {}
    for incident in incidents:
        cause = (incident.get("diagnosis") or {}).get("cause", "unknown")
        causes[cause] = causes.get(cause, 0) + 1
    protected = [
        i
        for i in incidents
        if (i.get("diagnosis") or {}).get("cause") in POND_CAUSES
        and i.get("status") == "resolved"
        and ((i.get("metrics") or {}).get("min_do") or 0) >= HYPOXIA_MGL
    ]
    minutes = sum(p["minutes"] for p in ponds)
    below = sum(p["below_safe"] for p in ponds)
    lowest = min(ponds, key=lambda p: p["min_do"], default=None)
    return {
        "incidents": len(incidents),
        "by_cause": causes,
        "recovered": sum(1 for i in incidents if i.get("status") == "resolved"),
        "false_alarms_stopped": sum(1 for i in incidents if i.get("status") == "dismissed"),
        "escalated": sum(
            1 for i in incidents if any(e["kind"] == "escalated" for e in i.get("timeline", []))
        ),
        "protected_vnd": sum((i.get("at_risk") or {}).get("value_vnd", 0) for i in protected),
        "oxygen_safety": round(1 - below / minutes, 4) if minutes else None,
        "pond_minutes": minutes,
        "lowest": {"pond": lowest["_id"], "do": round(lowest["min_do"], 2)} if lowest else None,
    }


def message_vi(report: Doc) -> str:
    """The estate's night in two lines of Vietnamese, for the owner's phone."""
    s = report["summary"]
    protected = (
        f", giữ an toàn khoảng {s['protected_vnd'] / 1e9:.1f} tỷ đồng tôm" if s["protected_vnd"] else ""
    )
    safety = (
        f" Oxy an toàn {s['oxygen_safety'] * 100:.1f}% thời gian." if s["oxygen_safety"] is not None else ""
    )
    if not s["incidents"]:
        return f"Báo cáo bình minh {report['date']}: đêm qua yên ổn, không có sự cố.{safety}"
    return (
        f"Báo cáo bình minh {report['date']}: {s['incidents']} sự cố, {s['recovered']} đã hồi phục, "
        f"{s['false_alarms_stopped']} báo động giả đã chặn{protected}.{safety}"
    )


async def build(db: AsyncDatabase[Doc], start: datetime, end: datetime, date: str) -> list[Doc]:
    incidents = await db.incidents.find(
        {"opened_at": {"$gte": start, "$lt": end}},
        {"embedding": 0, "memory_text": 0, "investigation.tool_calls": 0},
    ).to_list()
    ponds = await (await db.readings_1m.aggregate(pond_minutes_pipeline(start, end))).to_list()
    made_at = datetime.now(UTC)
    reports = [
        {
            "_id": f"*:{date}",
            "farm": "*",
            "date": date,
            "night": {"start": start, "end": end},
            "summary": _summary(incidents, ponds),
            "incidents": [i["_id"] for i in incidents],
            "made_at": made_at,
        }
    ]
    reports[0]["message_vi"] = message_vi(reports[0])
    farms: set[str] = {str(p["farm"]) for p in ponds if p.get("farm")}
    for farm in sorted(farms):
        farm_ponds = [p for p in ponds if p.get("farm") == farm]
        farm_incidents = [i for i in incidents if i.get("farm") == farm]
        if not farm_incidents and not any(p["below_safe"] for p in farm_ponds):
            continue  # a quiet farm needs no page of its own
        reports.append(
            {
                "_id": f"{farm}:{date}",
                "farm": farm,
                "date": date,
                "night": {"start": start, "end": end},
                "summary": _summary(farm_incidents, farm_ponds),
                "incidents": [i["_id"] for i in farm_incidents],
                "ponds": sorted(
                    (
                        {"pond": p["_id"], "min_do": round(p["min_do"], 2), "below_safe_min": p["below_safe"]}
                        for p in farm_ponds
                    ),
                    key=lambda p: p["pond"],
                ),
                "made_at": made_at,
            }
        )
    await db.reports.bulk_write([ReplaceOne({"_id": r["_id"]}, r, upsert=True) for r in reports])
    return reports


async def dawn_report_due(db: AsyncDatabase[Doc], now: datetime, offset_hours: float) -> list[Doc] | None:
    """Build last night's report once, a few minutes after dawn on the farm clock."""
    start, end, date = last_night(now, offset_hours)
    if now < end + READY_AFTER or await db.reports.find_one({"_id": f"*:{date}"}, {"_id": 1}):
        return None
    return await build(db, start, end, date)
