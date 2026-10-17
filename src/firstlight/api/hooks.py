"""Datadog monitor webhooks. Answered at once: the brain links each alert to an incident on its next cycle.

The monitor's webhook payload template (set with the monitors, in infra/datadog):

    {"alert_id": "$ALERT_CYCLE_KEY", "transition": "$ALERT_TRANSITION", "monitor_id": "$ALERT_ID",
     "title": "$EVENT_TITLE", "scope": "$ALERT_SCOPE", "tags": "$TAGS", "link": "$LINK", "date": "$DATE"}

and its custom header `X-Firstlight-Signature` carries WEBHOOK_SECRET.
"""

import hmac
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from pymongo.errors import DuplicateKeyError

from firstlight.core.config import get_settings

router = APIRouter(prefix="/v1/hooks")

TARGET_TAGS = ("pond", "gateway", "farm")


def require_signature(x_firstlight_signature: str = Header(default="")) -> None:
    expected = get_settings().webhook_secret
    if not expected or not hmac.compare_digest(x_firstlight_signature.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="invalid signature")


class DatadogAlert(BaseModel):
    alert_id: str
    transition: str
    monitor_id: str = ""
    title: str = ""
    scope: str = ""
    tags: str = ""
    link: str = ""
    date: str = ""


def targets(alert: DatadogAlert) -> dict[str, str]:
    """Pond, gateway and farm from the alert's group and tags. Datadog lowercases tag values."""
    found: dict[str, str] = {}
    for part in f"{alert.scope},{alert.tags}".split(","):
        key, _, value = part.strip().partition(":")
        if key in TARGET_TAGS and value and key not in found:
            found[key] = value.upper()
    return found


@router.post("/datadog", dependencies=[Depends(require_signature)])
async def datadog(alert: DatadogAlert, request: Request) -> dict[str, Any]:
    db = request.app.state.db
    doc = {
        **alert.model_dump(),
        "transition": alert.transition.lower(),
        "targets": targets(alert),
        "received_at": datetime.now(UTC),
        "status": "new",
    }
    try:
        await db.alerts.insert_one(doc)
    except DuplicateKeyError:
        return {"accepted": True, "duplicate": True}  # Datadog retried; we already have it
    return {"accepted": True, "duplicate": False}


def require_telegram_secret(x_telegram_bot_api_secret_token: str = Header(default="")) -> None:
    expected = get_settings().telegram_webhook_secret
    if not expected or not hmac.compare_digest(x_telegram_bot_api_secret_token.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="invalid secret")


@router.post("/telegram", dependencies=[Depends(require_telegram_secret)])
async def telegram(request: Request) -> dict[str, bool]:
    """The farm owner pressed "Đã nhận" under a message: record who acknowledged the incident, and when."""
    update = await request.json()
    pressed = update.get("callback_query") or {}
    data = str(pressed.get("data", ""))
    if not data.startswith("ack:"):
        return {"ok": True}
    incident_id = data.removeprefix("ack:")
    person = pressed.get("from") or {}
    who = person.get("first_name") or person.get("username") or "?"
    now = datetime.now(UTC)
    db = request.app.state.db
    client = request.app.state.telegram
    acknowledged = await db.incidents.find_one_and_update(
        {"_id": incident_id, "acknowledged_at": {"$exists": False}},
        {
            "$set": {"acknowledged_at": now, "acknowledged_by": who},
            "$push": {"timeline": {"t": now, "kind": "acknowledged", "by": who, "channel": "telegram"}},
        },
    )
    if acknowledged is None:
        await client.answer(pressed.get("id", ""), "Sự cố này đã có người nhận rồi.")
        return {"ok": True}
    offset = timedelta(hours=get_settings().sim_farm_clock_offset_hours)
    await client.answer(pressed.get("id", ""), "Đã ghi nhận. Cảm ơn!")
    message = pressed.get("message") or {}
    if message.get("message_id"):
        stamp = (now + offset).strftime("%H:%M")
        text = f"{message.get('text', '')}\n\n✅ {who} đã nhận lúc {stamp}"
        await client.edit((message.get("chat") or {}).get("id", ""), message["message_id"], text)
    return {"ok": True}
