"""Retrieval eval: does search_knowledge_base put the right article in the top k,
for every tenant?

    uv run python -m evals.retrieval              # all tenants, EMBEDDER from .env
    uv run python -m evals.retrieval --tenant nimbus --reseed

Reports hit@1, hit@3 and MRR per tenant, so changes to chunking, the embedding
model, or the hybrid fusion can be measured instead of eyeballed.
"""

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.db import create_pool
from app.rag.embeddings import build_embedder
from app.rag.store import VectorStore
from app.tenants.loader import TenantRegistry, load_tenants
from app.tenants.seed import seed_all

EVALS_DIR = Path(__file__).parent


def load_cases(slug: str) -> list[dict[str, str]]:
    path = EVALS_DIR / slug / "retrieval.json"
    return json.loads(path.read_text()) if path.exists() else []


async def evaluate(store: VectorStore, tenant: str, k: int = 3) -> dict[str, Any]:
    cases = load_cases(tenant)
    hits1 = hitsk = 0
    rr = 0.0
    misses = []
    for case in cases:
        results = await store.search(tenant, case["question"], limit=k * 2)
        titles = list(dict.fromkeys(h.title for h in results))  # dedupe chunks of one article
        rank = titles.index(case["article"]) + 1 if case["article"] in titles else None
        hits1 += rank == 1
        hitsk += rank is not None and rank <= k
        rr += 1 / rank if rank else 0.0
        if rank != 1:
            misses.append(
                {"question": case["question"], "expected": case["article"], "got": titles[:3]}
            )
    n = len(cases) or 1
    return {
        "n": len(cases),
        "hit@1": hits1 / n,
        f"hit@{k}": hitsk / n,
        "mrr": rr / n,
        "misses": misses,
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", help="one tenant slug (default: all)")
    parser.add_argument("--reseed", action="store_true", help="reset demo data first")
    args = parser.parse_args()
    cfg = get_settings()
    registry = TenantRegistry(load_tenants())
    pool = await create_pool(cfg.database_url, cfg.embedding_dim)
    embedder = build_embedder(
        cfg.embedder, cfg.openai_api_key, cfg.embedding_model, cfg.embedding_dim
    )
    store = VectorStore(pool, embedder)
    try:
        await registry.sync(pool, cfg.tenant_admin_tokens)
        if args.reseed:
            await seed_all(pool, store, registry, args.tenant)
        report = {
            t.slug: await evaluate(store, t.slug)
            for t in registry.all()
            if not args.tenant or t.slug == args.tenant
        }
    finally:
        await pool.close()
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
