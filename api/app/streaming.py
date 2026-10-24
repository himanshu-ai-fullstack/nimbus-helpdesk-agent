"""Encoder for the Vercel AI SDK UI message stream protocol (SSE, header
`x-vercel-ai-ui-message-stream: v1`), so `useChat` can talk to FastAPI directly."""

import json
from typing import Any

HEADERS = {
    "x-vercel-ai-ui-message-stream": "v1",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def sse(part: dict[str, Any]) -> str:
    return f"data: {json.dumps(part, separators=(',', ':'), default=str)}\n\n"


def done() -> str:
    return "data: [DONE]\n\n"


def start(message_id: str) -> str:
    return sse({"type": "start", "messageId": message_id})


def start_step() -> str:
    return sse({"type": "start-step"})


def finish_step() -> str:
    return sse({"type": "finish-step"})


def finish() -> str:
    return sse({"type": "finish"})


def text_start(id: str) -> str:
    return sse({"type": "text-start", "id": id})


def text_delta(id: str, delta: str) -> str:
    return sse({"type": "text-delta", "id": id, "delta": delta})


def text_end(id: str) -> str:
    return sse({"type": "text-end", "id": id})


def tool_input_start(call_id: str, name: str) -> str:
    return sse({"type": "tool-input-start", "toolCallId": call_id, "toolName": name})


def tool_input_delta(call_id: str, delta: str) -> str:
    return sse({"type": "tool-input-delta", "toolCallId": call_id, "inputTextDelta": delta})


def tool_input_available(call_id: str, name: str, input: Any) -> str:
    return sse(
        {"type": "tool-input-available", "toolCallId": call_id, "toolName": name, "input": input}
    )


def tool_output_available(call_id: str, output: Any) -> str:
    return sse({"type": "tool-output-available", "toolCallId": call_id, "output": output})


def source_document(source_id: str, title: str) -> str:
    return sse(
        {
            "type": "source-document",
            "sourceId": source_id,
            "mediaType": "text/plain",
            "title": title,
        }
    )


def data(name: str, payload: Any, id: str | None = None) -> str:
    part: dict[str, Any] = {"type": f"data-{name}", "data": payload}
    if id:
        part["id"] = id
    return sse(part)


def error(text: str) -> str:
    return sse({"type": "error", "errorText": text})
