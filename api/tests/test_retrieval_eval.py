from datetime import date

from app.helpdesk.seed import seed
from app.rag.embeddings import HashEmbedder
from app.rag.store import VectorStore
from evals.retrieval import evaluate


async def test_retrieval_eval_baseline(pool):
    """Regression floor using the offline hash embedder; real embeddings score higher
    (run `python -m evals.retrieval` with OPENAI_API_KEY set)."""
    store = VectorStore(pool, HashEmbedder(64))
    await seed(pool, store, today=date(2026, 10, 24))
    report = await evaluate(store)
    print(report)
    assert report["hit@3"] >= 0.8
