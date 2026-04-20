from __future__ import annotations

import os
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    max_bot_token: str = Field(..., alias="MAX_BOT_TOKEN")
    openai_api_key: str = Field(..., alias="OPENAI_API_KEY")
    operator_chat_id: int = Field(..., alias="OPERATOR_CHAT_ID")

    webhook_url: str | None = Field(default=None, alias="WEBHOOK_URL")
    webhook_secret: str = Field(default="reutov-max-secret", alias="WEBHOOK_SECRET")

    db_path: str = Field(default="./tickets.sqlite", alias="DB_PATH")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    yandex_geocoder_key: str | None = Field(default=None, alias="YANDEX_GEOCODER_KEY")
    port: int = Field(default=8080, alias="PORT")

    openai_chat_model: str = Field(default="gpt-4o-mini", alias="OPENAI_CHAT_MODEL")
    openai_transcribe_model: str = Field(default="whisper-1", alias="OPENAI_TRANSCRIBE_MODEL")

    def resolve_webhook_url(self) -> str | None:
        if self.webhook_url:
            return self.webhook_url.rstrip("/") + "/webhook" if not self.webhook_url.endswith("/webhook") else self.webhook_url
        domain = os.getenv("RAILWAY_PUBLIC_DOMAIN")
        if domain:
            return f"https://{domain}/webhook"
        return None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
