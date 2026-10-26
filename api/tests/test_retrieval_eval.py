import pytest

from evals.retrieval import evaluate, load_cases


@pytest.mark.parametrize("tenant", ["nimbus", "cartwheel", "northstar"])
async def test_retrieval_eval_baseline(seeded, store, tenant):
    """Regression floor using the offline hash embedder; real embeddings score higher
    (run `python -m evals.retrieval` with OPENAI_API_KEY set)."""
    assert len(load_cases(tenant)) >= 10
    report = await evaluate(store, tenant)
    print(tenant, report)
    assert report["hit@3"] >= 0.8
