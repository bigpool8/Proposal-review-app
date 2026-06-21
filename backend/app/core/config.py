from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    SECRET_KEY: str = "dev-secret-key-change-before-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_HOURS: int = 24
    ANTHROPIC_API_KEY: str = ""
    REDIS_URL: str = "redis://localhost:6379/0"
    SUPABASE_URL: str = ""
    SUPABASE_ANON_KEY: str = ""

    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), extra="ignore")


settings = Settings()
