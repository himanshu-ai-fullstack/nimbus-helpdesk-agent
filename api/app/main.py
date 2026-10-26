from contextlib import asynccontextmanager

import anthropic
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import get_settings
from .db import create_pool
from .platform.repo import PlatformRepo
from .rag.embeddings import build_embedder
from .rag.store import VectorStore
from .ratelimit import SlidingWindowLimiter
from .routes import admin, chat, knowledge
from .telemetry.store import ConversationStore
from .tenants.loader import TenantNotFound, TenantRegistry, load_tenants


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = get_settings()
    registry = TenantRegistry(load_tenants())
    pool = await create_pool(cfg.database_url, cfg.embedding_dim)
    await registry.sync(pool, cfg.tenant_admin_tokens)
    embedder = build_embedder(
        cfg.embedder, cfg.openai_api_key, cfg.embedding_model, cfg.embedding_dim
    )
    app.state.tenants = registry
    app.state.pool = pool
    app.state.store = VectorStore(pool, embedder)
    app.state.repo = PlatformRepo(pool)
    app.state.conversations = ConversationStore(pool)
    app.state.llm = anthropic.AsyncAnthropic(api_key=cfg.anthropic_api_key or None)
    app.state.limiter = SlidingWindowLimiter(cfg.chat_rate_limit, cfg.chat_rate_window_s)
    yield
    await pool.close()


app = FastAPI(title="HelpDesk Agent Platform API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(admin.router)
app.include_router(chat.router)
app.include_router(knowledge.router)


@app.exception_handler(TenantNotFound)
async def unknown_tenant(_request: Request, _exc: TenantNotFound) -> JSONResponse:
    return JSONResponse({"detail": "unknown tenant"}, status_code=404)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
