from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_ads_db"

    # Redis / Celery
    REDIS_URL: str = "redis://localhost:6379/0"

    # LLM (ClaudeHub proxy)
    CLAUDE_API_KEY: str = "sk-hub-U6sO4WBbMFVtCo8QDh7WJnpdWy42UDjM"
    CLAUDE_API_BASE: str = "https://api.claudehub.fun/v1"
    CLAUDE_MODEL: str = "claude-opus-4-6"

    # Wildberries
    WB_API_TOKEN: str = ""

    # Ozon
    OZON_CLIENT_ID: str = ""
    OZON_CLIENT_SECRET: str = ""

    # Encryption for storing tokens
    ENCRYPTION_KEY: str = ""

    # Auto-execution mode
    AUTO_MODE: bool = False

    # Logging
    LOG_LEVEL: str = "INFO"


settings = Settings()
