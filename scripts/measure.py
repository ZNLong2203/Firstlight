"""Measurements of a running deployment, for docs/MONGODB-DATA-MODEL.md.

It runs inside the API container, which has the package and the connection settings:
    ssh root@<host> 'docker exec -i firstlight-api-1 python - [--compare]' < scripts/measure.py
By default nothing is written: it times the brain's queries, explains the forecast and reads storage
statistics. --compare also copies the last hour of readings into a regular collection in a scratch
database, to compare the space each takes, and drops that database afterwards.
"""

import statistics
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import bson
from pymongo import MongoClient

from firstlight.brain.evidence import pond_window
from firstlight.brain.forecast import forecast_pipeline
from firstlight.core.config import get_settings

RUNS = 20
SCRATCH = "firstlight_measure"
MB = 1024 * 1024

settings = get_settings()
client: MongoClient[dict[str, Any]] = MongoClient(settings.mongodb_uri, tz_aware=True)
db = client[settings.mongodb_db]


def timed(run: Callable[[], object]) -> str:
    times = []
    for _ in range(RUNS):
        started = time.perf_counter()
        run()
        times.append((time.perf_counter() - started) * 1000)
    times.sort()
    return f"median {statistics.median(times):.0f} ms, p95 {times[round(0.95 * (RUNS - 1))]:.0f} ms"


def find(node: object, key: str) -> list[Any]:
    """Every value stored under `key` anywhere in an explain document."""
    found: list[Any] = []
    if isinstance(node, dict):
        if key in node:
            found.append(node[key])
        for value in node.values():
            found += find(value, key)
    elif isinstance(node, list):
        for value in node:
            found += find(value, key)
    return found


now = datetime.now(UTC)
window = now - timedelta(minutes=12)
ponds = db.pond_state.count_documents({})
recent = db.readings.count_documents({"ts": {"$gte": window}})
print(f"ponds {ponds}; readings in the 12-minute window {recent:,}")
print(
    "forecast, all ponds in one aggregation:",
    timed(lambda: list(db.readings.aggregate(forecast_pipeline(window)))),
)
pond = (db.pond_state.find_one({}, {"_id": 1}) or {}).get("_id")
since = now - timedelta(minutes=15)
print(
    f"evidence window, one pond ({pond}):",
    timed(lambda: list(db.readings.aggregate(pond_window(pond, since)))),
)

plan = db.command(
    "explain",
    {"aggregate": "readings", "pipeline": forecast_pipeline(window), "cursor": {}},
    verbosity="executionStats",
)
stages = list(dict.fromkeys(str(s) for s in find(plan, "stage")))
print("forecast plan stages:", " > ".join(stages))
for key in ("totalKeysExamined", "totalDocsExamined", "nReturned", "executionTimeMillis"):
    values = find(plan, key)
    if values:
        print(f"  {key}: {values[0]}")

stats = db.command("collStats", "readings")
series = stats.get("timeseries", {})
buckets = db["system.buckets.readings"]
count = next(buckets.aggregate([{"$group": {"_id": None, "n": {"$sum": "$control.count"}}}]), {}).get("n")
count = count or db.readings.count_documents({})  # buckets written before 8.0 carry no control.count
sample = list(db.readings.find({"ts": {"$gte": now - timedelta(minutes=2)}}).limit(1000))
bson_bytes = statistics.mean(len(bson.encode(doc)) for doc in sample) if sample else 0
print(
    f"readings: {count:,} in {series.get('bucketCount', 0):,} buckets; "
    f"{bson_bytes:.0f} bytes each as a document; on disk {stats['storageSize'] / MB:.1f} MB "
    f"({stats['storageSize'] / max(count, 1):.1f} bytes per reading), "
    f"indexes {stats['totalIndexSize'] / MB:.1f} MB"
)
for key in ("numBytesUncompressed", "numBytesCompressed", "numCompressedBuckets", "numUncompressedBuckets"):
    if key in series:
        print(f"  timeseries.{key}: {series[key]:,}")

if "--compare" in sys.argv:
    hour = now - timedelta(hours=1)
    scratch = client[SCRATCH]
    try:
        db.readings.aggregate(
            [{"$match": {"ts": {"$gte": hour}}}, {"$out": {"db": SCRATCH, "coll": "regular"}}]
        )
        scratch.regular.create_index([("meta.pond", 1), ("ts", 1)])  # what the brain's queries would need
        client.admin.command("fsync")  # write the blocks out so the sizes are the compressed ones
        regular = scratch.command("collStats", "regular")
        n = regular["count"]
        per_regular = (regular["storageSize"] + regular["totalIndexSize"]) / n
        per_series = (stats["storageSize"] + stats["totalIndexSize"]) / max(count, 1)
        print(
            f"compare, last hour ({n:,} readings): regular collection {per_regular:.1f} bytes per reading "
            f"with its index; time series {per_series:.1f} over the whole collection: "
            f"{per_regular / per_series:.1f}x smaller"
        )
    finally:
        client.drop_database(SCRATCH)
