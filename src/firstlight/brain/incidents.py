"""Incidents from detection to proof of recovery. One open incident per pond, gateway, farm or estate.

    investigating ─► mitigating ─► verifying ─► resolved
          │               └────────► escalated ──┘
          ├─► dismissed           (sensor fault: a ticket, nobody woken up)
          ├─► monitoring ──► resolved   (blind: wait for the data, then check the gap)
          └─► awaiting_approval ─► mitigating   (a costly step, such as the generator)

The brain detects problems itself every cycle, so a pond is protected even when Datadog or the network
to it is down. A Datadog alert for the same pond lands on the same open incident.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError

from firstlight.brain import messages
from firstlight.brain.evidence import (
    Diagnosis,
    Evidence,
    data_path_checks,
    diagnose,
    pond_checks,
    pond_readings,
    recent_release,
)
from firstlight.brain.forecast import HYPOXIA_MGL, SAFE_MGL, TURNING_AMPS
from firstlight.core import economics
from firstlight.core.metrics import Metrics

log = logging.getLogger("firstlight.brain.incidents")

Doc = dict[str, Any]
Db = AsyncDatabase[Doc]

STALE_S = 60
FRESH_S = 30
RISK_MINUTES = 30
FAST_DROP = -0.1  # mg/L per minute over 3 min: twice what a pond loses with its main aerator gone
CONFIDENT = 0.5
INVESTIGATE_FOR = timedelta(seconds=90)
ACK_TIMEOUT = timedelta(seconds=15)
DELIVER_FOR = timedelta(minutes=2)
KEEP_COMMANDS = timedelta(days=7)
MAX_RETRIES = 3
SLOT_S = 20  # a gap is a 20-second slot with no reading at all


@dataclass(frozen=True)
class Policy:
    recovery_min: float = 2.0  # DO ≥ 4 mg/L and not falling for this long counts as recovered
    escalate_after_min: float = 10.0
    farm_offset_hours: float = 0.0


@dataclass
class Problem:
    key: str
    scope: str  # pond | gateway | farm | estate
    farm: str | None
    gateway: str | None
    ponds: list[str]
    signals: list[str]


def _stale(state: Doc, now: datetime, limit: float = STALE_S) -> bool:
    last = state.get("last")
    return last is None or (now - last["ts"]).total_seconds() > limit


def stopped_unticketed(state: Doc) -> list[str]:
    """Aerators switched on but drawing no current, leaving out those already waiting for repair."""
    last = state.get("last") or {}
    ticketed = {t["device"] for t in state.get("repair_tickets", [])}
    if "aer" not in last:  # older readings only carry the counts
        return ["?"] if last.get("aerators_running", 0) < last.get("aerators_on", 0) else []
    return [a["id"] for a in last["aer"] if a["on"] and a["amp"] < TURNING_AMPS and a["id"] not in ticketed]


def _dark(state: Doc) -> bool:
    last = state.get("last") or {}
    return bool(last.get("aerators_on", 0) > 0 and last.get("aerators_running", 1) == 0)


def find_problems(states: list[Doc], covered: set[str], now: datetime) -> list[Problem]:
    """Group what is wrong: a silent fleet, a silent gateway, a farm without power, then single ponds."""
    by_gateway: dict[str, list[Doc]] = {}
    by_farm: dict[str, list[Doc]] = {}
    for state in states:
        by_gateway.setdefault(state.get("gateway", "?"), []).append(state)
        by_farm.setdefault(state.get("farm", "?"), []).append(state)

    problems: list[Problem] = []
    grouped: set[str] = set()
    quiet = [g for g, ps in by_gateway.items() if all(_stale(p, now) for p in ps)]
    if len(by_gateway) >= 4 and len(quiet) * 2 > len(by_gateway):
        ponds = [p["_id"] for g in quiet for p in by_gateway[g]]
        problems.append(Problem("estate", "estate", None, None, ponds, ["fleet_silent"]))
        grouped.update(ponds)
    else:
        for gateway in quiet:
            ponds = [p["_id"] for p in by_gateway[gateway]]
            farm = by_gateway[gateway][0].get("farm")
            problems.append(Problem(gateway, "gateway", farm, gateway, ponds, ["gateway_silent"]))
            grouped.update(ponds)
    for farm, ps in by_farm.items():
        if len(ps) > 1 and all(not _stale(p, now) and _dark(p) for p in ps):
            ponds = [p["_id"] for p in ps]
            problems.append(Problem(farm, "farm", farm, ps[0].get("gateway"), ponds, ["farm_dark"]))
            grouped.update(ponds)

    for state in states:
        if state["_id"] in grouped or state["_id"] in covered:
            continue
        last = state.get("last") or {}
        minutes = (state.get("forecast") or {}).get("minutes_to_hypoxia")
        signals = []
        if _stale(state, now):
            signals.append("no_data")
        else:
            if stopped_unticketed(state):
                signals.append("aerator_down")
            if "sensor_ticket" not in state:  # the probe is known to be wrong: its oxygen is not news
                if last.get("do", 99.0) < HYPOXIA_MGL or (minutes is not None and minutes < RISK_MINUTES):
                    signals.append("hypoxia_risk")
                if last.get("probe_q", 1.0) < 0.8:
                    signals.append("probe_degraded")
                if ((state.get("forecast") or {}).get("rate_3m") or 0.0) < FAST_DROP:
                    signals.append("fast_drop")
        if signals:
            pond = state["_id"]
            problems.append(Problem(pond, "pond", state.get("farm"), state.get("gateway"), [pond], signals))
    return problems


async def _next_id(db: Db) -> str:
    counter = await db.counters.find_one_and_update(
        {"_id": "incident"}, {"$inc": {"seq": 1}}, upsert=True, return_document=ReturnDocument.AFTER
    )
    return f"INC-{(counter or {}).get('seq', 0):04d}"


def _at_risk(ponds: list[str], states: dict[str, Doc], now: datetime) -> Doc | None:
    """The shrimp in the affected ponds: what the incident puts at stake, as the team estimates it."""
    crops = [c for p in ponds if (c := economics.pond_crop(states.get(p, {}), now.date()))]
    if not crops:
        return None
    return {
        "value_vnd": sum(c.value_vnd for c in crops),
        "biomass_kg": sum(c.biomass_kg for c in crops),
        "ponds": len(crops),
    }


async def open_incident(
    db: Db, problem: Problem, states: dict[str, Doc], now: datetime, source: str = "brain"
) -> Doc | None:
    first = states[problem.ponds[0]]
    last = first.get("last") or {}
    doc: Doc = {
        "_id": await _next_id(db),
        "key": problem.key,
        "open": True,
        "scope": problem.scope,
        "pond": problem.ponds[0] if problem.scope == "pond" else None,
        "ponds": problem.ponds,
        "farm": problem.farm,
        "gateway": problem.gateway,
        "status": "investigating",
        "opened_at": now,
        "detected_by": source,
        "signals": problem.signals,
        "at_detection": {
            "do": last.get("do"),
            "minutes_to_hypoxia": (first.get("forecast") or {}).get("minutes_to_hypoxia"),
            "last_seen": last.get("ts"),
        },
        "at_risk": _at_risk(problem.ponds, states, now),
        "timeline": [{"t": now, "kind": "detected", "source": source, "signals": problem.signals}],
        "evidence": [],
        "actions": [],
    }
    try:
        await db.incidents.insert_one(doc)
    except DuplicateKeyError:
        return None  # someone else (another detector, a Datadog alert) opened it first
    await db.pond_state.update_many({"_id": {"$in": problem.ponds}}, {"$set": {"open_incident": doc["_id"]}})
    log.info(
        "incident opened",
        extra={
            "ctx": {
                "incident": doc["_id"],
                "key": problem.key,
                "scope": problem.scope,
                "signals": problem.signals,
            }
        },
    )
    return doc


async def investigate(
    db: Db, incident: Doc, states: list[Doc], by_id: dict[str, Doc], now: datetime
) -> tuple[list[Evidence], Diagnosis, list[Doc]]:
    scope_states = [by_id[p] for p in incident["ponds"] if p in by_id]
    rows: list[Doc] = []
    if incident["scope"] in ("gateway", "estate") or all(_stale(s, now) for s in scope_states):
        releases = (
            await db.deployments.find({"service": "firstlight-api"})
            .sort("started_at", -1)
            .limit(10)
            .to_list()
        )
        evidence = data_path_checks(scope_states, states, now, releases)
        diagnosis = diagnose(evidence)
        if diagnosis.cause == "ingest_regression":
            silent_from = (incident.get("at_detection") or {}).get("last_seen")
            diagnosis.release = recent_release(releases, silent_from)
        return evidence, diagnosis, rows
    else:
        rows = await pond_readings(db, incident["ponds"][0], now)
        farm_ponds = [s for s in states if s.get("farm") == incident.get("farm")]
        own = by_id.get(incident["ponds"][0], {})
        ticketed = frozenset(t["device"] for t in own.get("repair_tickets", []))
        evidence = pond_checks(rows, farm_ponds, now, ticketed)
    return evidence, diagnose(evidence), rows


async def _command(
    db: Db,
    incident: Doc,
    gateway: str | None,
    pond: str | None,
    device: str | None,
    action: str,
    now: datetime,
) -> ObjectId:
    result = await db.commands.insert_one(
        {
            "gateway": gateway,
            "pond": pond,
            "device": device,
            "action": action,
            "incident": incident["_id"],
            "risk": "auto",
            "status": "pending",
            "attempts": 0,
            "created_at": now,
            "deliver_by": now + DELIVER_FOR,
            "expires_at": now + KEEP_COMMANDS,
        }
    )
    return ObjectId(result.inserted_id)


async def respond(
    db: Db,
    incident: Doc,
    diagnosis: Diagnosis,
    rows: list[Doc],
    by_id: dict[str, Doc],
    now: datetime,
    policy: Policy,
) -> tuple[str, list[Doc], list[Doc], list[Doc]]:
    """Run the playbook for the diagnosis: returns the new status, timeline entries, actions, approvals."""
    playbook = await db.playbooks.find_one({"_id": diagnosis.cause}) or await db.playbooks.find_one(
        {"_id": "unknown"}
    )
    steps = playbook["steps"] if playbook else []
    timeline: list[Doc] = []
    actions: list[Doc] = []
    approvals: list[Doc] = []
    started: str | None = None
    pond = incident.get("pond")
    state = by_id.get(pond or "", {})
    last = state.get("last") or {}
    for step in steps:
        match step["action"]:
            case "aerator.on":
                turning_now = {a["id"]: a["on"] for a in rows[-1].get("aer", [])} if rows else {}
                standby = next((s for s in state.get("standby", []) if not turning_now.get(s, False)), None)
                if standby is None:
                    timeline.append(
                        {"t": now, "kind": "no_standby", "detail": "no standby aerator left to start"}
                    )
                    continue
                oid = await _command(db, incident, incident.get("gateway"), pond, standby, "aerator.on", now)
                started = standby
                actions.append({"kind": "command", "action": "aerator.on", "device": standby, "command": oid})
                timeline.append(
                    {
                        "t": now,
                        "kind": "action_sent",
                        "action": "aerator.on",
                        "device": standby,
                        "command": oid,
                    }
                )
            case "generator.start":
                approvals.append(
                    {"action": "generator.start", "farm": incident.get("farm"), "status": "pending"}
                )
                timeline.append({"t": now, "kind": "approval_requested", "action": "generator.start"})
            case "notify":
                text = messages.notify(
                    step["target"],
                    incident,
                    diagnosis.doc(),
                    policy.farm_offset_hours,
                    do_now=last.get("do"),
                    standby=started,
                    minutes=(state.get("forecast") or {}).get("minutes_to_hypoxia"),
                )
                timeline.append(
                    {"t": now, "kind": "notify", "to": step["target"], "channel": "console", "text": text}
                )
            case "ticket":
                device = diagnosis.device if step["target"] == "repair_aerator" else state.get("probe")
                text = messages.ticket(step["target"], device)
                actions.append(
                    {
                        "kind": "ticket",
                        "target": step["target"],
                        "device": device,
                        "status": "open",
                        "text": text,
                    }
                )
                timeline.append({"t": now, "kind": "ticket", "text": text})
                if step["target"] == "repair_aerator" and device and pond:
                    # Until it is repaired, this aerator's 0 A is known and handled, not a new alarm.
                    ticket = {"device": device, "incident": incident["_id"], "at": now}
                    await db.pond_state.update_one({"_id": pond}, {"$push": {"repair_tickets": ticket}})

    then = playbook.get("then") if playbook else "escalate"
    if then == "dismiss":
        status = "dismissed"
    elif approvals:
        status = "awaiting_approval"
    elif any(a["kind"] == "command" for a in actions):
        status = "mitigating"
    elif then == "monitor":
        status = "monitoring"
    else:
        status = "escalated"
    return status, timeline, actions, approvals


async def recovered(db: Db, ponds: list[str], now: datetime, minutes: float, after: datetime) -> bool:
    """DO at least 4 mg/L and not falling, in every pond, for `minutes` measured only after `after`
    (the action), so readings from before the fix can never count as recovery."""
    if now - after < timedelta(minutes=minutes):
        return False
    since = now - timedelta(minutes=minutes)
    rows = await db.readings.find(
        {"meta.pond": {"$in": ponds}, "ts": {"$gte": since}}, {"meta.pond": 1, "ts": 1, "do": 1}
    ).to_list()
    expected = minutes * 6 * 0.8
    for pond in ponds:
        points = sorted(((r["ts"], r["do"]) for r in rows if r["meta"]["pond"] == pond), key=lambda p: p[0])
        if len(points) < expected or min(do for _, do in points) < SAFE_MGL:
            return False
        t0 = points[0][0]
        xs = [(ts - t0).total_seconds() / 60 for ts, _ in points]
        ys = [do for _, do in points]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        var = sum((x - mx) ** 2 for x in xs)
        slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / var if var else 0.0
        if slope < -0.003:
            return False
    return True


def recovery_pipeline(ponds: list[str], start: datetime, end: datetime) -> list[Doc]:
    """Lowest DO, minutes below 4 mg/L, and oxygen debt: the area between 4 mg/L and the DO curve."""
    return [
        {"$match": {"meta.pond": {"$in": ponds}, "ts": {"$gte": start, "$lte": end}}},
        {"$set": {"deficit": {"$max": [0, {"$subtract": [SAFE_MGL, "$do"]}]}}},
        {
            "$setWindowFields": {
                "partitionBy": "$meta.pond",
                "sortBy": {"ts": 1},
                "output": {
                    "debt": {
                        "$integral": {"input": "$deficit", "unit": "minute"},
                        "window": {"documents": ["unbounded", "current"]},
                    }
                },
            }
        },
        {
            "$group": {
                "_id": None,
                "min_do": {"$min": "$do"},
                "oxygen_debt": {"$max": "$debt"},
                "below_safe": {"$sum": {"$cond": [{"$lt": ["$do", SAFE_MGL]}, 1, 0]}},
            }
        },
    ]


def _slot(ts: datetime) -> datetime:
    return ts.replace(microsecond=0) - timedelta(seconds=ts.second % SLOT_S)


def gap_pipeline(ponds: list[str], start: datetime, end: datetime) -> list[Doc]:
    """After a blind spell: which 20-second slots never got a reading, even after the backlog arrived.

    Only whole slots count: the one still in progress at `end` would look empty for no reason.
    """
    lower, upper = _slot(start), _slot(end)
    return [
        {"$match": {"meta.pond": {"$in": ponds}, "ts": {"$gte": lower, "$lt": upper}}},
        {
            "$group": {
                "_id": {
                    "pond": "$meta.pond",
                    "slot": {"$dateTrunc": {"date": "$ts", "unit": "second", "binSize": SLOT_S}},
                },
                "min_do": {"$min": "$do"},
            }
        },
        {"$project": {"_id": 0, "pond": "$_id.pond", "slot": "$_id.slot", "min_do": 1}},
        {
            "$densify": {
                "field": "slot",
                "partitionByFields": ["pond"],
                "range": {"step": SLOT_S, "unit": "second", "bounds": [lower, upper]},
            }
        },
        {
            "$group": {
                "_id": None,
                "slots": {"$sum": 1},
                "missing": {"$sum": {"$cond": [{"$eq": [{"$type": "$min_do"}, "missing"]}, 1, 0]}},
                "min_do": {"$min": "$min_do"},
            }
        },
    ]


async def _close(db: Db, incident: Doc, status: str, now: datetime, update: Doc, entry: Doc) -> None:
    await db.incidents.update_one(
        {"_id": incident["_id"]},
        {
            "$set": {"status": status, "closed_at": now, **update},
            "$unset": {"open": ""},
            "$push": {"timeline": entry},
        },
    )
    await db.pond_state.update_many(
        {"_id": {"$in": incident["ponds"]}, "open_incident": incident["_id"]},
        {"$unset": {"open_incident": ""}},
    )


def _first_sent(incident: Doc) -> datetime | None:
    times = [
        item["sent_at"]
        for item in incident.get("outbox", [])
        if item.get("sent_at") and item.get("to") == "owner"
    ]
    return min(times, default=None)


async def resolve(db: Db, incident: Doc, now: datetime, metrics: Metrics, extra: Doc | None = None) -> None:
    onset = (incident.get("diagnosis") or {}).get("onset") or incident["opened_at"]
    stats = await (
        await db.readings.aggregate(recovery_pipeline(incident["ponds"], onset - timedelta(minutes=1), now))
    ).to_list()
    first_done = next((e["t"] for e in incident.get("timeline", []) if e["kind"] == "action_done"), None)
    result: Doc = {
        "mttd_s": round((incident["opened_at"] - onset).total_seconds()),
        "time_to_action_s": round((first_done - incident["opened_at"]).total_seconds())
        if first_done
        else None,
        "mttr_min": round((now - onset).total_seconds() / 60, 1),
        "lead_time_min": (incident.get("at_detection") or {}).get("minutes_to_hypoxia"),
    }
    if stats:
        result |= {
            "min_do": round(stats[0]["min_do"], 2),
            "oxygen_debt": round(stats[0]["oxygen_debt"] or 0.0, 2),
            "below_safe_min": round(stats[0]["below_safe"] / 6, 1),
        }
    acknowledged, sent = incident.get("acknowledged_at"), _first_sent(incident)
    if acknowledged and sent:
        result["mtta_s"] = round((acknowledged - sent).total_seconds())
    if extra and "gap" in extra:
        result |= {"blind_s": extra["gap"]["blind_s"], "coverage": extra["gap"].get("coverage")}
    cause = (incident.get("diagnosis") or {}).get("cause", "unknown")
    entry = {"t": now, "kind": "resolved", "detail": result, **(extra or {})}
    await _close(db, incident, "resolved", now, {"metrics": result}, entry)
    tags = [f"cause:{cause}", f"scope:{incident['scope']}"]
    metrics.count("firstlight.incident.resolved", 1, tags)
    metrics.distribution("firstlight.incident.mttr_min", result["mttr_min"], tags)
    metrics.distribution("firstlight.incident.mttd_s", result["mttd_s"], tags)
    log.info("incident resolved", extra={"ctx": {"incident": incident["_id"], "cause": cause, **result}})


async def _push(db: Db, incident: Doc, entries: list[Doc], update: Doc | None = None) -> None:
    change: Doc = {"$push": {"timeline": {"$each": entries}}}
    if update:
        change["$set"] = update
    await db.incidents.update_one({"_id": incident["_id"]}, change)


async def advance(
    db: Db,
    incident: Doc,
    states: list[Doc],
    by_id: dict[str, Doc],
    now: datetime,
    policy: Policy,
    metrics: Metrics,
    active: set[str],
) -> None:
    """Move one incident a step. `active` holds the keys of everything that is still wrong right now."""
    status = incident["status"]

    if status == "investigating":
        # Datadog may see what the rules cannot; then the incident stays for a person instead of clearing.
        cleared = incident["key"] not in active and not set(incident["ponds"]) & active
        if cleared and incident.get("detected_by") != "datadog":
            await resolve(db, incident, now, metrics, {"note": "cleared on its own before a diagnosis"})
            return
        evidence, diagnosis, rows = await investigate(db, incident, states, by_id, now)
        update = {"evidence": [e.doc() for e in evidence], "diagnosis": diagnosis.doc()}
        sure = diagnosis.confidence >= CONFIDENT or now - incident["opened_at"] >= INVESTIGATE_FOR
        if not sure:
            await db.incidents.update_one({"_id": incident["_id"]}, {"$set": update})
            return
        incident = {**incident, **update}
        new_status, timeline, actions, approvals = await respond(
            db, incident, diagnosis, rows, by_id, now, policy
        )
        diagnosed = {
            "t": now,
            "kind": "diagnosed",
            "cause": diagnosis.cause,
            "confidence": diagnosis.confidence,
        }
        entries = [diagnosed, *timeline]
        outbox = [
            {"to": e["to"], "text": e["text"], "status": "pending", "at": now}
            for e in timeline
            if e["kind"] == "notify"
        ]
        update |= {"actions": actions, "approvals": approvals, "status": new_status, "outbox": outbox}
        tags = [f"cause:{diagnosis.cause}", f"scope:{incident['scope']}"]
        metrics.count("firstlight.incident.opened", 1, tags)
        if new_status == "dismissed":
            await _push(db, incident, entries[:-1], update)
            await _close(db, incident, "dismissed", now, {"false_alarm_prevented": True}, entries[-1])
            ticket = {
                "incident": incident["_id"],
                "probe": by_id.get(incident["pond"] or "", {}).get("probe"),
                "at": now,
            }
            await db.pond_state.update_one({"_id": incident["pond"]}, {"$set": {"sensor_ticket": ticket}})
            metrics.count("firstlight.false_alarm.prevented", 1, tags)
        else:
            await _push(db, incident, entries, update)
        log.info(
            "incident diagnosed",
            extra={"ctx": {"incident": incident["_id"], **diagnosed, "status": new_status}},
        )
        return

    if status == "mitigating":
        commands = await db.commands.find({"incident": incident["_id"]}).to_list()
        failed = [c for c in commands if c["status"] in ("failed", "expired")]
        idle = [
            c for c in commands if c["status"] == "done" and not (c.get("result") or {}).get("turning", True)
        ]
        if failed or idle:
            await _escalate(db, incident, now, "command_failed" if failed else "standby_idle")
        elif commands and all(c["status"] == "done" for c in commands):
            done_at = max(c.get("executed_at") or c["acked_at"] for c in commands)
            detail = f"waiting for DO ≥ 4 mg/L and steady for {policy.recovery_min:g} min"
            await _push(
                db,
                incident,
                [{"t": now, "kind": "verifying", "detail": detail}],
                {"status": "verifying", "mitigated_at": done_at},
            )
        return

    if status in ("verifying", "escalated", "awaiting_approval"):
        since = incident.get("mitigated_at") or incident["opened_at"]
        if await recovered(db, incident["ponds"], now, policy.recovery_min, since):
            await resolve(db, incident, now, metrics)
            return
        if status == "verifying":
            if now - since > timedelta(minutes=policy.escalate_after_min):
                await _escalate(db, incident, now, "no_recovery", policy.escalate_after_min)
        elif status == "awaiting_approval":
            await _approved_steps(db, incident, now)
        return

    if status == "monitoring":
        scope = [by_id[p] for p in incident["ponds"] if p in by_id]
        if scope and all(not _stale(s, now, FRESH_S) for s in scope):
            await _data_back(db, incident, now, metrics)


async def _escalate(db: Db, incident: Doc, now: datetime, reason: str, minutes: float = 0) -> None:
    text = messages.escalation(reason, incident, minutes)
    entries = [
        {"t": now, "kind": "escalated", "detail": reason},
        {"t": now, "kind": "notify", "to": "owner", "channel": "console", "text": text},
    ]
    await _push(db, incident, entries, {"status": "escalated"})
    await db.incidents.update_one(
        {"_id": incident["_id"]},
        {"$push": {"outbox": {"to": "owner", "text": text, "status": "pending", "at": now}}},
    )
    log.warning("incident escalated", extra={"ctx": {"incident": incident["_id"], "reason": reason}})


async def _approved_steps(db: Db, incident: Doc, now: datetime) -> None:
    """A person approved a costly step in the console: send it."""
    for i, approval in enumerate(incident.get("approvals", [])):
        if approval.get("status") != "approved":
            continue
        oid = await _command(db, incident, incident.get("gateway"), None, None, approval["action"], now)
        await db.incidents.update_one(
            {"_id": incident["_id"]},
            {
                "$set": {f"approvals.{i}.status": "sent", "status": "mitigating"},
                "$push": {
                    "actions": {"kind": "command", "action": approval["action"], "command": oid},
                    "timeline": {
                        "t": now,
                        "kind": "action_sent",
                        "action": approval["action"],
                        "command": oid,
                    },
                },
            },
        )


async def _data_back(db: Db, incident: Doc, now: datetime, metrics: Metrics) -> None:
    """The ponds report again. Check what happened while nobody could see them."""
    since = (incident.get("at_detection") or {}).get("last_seen") or incident["opened_at"]
    gap = await (await db.readings.aggregate(gap_pipeline(incident["ponds"], since, now))).to_list()
    failsafe = await db.events.find(
        {"pond": {"$in": incident["ponds"]}, "ts": {"$gte": since}, "kind": "failsafe"}, {"_id": 0}
    ).to_list()
    report: Doc = {"blind_s": round((now - since).total_seconds())}
    if gap:
        slots, missing = gap[0]["slots"], gap[0]["missing"]
        report |= {
            "coverage": round(1 - missing / slots, 3) if slots else 1.0,
            "min_do": round(gap[0]["min_do"], 2) if gap[0]["min_do"] is not None else None,
        }
    report["failsafe"] = [{"pond": e["pond"], "device": e.get("device"), "t": e["ts"]} for e in failsafe]
    await resolve(db, incident, now, metrics, {"gap": report})


async def retry_commands(db: Db, now: datetime) -> None:
    """Resend what was not acknowledged within 15 s; give up after three retries or two minutes."""
    async for command in db.commands.find(
        {"status": {"$in": ["pending", "sent"]}, "created_at": {"$lt": now - ACK_TIMEOUT}}
    ):
        current = {"_id": command["_id"], "status": command["status"]}
        if command["deliver_by"] <= now or command.get("attempts", 0) >= MAX_RETRIES:
            changed = await db.commands.update_one(
                current, {"$set": {"status": "expired", "expired_at": now}}
            )
            if changed.modified_count and command.get("incident"):
                entry = {
                    "t": now,
                    "kind": "action_expired",
                    "action": command["action"],
                    "command": command["_id"],
                }
                await db.incidents.update_one({"_id": command["incident"]}, {"$push": {"timeline": entry}})
        elif now - (command.get("tried_at") or command["created_at"]) >= ACK_TIMEOUT:
            await db.commands.update_one(
                current, {"$set": {"status": "pending", "tried_at": now}, "$inc": {"attempts": 1}}
            )


async def close_sensor_tickets(db: Db, states: list[Doc], now: datetime) -> None:
    """A cleaned probe reports good signal quality again: the ticket closes itself."""
    for state in states:
        ticket = state.get("sensor_ticket")
        last = state.get("last") or {}
        if not ticket or _stale(state, now) or last.get("probe_q", 0.0) < 0.95:
            continue
        await db.pond_state.update_one({"_id": state["_id"]}, {"$unset": {"sensor_ticket": ""}})
        await db.incidents.update_one(
            {"_id": ticket["incident"]},
            {
                "$set": {"actions.$[t].status": "done", "actions.$[t].closed_at": now},
                "$push": {
                    "timeline": {
                        "t": now,
                        "kind": "ticket_closed",
                        "detail": f"{ticket.get('probe')} reads normally again",
                    }
                },
            },
            array_filters=[{"t.kind": "ticket", "t.target": "clean_probe", "t.status": "open"}],
        )


async def close_repair_tickets(db: Db, states: list[Doc], now: datetime) -> None:
    """A repaired aerator draws current again: its ticket closes itself."""
    for state in states:
        last = state.get("last") or {}
        amps = {a["id"]: a["amp"] for a in last.get("aer", [])}
        for ticket in state.get("repair_tickets", []):
            if _stale(state, now) or amps.get(ticket["device"], 0.0) < TURNING_AMPS:
                continue
            await db.pond_state.update_one(
                {"_id": state["_id"]}, {"$pull": {"repair_tickets": {"device": ticket["device"]}}}
            )
            await db.incidents.update_one(
                {"_id": ticket["incident"]},
                {
                    "$set": {"actions.$[t].status": "done", "actions.$[t].closed_at": now},
                    "$push": {
                        "timeline": {
                            "t": now,
                            "kind": "ticket_closed",
                            "detail": f"{ticket['device']} runs again",
                        }
                    },
                },
                array_filters=[{"t.kind": "ticket", "t.target": "repair_aerator", "t.status": "open"}],
            )


TRIGGERS = {"triggered", "re-triggered", "warn", "no data"}


def _alert_problem(alert: Doc, states: list[Doc], by_id: dict[str, Doc]) -> Problem | None:
    """The pond, gateway or farm a Datadog alert is about, as the brain would describe the problem."""
    targets = alert.get("targets") or {}
    signal = [f"datadog: {alert.get('title') or alert.get('monitor_id') or 'monitor'}"]
    if (pond := targets.get("pond")) in by_id:
        state = by_id[pond]
        return Problem(pond, "pond", state.get("farm"), state.get("gateway"), [pond], signal)
    for scope in ("gateway", "farm"):
        if key := targets.get(scope):
            ponds = sorted(s["_id"] for s in states if s.get(scope) == key)
            if ponds:
                first = by_id[ponds[0]]
                return Problem(key, scope, first.get("farm"), first.get("gateway"), ponds, signal)
    return None


async def process_alerts(
    db: Db, states: list[Doc], by_id: dict[str, Doc], open_incidents: list[Doc], now: datetime
) -> None:
    """Each new Datadog alert lands on the open incident for its pond, gateway or farm. A trigger with no
    incident opens one, which the brain then investigates like its own."""
    async for alert in db.alerts.find({"status": "new"}).sort("received_at", 1).limit(100):
        problem = _alert_problem(alert, states, by_id)
        incident = None
        if problem:
            incident = next(
                (
                    i
                    for i in open_incidents
                    if i["key"] == problem.key or set(problem.ponds) <= set(i["ponds"])
                ),
                None,
            )
        if incident:
            lead = round((alert["received_at"] - incident["opened_at"]).total_seconds())
            entry = {
                "t": alert["received_at"],
                "kind": "datadog",
                "transition": alert["transition"],
                "monitor": alert.get("title"),
                "link": alert.get("link"),
                "after_brain_s": lead if incident.get("detected_by") == "brain" else None,
            }
            await db.incidents.update_one({"_id": incident["_id"]}, {"$push": {"timeline": entry}})
            incident["timeline"].append(entry)
            update: Doc = {"status": "linked", "incident": incident["_id"]}
        elif problem and alert["transition"] in TRIGGERS:
            opened = await open_incident(db, problem, by_id, now, source="datadog")
            if opened:
                open_incidents.append(opened)
            update = {"status": "linked" if opened else "ignored", "incident": opened and opened["_id"]}
        else:
            update = {"status": "ignored"}  # a recovery after we closed it, or a target we do not know
        await db.alerts.update_one({"_id": alert["_id"]}, {"$set": {**update, "processed_at": now}})


async def incident_cycle(db: Db, metrics: Metrics, policy: Policy, now: datetime) -> int:
    """Detect, then move every open incident one step. Returns how many incidents are open."""
    states = await db.pond_state.find({}).to_list()
    by_id = {s["_id"]: s for s in states}
    open_incidents = await db.incidents.find({"open": True}).to_list()
    await process_alerts(db, states, by_id, open_incidents, now)
    covered = {p for i in open_incidents for p in i.get("ponds", [])}
    open_keys = {i["key"] for i in open_incidents}
    active: set[str] = set()
    for problem in find_problems(states, set(), now):
        active.add(problem.key)
        active.update(problem.ponds)
        if problem.key in open_keys or (problem.scope == "pond" and problem.key in covered):
            continue
        if incident := await open_incident(db, problem, by_id, now):
            open_incidents.append(incident)
    for incident in open_incidents:
        try:
            await advance(db, incident, states, by_id, now, policy, metrics, active)
        except Exception:
            log.exception("incident step failed", extra={"ctx": {"incident": incident["_id"]}})
    await retry_commands(db, now)
    await close_sensor_tickets(db, states, now)
    await close_repair_tickets(db, states, now)
    return len(open_incidents)
