import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from firstlight.api.app import app
from firstlight.brain.notifier import Notifier
from firstlight.core import config
from firstlight.core.config import Settings
from firstlight.core.telegram import Telegram

SETTINGS = Settings(
    telegram_bot_token="123:abc",
    telegram_chat_id="100",
    public_host="demo.example",
)


def fake_telegram(sent: list[dict[str, Any]]) -> Telegram:
    def handle(request: httpx.Request) -> httpx.Response:
        sent.append({"method": request.url.path.rsplit("/", 1)[-1], **json.loads(request.read())})
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 40 + len(sent)}})

    return Telegram(SETTINGS, httpx.AsyncClient(transport=httpx.MockTransport(handle)))


async def test_messages_go_out_with_buttons_and_remind_when_nobody_answers(
    api: tuple[httpx.AsyncClient, Any],
) -> None:
    _, db = api
    now = datetime.now(UTC)
    await db.incidents.insert_one(
        {
            "_id": "INC-0001",
            "open": True,
            "pond": "BL-01-A3",
            "timeline": [],
            "outbox": [
                {"to": "owner", "text": "Ao BL-01-A3: quạt ngừng quay.", "status": "pending", "at": now}
            ],
        }
    )
    sent: list[dict[str, Any]] = []
    notifier = Notifier(db, fake_telegram(sent), SETTINGS)

    await notifier.cycle(now)
    first = sent[0]
    assert first["method"] == "sendMessage" and first["chat_id"] == "100"
    buttons = [b for row in first["reply_markup"]["inline_keyboard"] for b in row]
    assert buttons[0]["callback_data"] == "ack:INC-0001"
    assert buttons[1]["url"] == "https://demo.example/#BL-01-A3"
    incident = await db.incidents.find_one({"_id": "INC-0001"})
    assert incident["outbox"][0]["status"] == "sent" and incident["timeline"][-1]["kind"] == "telegram"

    await notifier.cycle(now + timedelta(minutes=1))
    assert len(sent) == 1, "nothing new before three minutes"
    await notifier.cycle(now + timedelta(minutes=4))
    assert sent[-1]["chat_id"] == "100" and sent[-1]["text"].startswith("⚠️ Chưa ai nhận")
    await notifier.cycle(now + timedelta(minutes=8))
    assert len(sent) == 2, "reminded once"


async def test_without_a_bot_messages_stay_in_the_console(api: tuple[httpx.AsyncClient, Any]) -> None:
    _, db = api
    now = datetime.now(UTC)
    outbox = [{"to": "owner", "text": "x", "status": "pending", "at": now}]
    await db.incidents.insert_one({"_id": "INC-0002", "open": True, "timeline": [], "outbox": outbox})
    await Notifier(db, Telegram(Settings()), Settings()).cycle(now)
    assert (await db.incidents.find_one({"_id": "INC-0002"}))["outbox"][0]["status"] == "console"


async def test_the_button_records_who_acknowledged(
    api: tuple[httpx.AsyncClient, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = api
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "hook-secret")
    config.get_settings.cache_clear()
    sent: list[dict[str, Any]] = []
    app.state.telegram = fake_telegram(sent)
    await db.incidents.insert_one({"_id": "INC-0003", "open": True, "timeline": []})
    press = {
        "update_id": 1,
        "callback_query": {
            "id": "cb-1",
            "from": {"id": 7, "first_name": "Minh"},
            "data": "ack:INC-0003",
            "message": {"message_id": 41, "chat": {"id": 100}, "text": "Ao BL-01-A3: quạt ngừng quay."},
        },
    }
    assert (await client.post("/v1/hooks/telegram", json=press)).status_code == 401
    headers = {"X-Telegram-Bot-Api-Secret-Token": "hook-secret"}
    assert (await client.post("/v1/hooks/telegram", json=press, headers=headers)).json() == {"ok": True}
    incident = await db.incidents.find_one({"_id": "INC-0003"})
    assert incident["acknowledged_by"] == "Minh" and incident["timeline"][-1]["kind"] == "acknowledged"
    assert [s["method"] for s in sent] == ["answerCallbackQuery", "editMessageText"]
    assert "✅ Minh đã nhận lúc" in sent[1]["text"]

    await client.post("/v1/hooks/telegram", json=press, headers=headers)
    assert sent[-1]["text"] == "Sự cố này đã có người nhận rồi.", "a second press changes nothing"
