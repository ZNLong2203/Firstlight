"""Read-only tools the investigator may call. Each returns a small JSON-able summary, never raw rows."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from google.genai import types
from pymongo.asynchronous.database import AsyncDatabase

Db = AsyncDatabase[dict[str, Any]]


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, datetime) else value


async def pond_readings(db: Db, pond: str, minutes: int = 20) -> dict[str, Any]:
    """Per-minute DO (mean and minimum), pH, aerators turning and probe signal quality of one pond."""
    minutes = max(5, min(int(minutes), 60))
    since = datetime.now(UTC) - timedelta(minutes=minutes)
    turning = {
        "$size": {"$filter": {"input": {"$ifNull": ["$aer", []]}, "cond": {"$gte": ["$$this.amp", 0.5]}}}
    }
    pipeline: list[dict[str, Any]] = [
        {"$match": {"meta.pond": pond, "ts": {"$gte": since}}},
        {
            "$group": {
                "_id": {"$dateTrunc": {"date": "$ts", "unit": "minute"}},
                "do": {"$avg": "$do"},
                "do_min": {"$min": "$do"},
                "ph": {"$avg": "$ph"},
                "aerators_turning": {"$min": turning},
                "probe_quality": {"$min": "$probe.q"},
            }
        },
        {"$sort": {"_id": 1}},
    ]
    rows = [
        {
            "minute": _iso(r["_id"]),
            "do": round(r["do"], 2),
            "do_min": round(r["do_min"], 2),
            "ph": round(r["ph"], 2),
            "aerators_turning": r["aerators_turning"],
            "probe_quality": r["probe_quality"],
        }
        async for r in await db.readings.aggregate(pipeline)
    ]
    return {"pond": pond, "minutes": rows}


async def gateway_status(db: Db, gateway: str) -> dict[str, Any]:
    """How fresh each pond of a gateway is, when its last batch arrived, and what it did on its own."""
    now = datetime.now(UTC)
    ponds = [
        {
            "pond": s["_id"],
            "last_reading_age_s": round((now - s["last"]["ts"]).total_seconds()) if s.get("last") else None,
            "do": (s.get("last") or {}).get("do"),
        }
        async for s in db.pond_state.find({"gateway": gateway}, {"last": 1})
    ]
    last_batch = await db.ingest_batches.find_one({"gateway": gateway}, sort=[("received_at", -1)])
    events = [
        {"ts": _iso(e["ts"]), "kind": e["kind"], "pond": e["pond"], "device": e.get("device")}
        async for e in db.events.find({"gateway": gateway, "ts": {"$gte": now - timedelta(hours=1)}}).limit(
            10
        )
    ]
    return {
        "gateway": gateway,
        "ponds": ponds,
        "last_batch_age_s": round((now - last_batch["received_at"]).total_seconds()) if last_batch else None,
        "local_actions_last_hour": events,
    }


async def farm_overview(db: Db, farm: str) -> dict[str, Any]:
    """Status, oxygen, aerators and forecast of every pond on a farm."""
    ponds = []
    async for s in db.pond_state.find({"farm": farm}):
        last = s.get("last") or {}
        ponds.append(
            {
                "pond": s["_id"],
                "status": s.get("status"),
                "do": last.get("do"),
                "aerators_turning": last.get("aerators_running"),
                "aerators_on": last.get("aerators_on"),
                "minutes_to_3mg": (s.get("forecast") or {}).get("minutes_to_hypoxia"),
            }
        )
    return {"farm": farm, "ponds": sorted(ponds, key=lambda p: p["pond"])}


async def recent_deployments(db: Db) -> dict[str, Any]:
    """The API's last five deployments: version, start time and configuration."""
    rows = [
        {"version": d["version"], "started_at": _iso(d["started_at"]), "config": d.get("config", {})}
        async for d in db.deployments.find({"service": "firstlight-api"}).sort("started_at", -1).limit(5)
    ]
    return {"service": "firstlight-api", "deployments": rows}


async def past_incidents(db: Db, cause: str) -> dict[str, Any]:
    """The last five closed incidents with this cause: what was decided, done and measured."""
    rows = [
        {
            "id": i["_id"],
            "key": i["key"],
            "cause": (i.get("diagnosis") or {}).get("cause"),
            "status": i["status"],
            "metrics": i.get("metrics"),
            "summary": (i.get("investigation") or {}).get("summary"),
        }
        async for i in db.incidents.find({"open": {"$exists": False}, "diagnosis.cause": cause})
        .sort("closed_at", -1)
        .limit(5)
    ]
    return {"cause": cause, "incidents": rows}


Tool = Callable[..., Awaitable[dict[str, Any]]]
TOOLS: dict[str, Tool] = {
    "pond_readings": pond_readings,
    "gateway_status": gateway_status,
    "farm_overview": farm_overview,
    "recent_deployments": recent_deployments,
    "past_incidents": past_incidents,
}

DECLARATIONS = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="pond_readings",
            description=pond_readings.__doc__,
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "pond": {"type": "string", "description": "pond id, for example BL-01-A3"},
                    "minutes": {"type": "integer", "description": "how far back, 5 to 60"},
                },
                "required": ["pond"],
            },
        ),
        types.FunctionDeclaration(
            name="gateway_status",
            description=gateway_status.__doc__,
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "gateway": {"type": "string", "description": "gateway id, for example GW-BL01-1"}
                },
                "required": ["gateway"],
            },
        ),
        types.FunctionDeclaration(
            name="farm_overview",
            description=farm_overview.__doc__,
            parameters_json_schema={
                "type": "object",
                "properties": {"farm": {"type": "string", "description": "farm id, for example BL-01"}},
                "required": ["farm"],
            },
        ),
        types.FunctionDeclaration(
            name="recent_deployments",
            description=recent_deployments.__doc__,
            parameters_json_schema={"type": "object", "properties": {}},
        ),
        types.FunctionDeclaration(
            name="past_incidents",
            description=past_incidents.__doc__,
            parameters_json_schema={
                "type": "object",
                "properties": {"cause": {"type": "string", "description": "a cause such as aerator_failure"}},
                "required": ["cause"],
            },
        ),
    ]
)


async def run(db: Db, name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name not in TOOLS:
        return {"error": f"no tool called {name}"}
    try:
        return await TOOLS[name](db, **args)
    except TypeError as exc:
        return {"error": f"bad arguments for {name}: {exc}"}
