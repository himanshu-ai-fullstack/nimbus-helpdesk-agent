"""Structured ticket triage: Claude reads a conversation and returns a validated
Pydantic object (structured outputs), which a human queue can sort and route.
The category list comes from each tenant's config, so the schema is built per
tenant."""

from functools import cache
from typing import Any, Literal

import anthropic
from pydantic import BaseModel, Field, create_model

from ..tenants.models import TenantConfig


class TriageBase(BaseModel):
    priority: Literal["low", "medium", "high", "urgent"]
    sentiment: Literal["positive", "neutral", "frustrated", "angry"]
    summary: str = Field(description="One or two sentences a human agent can act on")
    customer_asks: list[str] = Field(description="Each distinct thing the customer wants")
    suggested_next_step: str


@cache
def triage_model(categories: tuple[str, ...]) -> type[TriageBase]:
    return create_model(
        "TicketTriage",
        __base__=TriageBase,
        category=(Literal[categories], ...),  # type: ignore[arg-type,valid-type]
    )


def triage_prompt(tenant: TenantConfig) -> str:
    return (
        f"You triage support conversations for {tenant.name}, a {tenant.industry}.\n"
        f"Priority guide: {tenant.triage.priority_guide}\n"
        "Read the conversation and fill in the triage fields."
    )


def render_transcript(messages: list[dict[str, Any]]) -> str:
    lines = []
    for m in messages:
        if isinstance(m["content"], str):
            lines.append(f"{m['role'].upper()}: {m['content']}")
            continue
        for block in m["content"]:
            b = block if isinstance(block, dict) else block.model_dump()
            if b.get("type") == "text":
                lines.append(f"{m['role'].upper()}: {b['text']}")
            elif b.get("type") == "tool_use":
                lines.append(f"[agent called {b['name']} with {b['input']}]")
    return "\n".join(lines)


async def triage_conversation(
    client: anthropic.AsyncAnthropic, tenant: TenantConfig, transcript: str, reason: str
) -> BaseModel:
    response = await client.messages.parse(
        model=tenant.models.fast,
        max_tokens=4000,
        system=triage_prompt(tenant),
        messages=[
            {
                "role": "user",
                "content": f"Escalation reason: {reason}\n\n<conversation>\n{transcript}\n</conversation>",
            }
        ],
        output_format=triage_model(tuple(tenant.triage.categories)),
        output_config={"effort": "low"},
    )
    if response.parsed_output is None:
        raise RuntimeError(f"triage failed (stop_reason={response.stop_reason})")
    return response.parsed_output
