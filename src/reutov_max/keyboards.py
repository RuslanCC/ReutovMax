from __future__ import annotations

from typing import Any


def _kbd(buttons: list[list[dict[str, Any]]]) -> dict[str, Any]:
    return {"type": "inline_keyboard", "payload": {"buttons": buttons}}


def main_menu(*, faq_enabled: bool = True) -> dict[str, Any]:
    rows: list[list[dict[str, Any]]] = [
        [{"type": "callback", "text": "📋 Как со мной общаться", "payload": "help"}],
    ]
    if faq_enabled:
        rows.append([{"type": "callback", "text": "❓ Частые вопросы", "payload": "faq"}])
    rows.extend([
        [{"type": "callback", "text": "✏️ Подать заявку", "payload": "new_ticket"}],
        [{"type": "request_geo_location", "text": "📍 Отправить геопозицию", "quick": True}],
        [{"type": "request_contact", "text": "📞 Поделиться телефоном"}],
        [{"type": "callback", "text": "ℹ️ О боте", "payload": "about"}],
    ])
    return _kbd(rows)


def back_to_menu() -> dict[str, Any]:
    return _kbd([[{"type": "callback", "text": "⬅️ В главное меню", "payload": "menu"}]])


def unknown_fallback_kbd() -> dict[str, Any]:
    return _kbd([
        [{"type": "callback", "text": "📨 Передать вопрос оператору", "payload": "q_to_operator"}],
        [{"type": "callback", "text": "⬅️ В главное меню", "payload": "menu"}],
    ])


def operator_card_kbd(ticket_id: int, *, lat: float | None, lon: float | None) -> dict[str, Any]:
    rows: list[list[dict[str, Any]]] = []
    if lat is not None and lon is not None:
        rows.append([{
            "type": "link",
            "text": "🗺 Открыть на карте",
            "url": f"https://yandex.ru/maps/?pt={lon},{lat}&z=17&l=map",
        }])
    rows.append([
        {"type": "callback", "text": "▶️ Взять в работу", "payload": f"op_take:{ticket_id}"},
        {"type": "callback", "text": "✅ Закрыть", "payload": f"op_done:{ticket_id}"},
    ])
    return _kbd(rows)
