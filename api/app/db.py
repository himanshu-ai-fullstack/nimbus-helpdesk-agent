"""Schema, the runtime role, and tenant-scoped connections.

Tenant isolation is enforced by Postgres row-level security, not only by WHERE
clauses: every tenant-owned table has a policy that compares `tenant_id` to the
`app.tenant_id` setting, and the app's pool runs as a role that cannot bypass it.
A query that forgets its tenant filter therefore returns nothing instead of
another company's rows."""

import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from pgvector.psycopg import register_vector_async
from psycopg import AsyncConnection, sql
from psycopg_pool import AsyncConnectionPool

RUNTIME_ROLE = "helpdesk_app"

TENANT_TABLES = [
    "documents",
    "chunks",
    "demo_accounts",
    "demo_records",
    "actions",
    "tickets",
    "conversations",
    "messages",
    "agent_events",
    "feedback",
    "knowledge_gaps",
]

SCHEMA = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS tenants (
    id                TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    config_version    TEXT NOT NULL,
    admin_token_hash  TEXT,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS documents (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    title         TEXT NOT NULL,
    kind          TEXT NOT NULL DEFAULT 'article',
    source        TEXT NOT NULL,
    content_hash  TEXT NOT NULL,
    pages         JSONB NOT NULL DEFAULT '[]',
    status        TEXT NOT NULL DEFAULT 'processing',
    error         TEXT,
    metadata      JSONB NOT NULL DEFAULT '{{}}',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, content_hash)
);

CREATE TABLE IF NOT EXISTS chunks (
    id           BIGSERIAL PRIMARY KEY,
    tenant_id    TEXT NOT NULL,
    document_id  BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ordinal      INT NOT NULL,
    page         INT,
    content      TEXT NOT NULL,
    embedding    vector({dim}) NOT NULL,
    tsv          tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
);

CREATE INDEX IF NOT EXISTS chunks_tenant ON chunks (tenant_id);
CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw
    ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS chunks_tsv_gin ON chunks USING gin (tsv);

-- Stand-in for a company's own systems (billing, orders, HR). The agent reads it
-- only through the DemoConnector, the same interface a real integration would use.
CREATE TABLE IF NOT EXISTS demo_accounts (
    tenant_id   TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    id          TEXT NOT NULL,
    email       TEXT NOT NULL,
    name        TEXT NOT NULL,
    status      TEXT NOT NULL,
    attributes  JSONB NOT NULL DEFAULT '{{}}',
    created_on  DATE NOT NULL,
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, email)
);

CREATE TABLE IF NOT EXISTS demo_records (
    tenant_id     TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    id            TEXT NOT NULL,
    account_id    TEXT NOT NULL,
    type          TEXT NOT NULL,
    title         TEXT NOT NULL,
    status        TEXT NOT NULL,
    amount_cents  INT,
    currency      TEXT NOT NULL DEFAULT 'USD',
    occurred_on   DATE NOT NULL,
    attributes    JSONB NOT NULL DEFAULT '{{}}',
    PRIMARY KEY (tenant_id, id)
);

CREATE TABLE IF NOT EXISTS conversations (
    id               TEXT PRIMARY KEY,
    tenant_id        TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    config_version   TEXT NOT NULL,
    outcome          TEXT NOT NULL DEFAULT 'answered',
    started_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_message_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS conversations_tenant ON conversations (tenant_id, started_at);

CREATE TABLE IF NOT EXISTS messages (
    id               TEXT PRIMARY KEY,
    tenant_id        TEXT NOT NULL,
    conversation_id  TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    seq              BIGSERIAL,
    role             TEXT NOT NULL,
    parts            JSONB NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS messages_conversation ON messages (conversation_id, seq);

CREATE TABLE IF NOT EXISTS actions (
    id               BIGSERIAL PRIMARY KEY,
    tenant_id        TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    conversation_id  TEXT,
    kind             TEXT NOT NULL,
    record_id        TEXT NOT NULL,
    account_id       TEXT NOT NULL,
    account_name     TEXT NOT NULL,
    amount_cents     INT,
    currency         TEXT NOT NULL DEFAULT 'USD',
    reason           TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'pending_approval',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_at       TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS tickets (
    id               BIGSERIAL PRIMARY KEY,
    tenant_id        TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    conversation_id  TEXT,
    account_id       TEXT,
    account_name     TEXT,
    triage           JSONB NOT NULL,
    transcript       JSONB NOT NULL,
    status           TEXT NOT NULL DEFAULT 'open',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS agent_events (
    id                  BIGSERIAL PRIMARY KEY,
    tenant_id           TEXT NOT NULL,
    conversation_id     TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    message_id          TEXT NOT NULL,
    step                INT NOT NULL,
    kind                TEXT NOT NULL,
    tool_name           TEXT,
    model               TEXT,
    latency_ms          INT NOT NULL,
    input_tokens        INT NOT NULL DEFAULT 0,
    output_tokens       INT NOT NULL DEFAULT 0,
    cache_read_tokens   INT NOT NULL DEFAULT 0,
    cache_write_tokens  INT NOT NULL DEFAULT 0,
    is_error            BOOLEAN NOT NULL DEFAULT false,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS agent_events_tenant ON agent_events (tenant_id, created_at);

CREATE TABLE IF NOT EXISTS feedback (
    message_id       TEXT PRIMARY KEY,
    tenant_id        TEXT NOT NULL,
    conversation_id  TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    rating           SMALLINT NOT NULL CHECK (rating IN (-1, 1)),
    comment          TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS knowledge_gaps (
    id               BIGSERIAL PRIMARY KEY,
    tenant_id        TEXT NOT NULL,
    conversation_id  TEXT,
    topic            TEXT NOT NULL,
    question         TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


async def _apply_security(conn: AsyncConnection) -> None:
    role = sql.Identifier(RUNTIME_ROLE)
    exists = await (
        await conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (RUNTIME_ROLE,))
    ).fetchone()
    if not exists:
        await conn.execute(sql.SQL("CREATE ROLE {} NOLOGIN NOBYPASSRLS").format(role))
    # The connecting (owner) role switches to the runtime role with SET ROLE, so it
    # must be a member. Superusers can SET ROLE to anything; managed Postgres
    # owners (e.g. Neon) need the explicit grant.
    await conn.execute(sql.SQL("GRANT {} TO CURRENT_USER").format(role))
    await conn.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
    await conn.execute(
        sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}").format(
            role
        )
    )
    await conn.execute(
        sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}").format(role)
    )
    for table in TENANT_TABLES:
        t = sql.Identifier(table)
        await conn.execute(sql.SQL("ALTER TABLE {} ENABLE ROW LEVEL SECURITY").format(t))
        await conn.execute(sql.SQL("DROP POLICY IF EXISTS tenant_isolation ON {}").format(t))
        await conn.execute(
            sql.SQL(
                "CREATE POLICY tenant_isolation ON {} "
                "USING (tenant_id = current_setting('app.tenant_id', true)) "
                "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
            ).format(t)
        )


def schema_version(embedding_dim: int) -> str:
    source = SCHEMA.format(dim=embedding_dim) + RUNTIME_ROLE + ",".join(TENANT_TABLES)
    return hashlib.sha256(source.encode()).hexdigest()[:16]


async def migrate(database_url: str, embedding_dim: int) -> None:
    """Create tables, indexes, the runtime role and RLS policies. Skipped when this
    schema version is already applied, so restarts don't rewrite grants and
    policies (which takes table locks and bloats the catalogs)."""
    version = schema_version(embedding_dim)
    async with await AsyncConnection.connect(database_url, autocommit=True) as conn:
        # One migrator at a time when several instances start together; the lock
        # is released when this connection closes.
        await conn.execute("SELECT pg_advisory_lock(hashtext('helpdesk_migrate'))")
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_versions "
            "(version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        applied = await (
            await conn.execute("SELECT 1 FROM schema_versions WHERE version = %s", (version,))
        ).fetchone()
        if applied:
            return
        await conn.execute(SCHEMA.format(dim=embedding_dim))
        await _apply_security(conn)
        await conn.execute("INSERT INTO schema_versions (version) VALUES (%s)", (version,))


async def _configure(conn: AsyncConnection) -> None:
    await register_vector_async(conn)
    await conn.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(RUNTIME_ROLE)))
    await conn.commit()


async def create_pool(database_url: str, embedding_dim: int) -> AsyncConnectionPool:
    # The extension must exist before register_vector_async can find the type.
    await migrate(database_url, embedding_dim)
    pool = AsyncConnectionPool(database_url, configure=_configure, open=False)
    await pool.open()
    return pool


@asynccontextmanager
async def tenant_conn(pool: AsyncConnectionPool, tenant_id: str) -> AsyncIterator[AsyncConnection]:
    """A pooled connection inside a transaction scoped to one tenant. RLS hides every
    other tenant's rows for the life of the transaction."""
    async with pool.connection() as conn, conn.transaction():
        # One round trip. iterative_scan lets filtered HNSW scans keep searching
        # until enough rows match the tenant (pgvector >= 0.8) instead of returning
        # a short list.
        await conn.execute(
            "SELECT set_config('app.tenant_id', %s, true), "
            "set_config('hnsw.iterative_scan', 'relaxed_order', true)",
            (tenant_id,),
        )
        yield conn
