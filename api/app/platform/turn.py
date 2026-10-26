"""One user turn, end to end: load the server-stored history, run the agent with
the tenant's tools, and save the reply and its telemetry. The chat route streams
it to the browser; the answer evals run exactly the same path."""

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import anthropic
from psycopg_pool import AsyncConnectionPool

from ..agent import run_agent, ui_to_anthropic
from ..connectors.demo import DemoConnector
from ..rag.store import VectorStore
from ..streaming import Part
from ..telemetry.store import ConversationStore
from ..tenants.models import TenantConfig
from ..tools.registry import ToolContext, build_tools
from .messages import MessageBuilder, accounts_seen
from .prompt import system_prompt
from .repo import PlatformRepo

log = logging.getLogger(__name__)


@dataclass
class Services:
    pool: AsyncConnectionPool
    store: VectorStore
    repo: PlatformRepo
    conversations: ConversationStore
    llm: anthropic.AsyncAnthropic


async def run_turn(
    svc: Services, tenant: TenantConfig, conversation_id: str, text: str
) -> AsyncIterator[Part]:
    """Yields AI SDK stream parts. The conversation must already be open."""
    history = await svc.conversations.history(tenant.slug, conversation_id)
    user_msg = {
        "id": f"usr_{uuid.uuid4().hex}",
        "role": "user",
        "parts": [{"type": "text", "text": text}],
    }
    await svc.conversations.add_message(tenant.slug, conversation_id, user_msg)

    ctx = ToolContext(
        tenant=tenant,
        store=svc.store,
        repo=svc.repo,
        connector=DemoConnector(svc.pool, tenant.slug),
        conversations=svc.conversations,
        llm=svc.llm,
        conversation_id=conversation_id,
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
                await svc.conversations.add_message(tenant.slug, conversation_id, builder.message())
            await svc.conversations.record_turn(
                tenant.slug, conversation_id, message_id, events, builder.outcome()
            )
        except Exception:
            log.exception("failed to save conversation %s", conversation_id)

    try:
        async for part in run_agent(
            svc.llm,
            tenant.models.chat,
            system_prompt(tenant),
            ctx.history,
            tools,
            effort=tenant.models.chat_effort,
            message_id=message_id,
            on_event=events.append,
        ):
            builder.add(part)
            yield part
    finally:
        # Save even if the client disconnects mid-stream.
        await asyncio.shield(asyncio.ensure_future(persist()))
