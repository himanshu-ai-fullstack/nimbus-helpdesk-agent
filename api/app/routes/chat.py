import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .. import streaming
from ..agent import run_agent, ui_to_anthropic
from ..config import get_settings
from ..connectors.demo import DemoConnector
from ..platform.messages import MessageBuilder, accounts_seen
from ..platform.prompt import system_prompt
from ..telemetry.store import ConversationNotFound
from ..tools.registry import ToolContext, build_tools
from .deps import Tenant, client_ip

log = logging.getLogger(__name__)
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
    history = await st.conversations.history(t.slug, req.id)
    user_msg = {
        "id": f"usr_{uuid.uuid4().hex}",
        "role": "user",
        "parts": [{"type": "text", "text": text}],
    }
    await st.conversations.add_message(t.slug, req.id, user_msg)

    ctx = ToolContext(
        tenant=t,
        store=st.store,
        repo=st.repo,
        connector=DemoConnector(st.pool, t.slug),
        conversations=st.conversations,
        llm=st.llm,
        conversation_id=req.id,
        history=[],
        known_accounts=accounts_seen(history),
        question=text,
    )
    tools = build_tools(ctx)
    # The agent appends to this list as it works; escalation reads the same list.
    ctx.history = ui_to_anthropic([*history, user_msg], tools)

    message_id = f"msg_{uuid.uuid4().hex}"
    builder = MessageBuilder()
    events: list[dict[str, Any]] = []

    async def persist() -> None:
        try:
            if builder.parts:
                await st.conversations.add_message(t.slug, req.id, builder.message())
            await st.conversations.record_turn(
                t.slug, req.id, message_id, events, builder.outcome()
            )
        except Exception:
            log.exception("failed to save conversation %s", req.id)

    async def stream() -> AsyncIterator[str]:
        try:
            async for part in run_agent(
                st.llm,
                t.models.chat,
                system_prompt(t),
                ctx.history,
                tools,
                effort=t.models.chat_effort,
                message_id=message_id,
                on_event=events.append,
            ):
                builder.add(part)
                yield streaming.encode(part)
            yield streaming.done()
        finally:
            # Save even if the client disconnects mid-stream.
            await asyncio.shield(asyncio.ensure_future(persist()))

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
