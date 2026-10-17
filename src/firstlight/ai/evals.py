"""How good was the investigator? Four checks, scored without asking another model.

- agrees_with_rules: same cause as the deterministic diagnosis.
- grounded: every pond, farm, gateway and device the AI names appears in the incident record.
- farmer_message_ok: Vietnamese, short, names the pond or farm, free of internal jargon.
- rca_correct: same cause as the fault the chaos panel really injected (demo mode only).
The last also scores the rules, so the demo can show both accuracies side by side.
"""

import re
from datetime import timedelta
from typing import Any

from pymongo.asynchronous.database import AsyncDatabase

NAMES = re.compile(r"\b(?:AE|DO|GW)-[A-Z0-9]+(?:-[A-Z0-9]+)*\b|\b[A-Z]{2}-\d{2}(?:-A\d)?\b")
VIETNAMESE = re.compile(
    "[ăâđêôơưàáạảãằắặẳẵầấậẩẫèéẹẻẽềếệểễìíịỉĩòóọỏõồốộổỗờớợởỡùúụủũừứựửữỳýỵỷỹ]", re.IGNORECASE
)
JARGON = re.compile(r"\b(incident|evidence|confidence|playbook|scope|INC-\d+)\b", re.IGNORECASE)
FAULT_CAUSE = {
    "aerator_trip": "aerator_failure",
    "probe_fouling": "sensor_fault",
    "gateway_offline": "gateway_offline",
    "power_outage": "power_outage",
}
TRUTH_WINDOW = timedelta(minutes=15)


def known_names(incident: dict[str, Any]) -> set[str]:
    return set(NAMES.findall(repr(incident)))


def grounded(texts: list[str], incident: dict[str, Any]) -> float:
    named = {name for text in texts for name in NAMES.findall(text)}
    if not named:
        return 1.0
    return round(len(named & known_names(incident)) / len(named), 2)


def farmer_message_ok(message: str, incident: dict[str, Any]) -> bool:
    where = incident.get("pond") or incident.get("farm") or ""
    return (
        bool(VIETNAMESE.search(message))
        and 0 < len(message) <= 320
        and (not where or where in message or incident.get("scope") == "estate")
        and not JARGON.search(message)
    )


def scored(investigation: dict[str, Any], incident: dict[str, Any]) -> dict[str, Any]:
    rules = (incident.get("diagnosis") or {}).get("cause")
    texts = [investigation.get("summary", ""), investigation.get("farmer_message_vi", "")]
    texts += investigation.get("next_steps", [])
    return {
        "agrees_with_rules": investigation.get("cause") == rules,
        "grounded": grounded(texts, incident),
        "farmer_message_ok": farmer_message_ok(investigation.get("farmer_message_vi", ""), incident),
    }


async def ground_truth(db: AsyncDatabase[dict[str, Any]], incident: dict[str, Any]) -> str | None:
    """The cause of the fault that was really injected around this incident, if the demo injected one."""
    opened = incident["opened_at"]
    window = {"$gte": opened - TRUTH_WINDOW, "$lte": opened}
    targets: list[dict[str, Any]] = [{"pond": {"$in": incident.get("ponds", [])}}]
    if incident.get("gateway"):
        targets.append({"gateway": incident["gateway"], "kind": "gateway_offline"})
    if incident.get("farm"):
        targets.append({"farm": incident["farm"], "kind": "power_outage"})
    fault = await db.chaos.find_one({"started_at": window, "$or": targets}, sort=[("started_at", -1)])
    if fault:
        return FAULT_CAUSE.get(fault["kind"])
    regression = await db.deployments.find_one(
        {"config.ingest_duplicate_check": "fields", "started_at": window}, sort=[("started_at", -1)]
    )
    return "ingest_regression" if regression else None
