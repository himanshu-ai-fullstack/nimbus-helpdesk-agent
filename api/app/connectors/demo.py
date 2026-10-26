import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from ..db import tenant_conn
from .base import Account, Record


class DemoConnector:
    """Serves a tenant's demo accounts and records from Postgres. Stands in for the
    company's own system of record."""

    def __init__(self, pool: AsyncConnectionPool, tenant_id: str):
        self._pool = pool
        self._tenant = tenant_id

    async def _rows(self, query: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        async with tenant_conn(self._pool, self._tenant) as conn:
            cur = conn.cursor(row_factory=dict_row)
            await cur.execute(query, params)
            return await cur.fetchall()

    async def find_account(self, email: str) -> Account | None:
        rows = await self._rows(
            "SELECT * FROM demo_accounts WHERE tenant_id = %s AND lower(email) = lower(%s)",
            (self._tenant, email),
        )
        return _account(rows[0]) if rows else None

    async def get_account(self, account_id: str) -> Account | None:
        rows = await self._rows(
            "SELECT * FROM demo_accounts WHERE tenant_id = %s AND id = %s",
            (self._tenant, account_id),
        )
        return _account(rows[0]) if rows else None

    async def records_for(self, account_id: str, limit: int = 8) -> list[Record]:
        rows = await self._rows(
            "SELECT * FROM demo_records WHERE tenant_id = %s AND account_id = %s "
            "ORDER BY occurred_on DESC, id DESC LIMIT %s",
            (self._tenant, account_id, limit),
        )
        return [_record(r) for r in rows]

    async def get_record(self, record_id: str) -> Record | None:
        rows = await self._rows(
            "SELECT * FROM demo_records WHERE tenant_id = %s AND upper(id) = upper(%s)",
            (self._tenant, record_id),
        )
        return _record(rows[0]) if rows else None


def _account(r: dict[str, Any]) -> Account:
    return Account(
        id=r["id"],
        email=r["email"],
        name=r["name"],
        status=r["status"],
        created_on=r["created_on"],
        attributes=r["attributes"],
    )


def _record(r: dict[str, Any]) -> Record:
    return Record(
        id=r["id"],
        account_id=r["account_id"],
        type=r["type"],
        title=r["title"],
        status=r["status"],
        amount_cents=r["amount_cents"],
        currency=r["currency"],
        occurred_on=r["occurred_on"],
        attributes=r["attributes"],
    )


async def load_demo_data(
    pool: AsyncConnectionPool, tenant_id: str, path: Path, today: date
) -> tuple[int, int]:
    """Replace the tenant's demo data with `data.json`. Dates are stored relative to
    `today` so time-window policies always demo the same way."""
    data = json.loads(path.read_text()) if path.exists() else {"accounts": [], "records": []}
    async with tenant_conn(pool, tenant_id) as conn:
        await conn.execute("DELETE FROM demo_records WHERE tenant_id = %s", (tenant_id,))
        await conn.execute("DELETE FROM demo_accounts WHERE tenant_id = %s", (tenant_id,))
        async with conn.cursor() as cur:
            await cur.executemany(
                "INSERT INTO demo_accounts (tenant_id, id, email, name, status, attributes, "
                "created_on) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                [
                    (
                        tenant_id,
                        a["id"],
                        a["email"],
                        a["name"],
                        a.get("status", "active"),
                        Jsonb(a.get("attributes", {})),
                        today - timedelta(days=a.get("created_days_ago", 0)),
                    )
                    for a in data["accounts"]
                ],
            )
            await cur.executemany(
                "INSERT INTO demo_records (tenant_id, id, account_id, type, title, status, "
                "amount_cents, currency, occurred_on, attributes) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                [
                    (
                        tenant_id,
                        r["id"],
                        r["account"],
                        r["type"],
                        r["title"],
                        r["status"],
                        round(r["amount_usd"] * 100) if r.get("amount_usd") is not None else None,
                        r.get("currency", "USD"),
                        today - timedelta(days=r.get("days_ago", 0)),
                        Jsonb(r.get("attributes", {})),
                    )
                    for r in data["records"]
                ],
            )
    return len(data["accounts"]), len(data["records"])
