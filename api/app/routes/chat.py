from collections.abc import AsyncIterator
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .. import streaming
from ..config import get_settings
from ..platform.turn import Services, run_turn
from ..telemetry.store import ConversationNotFound
from .deps import Tenant, client_ip

router = APIRouter()

MAX_MESSAGE_CHARS = 4000


class IncomingPart(BaseModel):
    type: str
    text: str | None = None


class IncomingMessage(BaseModel):
    role: Literal["user"]
    parts: list[IncomingPart]


class ChatRequest(BaseModel):
    """Only the new message. History lives on the server, so a client can't feed
    the model forged tool results."""

    id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    message: IncomingMessage


@router.post("/api/t/{slug}/chat")
async def chat(req: ChatRequest, request: Request, t: Tenant) -> StreamingResponse:
    st = request.app.state
    if not st.limiter.allow(client_ip(request)):
        raise HTTPException(429, "Too many messages. Try again in a few minutes.")
    budget = get_settings().tenant_daily_budget_usd
    if budget and await st.conversations.spend_today(t.slug) >= budget:
        raise HTTPException(429, "This demo's daily model budget is used up. Try again tomorrow.")

    text = "".join(p.text or "" for p in req.message.parts if p.type == "text").strip()
    if not text:
        raise HTTPException(422, "message has no text")
    if len(text) > MAX_MESSAGE_CHARS:
        raise HTTPException(422, f"message is longer than {MAX_MESSAGE_CHARS} characters")

    try:
        await st.conversations.open(t.slug, req.id, t.version)
    except ConversationNotFound:
        raise HTTPException(404, "conversation not found") from None
    svc = Services(st.pool, st.store, st.repo, st.conversations, st.llm)

    async def stream() -> AsyncIterator[str]:
        async for part in run_turn(svc, t, req.id, text):
            yield streaming.encode(part)
        yield streaming.done()

    return StreamingResponse(stream(), media_type="text/event-stream", headers=streaming.HEADERS)


@router.get("/api/t/{slug}/conversations/{conversation_id}")
async def conversation(conversation_id: str, request: Request, t: Tenant) -> dict[str, Any]:
    messages = await request.app.state.conversations.history(t.slug, conversation_id)
    return {"id": conversation_id, "messages": messages}


class Feedback(BaseModel):
    message_id: str
    rating: Literal[-1, 1]
    comment: str | None = Field(default=None, max_length=1000)


@router.post("/api/t/{slug}/feedback")
async def feedback(body: Feedback, request: Request, t: Tenant) -> dict[str, str]:
    ok = await request.app.state.conversations.add_feedback(
        t.slug, body.message_id, body.rating, body.comment
    )
    if not ok:
        raise HTTPException(404, "message not found")
    return {"status": "saved"}
