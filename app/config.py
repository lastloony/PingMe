"""Application configuration"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # Telegram Bot
    bot_token: str
    
    # Database
    database_url: str = "sqlite+aiosqlite:///./pingme.db"
    
    # FastAPI
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_reload: bool = True
    
    # Application
    debug: bool = True
    timezone: str = "Europe/Moscow"
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False
    )


settings = Settings()
