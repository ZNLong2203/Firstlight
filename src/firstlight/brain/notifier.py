"""Messages leave through an outbox on the incident, so a slow or absent Telegram never holds up the brain.

The playbook's notify steps and escalations append to `incident.outbox`. Each cycle the notifier sends
what is pending, with a button to acknowledge and a link to the pond in the console. An owner message
nobody acknowledged within three minutes, on an incident still open, is sent once more as a reminder.
Without a bot, messages stay in the console and are marked so.
"""

import logging
from datetime import datetime, timedelta
from typing import Any

from pymongo.asynchronous.database import AsyncDatabase

from firstlight.core.config import Settings
from firstlight.core.telegram import Telegram

log = logging.getLogger("firstlight.brain.notifier")

Doc = dict[str, Any]
ACK_WAIT = timedelta(minutes=3)
MAX_TRIES = 3


class Notifier:
    def __init__(self, db: AsyncDatabase[Doc], telegram: Telegram, settings: Settings) -> None:
        self.db, self.telegram = db, telegram
        self.public = settings.public_host if settings.public_host not in ("", "localhost") else None

    async def cycle(self, now: datetime) -> None:
        await self._remind_unacknowledged(now)
        async for incident in self.db.incidents.find({"outbox.status": "pending"}).limit(20):
            for i, item in enumerate(incident.get("outbox", [])):
                if item.get("status") == "pending":
                    await self._deliver(incident, i, item, now)

    def _buttons(self, incident: Doc) -> list[list[dict[str, str]]]:
        buttons = [[{"text": "✅ Đã nhận", "callback_data": f"ack:{incident['_id']}"}]]
        if self.public:  # Telegram only accepts public https links in buttons
            target = incident.get("pond") or incident["_id"]
            buttons.append([{"text": "Mở trên Firstlight", "url": f"https://{self.public}/#{target}"}])
        return buttons

    async def _deliver(self, incident: Doc, i: int, item: Doc, now: datetime) -> None:
        key = f"outbox.{i}"
        if not self.telegram.enabled:
            await self.db.incidents.update_one(
                {"_id": incident["_id"]}, {"$set": {f"{key}.status": "console"}}
            )
            return
        chat = self.telegram.chat
        message_id = await self.telegram.send(chat, item["text"], self._buttons(incident))
        if message_id is None:
            tries = item.get("tries", 0) + 1
            status = "failed" if tries >= MAX_TRIES else "pending"
            await self.db.incidents.update_one(
                {"_id": incident["_id"]}, {"$set": {f"{key}.tries": tries, f"{key}.status": status}}
            )
            return
        await self.db.incidents.update_one(
            {"_id": incident["_id"]},
            {
                "$set": {
                    f"{key}.status": "sent",
                    f"{key}.sent_at": now,
                    f"{key}.chat": chat,
                    f"{key}.message_id": message_id,
                },
                "$push": {
                    "timeline": {"t": now, "kind": "telegram", "to": item["to"], "message_id": message_id}
                },
            },
        )

    async def _remind_unacknowledged(self, now: datetime) -> None:
        waiting = {"to": "owner", "status": "sent", "sent_at": {"$lt": now - ACK_WAIT}}
        async for incident in self.db.incidents.find(
            {
                "open": True,
                "acknowledged_at": {"$exists": False},
                "reminded_at": {"$exists": False},
                "outbox": {"$elemMatch": waiting},
            }
        ):
            first = next(item for item in incident["outbox"] if item.get("to") == "owner")
            text = f"⚠️ Chưa ai nhận sau 3 phút. {first['text']}"
            reminder = {"to": "owner", "text": text, "status": "pending", "reminder": True, "at": now}
            await self.db.incidents.update_one(
                {"_id": incident["_id"]},
                {
                    "$set": {"reminded_at": now},
                    "$push": {
                        "outbox": reminder,
                        "timeline": {
                            "t": now,
                            "kind": "unacknowledged",
                            "detail": "nobody acknowledged in 3 min",
                        },
                    },
                },
            )
            log.warning("incident unacknowledged, reminding", extra={"ctx": {"incident": incident["_id"]}})
