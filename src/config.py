"""Application configuration using pydantic-settings."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # TTS Configuration
    unrealspeech_api_key: str = ""
    openai_api_key: str = ""
    tts_engine: Literal["unrealspeech", "openai", "kokoro_api"] = "unrealspeech"
    tts_voice_id: str = "Scarlett"
    kokoro_api_url: str = "https://kokoro.nicky.pro/v1"

    # Server
    web_host: str = "127.0.0.1"
    web_port: int = 8000
    base_url: str = "http://localhost:8000"
    debug: bool = False

    # OpenRouter (for summaries)
    openrouter_api_key: str = ""
    summary_model: str = "google/gemini-2.0-flash-001"

    # Database
    database_path: str = "./data/db.sqlite"

    # Processing
    lazy_threshold: int = 10  # Items >= this use lazy processing

    # Scraper
    scraper_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    # Auth (optional - leave empty to disable)
    admin_password: str = ""


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
