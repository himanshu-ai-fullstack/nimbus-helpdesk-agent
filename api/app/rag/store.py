import hashlib
from dataclasses import dataclass
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from ..db import tenant_conn
from .chunking import chunk_text
from .embeddings import Embedder


@dataclass
class SearchHit:
    chunk_id: int
    document_id: int
    title: str
    source: str
    page: int | None
    content: str
    score: float


@dataclass(frozen=True)
class Page:
    """A unit of source text. PDFs have one per page so citations can name it."""

    text: str
    number: int | None = None


class DuplicateDocument(Exception):
    def __init__(self, existing_id: int):
        super().__init__(f"this content is already in the knowledge base (document {existing_id})")
        self.existing_id = existing_id


def content_hash(pages: list[Page]) -> str:
    h = hashlib.sha256()
    for p in pages:
        h.update(p.text.encode())
    return h.hexdigest()


# Hybrid retrieval: vector (cosine) and keyword (full-text) rankings fused with
# Reciprocal Rank Fusion, so exact terms like "pgvector" still match when the
# embedding alone would miss them. Query terms are OR-ed: an AND of every word in
# a conversational question almost never matches anything. The tenant filter is
# explicit for the indexes; row-level security enforces it regardless.
HYBRID_SQL = """
WITH vec AS (
    SELECT id, row_number() OVER (ORDER BY embedding <=> %(emb)s) AS rnk
    FROM chunks
    WHERE tenant_id = %(tenant)s
    ORDER BY embedding <=> %(emb)s
    LIMIT %(pool)s
),
kw AS (
    SELECT id, row_number() OVER (ORDER BY ts_rank_cd(tsv, q) DESC) AS rnk
    FROM chunks,
         to_tsquery('english', replace(plainto_tsquery('english', %(q)s)::text, '&', '|')) q
    WHERE tenant_id = %(tenant)s AND tsv @@ q
    ORDER BY ts_rank_cd(tsv, q) DESC
    LIMIT %(pool)s
),
fused AS (
    SELECT id, sum(1.0 / (%(k)s + rnk)) AS score
    FROM (SELECT * FROM vec UNION ALL SELECT * FROM kw) r
    GROUP BY id
)
SELECT c.id, c.document_id, d.title, d.source, c.page, c.content, f.score
FROM fused f
JOIN chunks c ON c.id = f.id
JOIN documents d ON d.id = c.document_id
WHERE d.status = 'ready'
ORDER BY f.score DESC
LIMIT %(limit)s
"""


class VectorStore:
    def __init__(self, pool: AsyncConnectionPool, embedder: Embedder):
        self._pool = pool
        self._embedder = embedder

    async def create_document(
        self,
        tenant_id: str,
        title: str,
        pages: list[Page],
        *,
        source: str,
        kind: str = "article",
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Store the source text with status 'processing'. Indexing is separate so
        it can run in the background."""
        digest = content_hash(pages)
        async with tenant_conn(self._pool, tenant_id) as conn:
            dup = await (
                await conn.execute(
                    "SELECT id FROM documents WHERE tenant_id = %s AND content_hash = %s",
                    (tenant_id, digest),
                )
            ).fetchone()
            if dup:
                raise DuplicateDocument(dup[0])
            row = await (
                await conn.execute(
                    "INSERT INTO documents (tenant_id, title, kind, source, content_hash, pages, "
                    "metadata) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                    (
                        tenant_id,
                        title,
                        kind,
                        source,
                        digest,
                        Jsonb([{"text": p.text, "number": p.number} for p in pages]),
                        Jsonb(metadata or {}),
                    ),
                )
            ).fetchone()
        assert row is not None
        return int(row[0])

    async def index_document(self, tenant_id: str, document_id: int) -> int:
        """Chunk, embed and index a stored document; returns the chunk count. On
        failure the document is marked 'failed' with the error and the error is
        re-raised."""
        try:
            async with tenant_conn(self._pool, tenant_id) as conn:
                row = await (
                    await conn.execute("SELECT pages FROM documents WHERE id = %s", (document_id,))
                ).fetchone()
            if row is None:
                raise LookupError(f"document {document_id} not found")
            chunks = [(p.get("number"), c.content) for p in row[0] for c in chunk_text(p["text"])]
            if not chunks:
                raise ValueError("no text could be extracted from this document")
            # Embedding is a network call, so it runs outside any transaction.
            embeddings = await self._embedder.embed([c for _, c in chunks])
            async with tenant_conn(self._pool, tenant_id) as conn:
                await conn.execute("DELETE FROM chunks WHERE document_id = %s", (document_id,))
                async with conn.cursor() as cur:
                    await cur.executemany(
                        "INSERT INTO chunks (tenant_id, document_id, ordinal, page, content, "
                        "embedding) VALUES (%s, %s, %s, %s, %s, %s)",
                        [
                            (tenant_id, document_id, i, page, content, emb)
                            for i, ((page, content), emb) in enumerate(zip(chunks, embeddings))
                        ],
                    )
                await conn.execute(
                    "UPDATE documents SET status = 'ready', error = NULL WHERE id = %s",
                    (document_id,),
                )
            return len(chunks)
        except Exception as e:
            async with tenant_conn(self._pool, tenant_id) as conn:
                await conn.execute(
                    "UPDATE documents SET status = 'failed', error = %s WHERE id = %s",
                    (str(e)[:500], document_id),
                )
            raise

    async def add_document(
        self,
        tenant_id: str,
        title: str,
        text: str,
        *,
        source: str,
        kind: str = "article",
        metadata: dict[str, Any] | None = None,
    ) -> int:
        doc_id = await self.create_document(
            tenant_id, title, [Page(text)], source=source, kind=kind, metadata=metadata
        )
        await self.index_document(tenant_id, doc_id)
        return doc_id

    async def search(
        self, tenant_id: str, query: str, limit: int = 5, k: int = 60
    ) -> list[SearchHit]:
        [emb] = await self._embedder.embed([query])
        async with tenant_conn(self._pool, tenant_id) as conn:
            rows = await (
                await conn.execute(
                    HYBRID_SQL,
                    {
                        "tenant": tenant_id,
                        "emb": emb,
                        "q": query,
                        "pool": limit * 4,
                        "k": k,
                        "limit": limit,
                    },
                )
            ).fetchall()
        return [SearchHit(r[0], r[1], r[2], r[3], r[4], r[5], float(r[6])) for r in rows]

    async def list_documents(self, tenant_id: str) -> list[dict[str, Any]]:
        async with tenant_conn(self._pool, tenant_id) as conn:
            cur = conn.cursor(row_factory=dict_row)
            await cur.execute(
                "SELECT d.id, d.title, d.kind, d.source, d.status, d.error, d.created_at, "
                "count(c.id) AS chunks FROM documents d "
                "LEFT JOIN chunks c ON c.document_id = d.id "
                "WHERE d.tenant_id = %s GROUP BY d.id ORDER BY d.created_at DESC, d.id DESC",
                (tenant_id,),
            )
            rows = await cur.fetchall()
        return [{**r, "created_at": r["created_at"].isoformat()} for r in rows]

    async def delete_document(self, tenant_id: str, document_id: int) -> bool:
        async with tenant_conn(self._pool, tenant_id) as conn:
            cur = await conn.execute(
                "DELETE FROM documents WHERE tenant_id = %s AND id = %s", (tenant_id, document_id)
            )
            return cur.rowcount > 0

    async def mark_processing(self, tenant_id: str, document_id: int) -> bool:
        async with tenant_conn(self._pool, tenant_id) as conn:
            cur = await conn.execute(
                "UPDATE documents SET status = 'processing', error = NULL "
                "WHERE tenant_id = %s AND id = %s",
                (tenant_id, document_id),
            )
            return cur.rowcount > 0
