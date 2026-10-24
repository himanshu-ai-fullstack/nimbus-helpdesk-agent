from app.rag.embeddings import HashEmbedder
from app.rag.store import VectorStore


async def test_hybrid_search_ranks_relevant_document_first(pool):
    store = VectorStore(pool, HashEmbedder(64))
    await store.add_document("Cooking", "Boil pasta in salted water for nine minutes.")
    target = await store.add_document(
        "Databases", "pgvector adds vector similarity search to Postgres with HNSW indexes."
    )
    await store.add_document("Travel", "Goa beaches are best visited between November and March.")

    hits = await store.search("how does pgvector do similarity search", limit=3)
    assert hits[0].document_id == target
    assert hits[0].title == "Databases"


async def test_list_documents(pool):
    store = VectorStore(pool, HashEmbedder(64))
    await store.add_document("A", "alpha")
    docs = await store.list_documents()
    assert [d["title"] for d in docs] == ["A"]
