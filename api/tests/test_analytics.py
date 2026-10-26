from datetime import date

from app.db import tenant_conn
from app.telemetry.analytics import tenant_analytics
from app.telemetry.store import ConversationStore

TODAY = date.today()


async def converse(store, tenant, cid, outcome, events, cited=(), rating=None):
    await store.open(tenant, cid, "v1")
    await store.add_message(
        tenant,
        cid,
        {"id": f"u-{cid}", "role": "user", "parts": [{"type": "text", "text": f"q {cid}"}]},
    )
    parts = [{"type": "text", "text": "answer"}] + [
        {"type": "data-citation", "data": {"title": t, "source": "doc:1", "citedText": "x"}}
        for t in cited
    ]
    await store.add_message(tenant, cid, {"id": f"a-{cid}", "role": "assistant", "parts": parts})
    await store.record_turn(tenant, cid, f"a-{cid}", events, outcome)
    if rating:
        await store.add_feedback(tenant, f"a-{cid}", rating, "wrong" if rating < 0 else None)


def llm(ms, inp=1000, out=100, read=0, model="claude-opus-5-5"):
    return {
        "kind": "llm",
        "step": 0,
        "model": model,
        "latency_ms": ms,
        "input_tokens": inp,
        "output_tokens": out,
        "cache_read_tokens": read,
        "cache_write_tokens": 0,
    }


def tool(name, ms=10, error=False):
    return {"kind": "tool", "step": 0, "tool_name": name, "latency_ms": ms, "is_error": error}


async def test_metrics_are_computed_per_tenant(pool, registry):
    store = ConversationStore(pool)
    await converse(
        store,
        "nimbus",
        "c1",
        "answered",
        [llm(1000), tool("search_knowledge_base")],
        cited=["Refund policy", "Refund policy"],
        rating=1,
    )
    await converse(
        store,
        "nimbus",
        "c2",
        "action_proposed",
        [llm(2000, read=9000), tool("propose_action")],
        rating=1,
    )
    await converse(
        store,
        "nimbus",
        "c3",
        "escalated",
        [llm(4000), tool("escalate_to_human", error=True)],
        rating=-1,
    )
    await converse(store, "cartwheel", "c4", "escalated", [llm(9000)])
    await store.add_gap("nimbus", "c1", "Parking", "where do I park?")
    await store.add_gap("nimbus", "c3", "parking", None)
    async with tenant_conn(pool, "nimbus") as conn:
        for status in ("approved", "approved", "denied", "pending_approval"):
            await conn.execute(
                "INSERT INTO actions (tenant_id, kind, record_id, account_id, account_name, "
                "amount_cents, reason, status) VALUES ('nimbus', 'refund', 'INV-1', 'a', 'A', 100, "
                "'r', %s)",
                (status,),
            )

    a = await tenant_analytics(pool, "nimbus", days=7, today=TODAY)
    assert a["conversations"] == 3
    assert a["outcomes"] == {"answered": 1, "action_proposed": 1, "escalated": 1}
    assert a["containment_rate"] == round(2 / 3, 4) and a["escalation_rate"] == round(1 / 3, 4)
    assert a["helpfulness"] == round(2 / 3, 4)
    assert a["approval_rate"] == round(2 / 3, 4) and a["actions"]["pending"] == 1
    assert a["latency_ms"]["turns"] == 3 and a["latency_ms"]["p50"] == 2010
    # 3000 input + 300 output on Opus, plus 9000 cache-read tokens at a tenth of the price
    assert a["cost"]["total_usd"] == round((3000 * 4 + 300 * 20 + 9000 * 0.4) / 1e6, 4)
    assert a["cost"]["cache_hit_rate"] == round(9000 / 12000, 4)
    assert {t["name"]: t["errors"] for t in a["tools"]}["escalate_to_human"] == 1
    assert a["top_cited"] == [{"title": "Refund policy", "citations": 2}]
    assert a["knowledge_gaps"][0]["topic"] == "parking" and a["knowledge_gaps"][0]["n"] == 2
    assert a["thumbs_down"][0]["question"] == "q c3"
    assert a["config_versions"][0]["version"] == "v1"
    assert len(a["daily"]) == 7 and a["daily"][-1]["escalated"] == 1

    other = await tenant_analytics(pool, "cartwheel", days=7, today=TODAY)
    assert other["conversations"] == 1 and other["escalation_rate"] == 1.0
    assert other["top_cited"] == [] and other["knowledge_gaps"] == []


async def test_empty_tenant_has_no_rates(pool, registry):
    a = await tenant_analytics(pool, "northstar", days=30, today=TODAY)
    assert a["conversations"] == 0 and a["containment_rate"] is None
    assert a["cost"]["per_conversation_usd"] is None and len(a["daily"]) == 30
