"""A small Telegram Bot API client: send with buttons, answer a button press, edit, register the webhook.

The bot token is part of every request URL, so errors are logged by type and status only, never with
the request or the exception text.
"""

import logging
from typing import Any

import httpx

from firstlight.core.config import Settings

log = logging.getLogger("firstlight.telegram")

API = "https://api.telegram.org"


class Telegram:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.enabled = bool(settings.telegram_bot_token and settings.telegram_chat_id)
        self.chat = settings.telegram_chat_id
        self._base = f"{API}/bot{settings.telegram_bot_token}"
        self._client = client or httpx.AsyncClient(timeout=8.0)

    async def _call(self, method: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        try:
            response = await self._client.post(f"{self._base}/{method}", json=payload)
        except httpx.HTTPError as exc:
            log.warning(
                "telegram unreachable", extra={"ctx": {"method": method, "error": type(exc).__name__}}
            )
            return None
        body: dict[str, Any] = response.json() if response.content else {}
        if response.status_code != 200 or not body.get("ok"):
            log.warning(
                "telegram refused",
                extra={
                    "ctx": {
                        "method": method,
                        "status_code": response.status_code,
                        "error": body.get("description"),
                    }
                },
            )
            return None
        return body

    async def send(
        self, chat_id: str, text: str, buttons: list[list[dict[str, str]]] | None = None
    ) -> int | None:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
        if buttons:
            payload["reply_markup"] = {"inline_keyboard": buttons}
        body = await self._call("sendMessage", payload)
        return int(body["result"]["message_id"]) if body else None

    async def answer(self, callback_id: str, text: str) -> None:
        await self._call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})

    async def edit(self, chat_id: str | int, message_id: int, text: str) -> None:
        await self._call("editMessageText", {"chat_id": chat_id, "message_id": message_id, "text": text})

    async def set_webhook(self, url: str, secret: str) -> bool:
        body = await self._call(
            "setWebhook", {"url": url, "secret_token": secret, "allowed_updates": ["callback_query"]}
        )
        return body is not None

    async def close(self) -> None:
        await self._client.aclose()
