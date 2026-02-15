"""Конфигурация приложения"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Корневая директория проекта (на уровень выше папки app/)
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Настройки приложения, загружаемые из переменных окружения / .env"""

    # Telegram-бот
    bot_token: str

    # База данных
    database_url: str = "sqlite+aiosqlite:///./pingme.db"
    postgres_user: str = "pingme"
    postgres_password: str = "pingme"
    postgres_db: str = "pingme"

    # FastAPI
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_reload: bool = True

    # Приложение
    debug: bool = True
    timezone: str = "Europe/Moscow"

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False
    )


settings = Settings()