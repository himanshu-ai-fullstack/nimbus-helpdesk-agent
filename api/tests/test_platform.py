import re
from types import SimpleNamespace as NS

import pytest

from app.connectors.demo import DemoConnector
from app.platform.repo import PlatformRepo
from app.platform.triage import render_transcript, triage_model
from app.telemetry.store import ConversationStore
from app.tenants.loader import load_tenant
from app.tools.registry import ToolContext, build_tools

from .conftest import TODAY


class FakeTriageLLM:
    """Answers messages.parse with a fixed triage for the tenant's schema."""

    def __init__(self):
        self.messages = self
        self.calls = []

    async def parse(self, **kw):
        self.calls.append(kw)
        model = kw["output_format"]
        category = model.model_fields["category"].annotation.__args__[0]
        return NS(
            parsed_output=model(
                category=category,
                priority="high",
                sentiment="frustrated",
                summary="Needs a human.",
                customer_asks=["help"],
                suggested_next_step="Call back.",
            ),
            stop_reason="end_turn",
        )


@pytest.fixture
def make_tools(pool, seeded, store, monkeypatch):
    # Policy windows are measured from the seeded dates.
    import app.platform.repo as repo_mod

    class FixedDate:
        @staticmethod
        def today():
            return TODAY

    monkeypatch.setattr(repo_mod, "date", FixedDate)
    repo = PlatformRepo(pool)

    def make(slug, llm=None):
        ctx = ToolContext(
            tenant=seeded.get(slug),
            store=store,
            repo=repo,
            connector=DemoConnector(pool, slug),
            conversations=ConversationStore(pool),
            llm=llm or FakeTriageLLM(),
            conversation_id=None,
            history=[{"role": "user", "content": "help me"}],
            question="help me",
        )
        return ctx, {t.name: t for t in build_tools(ctx)}, repo

    return make


async def run(tools, name, **args):
    out, is_error = await tools[name].run(args)
    assert not is_error, out
    return out


async def test_search_returns_citable_search_results(make_tools):
    _, tools, _ = make_tools("nimbus")
    out = await run(tools, "search_knowledge_base", query="can I get a refund on my invoice")
    assert out["articles"][0]["title"] == "Refund policy"
    [first, *_] = tools["search_knowledge_base"].result_content(out, False)
    assert first["type"] == "search_result" and first["citations"] == {"enabled": True}
    assert first["source"].startswith("doc:") and first["title"] == "Refund policy"


async def test_lookup_is_case_insensitive_and_unlocks_records(make_tools):
    ctx, tools, _ = make_tools("nimbus")
    hidden = await run(tools, "get_record", record_id="INV-1043")
    assert hidden["found"] is False  # not looked up yet

    out = await run(tools, "lookup_account", email="PRIYA@lumen.example")
    assert out["account"]["id"] == "cus_001" and ctx.known_accounts == {"cus_001"}
    assert out["records"][0]["id"] in {"INV-1042", "INV-1043"}
    assert (await run(tools, "get_record", record_id="inv-1043"))["record"]["amount_usd"] == 72.0
    # Another customer's invoice stays hidden.
    assert (await run(tools, "get_record", record_id="INV-2001"))["found"] is False


async def test_refund_is_pending_until_approved(make_tools):
    _, tools, repo = make_tools("nimbus")
    await run(tools, "lookup_account", email="priya@lumen.example")
    out = await run(
        tools, "propose_action", kind="refund", record_id="INV-1043", amount_usd=72, reason="seats"
    )
    action = out["action"]
    assert out["created"] and action["status"] == "pending_approval" and action["label"] == "Refund"

    decided = await repo.decide_action("nimbus", action["id"], approve=True)
    assert decided["status"] == "approved"
    assert await repo.decide_action("nimbus", action["id"], approve=False) is None
    assert await repo.decide_action("cartwheel", action["id"], approve=True) is None
    again = await run(tools, "lookup_account", email="priya@lumen.example")
    assert again["actions"][0]["status"] == "approved"


@pytest.mark.parametrize(
    "record, amount, message",
    [
        ("INV-1041", 10, "34 days old"),
        ("INV-1042", 432.01, r"between \$0.01 and \$432.00"),
        ("INV-9999", 10, "not found"),
        ("INV-2001", 10, "does not belong to an account looked up"),
    ],
)
async def test_refund_policy_violations_are_returned(make_tools, record, amount, message):
    _, tools, _ = make_tools("nimbus")
    await run(tools, "lookup_account", email="priya@lumen.example")
    out = await run(
        tools, "propose_action", kind="refund", record_id=record, amount_usd=amount, reason="r"
    )
    assert out["created"] is False
    assert re.search(message, out["policy_violation"])


async def test_pending_refunds_count_against_remaining(make_tools):
    _, tools, _ = make_tools("nimbus")
    await run(tools, "lookup_account", email="priya@lumen.example")
    await run(
        tools, "propose_action", kind="refund", record_id="INV-1043", amount_usd=50, reason="a"
    )
    out = await run(
        tools, "propose_action", kind="refund", record_id="INV-1043", amount_usd=50, reason="b"
    )
    assert "between $0.01 and $22.00" in out["policy_violation"]


async def test_over_limit_refund_is_blocked(make_tools):
    _, tools, _ = make_tools("nimbus")
    await run(tools, "lookup_account", email="arjun@tinyfox.example")
    out = await run(
        tools, "propose_action", kind="refund", record_id="INV-2001", amount_usd=600, reason="all"
    )
    assert "above $500.00 must be escalated" in out["policy_violation"]


@pytest.mark.parametrize(
    "email, kind, record, amount, expected",
    [
        ("maya@trailmix.example", "return_refund", "ORD-5001", 149, None),
        ("maya@trailmix.example", "cancel_order", "ORD-5002", None, None),
        ("maya@trailmix.example", "return_refund", "ORD-5003", 89, "45 days old"),
        ("maya@trailmix.example", "cancel_order", "ORD-5001", None, "needs it to be processing"),
        ("owen@ridgeline.example", "return_refund", "ORD-6001", 420, r"above \$200.00"),
        ("owen@ridgeline.example", "return_refund", "ORD-6002", 35, "needs it to be delivered"),
    ],
)
async def test_cartwheel_order_policies(make_tools, email, kind, record, amount, expected):
    _, tools, _ = make_tools("cartwheel")
    await run(tools, "lookup_account", email=email)
    args = {"kind": kind, "record_id": record, "reason": "r"}
    if amount:
        args["amount_usd"] = amount
    out = await run(tools, "propose_action", **args)
    if expected is None:
        assert out["created"], out
    else:
        assert re.search(expected, out["policy_violation"])


async def test_northstar_access_requests(make_tools):
    _, tools, _ = make_tools("northstar")
    await run(tools, "lookup_account", email="ana@northstar.example")
    ok = await run(
        tools, "propose_action", kind="software_access", record_id="APP-1001", reason="review"
    )
    assert ok["created"] and ok["action"]["amount_usd"] is None
    dup = await run(
        tools, "propose_action", kind="software_access", record_id="APP-1001", reason="again"
    )
    assert "already awaiting approval" in dup["policy_violation"]
    laptop = await run(
        tools, "propose_action", kind="laptop_replacement", record_id="DEV-1001", reason="slow"
    )
    assert "needs it to be damaged or end_of_life" in laptop["policy_violation"]
    # Kinds come from the tenant's config: Nimbus's refund doesn't exist here.
    out, is_error = await tools["propose_action"].run(
        {"kind": "refund", "record_id": "APP-1001", "reason": "x"}
    )
    assert is_error and out["error"] == "invalid input"


async def test_tenant_without_matching_account_data_finds_nothing(make_tools):
    _, tools, _ = make_tools("cartwheel")
    assert (await run(tools, "lookup_account", email="priya@lumen.example"))["found"] is False


async def test_escalation_creates_triaged_ticket_for_this_tenant_only(make_tools):
    llm = FakeTriageLLM()
    _, tools, repo = make_tools("cartwheel", llm)
    out = await run(
        tools, "escalate_to_human", reason="wants a person", account_email="maya@trailmix.example"
    )
    assert out["triage"]["category"] == "order_status"
    assert llm.calls[0]["model"] == "claude-haiku-5-5"
    [ticket] = await repo.list_tickets("cartwheel")
    assert ticket["id"] == out["ticket_id"] and ticket["customer_name"] == "Maya Patel"
    assert await repo.list_tickets("nimbus") == []


async def test_knowledge_gap_is_logged(make_tools, pool):
    _, tools, _ = make_tools("northstar")
    assert (await run(tools, "flag_knowledge_gap", topic="parking"))["logged"]
    from app.db import tenant_conn

    async with tenant_conn(pool, "northstar") as conn:
        row = await (await conn.execute("SELECT topic, question FROM knowledge_gaps")).fetchone()
    assert row == ("parking", "help me")


def test_triage_schema_uses_tenant_categories(registry):
    model = triage_model(tuple(registry.get("northstar").triage.categories))
    assert "security" in model.model_json_schema()["properties"]["category"]["enum"]


def test_render_transcript_includes_tool_calls():
    out = render_transcript(
        [
            {"role": "user", "content": "refund please"},
            {
                "role": "assistant",
                "content": [{"type": "tool_use", "name": "get_record", "input": {"id": "INV-1"}}],
            },
        ]
    )
    assert "USER: refund please" in out and "get_record" in out


def test_invalid_tenant_config_fails_to_load(tmp_path):
    folder = tmp_path / "acme"
    folder.mkdir()
    (folder / "tenant.yaml").write_text("slug: other\nname: Acme\n")
    with pytest.raises(ValueError, match="must match the folder name"):
        load_tenant(folder)
    (folder / "tenant.yaml").write_text("name: Acme\nbrand_color: blue\n")
    with pytest.raises(ValueError, match="brand_color"):
        load_tenant(folder)


async def test_a_conversation_can_only_access_one_account(make_tools):
    ctx, tools, _ = make_tools("nimbus")
    await run(tools, "lookup_account", email="priya@lumen.example")
    other = await run(tools, "lookup_account", email="sara@northwind.example")
    assert other["found"] is False and "only access one account" in other["note"]
    assert ctx.known_accounts == {"cus_001"}
    # Looking up the same person again is fine.
    assert (await run(tools, "lookup_account", email="priya@lumen.example"))["found"]


def test_scaffolded_tenant_is_valid(tmp_path):
    from app.tenants.new import scaffold

    folder = scaffold("acme", "Acme Robotics", "robot vacuum maker", root=tmp_path)
    tenant = load_tenant(folder)
    assert tenant.name == "Acme Robotics" and "refund" in tenant.actions
    with pytest.raises(FileExistsError):
        scaffold("acme", "Acme", "x", root=tmp_path)
    with pytest.raises(ValueError, match="slug"):
        scaffold("Bad Slug", "Acme", "x", root=tmp_path)


def test_tool_description_states_each_policy(registry):
    from app.tools.registry import rules

    nimbus = registry.get("nimbus").actions["refund"]
    assert rules(nimbus) == (
        "Applies to invoices, whose status is paid, dated within the last 14 days. "
        "Takes an amount in USD, at most what remains after earlier pending or approved "
        "requests, and at most $500 per request (escalate larger ones)."
    )
    access = registry.get("northstar").actions["software_access"]
    assert rules(access).endswith("Takes no amount.")
