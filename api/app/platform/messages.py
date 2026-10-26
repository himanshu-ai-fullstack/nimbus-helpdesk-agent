"""Rebuild the assistant UIMessage from the stream parts the server sent, so the
stored conversation is exactly what the browser rendered."""

from typing import Any

from ..streaming import Part

OUTCOME_RANK = {"answered": 0, "action_proposed": 1, "escalated": 2}


class MessageBuilder:
    def __init__(self) -> None:
        self.id = ""
        self.parts: list[dict[str, Any]] = []
        self.error: str | None = None
        self._open: dict[str, dict[str, Any]] = {}

    def add(self, p: Part) -> None:
        t = p["type"]
        if t == "start":
            self.id = p["messageId"]
        elif t == "start-step":
            self.parts.append({"type": "step-start"})
        elif t in ("text-start", "reasoning-start"):
            part = {"type": t.removesuffix("-start"), "text": ""}
            self._open[p["id"]] = part
            self.parts.append(part)
        elif t in ("text-delta", "reasoning-delta"):
            self._open[p["id"]]["text"] += p["delta"]
        elif t == "tool-input-start":
            part = {
                "type": f"tool-{p['toolName']}",
                "toolCallId": p["toolCallId"],
                "state": "input-streaming",
            }
            self._open[p["toolCallId"]] = part
            self.parts.append(part)
        elif t == "tool-input-available":
            part = self._open[p["toolCallId"]]
            part.update(state="input-available", input=p["input"])
        elif t == "tool-output-available":
            part = self._open[p["toolCallId"]]
            part.update(state="output-available", output=p["output"])
        elif t.startswith("data-"):
            self.parts.append({k: v for k, v in p.items() if k in ("type", "id", "data")})
        elif t == "error":
            self.error = p["errorText"]

    def message(self) -> dict[str, Any]:
        return {"id": self.id, "role": "assistant", "parts": self.parts}

    def outcome(self) -> str:
        outcome = "answered"
        for p in self.parts:
            out = p.get("output")
            if not isinstance(out, dict):
                continue
            found = None
            if p["type"] == "tool-escalate_to_human" and "ticket_id" in out:
                found = "escalated"
            elif p["type"] == "tool-propose_action" and out.get("created"):
                found = "action_proposed"
            if found and OUTCOME_RANK[found] > OUTCOME_RANK[outcome]:
                outcome = found
        return outcome


def accounts_seen(ui_messages: list[dict[str, Any]]) -> set[str]:
    """Account ids the agent looked up earlier in this (server-stored) conversation.
    Records and actions are limited to these."""
    seen = set()
    for m in ui_messages:
        for p in m.get("parts", []):
            out = p.get("output")
            if (
                p.get("type") == "tool-lookup_account"
                and isinstance(out, dict)
                and out.get("found")
            ):
                seen.add(out["account"]["id"])
    return seen
