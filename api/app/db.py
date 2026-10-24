from pgvector.psycopg import register_vector_async
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from .helpdesk.schema import SCHEMA as HELPDESK_SCHEMA

SCHEMA = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    id          BIGSERIAL PRIMARY KEY,
    title       TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'note',
    metadata    JSONB NOT NULL DEFAULT '{{}}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunks (
    id           BIGSERIAL PRIMARY KEY,
    document_id  BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ordinal      INT NOT NULL,
    content      TEXT NOT NULL,
    embedding    vector({dim}) NOT NULL,
    tsv          tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
);

CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw
    ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS chunks_tsv_gin ON chunks USING gin (tsv);
"""


async def _configure(conn: AsyncConnection) -> None:
    await register_vector_async(conn)


async def create_pool(database_url: str, embedding_dim: int) -> AsyncConnectionPool:
    # The extension must exist before register_vector_async can find the type.
    async with await AsyncConnection.connect(database_url, autocommit=True) as conn:
        await conn.execute(SCHEMA.format(dim=embedding_dim))
        await conn.execute(HELPDESK_SCHEMA)
    pool = AsyncConnectionPool(database_url, configure=_configure, open=False)
    await pool.open()
    return pool
