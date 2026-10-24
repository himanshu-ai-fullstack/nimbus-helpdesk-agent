"""Structured ticket triage: Claude reads a conversation and returns a validated
Pydantic object (structured outputs), which a human queue can sort and route."""

from typing import Literal

import anthropic
from pydantic import BaseModel, Field


class TicketTriage(BaseModel):
    category: Literal["billing", "bug", "account", "how_to", "feature_request", "other"]
    priority: Literal["low", "medium", "high", "urgent"]
    sentiment: Literal["positive", "neutral", "frustrated", "angry"]
    summary: str = Field(description="One or two sentences a human agent can act on")
    customer_asks: list[str] = Field(description="Each distinct thing the customer wants")
    suggested_next_step: str


TRIAGE_PROMPT = """You triage support conversations for Nimbus, a project management SaaS.
Priority guide: urgent = outage, data loss, or security; high = blocked from working or a
billing error; medium = degraded experience; low = questions and feature requests.
Read the conversation and fill in the triage fields."""


def render_transcript(messages: list[dict]) -> str:
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
    client: anthropic.AsyncAnthropic, model: str, transcript: str, reason: str
) -> TicketTriage:
    response = await client.messages.parse(
        model=model,
        max_tokens=4000,
        system=TRIAGE_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Escalation reason: {reason}\n\n<conversation>\n{transcript}\n</conversation>",
            }
        ],
        output_format=TicketTriage,
        output_config={"effort": "low"},
    )
    if response.parsed_output is None:
        raise RuntimeError(f"triage failed (stop_reason={response.stop_reason})")
    return response.parsed_output
