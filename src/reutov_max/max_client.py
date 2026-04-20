from __future__ import annotations

import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)

BASE_URL = "https://botapi.max.ru"


class MaxClient:
    """Тонкая обёртка над Max Bot API.

    Используется заголовок Authorization: <token>. Передача токена через
    access_token в query больше не поддерживается Max.
    """

    def __init__(self, token: str, base_url: str = BASE_URL, timeout: float = 30.0) -> None:
        self._token = token
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
            headers={"Authorization": token},
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        resp = await self._client.request(method, path, params=params or None, json=json)
        if resp.status_code >= 400:
            log.error("Max API %s %s -> %s: %s", method, path, resp.status_code, resp.text)
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    async def get_me(self) -> dict[str, Any]:
        return await self._request("GET", "/me")

    async def list_subscriptions(self) -> dict[str, Any]:
        return await self._request("GET", "/subscriptions")

    async def subscribe_webhook(
        self,
        url: str,
        *,
        secret: str | None = None,
        update_types: list[str] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"url": url}
        if secret:
            body["secret"] = secret
        if update_types:
            body["update_types"] = update_types
        return await self._request("POST", "/subscriptions", json=body)

    async def unsubscribe_webhook(self, url: str) -> dict[str, Any]:
        return await self._request("DELETE", "/subscriptions", params={"url": url})

    async def send_message(
        self,
        *,
        chat_id: int | None = None,
        user_id: int | None = None,
        text: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
        format: str | None = None,
        notify: bool = True,
        disable_link_preview: bool = False,
    ) -> dict[str, Any]:
        if (chat_id is None) == (user_id is None):
            raise ValueError("Provide exactly one of chat_id or user_id")
        params: dict[str, Any] = {"disable_link_preview": str(disable_link_preview).lower()}
        if chat_id is not None:
            params["chat_id"] = chat_id
        else:
            params["user_id"] = user_id
        body: dict[str, Any] = {"notify": notify}
        if text is not None:
            body["text"] = text
        if attachments:
            body["attachments"] = attachments
        if format:
            body["format"] = format
        return await self._request("POST", "/messages", params=params, json=body)

    async def answer_callback(
        self,
        callback_id: str,
        *,
        notification: str | None = None,
        message: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if message:
            body["message"] = message
        # Max требует либо message, либо notification — тихо подставляем "✓"
        if "message" not in body:
            body["notification"] = notification or "✓"
        elif notification:
            body["notification"] = notification
        return await self._request(
            "POST", "/answers", params={"callback_id": callback_id}, json=body
        )

    async def download(self, url: str) -> bytes:
        async with httpx.AsyncClient(timeout=60.0) as c:
            r = await c.get(url)
            r.raise_for_status()
            return r.content
