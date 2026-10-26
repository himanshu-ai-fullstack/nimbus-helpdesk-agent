from typing import Any

import anthropic
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from ..rag.store import VectorStore
from ..tools.base import Tool
from .repo import HelpdeskRepo, RefundNotAllowed
from .triage import render_transcript, triage_conversation


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchIn(_In):
    query: str = Field(description="Search query for the help center")


class CustomerIn(_In):
    email: EmailStr = Field(description="The customer's account email")


class InvoiceIn(_In):
    invoice_id: str = Field(description="Invoice id, e.g. INV-1042")


class RefundIn(_In):
    invoice_id: str
    amount_usd: float = Field(gt=0, description="Refund amount in US dollars")
    reason: str = Field(description="Short reason shown to the approver")


class EscalateIn(_In):
    reason: str = Field(description="Why a human needs to take over")
    customer_email: EmailStr | None = None


def _money(cents: int) -> float:
    return round(cents / 100, 2)


def helpdesk_tools(
    store: VectorStore,
    repo: HelpdeskRepo,
    llm: anthropic.AsyncAnthropic,
    model: str,
    conversation: list[dict[str, Any]],
) -> list[Tool]:
    async def search(args: SearchIn) -> dict:
        hits = await store.search(args.query, limit=4)
        return {
            "articles": [
                {
                    "id": h.chunk_id,
                    "title": h.title,
                    "excerpt": h.content,
                    "score": round(h.score, 4),
                }
                for h in hits
            ]
        }

    async def lookup_customer(args: CustomerIn) -> dict:
        c = await repo.find_customer(args.email)
        if c is None:
            return {"found": False, "email": args.email}
        invoices = await repo.invoices_for(c["id"])
        refunds = await repo.refunds_for(c["id"])
        return {
            "found": True,
            "customer": {**c, "created_at": c["created_at"].isoformat()},
            "invoices": [
                {
                    "id": i["id"],
                    "amount_usd": _money(i["amount_cents"]),
                    "refunded_usd": _money(i["refunded_cents"]),
                    "status": i["status"],
                    "description": i["description"],
                    "issued_on": i["issued_on"].isoformat(),
                }
                for i in invoices
            ],
            "refunds": [
                {
                    "id": r["id"],
                    "invoice_id": r["invoice_id"],
                    "amount_usd": _money(r["amount_cents"]),
                    "status": r["status"],
                }
                for r in refunds
            ],
        }

    async def get_invoice(args: InvoiceIn) -> dict:
        i = await repo.get_invoice(args.invoice_id)
        if i is None:
            return {"found": False, "invoice_id": args.invoice_id}
        return {
            "found": True,
            "invoice": {
                "id": i["id"],
                "customer_name": i["customer_name"],
                "email": i["email"],
                "amount_usd": _money(i["amount_cents"]),
                "refunded_or_pending_usd": _money(i["refunded_or_pending_cents"]),
                "status": i["status"],
                "description": i["description"],
                "issued_on": i["issued_on"].isoformat(),
            },
        }

    async def propose_refund(args: RefundIn) -> dict:
        try:
            r = await repo.propose_refund(
                args.invoice_id, round(args.amount_usd * 100), args.reason
            )
        except RefundNotAllowed as e:
            return {"created": False, "policy_violation": str(e)}
        return {
            "created": True,
            "refund": {
                "id": r["id"],
                "invoice_id": r["invoice_id"],
                "amount_usd": _money(r["amount_cents"]),
                "reason": r["reason"],
                "status": r["status"],
                "customer_name": r["customer_name"],
            },
            "note": "Pending human approval in the UI. Tell the customer it is awaiting approval.",
        }

    async def escalate(args: EscalateIn) -> dict:
        triage = await triage_conversation(llm, model, render_transcript(conversation), args.reason)
        customer = await repo.find_customer(args.customer_email) if args.customer_email else None
        ticket_id = await repo.create_ticket(
            customer["id"] if customer else None,
            triage.model_dump(),
            [{"role": m["role"], "content": render_transcript([m])} for m in conversation],
        )
        return {"ticket_id": ticket_id, "triage": triage.model_dump()}

    return [
        Tool(
            "search_help_center",
            "Search Nimbus help-center articles (hybrid vector + keyword). Use it for any "
            "product, policy, or how-to question before answering, and cite article titles.",
            SearchIn,
            search,
        ),
        Tool(
            "lookup_customer",
            "Look up a customer account by email: plan, seats, status, recent invoices, and the "
            "current status of their refund requests.",
            CustomerIn,
            lookup_customer,
        ),
        Tool("get_invoice", "Fetch one invoice by id.", InvoiceIn, get_invoice),
        Tool(
            "propose_refund",
            "Propose a refund on a paid invoice. It is NOT issued until a human approves it in "
            "the UI. The backend enforces the refund policy and returns policy_violation if not "
            "allowed. Only call after confirming the invoice and the amount with the customer.",
            RefundIn,
            propose_refund,
        ),
        Tool(
            "escalate_to_human",
            "Hand the conversation to a human agent: creates a triaged ticket. Use when the "
            "customer asks for a human, the issue is a bug or outage you cannot resolve, or "
            "policy blocks what they need.",
            EscalateIn,
            escalate,
        ),
    ]
