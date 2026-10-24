import os

import pytest

TEST_DB = os.environ.get("TEST_DATABASE_URL", "postgresql://postgres@localhost:5433/app?host=/tmp")


@pytest.fixture(scope="session")
def database_url() -> str:
    return TEST_DB


@pytest.fixture
async def pool(database_url):
    from app.db import create_pool

    p = await create_pool(database_url, 64)
    async with p.connection() as conn:
        await conn.execute("TRUNCATE documents RESTART IDENTITY CASCADE")
    yield p
    await p.close()
