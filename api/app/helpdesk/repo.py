from datetime import date
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

REFUND_WINDOW_DAYS = 14
AGENT_REFUND_LIMIT_CENTS = 50_000


class RefundNotAllowed(Exception):
    pass


class HelpdeskRepo:
    def __init__(self, pool: AsyncConnectionPool):
        self._pool = pool

    async def _one(self, sql: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
        async with self._pool.connection() as conn:
            cur = conn.cursor(row_factory=dict_row)
            await cur.execute(sql, params)
            return await cur.fetchone()

    async def _all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        async with self._pool.connection() as conn:
            cur = conn.cursor(row_factory=dict_row)
            await cur.execute(sql, params)
            return await cur.fetchall()

    async def find_customer(self, email: str) -> dict[str, Any] | None:
        return await self._one("SELECT * FROM customers WHERE lower(email) = lower(%s)", (email,))

    async def invoices_for(self, customer_id: str, limit: int = 6) -> list[dict[str, Any]]:
        return await self._all(
            "SELECT i.*, coalesce(sum(r.amount_cents) FILTER (WHERE r.status = 'approved'), 0) "
            "AS refunded_cents FROM invoices i LEFT JOIN refunds r ON r.invoice_id = i.id "
            "WHERE i.customer_id = %s GROUP BY i.id ORDER BY i.issued_on DESC LIMIT %s",
            (customer_id, limit),
        )

    async def get_invoice(self, invoice_id: str) -> dict[str, Any] | None:
        return await self._one(
            "SELECT i.*, c.email, c.name AS customer_name, "
            "coalesce((SELECT sum(amount_cents) FROM refunds WHERE invoice_id = i.id "
            "AND status IN ('approved', 'pending_approval')), 0) AS refunded_or_pending_cents "
            "FROM invoices i JOIN customers c ON c.id = i.customer_id WHERE i.id = %s",
            (invoice_id,),
        )

    async def propose_refund(
        self, invoice_id: str, amount_cents: int, reason: str, today: date | None = None
    ) -> dict[str, Any]:
        """Policy is enforced here, not just in the prompt: the model can only ever
        create a *pending* refund inside policy; a human approves it in the UI."""
        inv = await self.get_invoice(invoice_id)
        if inv is None:
            raise RefundNotAllowed(f"invoice {invoice_id} not found")
        if inv["status"] != "paid":
            raise RefundNotAllowed(
                f"invoice is {inv['status']}, only paid invoices can be refunded"
            )
        age = ((today or date.today()) - inv["issued_on"]).days
        if age > REFUND_WINDOW_DAYS:
            raise RefundNotAllowed(
                f"invoice is {age} days old; refunds are only allowed within "
                f"{REFUND_WINDOW_DAYS} days. Escalate to a human if there is a strong reason."
            )
        remaining = inv["amount_cents"] - inv["refunded_or_pending_cents"]
        if amount_cents <= 0 or amount_cents > remaining:
            raise RefundNotAllowed(f"amount must be between 1 and {remaining} cents")
        if amount_cents > AGENT_REFUND_LIMIT_CENTS:
            raise RefundNotAllowed("refunds above $500 must be escalated to a human")
        row = await self._one(
            "INSERT INTO refunds (invoice_id, amount_cents, reason) VALUES (%s, %s, %s) "
            "RETURNING *",
            (invoice_id, amount_cents, reason),
        )
        assert row is not None
        return {**row, "currency": inv["currency"], "customer_name": inv["customer_name"]}

    async def decide_refund(self, refund_id: int, approve: bool) -> dict[str, Any] | None:
        return await self._one(
            "UPDATE refunds SET status = %s, decided_at = now() "
            "WHERE id = %s AND status = 'pending_approval' RETURNING *",
            ("approved" if approve else "denied", refund_id),
        )

    async def create_ticket(
        self, customer_id: str | None, triage: dict[str, Any], transcript: list[dict[str, Any]]
    ) -> int:
        row = await self._one(
            "INSERT INTO tickets (customer_id, triage, transcript) VALUES (%s, %s, %s) RETURNING id",
            (customer_id, Jsonb(triage), Jsonb(transcript)),
        )
        assert row is not None
        return int(row["id"])

    async def list_tickets(self) -> list[dict[str, Any]]:
        return await self._all(
            "SELECT t.id, t.customer_id, c.name AS customer_name, t.triage, t.status, t.created_at "
            "FROM tickets t LEFT JOIN customers c ON c.id = t.customer_id "
            "ORDER BY t.created_at DESC"
        )
