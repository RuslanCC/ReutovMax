from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiohttp import web

from .config import get_settings
from .handlers import BotHandlers
from .max_client import MaxClient
from .openai_service import OpenAIService
from .operator import Operator
from .tickets import TicketRepo

log = logging.getLogger(__name__)


def _load_system_prompt() -> str:
    base = Path(__file__).resolve().parent.parent.parent / "prompts"
    sys_p = (base / "system_prompt.md").read_text(encoding="utf-8")
    faq_p = (base / "faq.md").read_text(encoding="utf-8")
    contacts_p = (base / "contacts.md").read_text(encoding="utf-8")
    return (
        f"{sys_p}\n\n"
        f"## База FAQ\n\n{faq_p}\n\n"
        f"## Справочник контактов\n\n{contacts_p}"
    )


async def _on_startup(app: web.Application) -> None:
    settings = app["settings"]
    repo: TicketRepo = app["repo"]
    client: MaxClient = app["client"]
    await repo.init()
    me = await client.get_me()
    log.info("Bot identity: %s", me)

    webhook_url = settings.resolve_webhook_url()
    if webhook_url:
        try:
            await client.subscribe_webhook(
                webhook_url,
                secret=settings.webhook_secret,
                update_types=[
                    "message_created",
                    "message_callback",
                    "bot_started",
                ],
            )
            log.info("Webhook subscribed: %s", webhook_url)
        except Exception:
            log.exception("Failed to subscribe webhook to %s", webhook_url)
    else:
        log.warning("WEBHOOK_URL is not set and RAILWAY_PUBLIC_DOMAIN is missing — webhook not registered")


async def _on_cleanup(app: web.Application) -> None:
    client: MaxClient = app["client"]
    await client.close()


async def _health(_: web.Request) -> web.Response:
    return web.Response(text="ok")


async def _webhook(request: web.Request) -> web.Response:
    settings = request.app["settings"]
    handlers: BotHandlers = request.app["handlers"]
    if settings.webhook_secret:
        # Max шлёт секрет в заголовке "Verify" (имя задаётся в подписке);
        # документация не фиксирует имя — поэтому проверяем мягко: если секрет
        # пришёл хоть в одном заголовке — он должен совпасть.
        candidates = [
            request.headers.get("X-Max-Secret"),
            request.headers.get("X-Verify-Token"),
            request.headers.get("Verify"),
        ]
        if any(candidates) and settings.webhook_secret not in candidates:
            return web.Response(status=401, text="bad secret")
    try:
        update = await request.json()
    except Exception:  # noqa: BLE001
        return web.Response(status=400, text="bad json")
    log.debug("incoming update: %s", update)
    asyncio.create_task(handlers.dispatch(update))
    return web.Response(text="ok")


def build_app() -> web.Application:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    client = MaxClient(settings.max_bot_token)
    repo = TicketRepo(settings.db_path)
    operator = Operator(client, repo, settings.operator_chat_id)
    openai_service = OpenAIService(
        settings.openai_api_key,
        _load_system_prompt(),
        chat_model=settings.openai_chat_model,
        transcribe_model=settings.openai_transcribe_model,
    )
    handlers = BotHandlers(
        client, openai_service, repo, operator,
        yandex_geocoder_key=settings.yandex_geocoder_key,
    )

    app = web.Application()
    app["settings"] = settings
    app["client"] = client
    app["repo"] = repo
    app["handlers"] = handlers
    app.router.add_get("/health", _health)
    app.router.add_post("/webhook", _webhook)
    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)
    return app


def main() -> None:
    app = build_app()
    settings = app["settings"]
    web.run_app(app, host="0.0.0.0", port=settings.port)


if __name__ == "__main__":
    main()
