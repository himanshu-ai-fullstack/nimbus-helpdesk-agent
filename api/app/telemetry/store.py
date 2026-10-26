from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from ..config import cost_usd
from ..db import tenant_conn
from ..platform.messages import OUTCOME_RANK


class ConversationNotFound(Exception):
    pass


class ConversationStore:
    """Server-owned conversation history plus per-call telemetry. The client sends
    only the new message; history always comes from here, so tool outputs the model
    sees are ones the server produced."""

    def __init__(self, pool: AsyncConnectionPool):
        self._pool = pool

    async def open(self, tenant_id: str, conversation_id: str, config_version: str) -> None:
        async with tenant_conn(self._pool, tenant_id) as conn:
            await conn.execute(
                "INSERT INTO conversations (id, tenant_id, config_version) VALUES (%s, %s, %s) "
                "ON CONFLICT (id) DO NOTHING",
                (conversation_id, tenant_id, config_version),
            )
            # The id is client-chosen: refuse one that belongs to another tenant.
            # RLS hides that row, so a conflict we can't see means it isn't ours.
            row = await (
                await conn.execute("SELECT 1 FROM conversations WHERE id = %s", (conversation_id,))
            ).fetchone()
        if row is None:
            raise ConversationNotFound(conversation_id)

    async def history(self, tenant_id: str, conversation_id: str) -> list[dict[str, Any]]:
        async with tenant_conn(self._pool, tenant_id) as conn:
            cur = conn.cursor(row_factory=dict_row)
            await cur.execute(
                "SELECT id, role, parts FROM messages WHERE tenant_id = %s AND "
                "conversation_id = %s ORDER BY seq",
                (tenant_id, conversation_id),
            )
            return list(await cur.fetchall())

    async def add_message(
        self, tenant_id: str, conversation_id: str, message: dict[str, Any]
    ) -> None:
        async with tenant_conn(self._pool, tenant_id) as conn:
            await conn.execute(
                "INSERT INTO messages (id, tenant_id, conversation_id, role, parts) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
                (
                    message["id"],
                    tenant_id,
                    conversation_id,
                    message["role"],
                    Jsonb(message["parts"]),
                ),
            )
            await conn.execute(
                "UPDATE conversations SET last_message_at = now() WHERE id = %s",
                (conversation_id,),
            )

    async def record_turn(
        self,
        tenant_id: str,
        conversation_id: str,
        message_id: str,
        events: list[dict[str, Any]],
        outcome: str,
    ) -> None:
        async with tenant_conn(self._pool, tenant_id) as conn:
            async with conn.cursor() as cur:
                await cur.executemany(
                    "INSERT INTO agent_events (tenant_id, conversation_id, message_id, step, kind, "
                    "tool_name, model, latency_ms, input_tokens, output_tokens, "
                    "cache_read_tokens, cache_write_tokens, is_error) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    [
                        (
                            tenant_id,
                            conversation_id,
                            message_id,
                            e["step"],
                            e["kind"],
                            e.get("tool_name"),
                            e.get("model"),
                            e["latency_ms"],
                            e.get("input_tokens", 0),
                            e.get("output_tokens", 0),
                            e.get("cache_read_tokens", 0),
                            e.get("cache_write_tokens", 0),
                            e.get("is_error", False),
                        )
                        for e in events
                    ],
                )
            # Outcome only ever escalates: answered < action_proposed < escalated.
            await conn.execute(
                "UPDATE conversations SET outcome = %s WHERE id = %s AND "
                "array_position(%s::text[], outcome) < array_position(%s::text[], %s)",
                (
                    outcome,
                    conversation_id,
                    list(OUTCOME_RANK),
                    list(OUTCOME_RANK),
                    outcome,
                ),
            )

    async def add_feedback(
        self, tenant_id: str, message_id: str, rating: int, comment: str | None
    ) -> bool:
        async with tenant_conn(self._pool, tenant_id) as conn:
            row = await (
                await conn.execute(
                    "SELECT conversation_id FROM messages WHERE id = %s AND role = 'assistant'",
                    (message_id,),
                )
            ).fetchone()
            if row is None:
                return False
            await conn.execute(
                "INSERT INTO feedback (message_id, tenant_id, conversation_id, rating, comment) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (message_id) DO UPDATE SET "
                "rating = excluded.rating, comment = excluded.comment, created_at = now()",
                (message_id, tenant_id, row[0], rating, comment),
            )
        return True

    async def add_gap(
        self, tenant_id: str, conversation_id: str | None, topic: str, question: str | None
    ) -> None:
        async with tenant_conn(self._pool, tenant_id) as conn:
            await conn.execute(
                "INSERT INTO knowledge_gaps (tenant_id, conversation_id, topic, question) "
                "VALUES (%s, %s, %s, %s)",
                (tenant_id, conversation_id, topic, question),
            )

    async def spend_today(self, tenant_id: str) -> float:
        async with tenant_conn(self._pool, tenant_id) as conn:
            rows = await (
                await conn.execute(
                    "SELECT model, sum(input_tokens), sum(output_tokens), sum(cache_read_tokens), "
                    "sum(cache_write_tokens) FROM agent_events WHERE tenant_id = %s AND "
                    "kind = 'llm' AND created_at >= date_trunc('day', now()) GROUP BY model",
                    (tenant_id,),
                )
            ).fetchall()
        return sum(cost_usd(r[0] or "", r[1], r[2], r[3], r[4]) for r in rows)
