# Реутов на связи — чат-бот мессенджера MAX

MVP бота для приёма обращений жителей города Реутов:
- Текст / голос / фото / геолокация
- Распознавание голоса через OpenAI Whisper
- Описание фото через GPT-4o-mini Vision
- Ответы на FAQ через GPT-4o-mini (FAQ зашит в системный промт)
- Хранение заявок в SQLite
- Уведомления оператору (группе администрации) в Max

## Стек
Python 3.11, aiohttp, httpx, OpenAI Python SDK, aiosqlite, Pillow.

## Структура
```
src/reutov_max/
  app.py            # точка входа aiohttp + регистрация webhook
  config.py         # настройки из env
  max_client.py     # обёртка Max Bot API
  openai_service.py # whisper, vision, classify
  handlers.py       # диспетчер update'ов
  keyboards.py      # инлайн-кнопки
  tickets.py        # SQLite-репозиторий заявок
  geo.py            # Yandex Geocoder
  operator.py       # уведомление оператора
  utils/media.py    # EXIF GPS из фото
prompts/
  system_prompt.md
  faq.md
```

## Локальный запуск
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .[dev]
cp .env.example .env  # вписать токены
python -m reutov_max.app
```
Для приёма webhook'ов нужен публичный HTTPS — на проде это Railway, локально — `ngrok http 8080`.

## Деплой на Railway
1. Создаёте проект (уже сделано).
2. В **Variables** задаёте: `MAX_BOT_TOKEN`, `OPENAI_API_KEY`, `OPERATOR_CHAT_ID`, `WEBHOOK_SECRET`, `DB_PATH=/data/tickets.sqlite`, опционально `YANDEX_GEOCODER_KEY`.
3. В **Volumes** монтируете volume в `/data` (чтобы SQLite пережил редеплой).
4. Включаете **Public Networking** → Railway отдаёт домен `*.up.railway.app`. Бот при старте сам зарегистрирует `https://<domain>/webhook` в Max.
5. Healthcheck: `GET /health` (уже прописан в `railway.json`).
6. Push в репозиторий — Railway собирает по nixpacks (`Procfile`/`runtime.txt` присутствуют).

## Тесты
```bash
pytest
```

## Безопасность
Все секреты — только в Railway Variables. В git ничего секретного не коммитим (см. `.gitignore`). Если токен случайно засветился — отзовите и создайте новый.
