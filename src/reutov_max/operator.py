from __future__ import annotations

import logging

from .keyboards import operator_card_kbd
from .max_client import MaxClient
from .tickets import Ticket, TicketRepo

log = logging.getLogger(__name__)


def _format_card(t: Ticket, *, phone: str | None = None) -> str:
    contact_lines = [f"👤 *Заявитель:* {t.user_name or 'житель'}", f"🆔 user_id: `{t.user_id}`"]
    if phone:
        contact_lines.append(f"📞 *Телефон:* {phone}")
    parts = [
        f"🆕 *Заявка №{t.id}*  ·  _{t.category or 'прочее'}_",
        *contact_lines,
        "",
        t.ai_summary or t.original_text or t.transcript or "(без описания)",
    ]
    if t.address:
        parts += ["", f"📍 {t.address}"]
    elif t.lat is not None and t.lon is not None:
        parts += ["", f"📍 {t.lat:.5f}, {t.lon:.5f}"]
    if t.transcript and t.kind == "voice":
        parts += ["", f"🗣 _Расшифровка:_ {t.transcript}"]
    if t.photo_url:
        parts += ["", f"🖼 {t.photo_url}"]
    return "\n".join(parts)


class Operator:
    def __init__(self, client: MaxClient, repo: TicketRepo, chat_id: int) -> None:
        self._client = client
        self._repo = repo
        self._chat_id = chat_id

    async def notify(self, ticket: Ticket) -> None:
        phone = await self._repo.get_user_phone(ticket.user_id)
        try:
            resp = await self._client.send_message(
                chat_id=self._chat_id,
                text=_format_card(ticket, phone=phone),
                attachments=[operator_card_kbd(ticket.id, lat=ticket.lat, lon=ticket.lon)],
                format="markdown",
            )
            mid = resp.get("message", {}).get("body", {}).get("mid")
            if mid:
                await self._repo.update(ticket.id, operator_message_id=mid)
        except Exception as e:  # noqa: BLE001
            log.exception("Failed to notify operator about ticket %s: %s", ticket.id, e)
