from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = ""
    openai_api_key: str = ""
    database_url: str = "postgresql://app:app@localhost:5432/app"
    chat_model: str = "claude-opus-5-5"
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536
    cors_origins: list[str] = ["http://localhost:3000"]
    # "openai" for real embeddings, "hash" for offline dev and tests
    embedder: str = "openai"
    # Protects POST /api/admin/reset on the public demo
    admin_token: str = ""
    # Per-IP chat requests allowed per window, to cap API spend on a public deploy
    chat_rate_limit: int = 20
    chat_rate_window_s: int = 600


@lru_cache
def get_settings() -> Settings:
    return Settings()
