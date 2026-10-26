"""Reset and seed every tenant from its folder: help articles from `docs/*.md` and
demo accounts and records from `data.json`.

    uv run python -m app.tenants.seed            # all tenants
    uv run python -m app.tenants.seed nimbus     # one tenant
"""

import asyncio
import sys
from datetime import date
from pathlib import Path

from psycopg_pool import AsyncConnectionPool

from ..config import get_settings
from ..connectors.demo import load_demo_data
from ..db import create_pool, tenant_conn
from ..rag.embeddings import build_embedder
from ..rag.store import VectorStore
from .loader import TenantRegistry, load_tenants
from .models import TenantConfig

# Deleting these cascades to messages, events and feedback.
RUNTIME_TABLES = ["knowledge_gaps", "actions", "tickets", "conversations", "documents"]


def _title(markdown: str, fallback: str) -> str:
    first = markdown.strip().splitlines()[0]
    return first.lstrip("# ").strip() if first.startswith("#") else fallback


async def seed_tenant(
    pool: AsyncConnectionPool,
    store: VectorStore,
    tenant: TenantConfig,
    folder: Path,
    today: date | None = None,
) -> dict[str, int]:
    today = today or date.today()
    async with tenant_conn(pool, tenant.slug) as conn:
        for table in RUNTIME_TABLES:
            await conn.execute(f"DELETE FROM {table} WHERE tenant_id = %s", (tenant.slug,))
    accounts, records = await load_demo_data(pool, tenant.slug, folder / "data.json", today)
    docs = sorted((folder / "docs").glob("*.md"))
    for path in docs:
        text = path.read_text()
        await store.add_document(
            tenant.slug,
            _title(text, path.stem),
            text,
            source=f"docs/{path.name}",
            kind="article",
            metadata={"slug": path.stem},
        )
    return {"articles": len(docs), "accounts": accounts, "records": records}


async def seed_all(
    pool: AsyncConnectionPool,
    store: VectorStore,
    registry: TenantRegistry,
    only: str | None = None,
    today: date | None = None,
) -> dict[str, dict[str, int]]:
    out = {}
    for t in registry.all():
        if only and t.slug != only:
            continue
        out[t.slug] = await seed_tenant(pool, store, t, registry.folder(t.slug), today)
    return out


async def main() -> None:
    cfg = get_settings()
    registry = TenantRegistry(load_tenants())
    pool = await create_pool(cfg.database_url, cfg.embedding_dim)
    try:
        await registry.sync(pool, cfg.tenant_admin_tokens)
        store = VectorStore(
            pool,
            build_embedder(
                cfg.embedder, cfg.openai_api_key, cfg.embedding_model, cfg.embedding_dim
            ),
        )
        report = await seed_all(
            pool, store, registry, only=sys.argv[1] if len(sys.argv) > 1 else None
        )
    finally:
        await pool.close()
    for slug, counts in report.items():
        print(f"{slug}: " + ", ".join(f"{v} {k}" for k, v in counts.items()))


if __name__ == "__main__":
    asyncio.run(main())
