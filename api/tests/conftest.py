import os
from datetime import date

import pytest
from psycopg import AsyncConnection

from app.db import TENANT_TABLES

TEST_DB = os.environ.get("TEST_DATABASE_URL", "postgresql://app:app@localhost:5432/platform_test")
TODAY = date(2026, 10, 24)
TOKENS = {"nimbus": "nimbus-token", "cartwheel": "cartwheel-token", "northstar": "northstar-token"}


@pytest.fixture(scope="session")
def database_url() -> str:
    return TEST_DB


@pytest.fixture
async def pool(database_url):
    from app.db import create_pool

    p = await create_pool(database_url, 64)
    # Truncate as the owner: the app's runtime role can't see across tenants.
    async with await AsyncConnection.connect(database_url, autocommit=True) as conn:
        await conn.execute(f"TRUNCATE tenants, {', '.join(TENANT_TABLES)} RESTART IDENTITY CASCADE")
    yield p
    await p.close()


@pytest.fixture
async def registry(pool):
    from app.tenants.loader import TenantRegistry, load_tenants

    reg = TenantRegistry(load_tenants())
    await reg.sync(pool, TOKENS)
    return reg


@pytest.fixture
def store(pool):
    from app.rag.embeddings import HashEmbedder
    from app.rag.store import VectorStore

    return VectorStore(pool, HashEmbedder(64))


@pytest.fixture
async def seeded(pool, registry, store):
    from app.tenants.seed import seed_all

    await seed_all(pool, store, registry, today=TODAY)
    return registry
