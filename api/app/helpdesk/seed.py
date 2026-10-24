"""Reset and seed demo data: help-center articles plus fictional customers whose
invoice dates are relative to today, so the 14-day refund window always demos.

    uv run python -m app.helpdesk.seed
"""

import asyncio
from datetime import date, timedelta
from pathlib import Path

from psycopg_pool import AsyncConnectionPool

from ..config import get_settings
from ..db import create_pool
from ..rag.embeddings import build_embedder
from ..rag.store import VectorStore

DOCS_DIR = Path(__file__).parent / "docs"

CUSTOMERS = [
    # id, name, email, plan, seats, status, days since signup
    ("cus_001", "Priya Sharma", "priya@lumen.example", "business", 18, "active", 410),
    ("cus_002", "Arjun Mehta", "arjun@tinyfox.example", "pro", 5, "active", 95),
    ("cus_003", "Sara Kim", "sara@northwind.example", "pro", 12, "past_due", 220),
    ("cus_004", "Leo Martins", "leo@brightpath.example", "free", 2, "active", 30),
]

INVOICES = [
    # id, customer, cents, status, description, days ago
    ("INV-1041", "cus_001", 43200, "paid", "Business plan, 18 seats, monthly", 34),
    ("INV-1042", "cus_001", 43200, "paid", "Business plan, 18 seats, monthly", 4),
    ("INV-1043", "cus_001", 7200, "paid", "3 extra seats added mid-cycle", 3),
    ("INV-2001", "cus_002", 60000, "paid", "Pro plan, 5 seats, annual", 6),
    ("INV-2002", "cus_002", 1000, "paid", "Automation run pack (1,000 runs)", 2),
    ("INV-3001", "cus_003", 14400, "paid", "Pro plan, 12 seats, monthly", 40),
    ("INV-3002", "cus_003", 14400, "unpaid", "Pro plan, 12 seats, monthly", 10),
]


def _title(markdown: str, fallback: str) -> str:
    first = markdown.strip().splitlines()[0]
    return first.lstrip("# ").strip() if first.startswith("#") else fallback


async def seed(pool: AsyncConnectionPool, store: VectorStore, today: date | None = None) -> None:
    today = today or date.today()
    async with pool.connection() as conn:
        await conn.execute(
            "TRUNCATE tickets, refunds, invoices, customers, documents RESTART IDENTITY CASCADE"
        )
        async with conn.cursor() as cur:
            await cur.executemany(
                "INSERT INTO customers (id, name, email, plan, seats, status, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                [(*c[:6], today - timedelta(days=c[6])) for c in CUSTOMERS],
            )
            await cur.executemany(
                "INSERT INTO invoices (id, customer_id, amount_cents, status, description, issued_on) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                [(*i[:5], today - timedelta(days=i[5])) for i in INVOICES],
            )
    for path in sorted(DOCS_DIR.glob("*.md")):
        text = path.read_text()
        await store.add_document(_title(text, path.stem), text, "help_article", {"slug": path.stem})


async def main() -> None:
    cfg = get_settings()
    pool = await create_pool(cfg.database_url, cfg.embedding_dim)
    try:
        await seed(
            pool,
            VectorStore(
                pool,
                build_embedder(
                    cfg.embedder, cfg.openai_api_key, cfg.embedding_model, cfg.embedding_dim
                ),
            ),
        )
    finally:
        await pool.close()
    print(f"Seeded {len(CUSTOMERS)} customers, {len(INVOICES)} invoices and the help center.")


if __name__ == "__main__":
    asyncio.run(main())
