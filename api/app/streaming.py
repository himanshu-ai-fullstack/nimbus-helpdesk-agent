"""Vercel AI SDK UI message stream protocol (SSE, header
`x-vercel-ai-ui-message-stream: v1`), so `useChat` can talk to FastAPI directly.

Helpers build part dicts; `encode` turns one into an SSE frame. Keeping parts as
data lets the server store the same parts it streams, so stored conversations
are exactly what the user saw."""

import json
from typing import Any

Part = dict[str, Any]

HEADERS = {
    "x-vercel-ai-ui-message-stream": "v1",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def encode(part: Part) -> str:
    return f"data: {json.dumps(part, separators=(',', ':'), default=str)}\n\n"


def done() -> str:
    return "data: [DONE]\n\n"


def start(message_id: str) -> Part:
    return {"type": "start", "messageId": message_id}


def start_step() -> Part:
    return {"type": "start-step"}


def finish_step() -> Part:
    return {"type": "finish-step"}


def finish() -> Part:
    return {"type": "finish"}


def text_start(id: str) -> Part:
    return {"type": "text-start", "id": id}


def text_delta(id: str, delta: str) -> Part:
    return {"type": "text-delta", "id": id, "delta": delta}


def text_end(id: str) -> Part:
    return {"type": "text-end", "id": id}


def reasoning_start(id: str) -> Part:
    return {"type": "reasoning-start", "id": id}


def reasoning_delta(id: str, delta: str) -> Part:
    return {"type": "reasoning-delta", "id": id, "delta": delta}


def reasoning_end(id: str) -> Part:
    return {"type": "reasoning-end", "id": id}


def tool_input_start(call_id: str, name: str) -> Part:
    return {"type": "tool-input-start", "toolCallId": call_id, "toolName": name}


def tool_input_delta(call_id: str, delta: str) -> Part:
    return {"type": "tool-input-delta", "toolCallId": call_id, "inputTextDelta": delta}


def tool_input_available(call_id: str, name: str, input: Any) -> Part:
    return {"type": "tool-input-available", "toolCallId": call_id, "toolName": name, "input": input}


def tool_output_available(call_id: str, output: Any) -> Part:
    return {"type": "tool-output-available", "toolCallId": call_id, "output": output}


def data(name: str, payload: Any, id: str | None = None) -> Part:
    part: Part = {"type": f"data-{name}", "data": payload}
    if id:
        part["id"] = id
    return part


def error(text: str) -> Part:
    return {"type": "error", "errorText": text}
