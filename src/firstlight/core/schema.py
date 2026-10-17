"""Collections, validators and indexes. Idempotent: the API runs it on every start."""

from typing import Any

from pymongo import ASCENDING, DESCENDING, IndexModel
from pymongo.asynchronous.database import AsyncDatabase

DAY = 86_400

# Probes, aerators, feeders, generators and gateways share one collection; each type has its own shape.
DEVICE_VALIDATOR: dict[str, Any] = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["_id", "type", "farm"],
        "properties": {
            "_id": {"bsonType": "string"},
            "type": {"enum": ["gateway", "aerator", "do_probe", "feeder", "generator"]},
            "farm": {"bsonType": "string"},
            "pond": {"bsonType": "string"},
            "gateway": {"bsonType": "string"},
        },
        "oneOf": [
            {
                "properties": {
                    "type": {"enum": ["aerator"]},
                    "aerator": {
                        "bsonType": "object",
                        "required": ["kw", "standby"],
                        "properties": {
                            "kw": {"bsonType": ["double", "int"], "minimum": 0},
                            "standby": {"bsonType": "bool"},
                        },
                    },
                },
                "required": ["pond", "gateway", "aerator"],
            },
            {
                "properties": {
                    "type": {"enum": ["do_probe"]},
                    "probe": {"bsonType": "object", "required": ["model"]},
                },
                "required": ["pond", "gateway", "probe"],
            },
            {
                "properties": {
                    "type": {"enum": ["gateway"]},
                    "location": {
                        "bsonType": "object",
                        "required": ["type", "coordinates"],
                        "properties": {"type": {"enum": ["Point"]}, "coordinates": {"bsonType": "array"}},
                    },
                },
                "required": ["location", "province"],
            },
            {"properties": {"type": {"enum": ["feeder", "generator"]}}, "required": ["pond"]},
        ],
    }
}

INDEXES: dict[str, list[IndexModel]] = {
    "readings": [
        IndexModel([("meta.pond", ASCENDING), ("ts", DESCENDING)], name="pond_ts"),
        IndexModel([("meta.gateway", ASCENDING), ("ts", DESCENDING)], name="gateway_ts"),
    ],
    "readings_1m": [
        IndexModel([("_id.pond", ASCENDING), ("_id.minute", DESCENDING)], name="pond_minute"),
        IndexModel([("minute", ASCENDING)], name="ttl_180d", expireAfterSeconds=180 * DAY),
    ],
    "readings_1h": [IndexModel([("_id.pond", ASCENDING), ("_id.hour", DESCENDING)], name="pond_hour")],
    "pond_state": [
        IndexModel([("farm", ASCENDING)], name="farm"),
        IndexModel([("status", ASCENDING)], name="status"),
    ],
    "devices": [
        IndexModel([("pond", ASCENDING), ("type", ASCENDING)], name="pond_type"),
        IndexModel([("gateway", ASCENDING)], name="gateway"),
        IndexModel([("location", "2dsphere")], name="location", sparse=True),
    ],
    "commands": [
        IndexModel([("gateway", ASCENDING), ("status", ASCENDING)], name="gateway_status"),
        IndexModel([("expires_at", ASCENDING)], name="ttl", expireAfterSeconds=0),
    ],
    "alerts": [IndexModel([("alert_id", ASCENDING), ("transition", ASCENDING)], name="dedupe", unique=True)],
    "incidents": [IndexModel([("pond", ASCENDING), ("status", ASCENDING)], name="pond_status")],
    "ingest_batches": [IndexModel([("received_at", ASCENDING)], name="ttl_1d", expireAfterSeconds=DAY)],
    "playbooks": [IndexModel([("cause", ASCENDING)], name="cause", unique=True)],
    "reports": [IndexModel([("farm", ASCENDING), ("date", ASCENDING)], name="farm_date", unique=True)],
}


async def ensure_schema(db: AsyncDatabase[dict[str, Any]]) -> None:
    existing = set(await db.list_collection_names())

    if "readings" not in existing:
        # One document per pond per tick; meta holds only stable identifiers.
        await db.create_collection(
            "readings",
            timeseries={"timeField": "ts", "metaField": "meta", "granularity": "seconds"},
            expireAfterSeconds=14 * DAY,
        )

    if "devices" not in existing:
        await db.create_collection("devices", validator=DEVICE_VALIDATOR, validationLevel="strict")
    else:
        await db.command("collMod", "devices", validator=DEVICE_VALIDATOR, validationLevel="strict")

    for name in INDEXES:
        if name not in existing and name not in ("readings", "devices"):
            await db.create_collection(name)
    for name in ("stream_state",):
        if name not in existing:
            await db.create_collection(name)

    for name, models in INDEXES.items():
        await db[name].create_indexes(models)
