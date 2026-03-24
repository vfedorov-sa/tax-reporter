"""Настройки сервиса. Всё, что отличается между стендами, приходит из окружения."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TAX_REPORTER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    templates_dir: Path = Path("templates")
    clinics_path: Path = Path("templates/clinics.json")
    output_dir: Path = Path("out")
    signature_path: Path | None = None

    gateway: Literal["local", "http"] = "local"
    gateway_url: str | None = None
    gateway_token: str = ""

    intake_url: str | None = None
    intake_token: str = ""

    request_timeout: float = 30.0
    max_attempts: int = 3


def load_settings() -> Settings:
    return Settings()
