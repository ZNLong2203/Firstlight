"""The chaos panel: inject a real fault into the simulated world and keep the ground truth.

Every fault is recorded in `chaos` first, so the demo can later score Firstlight's diagnosis against
what really happened. The brain never reads this collection while it investigates.
"""

import hmac
import secrets
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from pymongo import ReturnDocument

from firstlight.core.config import get_settings
from firstlight.core.models import FaultKind

router = APIRouter(prefix="/v1/chaos")


def require_demo_code(x_demo_code: str = Header(default="")) -> None:
    expected = get_settings().demo_code
    if not expected or not hmac.compare_digest(x_demo_code.encode(), expected.encode()):
        raise HTTPException(status_code=403, detail="the chaos panel needs the demo code")


class ChaosRequest(BaseModel):
    kind: FaultKind
    farm: str | None = None
    pond: str | None = None
    gateway: str | None = None
    device: str | None = None


def _edge(request: Request) -> httpx.AsyncClient:
    client: httpx.AsyncClient = request.app.state.edge
    return client


def _detail(response: httpx.Response) -> str:
    try:
        return str(response.json().get("detail", "simulator refused"))
    except ValueError:
        return "simulator refused"


@router.get("", dependencies=[Depends(require_demo_code)])
async def faults(request: Request) -> list[dict[str, Any]]:
    """Active faults and the last few cleared ones. Faults the simulator lost in a restart are closed."""
    db = request.app.state.db
    try:
        response = await _edge(request).get("/faults")
        if response.status_code == 200:
            live = {fault["id"] for fault in response.json()}
            await db.chaos.update_many(
                {"status": "active", "_id": {"$nin": list(live)}},
                {
                    "$set": {
                        "status": "cleared",
                        "cleared_at": datetime.now(UTC),
                        "note": "simulator restarted",
                    }
                },
            )
    except httpx.HTTPError:
        pass  # the registry is still the best answer we have
    active: list[dict[str, Any]] = await db.chaos.find({"status": "active"}).sort("started_at", -1).to_list()
    recent: list[dict[str, Any]] = (
        await db.chaos.find({"status": "cleared"}).sort("cleared_at", -1).limit(10).to_list()
    )
    return active + recent


@router.post("", dependencies=[Depends(require_demo_code)])
async def inject(body: ChaosRequest, request: Request) -> dict[str, Any]:
    db = request.app.state.db
    now = datetime.now(UTC)
    fault_id = f"CH-{now:%m%d-%H%M%S}-{secrets.token_hex(2)}"
    await db.chaos.insert_one(
        {"_id": fault_id, "status": "requested", "requested_at": now, **body.model_dump()}
    )
    try:
        response = await _edge(request).post("/faults", json={"id": fault_id, **body.model_dump()})
    except httpx.HTTPError as exc:
        await db.chaos.delete_one({"_id": fault_id})
        raise HTTPException(status_code=502, detail="the simulator is not reachable") from exc
    if response.status_code != 200:
        await db.chaos.delete_one({"_id": fault_id})
        status = 404 if response.status_code == 404 else 502
        raise HTTPException(status_code=status, detail=_detail(response))
    view = response.json()
    fields = {key: view.get(key) for key in ("farm", "pond", "gateway", "device")}
    started_at = datetime.fromisoformat(view["started_at"])
    doc: dict[str, Any] = await db.chaos.find_one_and_update(
        {"_id": fault_id},
        {"$set": {"status": "active", "started_at": started_at, **fields}},
        return_document=ReturnDocument.AFTER,
    )
    return doc


@router.delete("/{fault_id}", dependencies=[Depends(require_demo_code)])
async def clear(fault_id: str, request: Request) -> dict[str, Any]:
    db = request.app.state.db
    try:
        response = await _edge(request).delete(f"/faults/{fault_id}")
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="the simulator is not reachable") from exc
    if response.status_code not in (200, 404):  # 404: the simulator restarted and forgot it already
        raise HTTPException(status_code=502, detail="simulator refused")
    doc: dict[str, Any] | None = await db.chaos.find_one_and_update(
        {"_id": fault_id, "status": "active"},
        {"$set": {"status": "cleared", "cleared_at": datetime.now(UTC)}},
        return_document=ReturnDocument.AFTER,
    )
    if doc is None:
        raise HTTPException(status_code=404, detail="no active fault with this id")
    return doc
