"""Streaming tool-use loop over the Claude Messages API, translated into AI SDK
UI message stream parts as it goes."""

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import anthropic

from . import streaming as s
from .tools.base import Tool

MAX_STEPS = 8


def ui_to_anthropic(ui_messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert AI SDK UIMessages to Anthropic messages. An assistant UIMessage can
    span several steps; each step becomes an assistant turn (text + tool_use) and,
    if it called tools, a user turn carrying the tool_results."""
    out: list[dict[str, Any]] = []
    for msg in ui_messages:
        parts = msg.get("parts", [])
        if msg["role"] == "user":
            text = "".join(p.get("text", "") for p in parts if p.get("type") == "text")
            if text:
                out.append({"role": "user", "content": text})
            continue
        if msg["role"] != "assistant":
            continue

        content: list[dict[str, Any]] = []
        results: list[dict[str, Any]] = []

        def flush(content: list[dict[str, Any]], results: list[dict[str, Any]]) -> None:
            if content:
                out.append({"role": "assistant", "content": list(content)})
            if results:
                out.append({"role": "user", "content": list(results)})
            content.clear()
            results.clear()

        for p in parts:
            ptype = p.get("type", "")
            if ptype == "step-start":
                flush(content, results)
            elif ptype == "text" and p.get("text"):
                content.append({"type": "text", "text": p["text"]})
            elif ptype.startswith("tool-") and p.get("state") == "output-available":
                content.append(
                    {
                        "type": "tool_use",
                        "id": p["toolCallId"],
                        "name": ptype.removeprefix("tool-"),
                        "input": p.get("input") or {},
                    }
                )
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": p["toolCallId"],
                        "content": json.dumps(p.get("output")),
                    }
                )
        flush(content, results)
    return out


async def run_agent(
    client: anthropic.AsyncAnthropic,
    model: str,
    system: str,
    messages: list[dict[str, Any]],
    tools: list[Tool],
) -> AsyncIterator[str]:
    by_name = {t.name: t for t in tools}
    tool_defs = [t.to_anthropic() for t in tools]

    yield s.start(f"msg_{uuid.uuid4().hex}")
    try:
        for _ in range(MAX_STEPS):
            yield s.start_step()
            block_ids: dict[int, str] = {}
            async with client.messages.stream(
                model=model,
                max_tokens=16000,
                system=system,
                messages=messages,
                tools=tool_defs,
                thinking={"type": "adaptive", "display": "summarized"},
            ) as stream:
                async for event in stream:
                    if event.type == "content_block_start":
                        block = event.content_block
                        if block.type == "text":
                            block_ids[event.index] = f"txt_{uuid.uuid4().hex[:12]}"
                            yield s.text_start(block_ids[event.index])
                        elif block.type == "thinking":
                            block_ids[event.index] = f"rsn_{uuid.uuid4().hex[:12]}"
                            yield s.sse({"type": "reasoning-start", "id": block_ids[event.index]})
                        elif block.type == "tool_use":
                            block_ids[event.index] = block.id
                            yield s.tool_input_start(block.id, block.name)
                    elif event.type == "content_block_delta":
                        bid = block_ids.get(event.index)
                        if bid is None:
                            continue
                        d = event.delta
                        if d.type == "text_delta":
                            yield s.text_delta(bid, d.text)
                        elif d.type == "thinking_delta":
                            yield s.sse({"type": "reasoning-delta", "id": bid, "delta": d.thinking})
                        elif d.type == "input_json_delta":
                            yield s.tool_input_delta(bid, d.partial_json)
                    elif event.type == "content_block_stop":
                        bid = block_ids.get(event.index)
                        if bid and bid.startswith("txt_"):
                            yield s.text_end(bid)
                        elif bid and bid.startswith("rsn_"):
                            yield s.sse({"type": "reasoning-end", "id": bid})
                final = await stream.get_final_message()

            tool_uses = [b for b in final.content if b.type == "tool_use"]
            if final.stop_reason == "refusal":
                yield s.error("The model declined this request.")
                yield s.finish_step()
                break
            if not tool_uses or final.stop_reason == "max_tokens":
                yield s.finish_step()
                break

            results = []
            for b in tool_uses:
                yield s.tool_input_available(b.id, b.name, b.input)
                tool = by_name.get(b.name)
                if tool is None:
                    output, is_error = {"error": f"unknown tool {b.name}"}, True
                else:
                    output, is_error = await tool.run(b.input)
                yield s.tool_output_available(b.id, output)
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": b.id,
                        "content": json.dumps(output, default=str),
                        "is_error": is_error,
                    }
                )
            messages.append({"role": "assistant", "content": final.content})
            messages.append({"role": "user", "content": results})
            yield s.finish_step()
    except anthropic.APIError as e:
        yield s.error(f"Model API error: {e.__class__.__name__}")
    yield s.finish()
    yield s.done()
