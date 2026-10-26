from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# USD per million tokens: (input, output). Cache reads bill at 0.1x input and
# 5-minute cache writes at 1.25x input.
MODEL_PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
}


def cost_usd(
    model: str, input_tokens: int, output_tokens: int, cache_read: int = 0, cache_write: int = 0
) -> float:
    inp, out = MODEL_PRICES.get(model, (0.0, 0.0))
    return (
        input_tokens * inp + output_tokens * out + cache_read * inp * 0.1 + cache_write * inp * 1.25
    ) / 1_000_000


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = ""
    openai_api_key: str = ""
    database_url: str = "postgresql://app:app@localhost:5432/app"
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536
    cors_origins: list[str] = ["http://localhost:3000"]
    # "openai" for real embeddings, "hash" for offline dev and tests
    embedder: str = "openai"
    # Platform operations such as POST /api/admin/reset
    admin_token: str = ""
    # Per-tenant admin tokens as JSON, e.g. {"nimbus": "..."}. They unlock that
    # tenant's approvals, tickets, knowledge base and analytics. Only hashes are stored.
    tenant_admin_tokens: dict[str, str] = {}
    # Per-IP chat requests allowed per window, to cap API spend on a public deploy
    chat_rate_limit: int = 20
    chat_rate_window_s: int = 600
    # Daily model spend cap per tenant, in USD; 0 disables it
    tenant_daily_budget_usd: float = 5.0
    # Uploaded files and fetched pages larger than this are rejected
    max_upload_bytes: int = 5_000_000


@lru_cache
def get_settings() -> Settings:
    return Settings()
