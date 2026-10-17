"""Incidents for the console: the list, one incident with its commands, and approving a costly step."""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from firstlight.api.chaos import require_demo_code
from firstlight.api.live import plain, recent_incidents

router = APIRouter(prefix="/v1/incidents")


class Approval(BaseModel):
    action: str
    by: str = "operator"


@router.get("")
async def incidents(request: Request) -> list[dict[str, Any]]:
    return await recent_incidents(request.app.state.db)


@router.get("/ai/stats")
async def ai_stats(request: Request) -> dict[str, Any]:
    """How the AI investigator and the rules score, over every incident with a score."""
    db = request.app.state.db
    pipeline: list[dict[str, Any]] = [
        {"$match": {"evals": {"$exists": True}}},
        {
            "$group": {
                "_id": None,
                "investigated": {"$sum": 1},
                "agrees": {"$sum": {"$cond": ["$evals.agrees_with_rules", 1, 0]}},
                "grounded": {"$avg": "$evals.grounded"},
                "message_ok": {"$sum": {"$cond": ["$evals.farmer_message_ok", 1, 0]}},
                "scored": {"$sum": {"$cond": [{"$ifNull": ["$evals.truth", False]}, 1, 0]}},
                "ai_correct": {"$sum": {"$cond": [{"$eq": ["$evals.rca_correct", True]}, 1, 0]}},
                "rules_correct": {"$sum": {"$cond": [{"$eq": ["$evals.rules_correct", True]}, 1, 0]}},
            }
        },
        {"$project": {"_id": 0}},
    ]
    rows = await (await db.incidents.aggregate(pipeline)).to_list()
    return rows[0] if rows else {"investigated": 0}


@router.get("/{incident_id}")
async def incident(incident_id: str, request: Request) -> dict[str, Any]:
    db = request.app.state.db
    doc = await db.incidents.find_one({"_id": incident_id})
    if doc is None:
        raise HTTPException(status_code=404, detail="no such incident")
    commands = (
        await db.commands.find({"incident": incident_id}, {"expires_at": 0}).sort("created_at", 1).to_list()
    )
    return {**plain(doc), "commands": plain(commands)}


@router.post("/{incident_id}/approve", dependencies=[Depends(require_demo_code)])
async def approve(incident_id: str, body: Approval, request: Request) -> dict[str, Any]:
    """A person approves a step the playbook would not take alone; the brain sends it on its next cycle."""
    db = request.app.state.db
    now = datetime.now(UTC)
    result = await db.incidents.update_one(
        {
            "_id": incident_id,
            "open": True,
            "approvals": {"$elemMatch": {"action": body.action, "status": "pending"}},
        },
        {
            "$set": {"approvals.$.status": "approved", "approvals.$.by": body.by, "approvals.$.at": now},
            "$push": {"timeline": {"t": now, "kind": "approved", "action": body.action, "by": body.by}},
        },
    )
    if result.modified_count == 0:
        raise HTTPException(status_code=409, detail="nothing to approve")
    return {"approved": body.action}
