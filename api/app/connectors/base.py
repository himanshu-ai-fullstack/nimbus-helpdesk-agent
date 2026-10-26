"""The boundary between the agent and a company's own systems.

Real tenants keep accounts, invoices, orders or employee records in systems they
already run (billing, e-commerce, HR). The agent never reads those tables
directly: it goes through a Connector, so swapping the demo data for a real API
or an MCP server changes one class, not the tools or the policy engine."""

from datetime import date
from typing import Any, Protocol

from pydantic import BaseModel


class Account(BaseModel):
    id: str
    email: str
    name: str
    status: str
    created_on: date
    attributes: dict[str, Any] = {}


class Record(BaseModel):
    """Anything an action can apply to: an invoice, an order, a laptop."""

    id: str
    account_id: str
    type: str
    title: str
    status: str
    amount_cents: int | None = None
    currency: str = "USD"
    occurred_on: date
    attributes: dict[str, Any] = {}


class Connector(Protocol):
    async def find_account(self, email: str) -> Account | None: ...

    async def get_account(self, account_id: str) -> Account | None: ...

    async def records_for(self, account_id: str, limit: int = 8) -> list[Record]: ...

    async def get_record(self, record_id: str) -> Record | None: ...
