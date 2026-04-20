from __future__ import annotations

import logging
from typing import Any

from .geo import geocode_yandex, yandex_maps_link
from .keyboards import main_menu, unknown_fallback_kbd
from .max_client import MaxClient
from .openai_service import OpenAIService, TicketAnalysis
from .operator import Operator
from .tickets import Ticket, TicketRepo
from .utils.media import extract_gps

log = logging.getLogger(__name__)


def _format_recap(t: Ticket) -> str:
    parts = [f"✅ *Заявка №{t.id} принята.* Спасибо за обращение!", ""]
    parts.append(f"*Категория:* {t.category or 'прочее'}")
    if t.ai_summary:
        parts.append(f"*Суть:* {t.ai_summary}")
    if t.kind == "voice" and t.transcript:
        parts.append(f"*Расшифровка голосового:* «{t.transcript}»")
    if t.kind == "photo":
        if t.original_text:
            parts.append(f"*Ваша подпись:* {t.original_text}")
        if t.ai_summary:
            parts.append(f"*На фото:* {t.ai_summary}")
    if t.address:
        parts.append(f"*Адрес:* {t.address}")
    elif t.lat is not None and t.lon is not None:
        parts.append(f"*Координаты:* {t.lat:.5f}, {t.lon:.5f}")
    return "\n".join(parts)

WELCOME = (
    "Здравствуйте! Я бот администрации г. Реутов.\n\n"
    "Через меня можно сообщить о городской проблеме: яма на дороге, "
    "не работает фонарь, переполненный мусорный бак и т.п.\n\n"
    "Выберите действие в меню ниже 👇"
)

HELP_TEXT = (
    "*Как со мной общаться:*\n\n"
    "✏️ *Текст* — опишите проблему словами, по возможности укажите адрес.\n"
    "🎙 *Голосовое* — расскажите голосом, я расшифрую.\n"
    "📷 *Фото* — пришлите фотографию проблемы, можно с подписью.\n"
    "📍 *Геопозиция* — нажмите 📎 в Max → «Геолокация», чтобы я знал точное место.\n\n"
    "После приёма заявки вы получите её номер. Оператор городской "
    "администрации свяжется при необходимости."
)

ABOUT_TEXT = (
    "*Бот «Реутов на связи»*\n\n"
    "Принимает обращения жителей г. Реутов и передаёт их в "
    "администрацию. Время реакции оператора — в рабочие дни с 9:00 до 18:00.\n\n"
    "Экстренные ситуации: 112."
)

NEW_TICKET_HINT = (
    "Опишите проблему: пришлите *текст*, *голосовое* или *фото*.\n"
    "Не забудьте указать адрес или прислать геопозицию (📎 → Геолокация)."
)


class BotHandlers:
    def __init__(
        self,
        client: MaxClient,
        openai: OpenAIService,
        repo: TicketRepo,
        operator: Operator,
        *,
        yandex_geocoder_key: str | None,
        faq_enabled: bool = True,
    ) -> None:
        self._client = client
        self._openai = openai
        self._repo = repo
        self._operator = operator
        self._yandex_key = yandex_geocoder_key
        self._faq_enabled = faq_enabled
        # user_id -> (text, user_name) последнего вопроса с intent=unknown,
        # чтобы по нажатию «Передать оператору» завести заявку из этого текста.
        self._pending_questions: dict[int, tuple[str, str | None]] = {}

    async def dispatch(self, update: dict[str, Any]) -> None:
        utype = update.get("update_type")
        try:
            if utype == "bot_started":
                await self._on_bot_started(update)
            elif utype == "message_callback":
                await self._on_callback(update)
            elif utype == "message_created":
                await self._on_message(update)
            else:
                log.debug("Ignoring update_type=%s", utype)
        except Exception:
            log.exception("dispatch failed for update_type=%s", utype)

    # ---------- entrypoints ----------

    async def _on_bot_started(self, update: dict[str, Any]) -> None:
        chat_id = update["chat_id"]
        await self._send_menu(chat_id, WELCOME)

    async def _on_callback(self, update: dict[str, Any]) -> None:
        cb = update["callback"]
        payload = cb.get("payload") or ""
        message = update.get("message") or {}
        recipient = message.get("recipient") or {}
        chat_id = recipient.get("chat_id") or cb.get("user", {}).get("user_id")

        if payload == "menu":
            await self._client.answer_callback(cb["callback_id"])
            await self._send_menu(chat_id, "Главное меню:")
        elif payload == "help":
            await self._client.answer_callback(cb["callback_id"])
            await self._send(chat_id, HELP_TEXT, kbd=main_menu(faq_enabled=self._faq_enabled), format="markdown")
        elif payload == "faq":
            await self._client.answer_callback(cb["callback_id"])
            await self._send(
                chat_id,
                "Просто задайте свой вопрос текстом или голосом — я постараюсь ответить.\n"
                "Например: _«Где оплатить ЖКУ?»_ или _«Как записаться к стоматологу?»_",
                kbd=main_menu(faq_enabled=self._faq_enabled),
                format="markdown",
            )
        elif payload == "new_ticket":
            await self._client.answer_callback(cb["callback_id"])
            await self._send(chat_id, NEW_TICKET_HINT, kbd=main_menu(faq_enabled=self._faq_enabled), format="markdown")
        elif payload == "about":
            await self._client.answer_callback(cb["callback_id"])
            await self._send(chat_id, ABOUT_TEXT, kbd=main_menu(faq_enabled=self._faq_enabled), format="markdown")
        elif payload == "q_to_operator":
            await self._client.answer_callback(cb["callback_id"])
            user_id = cb.get("user", {}).get("user_id")
            pending = self._pending_questions.pop(user_id, None) if user_id else None
            if not pending:
                await self._send(
                    chat_id,
                    "Не нашёл ваш последний вопрос — напишите его ещё раз, и я передам оператору.",
                    kbd=main_menu(faq_enabled=self._faq_enabled),
                )
                return
            text, user_name = pending
            analysis = TicketAnalysis(
                intent="ticket", is_faq=False, faq_answer=None,
                summary=text[:280], category="прочее", address=None,
            )
            await self._create_text_ticket(chat_id, user_id, user_name, text, analysis)
        elif payload.startswith("op_take:"):
            ticket_id = int(payload.split(":")[1])
            await self._repo.update(ticket_id, status="in_progress")
            await self._client.answer_callback(
                cb["callback_id"], notification=f"Заявка №{ticket_id} взята в работу"
            )
        elif payload.startswith("op_done:"):
            ticket_id = int(payload.split(":")[1])
            await self._repo.update(ticket_id, status="done")
            await self._client.answer_callback(
                cb["callback_id"], notification=f"Заявка №{ticket_id} закрыта"
            )
        else:
            await self._client.answer_callback(cb["callback_id"])

    async def _on_message(self, update: dict[str, Any]) -> None:
        msg = update["message"]
        sender = msg.get("sender") or {}
        if sender.get("is_bot"):
            return
        recipient = msg.get("recipient") or {}
        chat_id = recipient.get("chat_id")
        user_id = sender.get("user_id")
        name = sender.get("name") or sender.get("first_name") or "житель"
        username = sender.get("username")
        user_name = f"{name} (@{username})" if username else name

        body = msg.get("body") or {}
        text = (body.get("text") or "").strip()
        attachments = body.get("attachments") or []

        await self._repo.upsert_user(
            user_id, name=name, username=username,
        )

        # 0) контакт (телефон)
        for att in attachments:
            if att.get("type") == "contact":
                await self._handle_contact(chat_id, user_id, att)
                return

        # 1) геопозиция
        for att in attachments:
            if att.get("type") == "location":
                await self._handle_location(chat_id, user_id, user_name, att, text)
                return

        # 2) фото
        photos = [a for a in attachments if a.get("type") == "image"]
        if photos:
            await self._handle_photo(chat_id, user_id, user_name, photos[0], text)
            return

        # 3) голос/аудио
        audios = [a for a in attachments if a.get("type") == "audio"]
        if audios:
            await self._handle_voice(chat_id, user_id, user_name, audios[0])
            return

        # 4) текст
        if text:
            await self._handle_text(chat_id, user_id, user_name, text)

    # ---------- specific handlers ----------

    async def _handle_text(self, chat_id: int, user_id: int, user_name: str | None, text: str) -> None:
        low = text.lower().strip().lstrip("/")
        if low in ("start", "menu", "меню", "помощь", "help", "начать"):
            await self._send_menu(chat_id, WELCOME if low in ("start", "начать") else "Главное меню:")
            return

        await self._send(chat_id, "🤔 Обрабатываю ваше сообщение…", format=None)
        analysis = await self._openai.analyze(text)
        await self._route_analysis(chat_id, user_id, user_name, text, analysis)

    async def _route_analysis(
        self,
        chat_id: int,
        user_id: int,
        user_name: str | None,
        text: str,
        analysis: TicketAnalysis,
        *,
        kind: str = "text",
        transcript: str | None = None,
    ) -> None:
        intent = (analysis.intent or "").lower()
        if not self._faq_enabled:
            # FAQ-ответы и фолбэк «unknown» отключены — всё идёт в заявку.
            if not analysis.summary:
                analysis.summary = text[:280]
            await self._create_text_ticket(
                chat_id, user_id, user_name, text, analysis,
                kind=kind, transcript=transcript,
            )
            return
        if intent == "faq" or (analysis.is_faq and analysis.faq_answer):
            if analysis.faq_answer:
                await self._send(chat_id, analysis.faq_answer, kbd=main_menu(faq_enabled=self._faq_enabled))
                return
        if intent == "unknown":
            self._pending_questions[user_id] = (text, user_name)
            fallback = (
                "Не нашёл точного ответа в справочной базе. "
                "Попробуйте переформулировать вопрос или позвоните в приёмную "
                "администрации: *+7 (498) 661-25-25* (Пн–Чт 9:00–18:00, Пт 9:00–16:45).\n\n"
                "Если хотите, я могу передать ваш вопрос оператору — нажмите кнопку ниже."
            )
            await self._send(chat_id, fallback, kbd=unknown_fallback_kbd(), format="markdown")
            return
        await self._create_text_ticket(
            chat_id, user_id, user_name, text, analysis,
            kind=kind, transcript=transcript,
        )

    async def _handle_voice(
        self, chat_id: int, user_id: int, user_name: str | None, attachment: dict[str, Any]
    ) -> None:
        url = (attachment.get("payload") or {}).get("url")
        if not url:
            await self._send(chat_id, "Не удалось получить голосовое сообщение, попробуйте ещё раз.", kbd=main_menu(faq_enabled=self._faq_enabled))
            return
        await self._send(chat_id, "🎙 Слушаю, расшифровываю…", format=None)
        try:
            audio = await self._client.download(url)
            transcript = await self._openai.transcribe_voice(audio)
        except Exception:
            log.exception("voice transcription failed")
            await self._send(chat_id, "Не получилось расшифровать голосовое 🥲 Попробуйте текстом.", kbd=main_menu(faq_enabled=self._faq_enabled))
            return
        if not transcript:
            await self._send(chat_id, "Голосовое получилось пустым. Опишите проблему ещё раз.", kbd=main_menu(faq_enabled=self._faq_enabled))
            return
        analysis = await self._openai.analyze(transcript)
        await self._route_analysis(
            chat_id, user_id, user_name, transcript, analysis,
            kind="voice", transcript=transcript,
        )

    async def _handle_photo(
        self,
        chat_id: int,
        user_id: int,
        user_name: str | None,
        attachment: dict[str, Any],
        caption: str,
    ) -> None:
        url = (attachment.get("payload") or {}).get("url")
        if not url:
            await self._send(chat_id, "Не удалось получить фото, попробуйте ещё раз.", kbd=main_menu(faq_enabled=self._faq_enabled))
            return
        await self._send(chat_id, "📷 Изучаю фотографию…", format=None)
        image_bytes = b""
        try:
            image_bytes = await self._client.download(url)
        except Exception:
            log.exception("photo download failed")

        try:
            description = await self._openai.describe_image(image_bytes, hint=caption or None)
        except Exception:
            log.exception("vision failed")
            description = caption or "Фото от жителя"

        gps = extract_gps(image_bytes) if image_bytes else None
        lat, lon, geo_source = (gps[0], gps[1], "exif") if gps else (None, None, None)

        ai_text = (caption + "\n" + description).strip() if caption else description
        analysis: TicketAnalysis | None = None
        try:
            analysis = await self._openai.analyze(ai_text)
        except Exception:
            log.exception("analyze failed")

        ticket = await self._repo.create(
            user_id=user_id,
            user_name=user_name,
            chat_id=chat_id,
            kind="photo",
            category=(analysis.category if analysis else "прочее"),
            original_text=caption or None,
            photo_url=url,
            ai_summary=description,
            address=(analysis.address if analysis else None),
            lat=lat, lon=lon, geo_source=geo_source,
        )
        await self._maybe_geocode(ticket)
        await self._finish_ticket(ticket, chat_id)

    async def _handle_contact(self, chat_id: int, user_id: int, att: dict) -> None:
        payload = att.get("payload") or {}
        vcf = payload.get("vcf_info") or ""
        phone = None
        for line in vcf.splitlines():
            if line.upper().startswith("TEL"):
                phone = line.split(":", 1)[-1].strip()
                break
        if not phone:
            tam = payload.get("tam_info") or {}
            phone = tam.get("phone")
        if phone:
            await self._repo.upsert_user(user_id, phone=phone)
            await self._send(chat_id, f"Спасибо! Сохранил ваш телефон: {phone}", kbd=main_menu(faq_enabled=self._faq_enabled))
        else:
            await self._send(chat_id, "Не удалось распознать телефон в контакте.", kbd=main_menu(faq_enabled=self._faq_enabled))

    async def _handle_location(
        self,
        chat_id: int,
        user_id: int,
        user_name: str | None,
        att: dict[str, Any],
        text: str,
    ) -> None:
        lat = att.get("latitude")
        lon = att.get("longitude")
        if lat is None or lon is None:
            return
        existing = await self._repo.latest_awaiting_location(user_id)
        if existing:
            await self._repo.update(
                existing.id, lat=lat, lon=lon, geo_source="max_location", status="new"
            )
            ticket = await self._repo.get(existing.id)
            await self._send(
                chat_id,
                f"Спасибо! Координаты добавлены к заявке №{existing.id}.\n"
                f"🗺 {yandex_maps_link(lat, lon)}",
                kbd=main_menu(faq_enabled=self._faq_enabled),
            )
            if ticket:
                await self._operator.notify(ticket)
            return
        # геопозиция без предварительной заявки — заводим короткую запись
        ticket = await self._repo.create(
            user_id=user_id, user_name=user_name, chat_id=chat_id, kind="text",
            category="прочее", original_text=text or "(только геопозиция)",
            ai_summary=text or "Житель прислал геопозицию без описания",
            lat=lat, lon=lon, geo_source="max_location",
        )
        await self._finish_ticket(ticket, chat_id)

    # ---------- helpers ----------

    async def _create_text_ticket(
        self,
        chat_id: int,
        user_id: int,
        user_name: str | None,
        text: str,
        analysis: TicketAnalysis,
        *,
        kind: str = "text",
        transcript: str | None = None,
    ) -> None:
        ticket = await self._repo.create(
            user_id=user_id,
            user_name=user_name,
            chat_id=chat_id,
            kind=kind,
            category=analysis.category,
            original_text=text,
            transcript=transcript,
            ai_summary=analysis.summary,
            address=analysis.address,
        )
        await self._maybe_geocode(ticket)
        await self._finish_ticket(ticket, chat_id)

    async def _maybe_geocode(self, ticket: Ticket) -> None:
        if ticket.lat is not None or not ticket.address or not self._yandex_key:
            return
        result = await geocode_yandex(ticket.address, self._yandex_key)
        if not result:
            return
        lat, lon, normalized = result
        await self._repo.update(
            ticket.id, lat=lat, lon=lon, address=normalized, geo_source="ai_text"
        )
        ticket.lat, ticket.lon, ticket.address, ticket.geo_source = lat, lon, normalized, "ai_text"

    async def _finish_ticket(self, ticket: Ticket, chat_id: int) -> None:
        recap = _format_recap(ticket)
        # если адреса нет — просим уточнить
        if ticket.lat is None and not ticket.address:
            await self._repo.update(ticket.id, status="awaiting_location")
            await self._send(
                chat_id,
                recap + "\n\nЧтобы оператор быстрее её обработал, пришлите, "
                "пожалуйста, *геопозицию* (📎 → Геолокация) или адрес текстом.",
                kbd=main_menu(faq_enabled=self._faq_enabled),
                format="markdown",
            )
        else:
            await self._send(chat_id, recap, kbd=main_menu(faq_enabled=self._faq_enabled), format="markdown")
        await self._operator.notify(ticket)

    async def _send_menu(self, chat_id: int, text: str) -> None:
        await self._client.send_message(
            chat_id=chat_id, text=text,
            attachments=[main_menu(faq_enabled=self._faq_enabled)],
            format="markdown",
        )

    async def _send(
        self,
        chat_id: int,
        text: str,
        *,
        kbd: dict[str, Any] | None = None,
        format: str | None = "markdown",
    ) -> None:
        await self._client.send_message(
            chat_id=chat_id,
            text=text,
            attachments=[kbd] if kbd else None,
            format=format,
        )
