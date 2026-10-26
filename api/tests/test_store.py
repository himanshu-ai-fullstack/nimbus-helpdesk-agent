import pytest

from app.db import tenant_conn
from app.rag.store import DuplicateDocument, Page


async def test_hybrid_search_ranks_relevant_document_first(registry, store):
    await store.add_document("nimbus", "Cooking", "Boil pasta in salted water.", source="a")
    target = await store.add_document(
        "nimbus",
        "Databases",
        "pgvector adds vector similarity search to Postgres with HNSW indexes.",
        source="b",
    )
    await store.add_document("nimbus", "Travel", "Goa beaches are best in November.", source="c")

    hits = await store.search("nimbus", "how does pgvector do similarity search", limit=3)
    assert hits[0].document_id == target
    assert hits[0].title == "Databases"


async def test_search_never_returns_another_tenants_documents(registry, store):
    await store.add_document("nimbus", "Nimbus pricing", "Business costs $24 per seat.", source="a")
    await store.add_document("cartwheel", "Shipping", "Standard shipping takes 4 days.", source="b")

    hits = await store.search("cartwheel", "Business plan price per seat", limit=5)
    assert {h.title for h in hits} == {"Shipping"}


async def test_row_level_security_hides_other_tenants_without_a_where_clause(pool, registry, store):
    await store.add_document("nimbus", "N", "alpha", source="a")
    await store.add_document("cartwheel", "C", "beta", source="b")
    async with tenant_conn(pool, "cartwheel") as conn:
        titles = [
            r[0] for r in await (await conn.execute("SELECT title FROM documents")).fetchall()
        ]
        chunks = (await (await conn.execute("SELECT count(*) FROM chunks")).fetchone())[0]
    assert titles == ["C"] and chunks == 1
    # With no tenant set at all, RLS returns nothing.
    async with pool.connection() as conn:
        assert (await (await conn.execute("SELECT count(*) FROM documents")).fetchone())[0] == 0


async def test_row_level_security_blocks_writes_into_another_tenant(pool, registry):
    async with tenant_conn(pool, "cartwheel") as conn:
        with pytest.raises(Exception, match="row-level security"):
            await conn.execute(
                "INSERT INTO knowledge_gaps (tenant_id, topic) VALUES ('nimbus', 'x')"
            )


async def test_duplicate_content_is_rejected_per_tenant(registry, store):
    first = await store.add_document("nimbus", "A", "same text", source="a")
    with pytest.raises(DuplicateDocument) as e:
        await store.add_document("nimbus", "B", "same text", source="b")
    assert e.value.existing_id == first
    # The same content is fine in another tenant.
    await store.add_document("cartwheel", "A", "same text", source="a")


async def test_pages_keep_their_numbers_for_citations(registry, store):
    doc = await store.create_document(
        "nimbus",
        "Manual",
        [Page("Intro to widgets.", 1), Page("Resetting the frobnicator.", 2)],
        source="manual.pdf",
    )
    assert await store.index_document("nimbus", doc) == 2
    [hit, *_] = await store.search("nimbus", "frobnicator reset", limit=1)
    assert hit.page == 2 and hit.source == "manual.pdf"


async def test_empty_document_is_marked_failed(registry, store):
    doc = await store.create_document("nimbus", "Blank", [Page("   ")], source="blank.txt")
    with pytest.raises(ValueError):
        await store.index_document("nimbus", doc)
    [listed] = await store.list_documents("nimbus")
    assert listed["status"] == "failed" and "no text" in listed["error"]


async def test_list_and_delete_documents(registry, store):
    doc = await store.add_document("nimbus", "A", "alpha beta", source="a.md")
    [listed] = await store.list_documents("nimbus")
    assert listed["title"] == "A" and listed["chunks"] == 1 and listed["status"] == "ready"
    assert not await store.delete_document("cartwheel", doc)
    assert await store.delete_document("nimbus", doc)
    assert await store.list_documents("nimbus") == []
