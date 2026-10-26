from datetime import date, timedelta

import pytest

from app.connectors.base import Record
from app.platform.policy import ActionNotAllowed, evaluate
from app.tenants.models import ActionPolicy

TODAY = date(2026, 10, 24)
REFUND = ActionPolicy(
    label="Refund",
    description="d",
    record_type="invoice",
    require_status=["paid"],
    window_days=14,
    max_amount_usd=500,
    cap_to_remaining=True,
)
ACCESS = ActionPolicy(
    label="Software access",
    description="d",
    record_type="app",
    require_status=["not_granted"],
    amount="none",
)


def invoice(cents=10_000, status="paid", days_ago=3, type="invoice"):
    return Record(
        id="INV-1",
        account_id="a",
        type=type,
        title="t",
        status=status,
        amount_cents=cents,
        occurred_on=TODAY - timedelta(days=days_ago),
    )


def check(policy, record, amount, committed=0, pending=False):
    evaluate("k", policy, record, amount, committed, pending, TODAY)


def test_allows_refund_inside_policy():
    check(REFUND, invoice(), 5_000)


@pytest.mark.parametrize(
    "record, amount, committed, message",
    [
        (invoice(type="order"), 100, 0, "applies to a invoice, not a order"),
        (invoice(status="unpaid"), 100, 0, "is unpaid; a refund needs it to be paid"),
        (invoice(days_ago=15), 100, 0, "15 days old"),
        (invoice(), 0, 0, "needs a positive amount"),
        (invoice(), 10_001, 0, r"between \$0.01 and \$100.00"),
        (invoice(), 6_000, 5_000, r"between \$0.01 and \$50.00"),
        (invoice(), 100, 10_000, "nothing left to refund"),
        (invoice(cents=90_000), 60_000, 0, r"above \$500.00 must be escalated"),
    ],
)
def test_refund_rules(record, amount, committed, message):
    with pytest.raises(ActionNotAllowed, match=message):
        check(REFUND, record, amount, committed)


def test_window_boundary_is_inclusive():
    check(REFUND, invoice(days_ago=14), 100)


def test_no_amount_action_rejects_amount_and_duplicates():
    app = invoice(cents=None, status="not_granted", type="app")
    check(ACCESS, app, None)
    with pytest.raises(ActionNotAllowed, match="does not take an amount"):
        check(ACCESS, app, 500)
    with pytest.raises(ActionNotAllowed, match="already awaiting approval"):
        check(ACCESS, app, None, pending=True)
    with pytest.raises(ActionNotAllowed, match="needs it to be not_granted"):
        check(ACCESS, invoice(cents=None, status="granted", type="app"), None)


def test_policy_config_rejects_amount_rules_without_amount():
    with pytest.raises(ValueError, match="need amount: required"):
        ActionPolicy(label="x", description="d", record_type="r", amount="none", max_amount_usd=10)
