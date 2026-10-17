"""Minutes to hypoxia for every pond, from one aggregation over the time series collection."""

from datetime import datetime
from typing import Any

HYPOXIA_MGL = 3.0  # shrimp are stressed below this (Global Seafood Alliance)
SAFE_MGL = 4.0
MIN_POINTS = 9  # 90 s of readings in the current regime before a slope means anything
FALLING = -0.005  # mg/L per minute; anything flatter is noise
TURNING_AMPS = 0.5


def forecast_pipeline(since: datetime) -> list[dict[str, Any]]:
    """Least-squares slope of DO per pond: slope = cov(t, DO) / var(t), computed with window functions.

    The fit only uses readings since the number of turning aerators last changed. When an aerator
    stops, or a standby one starts, the old trend no longer describes the pond, so the regression
    starts again instead of averaging the two regimes for the next twelve minutes.
    """
    cumulative = {"documents": ["unbounded", "current"]}
    by_pond = {"partitionBy": "$meta.pond", "sortBy": {"ts": 1}}
    turning = {
        "$size": {
            "$filter": {"input": {"$ifNull": ["$aer", []]}, "cond": {"$gte": ["$$this.amp", TURNING_AMPS]}}
        }
    }
    changed = {
        "$cond": [
            {"$and": [{"$ne": ["$previous", None]}, {"$ne": ["$previous", "$turning"]}]},
            1,
            0,
        ]
    }
    return [
        {"$match": {"ts": {"$gte": since}}},
        {"$set": {"t": {"$toLong": "$ts"}, "turning": turning}},
        {
            "$setWindowFields": {
                **by_pond,
                "output": {"previous": {"$shift": {"output": "$turning", "by": -1}}},
            }
        },
        {"$setWindowFields": {**by_pond, "output": {"regime": {"$sum": changed, "window": cumulative}}}},
        {
            "$setWindowFields": {
                "partitionBy": {"pond": "$meta.pond", "regime": "$regime"},
                "sortBy": {"ts": 1},
                "output": {
                    "cov": {"$covariancePop": ["$t", "$do"], "window": cumulative},
                    "sd_t": {"$stdDevPop": "$t", "window": cumulative},
                    "n": {"$count": {}, "window": cumulative},
                    "do_1m": {"$avg": "$do", "window": {"range": [-60, 0], "unit": "second"}},
                },
            }
        },
        {
            "$group": {
                "_id": "$meta.pond",
                "last": {
                    "$top": {
                        "sortBy": {"ts": -1},
                        "output": {"ts": "$ts", "do": "$do_1m", "cov": "$cov", "sd_t": "$sd_t", "n": "$n"},
                    }
                },
            }
        },
        {
            "$set": {
                "slope_per_min": {
                    "$cond": [
                        {"$and": [{"$gt": ["$last.sd_t", 0]}, {"$gte": ["$last.n", MIN_POINTS]}]},
                        {"$multiply": [{"$divide": ["$last.cov", {"$pow": ["$last.sd_t", 2]}]}, 60_000]},
                        0,
                    ]
                }
            }
        },
        {
            "$set": {
                "minutes_to_hypoxia": {
                    "$switch": {
                        "branches": [
                            {"case": {"$lte": ["$last.do", HYPOXIA_MGL]}, "then": 0},
                            {
                                "case": {"$lt": ["$slope_per_min", FALLING]},
                                "then": {
                                    "$divide": [
                                        {"$subtract": ["$last.do", HYPOXIA_MGL]},
                                        {"$multiply": ["$slope_per_min", -1]},
                                    ]
                                },
                            },
                        ],
                        "default": None,
                    }
                }
            }
        },
        {
            "$project": {
                "_id": 1,
                "do": "$last.do",
                "slope_per_min": 1,
                "minutes_to_hypoxia": 1,
                "points": "$last.n",
            }
        },
    ]


def classify(
    last: dict[str, Any] | None, minutes: float | None, freshness_s: float, sensor_suspect: bool = False
) -> str:
    """ok, watch, alert, sensor or blind. `sensor` means the probe is known to be wrong: its oxygen
    reading is not trusted, a cleaning ticket is open, and nobody is woken up for it."""
    if last is None or freshness_s > 60:
        return "blind"
    if sensor_suspect:
        return "sensor"
    if last["do"] < HYPOXIA_MGL or (minutes is not None and minutes < 30):
        return "alert"
    falling_soon = minutes is not None and minutes < 60
    aerator_down = last.get("aerators_running", 0) < last.get("aerators_on", 0)
    if last["do"] < SAFE_MGL or falling_soon or aerator_down:
        return "watch"
    return "ok"
