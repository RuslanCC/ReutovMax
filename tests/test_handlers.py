from __future__ import annotations

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest

from reutov_max.handlers import BotHandlers
from reutov_max.openai_service import TicketAnalysis
from reutov_max.tickets import TicketRepo


@pytest.fixture
async def repo() -> TicketRepo:
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    r = TicketRepo(path)
    await r.init()
    yield r
    os.unlink(path)


def _make_handlers(repo: TicketRepo, analysis: TicketAnalysis) -> tuple[BotHandlers, MagicMock, MagicMock]:
    client = MagicMock()
    client.send_message = AsyncMock()
    client.answer_callback = AsyncMock()
    client.download = AsyncMock(return_value=b"")
    openai = MagicMock()
    openai.analyze = AsyncMock(return_value=analysis)
    openai.transcribe_voice = AsyncMock(return_value="расшифрованный текст")
    openai.describe_image = AsyncMock(return_value="яма на дороге")
    operator = MagicMock()
    operator._chat_id = -42
    operator.notify = AsyncMock()
    handlers = BotHandlers(client, openai, repo, operator, yandex_geocoder_key=None)
    return handlers, client, operator


async def test_text_ticket_creates_record(repo: TicketRepo) -> None:
    analysis = TicketAnalysis(
        intent="ticket", is_faq=False, faq_answer=None,
        summary="Яма на ул. Ленина 5", category="дороги", address="ул. Ленина 5",
    )
    h, client, operator = _make_handlers(repo, analysis)
    await h.dispatch({
        "update_type": "message_created",
        "message": {
            "sender": {"user_id": 100, "name": "Иван"},
            "recipient": {"chat_id": 999, "chat_type": "dialog"},
            "body": {"text": "На ул. Ленина 5 яма", "attachments": []},
        },
    })
    operator.notify.assert_awaited_once()
    client.send_message.assert_awaited()  # ответ жителю


async def test_faq_does_not_create_ticket(repo: TicketRepo) -> None:
    analysis = TicketAnalysis(
        intent="faq", is_faq=True, faq_answer="Часы работы 9-18", summary="", category="прочее", address=None,
    )
    h, _, operator = _make_handlers(repo, analysis)
    await h.dispatch({
        "update_type": "message_created",
        "message": {
            "sender": {"user_id": 1, "name": "A"},
            "recipient": {"chat_id": 2, "chat_type": "dialog"},
            "body": {"text": "Часы работы?", "attachments": []},
        },
    })
    operator.notify.assert_not_called()


async def test_bot_started_sends_menu(repo: TicketRepo) -> None:
    analysis = TicketAnalysis("ticket", False, None, "", "прочее", None)
    h, client, _ = _make_handlers(repo, analysis)
    await h.dispatch({"update_type": "bot_started", "chat_id": 555, "user": {"user_id": 1}})
    client.send_message.assert_awaited_once()
    kwargs = client.send_message.call_args.kwargs
    assert kwargs["chat_id"] == 555
    # есть инлайн-клавиатура
    assert any(a.get("type") == "inline_keyboard" for a in kwargs["attachments"])


async def test_location_attaches_to_pending_ticket(repo: TicketRepo) -> None:
    analysis = TicketAnalysis("ticket", False, None, "Заявка", "прочее", None)
    h, _, operator = _make_handlers(repo, analysis)
    # 1) житель присылает текст без адреса -> ticket awaiting_location
    await h.dispatch({
        "update_type": "message_created",
        "message": {
            "sender": {"user_id": 7, "name": "B"},
            "recipient": {"chat_id": 70, "chat_type": "dialog"},
            "body": {"text": "Тут проблема", "attachments": []},
        },
    })
    operator.notify.assert_awaited_once()
    operator.notify.reset_mock()
    # 2) житель присылает геопозицию -> заявка обновляется и оператор уведомляется снова
    await h.dispatch({
        "update_type": "message_created",
        "message": {
            "sender": {"user_id": 7},
            "recipient": {"chat_id": 70, "chat_type": "dialog"},
            "body": {"text": "", "attachments": [
                {"type": "location", "latitude": 55.76, "longitude": 37.86}
            ]},
        },
    })
    operator.notify.assert_awaited_once()
    ticket = await repo.get(1)
    assert ticket is not None
    assert ticket.lat == 55.76 and ticket.lon == 37.86
    assert ticket.geo_source == "max_location"
    assert ticket.status == "new"
