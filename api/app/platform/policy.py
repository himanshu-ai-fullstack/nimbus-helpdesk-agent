"""Action policy, enforced in code. Prompts are guidance; this is the guardrail:
whatever the model is told or tricked into, it can only create a *pending* action
that passes these rules, and a person still approves it."""

from datetime import date

from ..connectors.base import Record
from ..tenants.models import ActionPolicy


class ActionNotAllowed(Exception):
    pass


def usd(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def evaluate(
    kind: str,
    policy: ActionPolicy,
    record: Record,
    amount_cents: int | None,
    committed_cents: int,
    has_pending: bool,
    today: date,
) -> None:
    """Raise ActionNotAllowed with a reason the agent can relay to the customer.

    committed_cents: amounts of pending and approved actions already on the record.
    has_pending: a pending action of this kind already exists on the record."""
    label = policy.label.lower()
    if record.type != policy.record_type:
        raise ActionNotAllowed(f"a {label} applies to a {policy.record_type}, not a {record.type}")
    if policy.require_status and record.status not in policy.require_status:
        allowed = " or ".join(policy.require_status)
        raise ActionNotAllowed(
            f"{record.type} {record.id} is {record.status}; a {label} needs it to be {allowed}"
        )
    if policy.window_days is not None:
        age = (today - record.occurred_on).days
        if age > policy.window_days:
            raise ActionNotAllowed(
                f"{record.type} {record.id} is {age} days old; a {label} is only allowed within "
                f"{policy.window_days} days. Escalate to a human if there is a strong reason."
            )

    if policy.amount == "none":
        if amount_cents:
            raise ActionNotAllowed(f"a {label} does not take an amount")
        if has_pending:
            raise ActionNotAllowed(f"a {label} for {record.id} is already awaiting approval")
        return

    if amount_cents is None or amount_cents <= 0:
        raise ActionNotAllowed(f"a {label} needs a positive amount")
    if policy.cap_to_remaining:
        if record.amount_cents is None:
            raise ActionNotAllowed(f"{record.id} has no amount to {label} against")
        remaining = record.amount_cents - committed_cents
        if remaining <= 0:
            raise ActionNotAllowed(
                f"{record.id} has nothing left to {label}: {usd(committed_cents)} is already "
                "approved or awaiting approval"
            )
        if amount_cents > remaining:
            raise ActionNotAllowed(
                f"amount must be between $0.01 and {usd(remaining)}: {usd(committed_cents)} of "
                f"{usd(record.amount_cents)} is already approved or awaiting approval"
            )
    if policy.max_amount_usd is not None and amount_cents > round(policy.max_amount_usd * 100):
        raise ActionNotAllowed(
            f"a {label} above {usd(round(policy.max_amount_usd * 100))} must be escalated to "
            "a human"
        )
