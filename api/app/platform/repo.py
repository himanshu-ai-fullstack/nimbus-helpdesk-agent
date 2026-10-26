from datetime import date
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from ..connectors.base import Account, Connector
from ..db import tenant_conn
from ..tenants.models import TenantConfig
from .policy import ActionNotAllowed, evaluate


class PlatformRepo:
    """Actions (pending human approval) and tickets. Everything is tenant-scoped;
    company records themselves are read through the tenant's Connector."""

    def __init__(self, pool: AsyncConnectionPool):
        self._pool = pool

    async def _all(self, tenant: str, query: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        async with tenant_conn(self._pool, tenant) as conn:
            cur = conn.cursor(row_factory=dict_row)
            await cur.execute(query, params)
            return await cur.fetchall()

    async def _one(self, tenant: str, query: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
        rows = await self._all(tenant, query, params)
        return rows[0] if rows else None

    async def propose_action(
        self,
        tenant: TenantConfig,
        connector: Connector,
        *,
        kind: str,
        record_id: str,
        amount_cents: int | None,
        reason: str,
        allowed_accounts: set[str],
        conversation_id: str | None = None,
        today: date | None = None,
    ) -> dict[str, Any]:
        policy = tenant.actions.get(kind)
        if policy is None:
            raise ActionNotAllowed(f"{kind!r} is not an action this agent can take")
        record = await connector.get_record(record_id)
        if record is None:
            raise ActionNotAllowed(f"{record_id} not found")
        if record.account_id not in allowed_accounts:
            raise ActionNotAllowed(
                f"{record_id} does not belong to an account looked up in this conversation"
            )
        account = await connector.get_account(record.account_id)
        assert account is not None
        async with tenant_conn(self._pool, tenant.slug) as conn:
            # Serialise proposals per record so two concurrent requests can't both
            # pass the remaining-amount check.
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{tenant.slug}:{record.id}",)
            )
            cur = conn.cursor(row_factory=dict_row)
            await cur.execute(
                "SELECT kind, amount_cents, status FROM actions WHERE tenant_id = %s AND "
                "record_id = %s AND status IN ('pending_approval', 'approved')",
                (tenant.slug, record.id),
            )
            existing = await cur.fetchall()
            evaluate(
                kind,
                policy,
                record,
                amount_cents,
                committed_cents=sum(a["amount_cents"] or 0 for a in existing),
                has_pending=any(
                    a["kind"] == kind and a["status"] == "pending_approval" for a in existing
                ),
                today=today or date.today(),
            )
            await cur.execute(
                "INSERT INTO actions (tenant_id, conversation_id, kind, record_id, account_id, "
                "account_name, amount_cents, currency, reason) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *",
                (
                    tenant.slug,
                    conversation_id,
                    kind,
                    record.id,
                    account.id,
                    account.name,
                    amount_cents,
                    record.currency,
                    reason,
                ),
            )
            row = await cur.fetchone()
        assert row is not None
        return {**row, "record_title": record.title}

    async def decide_action(
        self, tenant_id: str, action_id: int, approve: bool
    ) -> dict[str, Any] | None:
        return await self._one(
            tenant_id,
            "UPDATE actions SET status = %s, decided_at = now() "
            "WHERE tenant_id = %s AND id = %s AND status = 'pending_approval' RETURNING *",
            ("approved" if approve else "denied", tenant_id, action_id),
        )

    async def actions_for_account(self, tenant_id: str, account_id: str) -> list[dict[str, Any]]:
        return await self._all(
            tenant_id,
            "SELECT id, kind, record_id, amount_cents, status, created_at FROM actions "
            "WHERE tenant_id = %s AND account_id = %s ORDER BY created_at DESC",
            (tenant_id, account_id),
        )

    async def list_actions(self, tenant_id: str, status: str | None = None) -> list[dict[str, Any]]:
        return await self._all(
            tenant_id,
            "SELECT * FROM actions WHERE tenant_id = %s AND (%s::text IS NULL OR status = %s) "
            "ORDER BY created_at DESC LIMIT 200",
            (tenant_id, status, status),
        )

    async def create_ticket(
        self,
        tenant_id: str,
        account: Account | None,
        triage: dict[str, Any],
        transcript: list[dict[str, Any]],
        conversation_id: str | None = None,
    ) -> int:
        row = await self._one(
            tenant_id,
            "INSERT INTO tickets (tenant_id, conversation_id, account_id, account_name, triage, "
            "transcript) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (
                tenant_id,
                conversation_id,
                account.id if account else None,
                account.name if account else None,
                Jsonb(triage),
                Jsonb(transcript),
            ),
        )
        assert row is not None
        return int(row["id"])

    async def list_tickets(self, tenant_id: str) -> list[dict[str, Any]]:
        return await self._all(
            tenant_id,
            "SELECT id, account_id, account_name AS customer_name, triage, status, created_at "
            "FROM tickets WHERE tenant_id = %s ORDER BY created_at DESC LIMIT 200",
            (tenant_id,),
        )
