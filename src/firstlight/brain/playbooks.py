"""Playbooks are data: what to do for each diagnosis, and how risky each step is.

`auto` steps run at once; `approve` steps wait for a person in the console. They live in MongoDB, so a
farm can change its policy without a deploy; these are only the defaults written on first start.
"""

from typing import Any

from pymongo.asynchronous.database import AsyncDatabase

PLAYBOOKS: list[dict[str, Any]] = [
    {
        "_id": "aerator_failure",
        "title": "Aerator failure",
        "steps": [
            {"action": "aerator.on", "target": "standby", "risk": "auto"},
            {"action": "notify", "target": "owner", "risk": "auto"},
            {"action": "ticket", "target": "repair_aerator", "risk": "auto"},
        ],
        "then": "verify",
    },
    {
        "_id": "power_outage",
        "title": "Farm power cut",
        "steps": [
            {"action": "generator.start", "target": "farm", "risk": "approve"},
            {"action": "notify", "target": "owner", "risk": "auto"},
        ],
        "then": "verify",
    },
    {
        "_id": "sensor_fault",
        "title": "DO probe fault",
        "steps": [{"action": "ticket", "target": "clean_probe", "risk": "auto"}],
        "then": "dismiss",  # the shrimp are fine: nobody is woken up
    },
    {
        "_id": "gateway_offline",
        "title": "Gateway offline",
        "steps": [{"action": "notify", "target": "technician", "risk": "auto"}],
        "then": "monitor",
    },
    {
        "_id": "ingest_regression",
        "title": "Backend stopped taking data",
        "steps": [{"action": "notify", "target": "engineer", "risk": "auto"}],
        "then": "monitor",
    },
    {
        "_id": "unknown",
        "title": "Unexplained oxygen drop",
        "steps": [{"action": "notify", "target": "owner", "risk": "auto"}],
        "then": "escalate",
    },
]


async def ensure_playbooks(db: AsyncDatabase[dict[str, Any]]) -> None:
    """Write the defaults that are missing and leave edited playbooks alone."""
    for playbook in PLAYBOOKS:
        await db.playbooks.update_one(
            {"_id": playbook["_id"]},
            {"$setOnInsert": {**playbook, "cause": playbook["_id"]}},
            upsert=True,
        )
