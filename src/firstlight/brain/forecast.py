"""Minutes to hypoxia for every pond, from one aggregation over the time series collection."""

from datetime import datetime
from typing import Any

HYPOXIA_MGL = 3.0  # shrimp are stressed below this (Global Seafood Alliance)
SAFE_MGL = 4.0
MIN_POINTS = 9  # 90 s of readings in the current regime before a slope means anything
RATE_POINTS = 12  # the 3-minute rate needs 2 minutes of readings; two points 10 s apart are mostly noise
FALLING = -0.005  # mg/L per minute; anything flatter is noise
TURNING_AMPS = 0.5
# A probe's signal quality changing this much between two readings means it was cleaned or swapped.
QUALITY_JUMP = 0.2


def forecast_pipeline(since: datetime) -> list[dict[str, Any]]:
    """Least-squares slope of DO per pond, slope = cov(t, DO) / var(t), for every pond in one pass.

    The fit only uses readings since the pond's setup last changed: the number of turning aerators,
    or a jump in the probe's signal quality. When an aerator stops, a standby starts, or a fouled
    probe is cleaned, the old readings no longer describe the pond, so the regression starts again
    instead of mixing two regimes for the next twelve minutes. Quality that drifts down as biofilm
    grows is not a jump, so the rate of change stays measurable while a probe fouls.

    Each reading is cut down to the five fields the fit reads before anything sorts it. Two window stages
    number the regimes ($shift, then a running $sum). The regression itself is a
    $group of running sums per pond and regime: a third window stage would sort every reading again,
    and measured on 200 ponds it cost as much as the rest of the pipeline together.
    """
    cumulative = {"documents": ["unbounded", "current"]}
    whole = {"documents": ["unbounded", "unbounded"]}
    by_pond = {"partitionBy": "$meta.pond", "sortBy": {"ts": 1}}
    turning = {
        "$size": {
            "$filter": {"input": {"$ifNull": ["$aer", []]}, "cond": {"$gte": ["$$this.amp", TURNING_AMPS]}}
        }
    }
    changed = {
        "$cond": [
            {
                "$and": [
                    {"$ne": ["$prev_turning", None]},
                    {
                        "$or": [
                            {"$ne": ["$prev_turning", "$turning"]},
                            {"$gte": [{"$abs": {"$subtract": ["$q", "$prev_q"]}}, QUALITY_JUMP]},
                        ]
                    },
                ]
            },
            1,
            0,
        ]
    }
    age_ms = {"$subtract": ["$newest_ts", "$ts"]}  # how long before the pond's newest reading
    in_1m = {"$lte": [age_ms, 60_000]}
    in_3m = {"$lte": [age_ms, 180_000]}
    point = {"t": "$t", "do": "$do"}
    fit = "$fit"
    n = f"{fit}.n"
    mean_t = {"$divide": [f"{fit}.st", n]}
    var_t = {"$subtract": [{"$divide": [f"{fit}.stt", n]}, {"$multiply": [mean_t, mean_t]}]}
    cov = {
        "$subtract": [
            {"$divide": [f"{fit}.sty", n]},
            {"$multiply": [mean_t, {"$divide": [f"{fit}.sy", n]}]},
        ]
    }
    return [
        {"$match": {"ts": {"$gte": since}}},
        # Only what the fit reads goes on: both window stages sort every reading, a whole reading is about
        # four times larger, and a stage that outgrows 100 MB of memory sorts on disk.
        {
            "$project": {
                "_id": 0,
                "ts": 1,
                "meta.pond": 1,
                "do": 1,
                "turning": turning,
                "q": {"$ifNull": ["$probe.q", 1.0]},
            }
        },
        {
            "$setWindowFields": {
                **by_pond,
                "output": {
                    "prev_turning": {"$shift": {"output": "$turning", "by": -1}},
                    "prev_q": {"$shift": {"output": "$q", "by": -1}},
                },
            }
        },
        {
            "$setWindowFields": {
                **by_pond,
                "output": {
                    "regime": {"$sum": changed, "window": cumulative},
                    "newest_ts": {"$max": "$ts", "window": whole},
                },
            }
        },
        # Minutes since the window opened: small numbers keep the sums of squares exact.
        {"$set": {"t": {"$divide": [{"$subtract": ["$ts", since]}, 60_000]}}},
        {
            "$group": {
                "_id": {"pond": "$meta.pond", "regime": "$regime"},
                "n": {"$sum": 1},
                "st": {"$sum": "$t"},
                "sy": {"$sum": "$do"},
                "stt": {"$sum": {"$multiply": ["$t", "$t"]}},
                "sty": {"$sum": {"$multiply": ["$t", "$do"]}},
                "do_1m": {"$avg": {"$cond": [in_1m, "$do", None]}},
                "n_3m": {"$sum": {"$cond": [in_3m, 1, 0]}},
                "first_3m": {"$min": {"$cond": [in_3m, point, None]}},  # $min skips the nulls
                "newest": {"$max": point},
            }
        },
        # The pond's current regime is its highest-numbered one.
        {"$group": {"_id": "$_id.pond", "fit": {"$top": {"sortBy": {"_id.regime": -1}, "output": "$$ROOT"}}}},
        {
            "$set": {
                "slope_per_min": {
                    "$cond": [
                        {"$and": [{"$gt": [var_t, 0]}, {"$gte": [n, MIN_POINTS]}]},
                        {"$divide": [cov, var_t]},
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
                            {"case": {"$lte": ["$fit.do_1m", HYPOXIA_MGL]}, "then": 0},
                            {
                                "case": {"$lt": ["$slope_per_min", FALLING]},
                                "then": {
                                    "$divide": [
                                        {"$subtract": ["$fit.do_1m", HYPOXIA_MGL]},
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
                "do": "$fit.do_1m",
                "slope_per_min": 1,
                "minutes_to_hypoxia": 1,
                "points": n,
                # The same as $derivative over the last three minutes: first and last reading.
                "rate_3m": {
                    "$cond": [
                        {"$gte": ["$fit.n_3m", RATE_POINTS]},
                        {
                            "$divide": [
                                {"$subtract": ["$fit.newest.do", "$fit.first_3m.do"]},
                                {"$subtract": ["$fit.newest.t", "$fit.first_3m.t"]},
                            ]
                        },
                        None,
                    ]
                },
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
