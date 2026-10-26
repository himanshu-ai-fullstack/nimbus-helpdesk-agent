import pytest

from evals.answers import Case, checks, load_cases, summarize


def tool(name, output, **extra):
    return {"type": f"tool-{name}", "state": "output-available", "output": output, **extra}


PARTS = [
    tool("search_knowledge_base", {"articles": [{"title": "Refunds", "excerpt": "14 days"}]}),
    {"type": "data-citation", "data": {"title": "Refunds"}},
    tool("propose_action", {"created": False, "policy_violation": "too old"}),
    tool("flag_knowledge_gap", {"logged": True}),
]


def test_summary_reads_tools_evidence_and_outcomes():
    s = summarize(PARTS)
    assert s["tools"] == ["search_knowledge_base", "propose_action", "flag_knowledge_gap"]
    assert s["citations"] == 1 and s["gap"] and not s["action_created"] and not s["escalated"]
    assert s["evidence"][0] == "[Refunds] 14 days"


def test_checks_report_each_failed_expectation():
    case = Case.model_validate(
        {
            "id": "x",
            "turns": ["q"],
            "expect": {
                "tools": ["lookup_account"],
                "action": "proposed",
                "escalate": True,
                "cites": True,
                "gap": False,
                "must_not_include": ["$24"],
            },
        }
    )
    failures = checks(case, summarize(PARTS), ["It costs $24."])
    assert failures == [
        "did not call lookup_account",
        "no action was proposed",
        "did not escalate",
        "flagged a knowledge gap",
        "answer contains '$24'",
    ]


@pytest.mark.parametrize("tenant", ["nimbus", "cartwheel", "northstar"])
def test_every_tenant_has_valid_cases_including_red_team(tenant):
    cases = load_cases(tenant)
    assert len(cases) >= 7 and any(c.redteam for c in cases)
    assert len({c.id for c in cases}) == len(cases)
