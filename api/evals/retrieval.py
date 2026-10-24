"""Retrieval eval: does search_help_center put the right article in the top k?

    uv run python -m evals.retrieval            # uses EMBEDDER from .env
    uv run python -m evals.retrieval --mode vector

Reports hit@1, hit@3 and MRR per retrieval mode, so changes to chunking, the
embedding model, or the hybrid fusion can be measured instead of eyeballed.
"""

import argparse
import asyncio
import json
from pathlib import Path

from app.config import get_settings
from app.db import create_pool
from app.helpdesk.seed import seed
from app.rag.embeddings import build_embedder
from app.rag.store import VectorStore

CASES = json.loads((Path(__file__).parent / "retrieval_cases.json").read_text())


async def evaluate(store: VectorStore, k: int = 3) -> dict[str, float]:
    hits1 = hitsk = 0
    rr = 0.0
    misses = []
    for case in CASES:
        results = await store.search(case["question"], limit=k * 2)
        titles = list(dict.fromkeys(h.title for h in results))  # dedupe chunks of one article
        rank = titles.index(case["article"]) + 1 if case["article"] in titles else None
        hits1 += rank == 1
        hitsk += rank is not None and rank <= k
        rr += 1 / rank if rank else 0.0
        if rank != 1:
            misses.append(
                {"question": case["question"], "expected": case["article"], "got": titles[:3]}
            )
    n = len(CASES)
    return {"n": n, "hit@1": hits1 / n, f"hit@{k}": hitsk / n, "mrr": rr / n, "misses": misses}


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reseed", action="store_true", help="reset demo data first")
    args = parser.parse_args()
    cfg = get_settings()
    pool = await create_pool(cfg.database_url, cfg.embedding_dim)
    embedder = build_embedder(
        cfg.embedder, cfg.openai_api_key, cfg.embedding_model, cfg.embedding_dim
    )
    store = VectorStore(pool, embedder)
    try:
        if args.reseed:
            await seed(pool, store)
        report = await evaluate(store)
    finally:
        await pool.close()
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
