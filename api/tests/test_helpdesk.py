from datetime import date

import pytest

from app.helpdesk.repo import HelpdeskRepo, RefundNotAllowed
from app.helpdesk.seed import seed
from app.helpdesk.triage import render_transcript
from app.rag.embeddings import HashEmbedder
from app.rag.store import VectorStore

TODAY = date(2026, 10, 24)


@pytest.fixture
async def seeded(pool):
    store = VectorStore(pool, HashEmbedder(64))
    await seed(pool, store, today=TODAY)
    return HelpdeskRepo(pool), store


async def test_help_center_search_finds_refund_policy(seeded):
    _, store = seeded
    hits = await store.search("can I get a refund on my invoice", limit=3)
    assert hits[0].title == "Refund policy"


async def test_customer_lookup_is_case_insensitive(seeded):
    repo, _ = seeded
    c = await repo.find_customer("PRIYA@lumen.example")
    assert c and c["id"] == "cus_001"
    invoices = await repo.invoices_for("cus_001")
    assert invoices[0]["id"] in {"INV-1042", "INV-1043"}


async def test_refund_within_window_is_pending_until_approved(seeded):
    repo, _ = seeded
    r = await repo.propose_refund("INV-1043", 7200, "seats added by mistake", today=TODAY)
    assert r["status"] == "pending_approval"
    decided = await repo.decide_refund(r["id"], approve=True)
    assert decided and decided["status"] == "approved"
    assert await repo.decide_refund(r["id"], approve=False) is None  # can't decide twice


@pytest.mark.parametrize(
    "invoice, cents, message",
    [
        ("INV-1041", 1000, "days old"),  # outside 14-day window
        ("INV-3002", 1000, "unpaid"),  # not paid
        ("INV-1042", 43201, "between 1 and"),  # more than the invoice
        ("INV-2001", 60000, r"above \$500"),  # over the agent's limit
        ("INV-9999", 100, "not found"),
    ],
)
async def test_refund_policy_is_enforced(seeded, invoice, cents, message):
    repo, _ = seeded
    with pytest.raises(RefundNotAllowed, match=message):
        await repo.propose_refund(invoice, cents, "test", today=TODAY)


async def test_pending_refunds_count_against_remaining_amount(seeded):
    repo, _ = seeded
    await repo.propose_refund("INV-1043", 5000, "partial", today=TODAY)
    with pytest.raises(RefundNotAllowed, match="between 1 and 2200"):
        await repo.propose_refund("INV-1043", 5000, "again", today=TODAY)


async def test_ticket_round_trip(seeded):
    repo, _ = seeded
    tid = await repo.create_ticket("cus_002", {"priority": "high"}, [])
    [t] = await repo.list_tickets()
    assert t["id"] == tid and t["customer_name"] == "Arjun Mehta"


def test_render_transcript_includes_tool_calls():
    out = render_transcript(
        [
            {"role": "user", "content": "refund please"},
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "name": "get_invoice", "input": {"invoice_id": "INV-1"}}
                ],
            },
        ]
    )
    assert "USER: refund please" in out and "get_invoice" in out
