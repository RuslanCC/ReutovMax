from __future__ import annotations

import base64
import io
import json
import logging
from dataclasses import dataclass

from openai import AsyncOpenAI

log = logging.getLogger(__name__)


@dataclass
class TicketAnalysis:
    """Структурированный разбор обращения жителя."""
    is_faq: bool
    faq_answer: str | None
    summary: str           # короткое описание заявки для оператора
    category: str          # дороги, ЖКХ, освещение, мусор, транспорт, благоустройство, прочее
    address: str | None    # извлечённый адрес или None


class OpenAIService:
    def __init__(self, api_key: str, system_prompt: str, *, chat_model: str, transcribe_model: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self._system_prompt = system_prompt
        self._chat_model = chat_model
        self._transcribe_model = transcribe_model

    async def transcribe_voice(self, audio_bytes: bytes, filename: str = "voice.ogg") -> str:
        buf = io.BytesIO(audio_bytes)
        buf.name = filename
        resp = await self._client.audio.transcriptions.create(
            model=self._transcribe_model,
            file=buf,
            language="ru",
        )
        return (resp.text or "").strip()

    async def describe_image(self, image_bytes: bytes, hint: str | None = None) -> str:
        b64 = base64.b64encode(image_bytes).decode()
        prompt = (
            "Опиши кратко (1-2 предложения), что изображено на фотографии "
            "с точки зрения городской проблемы (яма, мусор, граффити, сломанная "
            "лавочка и т.п.). Если на фото нет проблемы — так и скажи. "
            "Если есть подпись от пользователя, учти её."
        )
        if hint:
            prompt += f"\n\nПодпись пользователя: {hint}"
        resp = await self._client.chat.completions.create(
            model=self._chat_model,
            messages=[
                {"role": "system", "content": self._system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    ],
                },
            ],
            max_tokens=300,
        )
        return (resp.choices[0].message.content or "").strip()

    async def analyze(self, text: str) -> TicketAnalysis:
        """Решает: FAQ это или заявка. Возвращает структурированный ответ."""
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["is_faq", "faq_answer", "summary", "category", "address"],
            "properties": {
                "is_faq": {"type": "boolean"},
                "faq_answer": {"type": ["string", "null"]},
                "summary": {"type": "string"},
                "category": {
                    "type": "string",
                    "enum": [
                        "дороги", "ЖКХ", "освещение", "мусор",
                        "транспорт", "благоустройство", "прочее",
                    ],
                },
                "address": {"type": ["string", "null"]},
            },
        }
        resp = await self._client.chat.completions.create(
            model=self._chat_model,
            messages=[
                {"role": "system", "content": self._system_prompt},
                {
                    "role": "user",
                    "content": (
                        "Сообщение жителя:\n---\n" + text + "\n---\n"
                        "Если это вопрос, на который есть ответ в FAQ из системного "
                        "промта, верни is_faq=true и заполни faq_answer. Иначе это "
                        "заявка о городской проблеме — заполни summary (1-2 предложения), "
                        "category и address (если адрес явно упомянут, иначе null)."
                    ),
                },
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "ticket_analysis", "schema": schema, "strict": True},
            },
            max_tokens=500,
        )
        data = json.loads(resp.choices[0].message.content or "{}")
        return TicketAnalysis(**data)
