"""Proof of recovery: every closed incident gets a Datadog notebook of what happened and how it ended.

The notebook holds the incident in numbers (cause and evidence, actions, how fast it was detected and
fixed, the lowest oxygen, what was at stake), graphs of the minutes around it chosen by the plane the
cause is in, and the AI postmortem. It is written once the postmortem is in, or 10 minutes after the
incident closed without one. Like the AI investigator it runs beside the brain's loop: the incident is
claimed with an atomic update, the call has a short timeout, a failure is tried twice more, and the link
is stored on the incident.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

import httpx
from pymongo import ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase

from firstlight.brain.forecast import HYPOXIA_MGL, SAFE_MGL
from firstlight.brain.playbooks import PLAYBOOKS
from firstlight.core.config import Settings

log = logging.getLogger("firstlight.brain.notebooks")

Doc = dict[str, Any]
WAIT_FOR_POSTMORTEM = timedelta(minutes=10)
RECENT = timedelta(hours=24)  # older incidents are history: no notebook is written for them
STALE_CLAIM = timedelta(minutes=5)
ATTEMPTS = 3
MARGIN = timedelta(minutes=10)  # the graphs start before the onset and run on after the close
TIMEOUT_S = 15.0
TITLE = {p["_id"]: p["title"] for p in PLAYBOOKS}
DATA_PATH = ("gateway_offline", "ingest_regression")
INGEST = "service:firstlight-api,resource_name:post_/v1/ingest"


def app_host(site: str) -> str:
    """Where people open Datadog: app.datadoghq.com on the US1 and EU1 sites, the site itself elsewhere."""
    return f"app.{site}" if site.count(".") == 1 else site


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _iso(value: datetime) -> str:
    return _utc(value).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ms(value: datetime) -> int:
    return int(_utc(value).timestamp() * 1000)


def _duration(seconds: float) -> str:
    return f"{seconds:.0f} s" if seconds < 90 else f"{seconds / 60:.1f} min"


def _ponds(count: int) -> str:
    return "1 pond" if count == 1 else f"{count} ponds"


def _target(incident: Doc) -> str:
    count = _ponds(len(incident.get("ponds", [])))
    if incident["scope"] == "pond":
        return f"pond {incident['pond']}"
    if incident["scope"] == "estate":
        return f"the estate, {count}"
    return f"{incident['scope']} {incident.get(incident['scope'])}, {count}"


def _filter(env: str, incident: Doc) -> str:
    """The tags that pick the incident's ponds out of the estate. Datadog stores tag values in lower case."""
    tags = [f"env:{env}"]
    scope = incident["scope"]
    if scope in ("pond", "farm", "gateway"):
        tags.append(f"{scope}:{str(incident[scope]).lower()}")
    return ",".join(tags)


def _graph(title: str, queries: list[tuple[str, str]], markers: tuple[tuple[float, str], ...] = ()) -> Doc:
    definition: Doc = {
        "type": "timeseries",
        "title": title,
        "show_legend": True,
        "requests": [{"q": q, "display_type": display} for q, display in queries],
    }
    if markers:
        definition["markers"] = [
            {"value": f"y = {value}", "display_type": "error dashed", "label": label}
            for value, label in markers
        ]
    return {"type": "notebook_cells", "attributes": {"definition": definition, "graph_size": "m"}}


def _markdown(text: str) -> Doc:
    return {"type": "notebook_cells", "attributes": {"definition": {"type": "markdown", "text": text}}}


def graphs(incident: Doc, env: str) -> list[Doc]:
    """What proves this incident ended, by the plane its cause is in."""
    cause = (incident.get("diagnosis") or {}).get("cause", "unknown")
    tags = _filter(env, incident)
    split = "" if incident["scope"] == "pond" else " by {pond}"
    if cause in DATA_PATH:
        return [
            _graph(
                "Readings stored, and batches answered as duplicates, per minute",
                [
                    (f"sum:firstlight.ingest.readings{{{tags}}}.as_count().rollup(sum, 60)", "bars"),
                    (f"sum:firstlight.ingest.duplicates{{{tags}}}.as_count().rollup(sum, 60)", "bars"),
                ],
            ),
            _graph(
                "Seconds since each gateway's last reading",
                [(f"max:firstlight.pond.freshness_seconds{{{tags}}} by {{gateway}}", "line")],
                ((60, "blind"),),
            ),
            _graph(
                "Ingest latency p95, s, by version",
                [(f"p95:trace.fastapi.request{{env:{env},{INGEST}}} by {{version}}", "line")],
            ),
        ]
    cells = [
        _graph(
            "Dissolved oxygen, mg/L",
            [(f"avg:firstlight.pond.do{{{tags}}}{split}", "line")],
            ((SAFE_MGL, "safe"), (HYPOXIA_MGL, "hypoxia")),
        )
    ]
    if cause == "sensor_fault":  # pH follows the real oxygen; a fouled probe moves DO alone
        cells.append(_graph("pH", [(f"avg:firstlight.pond.ph{{{tags}}}{split}", "line")]))
    else:
        cells.append(
            _graph(
                "Minutes to hypoxia, as forecast",
                [(f"min:firstlight.pond.minutes_to_hypoxia{{{tags}}}{split}", "line")],
                ((30, "alert"),),
            )
        )
        cells.append(
            _graph(
                "Aerators switched on but not turning",
                [(f"max:firstlight.pond.aerators_off{{{tags}}}", "bars")],
            )
        )
    return cells


def _line(entry: Doc) -> str:
    kind = entry["kind"]
    if kind == "detected":
        return f"detected: {', '.join(entry.get('signals') or [])}".rstrip(": ")
    if kind == "diagnosed":
        cause = entry.get("cause", "")
        return f"diagnosed: {TITLE.get(cause, cause)}, {round(float(entry.get('confidence', 0)) * 100)}% sure"
    if kind == "action_sent":
        return f"sent `{entry.get('action')}`" + (f" to {entry['device']}" if entry.get("device") else "")
    if kind == "action_done":
        return f"{entry.get('device') or entry.get('action')} confirmed by the gateway"
    if kind == "notify":
        return f"message to the {entry.get('to')}: “{entry.get('text')}”"
    if kind == "telegram":
        return f"sent on Telegram to the {entry.get('to')}"
    if kind == "acknowledged":
        return f"{entry.get('by')} acknowledged on Telegram"
    if kind == "unacknowledged":
        return "nobody acknowledged in 3 min: reminded on Telegram"
    if kind == "datadog":
        count = entry.get("count", 1)
        groups = f" on {count} {entry.get('per') or 'group'}s" if count > 1 else ""
        return f"Datadog {entry.get('transition')}: {entry.get('monitor')}{groups}"
    if kind == "ai_investigation":
        cause = entry.get("cause", "")
        return f"AI investigator: {TITLE.get(cause, cause)}"
    if kind in ("ticket", "verifying", "escalated"):
        return f"{kind}: {entry.get('text') or entry.get('detail')}"
    return str(kind).replace("_", " ")


def summary(incident: Doc, commands: list[Doc], links: list[tuple[str, str]], offset_hours: float) -> str:
    diagnosis = incident.get("diagnosis") or {}
    cause = diagnosis.get("cause", "unknown")
    metrics = incident.get("metrics") or {}
    ai = (incident.get("investigation") or {}).get("cause")
    rows = [
        ("Cause", f"{TITLE.get(cause, cause)}, {round(float(diagnosis.get('confidence', 0)) * 100)}% sure")
    ]
    if ai:
        rows.append(("AI investigator", "agrees" if ai == cause else f"says {TITLE.get(ai, ai)}"))
    if incident["status"] == "dismissed":
        rows.append(("Outcome", "a false alarm, closed without waking anyone"))
    elif "mttr_min" in metrics:
        rows.append(("Outcome", f"resolved {metrics['mttr_min']} min after the onset"))
    if metrics.get("mttd_s") is not None:
        by = "Datadog" if incident.get("detected_by") == "datadog" else "Firstlight"
        rows.append(("Detected", f"{_duration(metrics['mttd_s'])} after the onset, by {by}"))
    if metrics.get("time_to_action_s") is not None:
        rows.append(("First action", f"{_duration(metrics['time_to_action_s'])} after detection"))
    if metrics.get("min_do") is not None:
        rows.append(
            (
                "Oxygen",
                f"lowest {metrics['min_do']} mg/L, "
                f"{metrics.get('below_safe_min', 0)} min below {SAFE_MGL:g} mg/L, "
                f"oxygen debt {metrics.get('oxygen_debt', 0)}",
            )
        )
    if metrics.get("blind_s") is not None:
        coverage = metrics.get("coverage")
        recovered = (
            f", {round(coverage * 100)}% of it recovered from the gateways' backlog" if coverage else ""
        )
        rows.append(("Blind spell", f"{_duration(metrics['blind_s'])}{recovered}"))
    if at_risk := incident.get("at_risk"):
        rows.append(
            ("At stake", f"{at_risk['value_vnd'] / 1e9:.1f} bn VND of shrimp in {_ponds(at_risk['ponds'])}")
        )

    acks = {c["_id"]: c for c in commands}
    actions = []
    for action in incident.get("actions", []):
        if action.get("kind") == "command":
            command = acks.get(action.get("command")) or {}
            line = f"`{action['action']}` {action.get('device') or ''}".rstrip()
            if acked := command.get("acked_at"):
                took = (acked - command["created_at"]).total_seconds()
                line += f", confirmed by the gateway in {_duration(took)}"
            actions.append(line)
        elif action.get("kind") == "ticket":
            actions.append(f"ticket: {action.get('text')}")

    def clock(value: datetime) -> str:
        return (_utc(value) + timedelta(hours=offset_hours)).strftime("%H:%M:%S")

    parts = [
        "**Firstlight's proof of recovery.** " + " · ".join(f"[{label}]({url})" for label, url in links),
        "| | |\n|---|---|\n" + "\n".join(f"| {name} | {value} |" for name, value in rows),
    ]
    if evidence := incident.get("evidence"):
        parts.append(
            "**Evidence**\n"
            + "\n".join(
                f"- {'for' if e['verdict'] == 'support' else 'against'} "
                f"{TITLE.get(e['cause'], e['cause']).lower()} "
                f"({'+' if e['verdict'] == 'support' else '-'}{e['weight']:.2f}): {e['detail']}"
                for e in evidence
            )
        )
    if actions:
        parts.append("**Actions**\n" + "\n".join(f"- {a}" for a in actions))
    timeline = [e for e in incident.get("timeline", []) if e["kind"] != "notebook"]
    parts.append("**Timeline**, farm time\n" + "\n".join(f"- {clock(e['t'])} {_line(e)}" for e in timeline))
    return "\n\n".join(parts)


def notebook(
    incident: Doc, commands: list[Doc], env: str, host: str, public: str | None, offset_hours: float
) -> Doc:
    """The body of POST /api/v1/notebooks for one closed incident."""
    diagnosis = incident.get("diagnosis") or {}
    cause = diagnosis.get("cause", "unknown")
    start = min(diagnosis.get("onset") or incident["opened_at"], incident["opened_at"]) - MARGIN
    end = incident["closed_at"] + MARGIN
    incident_id = incident["_id"]
    links = []
    if public:
        links.append(("open in Firstlight", f"https://{public}/#{incident_id}"))
    traces = quote(f"env:{env}")
    logs = quote(f"env:{env} @incident:{incident_id}")
    links += [
        ("traces", f"https://{host}/apm/traces?query={traces}&start={_ms(start)}&end={_ms(end)}"),
        ("logs", f"https://{host}/logs?query={logs}&from_ts={_ms(start)}&to_ts={_ms(end)}"),
    ]
    cells = [_markdown(summary(incident, commands, links, offset_hours)), *graphs(incident, env)]
    written = incident.get("postmortem") or {}
    if written.get("status") == "done":
        body = written.get("postmortem_md", "")
        # The postmortem is asked for a Follow-ups section of its own; the list is added only without one.
        listed = "follow-ups" in body.lower()
        follow_ups = "" if listed else "".join(f"\n- {item}" for item in written.get("follow_ups", []))
        cells.append(
            _markdown(
                f"## {written.get('title', 'Postmortem')}\n\n_Written by the AI investigator "
                f"({written.get('model', 'Gemini')}) from the incident's own data._\n\n"
                f"{body}" + (f"\n\n**Follow-ups**{follow_ups}" if follow_ups else "")
            )
        )
    return {
        "data": {
            "type": "notebooks",
            "attributes": {
                "name": f"Firstlight · {incident_id} · {TITLE.get(cause, cause)} · {_target(incident)}",
                "status": "published",
                "time": {"start": _iso(start), "end": _iso(end), "live": False},
                "cells": cells,
                "metadata": {"type": "postmortem", "is_template": False, "take_snapshots": False},
            },
        }
    }


class NotebookWriter:
    def __init__(
        self, db: AsyncDatabase[Doc], settings: Settings, client: httpx.AsyncClient | None = None
    ) -> None:
        self.db = db
        self.enabled = bool(settings.dd_site and settings.dd_api_key and settings.dd_app_key)
        self.env, self.host = settings.dd_env, app_host(settings.dd_site)
        self.offset_hours = settings.sim_farm_clock_offset_hours
        self.public = settings.public_host if settings.public_host not in ("", "localhost") else None
        self._headers = {"DD-API-KEY": settings.dd_api_key, "DD-APPLICATION-KEY": settings.dd_app_key}
        self._client = client or httpx.AsyncClient(
            base_url=f"https://api.{settings.dd_site}", timeout=TIMEOUT_S
        )
        self._task: asyncio.Task[bool] | None = None

    async def cycle(self, now: datetime) -> None:
        """Start writing the next notebook, unless one is still being written."""
        if self.enabled and (self._task is None or self._task.done()):
            self._task = asyncio.create_task(self.write_next(now))

    async def write_next(self, now: datetime) -> bool:
        """Claim one closed incident that has no notebook yet and write it. Returns whether there was one."""
        ready = {
            "$or": [
                {"postmortem.status": {"$in": ["done", "failed"]}},
                {"closed_at": {"$lt": now - WAIT_FOR_POSTMORTEM}},
            ]
        }
        free = {
            "$or": [
                {"notebook": {"$exists": False}},
                {"notebook.status": "running", "notebook.at": {"$lt": now - STALE_CLAIM}},
                {"notebook.status": "failed", "notebook.attempts": {"$lt": ATTEMPTS}},
            ]
        }
        incident = await self.db.incidents.find_one_and_update(
            {"closed_at": {"$gte": now - RECENT}, "open": {"$exists": False}, "$and": [ready, free]},
            {"$set": {"notebook.status": "running", "notebook.at": now}, "$inc": {"notebook.attempts": 1}},
            sort=[("closed_at", 1)],
            return_document=ReturnDocument.AFTER,
        )
        if incident is None:
            return False
        commands = await self.db.commands.find({"incident": incident["_id"]}).to_list()
        body = notebook(incident, commands, self.env, self.host, self.public, self.offset_hours)
        try:
            response = await self._client.post("/api/v1/notebooks", json=body, headers=self._headers)
            response.raise_for_status()
            notebook_id = response.json()["data"]["id"]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            failed = getattr(exc, "response", None)
            ctx = {"incident": incident["_id"], "error": type(exc).__name__}
            if failed is not None:  # Datadog's error body names the field it refused; it holds no keys
                ctx |= {"status_code": failed.status_code, "detail": failed.text[:300]}
            log.warning("notebook not written", extra={"ctx": ctx})
            await self.db.incidents.update_one(
                {"_id": incident["_id"]},
                {"$set": {"notebook.status": "failed", "notebook.error": type(exc).__name__}},
            )
            return True
        url = f"https://{self.host}/notebook/{notebook_id}"
        await self.db.incidents.update_one(
            {"_id": incident["_id"]},
            {
                "$set": {"notebook.status": "done", "notebook.id": notebook_id, "notebook.url": url},
                "$push": {"timeline": {"t": now, "kind": "notebook", "url": url}},
            },
        )
        log.info("notebook written", extra={"ctx": {"incident": incident["_id"], "notebook": notebook_id}})
        return True
