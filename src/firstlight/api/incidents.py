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
