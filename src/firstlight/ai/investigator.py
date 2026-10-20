"""Gemini as incident investigator: a bounded agent with read-only tools, and a postmortem writer.

The agent gets the incident as the rules left it, may call up to four tools a round for at most five
rounds, and must then answer in a fixed JSON shape. It never acts: its cause is a second opinion,
its message to the farmer a draft. Every call is traced by LLM Observability when it is enabled.
"""

import contextlib
import json
import time
from collections.abc import Awaitable, Callable, Iterator
from datetime import UTC, datetime
from typing import Any, cast

from ddtrace.llmobs import LLMObs
from ddtrace.llmobs.decorators import agent, workflow
from google.genai import types
from pymongo.asynchronous.database import AsyncDatabase

from firstlight.ai import evals, tools
from firstlight.ai.gemini import Gemini, usage

CAUSES = [
    "aerator_failure",
    "power_outage",
    "sensor_fault",
    "gateway_offline",
    "ingest_regression",
    "unknown",
]
MAX_ROUNDS = 5
MAX_CALLS_PER_ROUND = 4

SYSTEM = """\
You are Firstlight's incident investigator for intensive white-leg shrimp ponds in the Mekong Delta.
Firstlight's deterministic rules have already detected this incident, weighed the evidence and may
already have acted. Your job is a second opinion and the writing people will read.

Use the read-only tools to check the evidence before you decide; never invent readings, times or
devices.
How the system behaves:
- Dissolved oxygen (DO) below 3 mg/L stresses shrimp; below 4 mg/L is a warning. At night only aerators
  add oxygen.
- An aerator that is switched on but draws 0 A has stopped. If every aerator on a farm stops at once, it
  is power.
- When real oxygen falls, pH falls with it, because the same respiration makes CO2. A probe whose
  reading falls faster than 0.1 mg/L per minute while every aerator turns, with pH steady, is reading
  wrong (fouled).
- If only one gateway's ponds are silent and the others report, that gateway is offline. If most
  gateways go silent together, the backend stopped taking data: look at the API's recent deployments.

Answer in the JSON schema. "cause" is one of the listed causes. "summary" is two to four plain English
sentences for an engineer: what happened, why you think so, what was done. "farmer_message_vi" is a
message in Vietnamese for the farm owner, under 300 characters: what happened, what Firstlight already
did, what they should do. No evidence weights, no internal ids except the pond, farm and device names.
"next_steps" are at most four short actions for people. "checked" lists the tools and facts you relied
on. Write every time as Vietnam time (UTC+7), for example 15:19."""

INVESTIGATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "cause": {"type": "string", "enum": CAUSES},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "summary": {"type": "string"},
        "farmer_message_vi": {"type": "string"},
        "next_steps": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
        "checked": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
    },
    "required": ["cause", "confidence", "summary", "farmer_message_vi", "next_steps", "checked"],
}

POSTMORTEM_SYSTEM = """\
You write short, blameless postmortems for Firstlight, a night operations system for shrimp ponds. Use
only the facts in the incident record. Markdown with these sections: Summary, Impact (on the shrimp:
lowest DO, minutes under 4 mg/L), Detection, Response, Recovery, What went well, Follow-ups. Under 250
words. Times are Vietnam time (UTC+7)."""

POSTMORTEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "postmortem_md": {"type": "string"},
        "follow_ups": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
    },
    "required": ["title", "postmortem_md", "follow_ups"],
}

BRIEF_FIELDS = (
    "_id",
    "key",
    "scope",
    "pond",
    "ponds",
    "farm",
    "gateway",
    "status",
    "opened_at",
    "closed_at",
    "detected_by",
    "signals",
    "at_detection",
    "diagnosis",
    "evidence",
    "actions",
    "approvals",
    "metrics",
    "similar",
)


def brief(incident: dict[str, Any]) -> dict[str, Any]:
    """The incident as the model sees it: everything the rules recorded, timeline included, nothing else."""
    out = {k: incident.get(k) for k in BRIEF_FIELDS if incident.get(k) is not None}
    out["timeline"] = [
        {k: v for k, v in entry.items() if k in ("t", "kind", "text", "detail", "action", "device", "cause")}
        for entry in incident.get("timeline", [])
    ]
    out["now"] = datetime.now(UTC)
    return out


def as_json(value: Any) -> str:
    return json.dumps(
        value, default=lambda v: v.isoformat() if isinstance(v, datetime) else str(v), ensure_ascii=False
    )


@contextlib.contextmanager
def traced_tool(name: str, args: dict[str, Any]) -> Iterator[Any]:
    """A tool span under the agent span when LLM Observability is on; nothing otherwise."""
    if not LLMObs.enabled:
        yield None
        return
    with LLMObs.tool(name=name) as span:
        LLMObs.annotate(span=span, input_data=args)
        yield span


async def _investigate(
    gemini: Gemini, db: AsyncDatabase[dict[str, Any]], incident: dict[str, Any]
) -> dict[str, Any]:
    started = time.perf_counter()
    question = as_json(brief(incident))
    if LLMObs.enabled:  # set now, so a run cut short still shows what it was asked
        LLMObs.annotate(input_data=question, tags={"incident": incident["_id"]})
    contents = [types.Content(role="user", parts=[types.Part(text=question)])]
    calls_made: list[dict[str, Any]] = []
    seen: set[str] = set()
    spent: dict[str, int] = {"input_tokens": 0, "output_tokens": 0, "thinking_tokens": 0}
    report: dict[str, Any] = {}
    model = ""
    rounds = 0
    for rounds in range(1, MAX_ROUNDS + 1):
        last_round = rounds == MAX_ROUNDS
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM,
            tools=None if last_round else [tools.DECLARATIONS],
            response_mime_type="application/json",
            response_json_schema=INVESTIGATION_SCHEMA,
            temperature=0.2,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        response, model = await gemini.generate(contents, config)
        for key, value in usage(response).items():
            spent[key] += value or 0
        calls = response.function_calls or []
        if calls and not last_round and response.candidates and response.candidates[0].content:
            contents.append(response.candidates[0].content)
            parts = []
            for call in calls[:MAX_CALLS_PER_ROUND]:
                args = dict(call.args or {})
                with traced_tool(call.name or "?", args) as span:
                    result = await tools.run(db, call.name or "", args)
                    if span is not None:  # plain JSON: LLM Observability shows datetimes as a placeholder
                        LLMObs.annotate(span=span, output_data=json.loads(as_json(result)))
                calls_made.append({"tool": call.name, "args": args})
                seen.update(evals.NAMES.findall(as_json(result)))  # names a tool showed are grounded too
                parts.append(
                    types.Part.from_function_response(name=call.name or "", response={"result": result})
                )
            contents.append(types.Content(role="user", parts=parts))
            continue
        report = json.loads(response.text or "{}")
        break
    result = {
        **report,
        "model": model,
        "rounds": rounds,
        "tool_calls": calls_made,
        "seen": sorted(seen),
        "latency_ms": round((time.perf_counter() - started) * 1000),
        **spent,
    }
    if LLMObs.enabled:
        LLMObs.annotate(
            output_data=report,
            metadata={"model": model, "rounds": rounds},
            tags={
                "incident": incident["_id"],
                "rules_cause": (incident.get("diagnosis") or {}).get("cause", ""),
            },
        )
        result["span"] = LLMObs.export_span()
    return result


async def _postmortem(gemini: Gemini, incident: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    record = {
        **brief(incident),
        "investigation": {k: incident.get("investigation", {}).get(k) for k in ("cause", "summary")},
    }
    if LLMObs.enabled:
        LLMObs.annotate(input_data=as_json(record), tags={"incident": incident["_id"]})
    config = types.GenerateContentConfig(
        system_instruction=POSTMORTEM_SYSTEM,
        response_mime_type="application/json",
        response_json_schema=POSTMORTEM_SCHEMA,
        temperature=0.3,
    )
    response, model = await gemini.generate(
        [types.Content(role="user", parts=[types.Part(text=as_json(record))])], config
    )
    report = json.loads(response.text or "{}")
    if LLMObs.enabled:
        LLMObs.annotate(output_data=report, metadata={"model": model})
    return {
        **report,
        "model": model,
        "latency_ms": round((time.perf_counter() - started) * 1000),
        **usage(response),
    }


# ddtrace's LLM Observability decorators carry no type hints; the casts keep these signatures typed.
# Their automatic input is the call's arguments, a database handle and a client among them: each span
# annotates its own input and output instead.
investigate = cast(
    Callable[[Gemini, AsyncDatabase[dict[str, Any]], dict[str, Any]], Awaitable[dict[str, Any]]],
    agent(name="incident_investigator", _automatic_io_annotation=False)(_investigate),
)
postmortem = cast(
    Callable[[Gemini, dict[str, Any]], Awaitable[dict[str, Any]]],
    workflow(name="incident_postmortem", _automatic_io_annotation=False)(_postmortem),
)
