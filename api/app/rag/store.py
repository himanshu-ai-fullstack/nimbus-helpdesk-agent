from dataclasses import dataclass
from typing import Any

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from .chunking import chunk_text
from .embeddings import Embedder


@dataclass
class SearchHit:
    chunk_id: int
    document_id: int
    title: str
    content: str
    score: float


# Hybrid retrieval: vector (cosine) and keyword (full-text) rankings fused with
# Reciprocal Rank Fusion, so exact terms like "pgvector" still match when the
# embedding alone would miss them. Query terms are OR-ed: an AND of every word in
# a conversational question almost never matches anything.
HYBRID_SQL = """
WITH vec AS (
    SELECT id, row_number() OVER (ORDER BY embedding <=> %(emb)s) AS rnk
    FROM chunks
    ORDER BY embedding <=> %(emb)s
    LIMIT %(pool)s
),
kw AS (
    SELECT id, row_number() OVER (ORDER BY ts_rank_cd(tsv, q) DESC) AS rnk
    FROM chunks,
         to_tsquery('english', replace(plainto_tsquery('english', %(q)s)::text, '&', '|')) q
    WHERE tsv @@ q
    ORDER BY ts_rank_cd(tsv, q) DESC
    LIMIT %(pool)s
),
fused AS (
    SELECT id, sum(1.0 / (%(k)s + rnk)) AS score
    FROM (SELECT * FROM vec UNION ALL SELECT * FROM kw) r
    GROUP BY id
)
SELECT c.id, c.document_id, d.title, c.content, f.score
FROM fused f
JOIN chunks c ON c.id = f.id
JOIN documents d ON d.id = c.document_id
ORDER BY f.score DESC
LIMIT %(limit)s
"""


class VectorStore:
    def __init__(self, pool: AsyncConnectionPool, embedder: Embedder):
        self._pool = pool
        self._embedder = embedder

    async def add_document(
        self, title: str, text: str, kind: str = "note", metadata: dict[str, Any] | None = None
    ) -> int:
        chunks = chunk_text(text)
        embeddings = await self._embedder.embed([c.content for c in chunks])
        async with self._pool.connection() as conn, conn.transaction():
            row = await (
                await conn.execute(
                    "INSERT INTO documents (title, kind, metadata) VALUES (%s, %s, %s) RETURNING id",
                    (title, kind, Jsonb(metadata or {})),
                )
            ).fetchone()
            assert row is not None
            doc_id: int = row[0]
            async with conn.cursor() as cur:
                await cur.executemany(
                    "INSERT INTO chunks (document_id, ordinal, content, embedding) "
                    "VALUES (%s, %s, %s, %s)",
                    [(doc_id, c.ordinal, c.content, e) for c, e in zip(chunks, embeddings)],
                )
        return doc_id

    async def search(self, query: str, limit: int = 5, k: int = 60) -> list[SearchHit]:
        [emb] = await self._embedder.embed([query])
        async with self._pool.connection() as conn:
            rows = await (
                await conn.execute(
                    HYBRID_SQL, {"emb": emb, "q": query, "pool": limit * 4, "k": k, "limit": limit}
                )
            ).fetchall()
        return [SearchHit(r[0], r[1], r[2], r[3], float(r[4])) for r in rows]

    async def list_documents(self) -> list[dict[str, Any]]:
        async with self._pool.connection() as conn:
            rows = await (
                await conn.execute(
                    "SELECT id, title, kind, created_at FROM documents ORDER BY created_at DESC"
                )
            ).fetchall()
        return [
            {"id": r[0], "title": r[1], "kind": r[2], "created_at": r[3].isoformat()} for r in rows
        ]
