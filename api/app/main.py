from contextlib import asynccontextmanager
from typing import Any

import anthropic
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import streaming
from .agent import run_agent, ui_to_anthropic
from .config import get_settings
from .db import create_pool
from .helpdesk.repo import HelpdeskRepo
from .helpdesk.seed import seed
from .helpdesk.tools import helpdesk_tools
from .rag.embeddings import build_embedder
from .rag.store import VectorStore
from .ratelimit import SlidingWindowLimiter

SYSTEM_PROMPT = """You are Nim, the support agent for Nimbus, a project management SaaS.

How you work:
- For product, pricing, or policy questions, call search_help_center first and answer from the
  articles. Name the article you used. If the articles don't cover it, say so instead of guessing.
- For anything about a specific account or invoice, ask for the account email if you don't have
  it, then use lookup_customer or get_invoice. Never invent account details.
- Refunds: check the invoice, confirm the amount with the customer, then call propose_refund.
  A refund is only pending until a human approves it; never tell the customer it is done.
  Its status can change after you propose it, so call lookup_customer again before telling the
  customer whether a refund was approved.
  If the tool reports a policy violation, explain the policy and offer to escalate.
- Call escalate_to_human when the customer asks for a person, for bugs or outages you can't fix,
  for 2FA resets, or when policy blocks what they need. Tell them the ticket number.
- Be warm and brief. Use short paragraphs and bullet lists for steps."""


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = get_settings()
    pool = await create_pool(cfg.database_url, cfg.embedding_dim)
    embedder = build_embedder(
        cfg.embedder, cfg.openai_api_key, cfg.embedding_model, cfg.embedding_dim
    )
    app.state.pool = pool
    app.state.store = VectorStore(pool, embedder)
    app.state.repo = HelpdeskRepo(pool)
    app.state.llm = anthropic.AsyncAnthropic(api_key=cfg.anthropic_api_key or None)
    app.state.limiter = SlidingWindowLimiter(cfg.chat_rate_limit, cfg.chat_rate_window_s)
    yield
    await pool.close()


app = FastAPI(title="Nimbus HelpDesk API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


class ChatRequest(BaseModel):
    id: str | None = None
    messages: list[dict[str, Any]]


@app.post("/api/chat")
async def chat(req: ChatRequest, request: Request) -> StreamingResponse:
    if not request.app.state.limiter.allow(client_ip(request)):
        raise HTTPException(429, "Too many messages. Try again in a few minutes.")
    st = request.app.state
    model = get_settings().chat_model
    messages = ui_to_anthropic(req.messages)
    tools = helpdesk_tools(st.store, st.repo, st.llm, model, messages)
    stream = run_agent(st.llm, model, SYSTEM_PROMPT, messages, tools)
    return StreamingResponse(stream, media_type="text/event-stream", headers=streaming.HEADERS)


class RefundDecision(BaseModel):
    approve: bool


@app.post("/api/refunds/{refund_id}/decision")
async def decide_refund(refund_id: int, body: RefundDecision, request: Request) -> dict[str, Any]:
    row = await request.app.state.repo.decide_refund(refund_id, body.approve)
    if row is None:
        raise HTTPException(409, "refund not found or already decided")
    return {"id": row["id"], "status": row["status"]}


@app.get("/api/tickets")
async def list_tickets(request: Request) -> list[dict[str, Any]]:
    return await request.app.state.repo.list_tickets()


@app.get("/api/articles")
async def list_articles(request: Request) -> list[dict[str, Any]]:
    return await request.app.state.store.list_documents()


@app.post("/api/admin/reset")
async def reset_demo(request: Request, x_admin_token: str = Header(default="")) -> dict[str, str]:
    token = get_settings().admin_token
    if not token or x_admin_token != token:
        raise HTTPException(403, "forbidden")
    await seed(request.app.state.pool, request.app.state.store)
    return {"status": "reset"}
