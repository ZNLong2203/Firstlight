"""Pond, sensor or data path? Deterministic checks over MongoDB data, each with a weight and a reason.

Every check returns evidence for or against a cause. The diagnosis is the cause with the most weight,
and its confidence says how much of all the weight points that way. The same evidence is what the
console shows and what the AI investigator later reads; neither ever sees the chaos registry.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any

from pymongo.asynchronous.database import AsyncDatabase

from firstlight.brain.forecast import TURNING_AMPS

CAUSES = ("aerator_failure", "power_outage", "sensor_fault", "gateway_offline", "ingest_regression")
WINDOW = timedelta(minutes=15)
STALE_S = 60
IMPLAUSIBLE_FALL = -0.04  # mg/L per minute with every aerator turning: faster than the water can lose it
FALLING = -0.01
RATE_WINDOW_MIN = 3
PH_PER_DO = 0.11  # at night pH follows the same respiration that uses up oxygen, about 0.1 per mg/L


@dataclass
class Evidence:
    check: str
    cause: str
    verdict: str  # support | against
    weight: float
    detail: str
    at: datetime | None = None

    def doc(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class Diagnosis:
    cause: str
    confidence: float
    onset: datetime | None = None
    device: str | None = None
    scores: dict[str, float] = field(default_factory=dict)

    def doc(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


def pond_window(pond: str, since: datetime) -> list[dict[str, Any]]:
    """The pond's recent readings with the rate of change of DO and pH over a sliding three minutes."""
    rate = {"range": [-180, 0], "unit": "second"}
    return [
        {"$match": {"meta.pond": pond, "ts": {"$gte": since}}},
        {
            "$setWindowFields": {
                "sortBy": {"ts": 1},
                "output": {
                    "do_rate": {"$derivative": {"input": "$do", "unit": "minute"}, "window": rate},
                    "ph_rate": {"$derivative": {"input": "$ph", "unit": "minute"}, "window": rate},
                },
            }
        },
        {"$project": {"_id": 0, "ts": 1, "do": 1, "ph": 1, "aer": 1, "probe": 1, "do_rate": 1, "ph_rate": 1}},
    ]


async def pond_readings(db: AsyncDatabase[dict[str, Any]], pond: str, now: datetime) -> list[dict[str, Any]]:
    return [r async for r in await db.readings.aggregate(pond_window(pond, now - WINDOW))]


def stopped_aerators(rows: list[dict[str, Any]]) -> list[tuple[str, datetime, float]]:
    """Aerators switched on but drawing no current now: (id, when it stopped, current before)."""
    if not rows:
        return []
    out = []
    for aerator in rows[-1].get("aer", []):
        if not aerator["on"] or aerator["amp"] >= TURNING_AMPS:
            continue
        stopped_at, before = rows[-1]["ts"], 0.0
        for row in reversed(rows):
            amp = next((a["amp"] for a in row.get("aer", []) if a["id"] == aerator["id"]), 0.0)
            if amp >= TURNING_AMPS:
                before = amp
                break
            stopped_at = row["ts"]
        out.append((aerator["id"], stopped_at, before))
    return out


def pond_checks(
    rows: list[dict[str, Any]],
    farm_ponds: list[dict[str, Any]],
    now: datetime | None = None,
    ticketed: frozenset[str] = frozenset(),
) -> list[Evidence]:
    """Checks on all three planes for one pond. `farm_ponds` are the pond_state documents of its farm;
    `ticketed` aerators are already known to be broken and waiting for repair."""
    if not rows:
        return []
    latest = rows[-1]
    evidence: list[Evidence] = []
    stopped = [s for s in stopped_aerators(rows) if s[0] not in ticketed]
    farm_dark = bool(farm_ponds) and all(
        (p.get("last") or {}).get("aerators_on", 0) > 0
        and (p.get("last") or {}).get("aerators_running", 1) == 0
        for p in farm_ponds
    )
    do_rate = latest.get("do_rate") or 0.0
    ph_rate = latest.get("ph_rate") or 0.0

    # Pond plane.
    if farm_dark:
        evidence.append(
            Evidence(
                "farm_power",
                "power_outage",
                "support",
                0.9,
                "every aerator on the farm stopped at once",
                min((at for _, at, _ in stopped), default=None),
            )
        )
        evidence.append(
            Evidence(
                "farm_power", "aerator_failure", "against", 0.3, "one broken aerator would not stop the farm"
            )
        )
    elif stopped:
        # Switched on but drawing nothing: direct physical evidence, whatever the cause inside the motor.
        first_stop = min(at for _, at, _ in stopped)
        detail = "; ".join(f"{device} drew {before:.1f} A, then 0 A" for device, _, before in stopped)
        evidence.append(
            Evidence("aerator_current_drop", "aerator_failure", "support", 0.85, detail, first_stop)
        )
    if stopped and do_rate < FALLING:
        cause = "power_outage" if farm_dark else "aerator_failure"
        evidence.append(
            Evidence(
                "do_follows_aeration", cause, "support", 0.2, f"DO falls {do_rate:+.3f} mg/L per minute since"
            )
        )
    # pH is only informative for a large change: small ones are lost in its noise.
    do_change, ph_change = do_rate * RATE_WINDOW_MIN, ph_rate * RATE_WINDOW_MIN
    if do_change < -0.5:
        expected = PH_PER_DO * do_change
        if ph_change > expected / 2:
            detail = (
                f"DO fell {-do_change:.1f} mg/L in 3 min, "
                f"but pH moved only {ph_change:+.2f} (expected {expected:+.2f})"
            )
            evidence.append(Evidence("ph_disagrees", "sensor_fault", "support", 0.25, detail))
        else:
            detail = f"pH fell with DO ({ph_change:+.2f} in 3 min)"
            evidence.append(Evidence("ph_agrees", "sensor_fault", "against", 0.2, detail))

    # Sensor plane.
    quality = (latest.get("probe") or {}).get("q", 1.0)
    if quality >= 0.95:
        evidence.append(
            Evidence(
                "probe_quality",
                "sensor_fault",
                "against",
                0.2,
                f"the probe reports signal quality {quality:.2f}",
            )
        )
    if quality < 0.8:
        evidence.append(
            Evidence(
                "probe_quality",
                "sensor_fault",
                "support",
                0.4,
                f"the probe reports signal quality {quality:.2f}",
            )
        )
    if not stopped and do_rate < IMPLAUSIBLE_FALL:
        evidence.append(
            Evidence(
                "physics_bound",
                "sensor_fault",
                "support",
                0.35,
                f"DO reads {do_rate:+.2f} mg/L per minute with every aerator turning, "
                "faster than water can lose oxygen",
            )
        )
    # Data path plane.
    if now is not None and (now - latest["ts"]).total_seconds() < 30:
        age = (now - latest["ts"]).total_seconds()
        evidence.append(
            Evidence(
                "freshness", "gateway_offline", "against", 0.2, f"readings arrive on time ({age:.0f} s ago)"
            )
        )
    falling_neighbours = [
        p["_id"] for p in farm_ponds if ((p.get("forecast") or {}).get("slope_per_min") or 0.0) < FALLING
    ]
    if len(farm_ponds) > 1 and len(falling_neighbours) <= 1 and not farm_dark:
        evidence.append(
            Evidence("neighbours", "power_outage", "against", 0.3, "the other ponds on the farm are steady")
        )
    return evidence


def data_path_checks(
    scope_ponds: list[dict[str, Any]], all_ponds: list[dict[str, Any]], now: datetime
) -> list[Evidence]:
    """Is the data missing because of one gateway, or because the backend stopped taking it?"""

    def stale(p: dict[str, Any]) -> bool:
        last = p.get("last")
        return last is None or (now - last["ts"]).total_seconds() > STALE_S

    evidence: list[Evidence] = []
    silent = [p for p in scope_ponds if stale(p)]
    if not silent:
        return evidence
    last_seen = max((p["last"]["ts"] for p in silent if p.get("last")), default=None)
    gateways = {p.get("gateway") for p in all_ponds}
    quiet_gateways = {g for g in gateways if all(stale(p) for p in all_ponds if p.get("gateway") == g)}
    evidence.append(
        Evidence(
            "freshness",
            "gateway_offline",
            "support",
            0.4,
            f"{len(silent)} ponds silent",
            last_seen,
        )
    )
    if len(quiet_gateways) * 2 > len(gateways):
        evidence.append(
            Evidence(
                "fleet_silent",
                "ingest_regression",
                "support",
                0.7,
                f"{len(quiet_gateways)} of {len(gateways)} gateways silent: the backend, not the 4G links",
            )
        )
        evidence.append(
            Evidence("fleet_silent", "gateway_offline", "against", 0.4, "too many gateways at once")
        )
    else:
        evidence.append(
            Evidence(
                "fleet_healthy",
                "gateway_offline",
                "support",
                0.4,
                f"{len(gateways) - len(quiet_gateways)} other gateways report normally, so ingest works",
            )
        )
    return evidence


def diagnose(evidence: list[Evidence]) -> Diagnosis:
    scores = dict.fromkeys(CAUSES, 0.0)
    for item in evidence:
        scores[item.cause] += item.weight if item.verdict == "support" else -item.weight
    positive = {cause: score for cause, score in scores.items() if score > 0}
    if not positive:
        return Diagnosis("unknown", 0.0, scores=scores)
    cause = max(positive, key=lambda c: positive[c])
    # Share of the supporting weight, damped when there is little evidence altogether.
    confidence = positive[cause] / sum(positive.values()) * min(1.0, positive[cause])
    supporting = [e for e in evidence if e.cause == cause and e.verdict == "support" and e.at]
    onset = min((e.at for e in supporting if e.at), default=None)
    device = None
    if cause == "aerator_failure":
        device = next((e.detail.split(" ")[0] for e in supporting if e.check == "aerator_current_drop"), None)
    return Diagnosis(cause, round(confidence, 2), onset, device, {c: round(s, 2) for c, s in scores.items()})
