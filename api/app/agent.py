"""Streaming tool-use loop over the Claude Messages API, translated into AI SDK
UI message stream parts as it goes."""

import json
import time
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any, cast

import anthropic

from . import streaming as s
from .streaming import Part
from .tools.base import Tool

MAX_STEPS = 8
# On a policy refusal the API re-runs the request on a fallback model it picks by
# refusal category, inside the same call.
FALLBACK_BETA = "server-side-fallback-2026-07-01"

# Called with one dict per model call ("llm") and per tool run ("tool").
EventSink = Callable[[dict[str, Any]], None]


def ui_to_anthropic(
    ui_messages: list[dict[str, Any]], tools: list[Tool] | None = None
) -> list[dict[str, Any]]:
    """Convert stored AI SDK UIMessages to Anthropic messages. An assistant UIMessage
    can span several steps; each step becomes an assistant turn (text + tool_use)
    and, if it called tools, a user turn carrying the tool_results. Only call this
    on server-stored history: tool outputs become tool_results the model trusts."""
    by_name = {t.name: t for t in tools or []}
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
            elif (ptype.startswith("tool-") or ptype == "dynamic-tool") and p.get(
                "state"
            ) == "output-available":
                name = p.get("toolName") or ptype.removeprefix("tool-")
                output = p.get("output")
                tool = by_name.get(name)
                is_error = isinstance(output, dict) and "error" in output
                content.append(
                    {
                        "type": "tool_use",
                        "id": p["toolCallId"],
                        "name": name,
                        "input": p.get("input") or {},
                    }
                )
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": p["toolCallId"],
                        "content": tool.result_content(output, is_error)
                        if tool and isinstance(output, dict)
                        else json.dumps(output, default=str),
                    }
                )
        flush(content, results)
    return out


def _usage(final: Any) -> dict[str, int]:
    u = getattr(final, "usage", None)
    return {
        "input_tokens": getattr(u, "input_tokens", 0) or 0,
        "output_tokens": getattr(u, "output_tokens", 0) or 0,
        "cache_read_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
        "cache_write_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
    }


async def run_agent(
    client: anthropic.AsyncAnthropic,
    model: str,
    system: str,
    messages: list[dict[str, Any]],
    tools: list[Tool],
    *,
    effort: str = "medium",
    message_id: str | None = None,
    on_event: EventSink | None = None,
) -> AsyncIterator[Part]:
    by_name = {t.name: t for t in tools}
    tool_defs = [t.to_anthropic() for t in tools]
    emit = on_event or (lambda _e: None)

    yield s.start(message_id or f"msg_{uuid.uuid4().hex}")
    try:
        for step in range(MAX_STEPS):
            yield s.start_step()
            block_ids: dict[int, str] = {}
            started = time.monotonic()
            async with client.beta.messages.stream(
                model=model,
                max_tokens=16000,
                # The system prompt and tools are identical for every conversation
                # of a tenant: cache them, and let auto-caching cover the history.
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                # Plain dicts are valid request params; the SDK's TypedDicts are stricter.
                messages=cast(Any, messages),
                tools=cast(Any, tool_defs),
                thinking={"type": "adaptive", "display": "summarized"},
                output_config=cast(Any, {"effort": effort}),
                cache_control={"type": "ephemeral"},
                betas=[FALLBACK_BETA],
                fallbacks="default",
            ) as stream:
                async for event in stream:
                    if event.type == "content_block_start":
                        block = event.content_block
                        if block.type == "text":
                            block_ids[event.index] = f"txt_{uuid.uuid4().hex[:12]}"
                            yield s.text_start(block_ids[event.index])
                        elif block.type == "thinking":
                            block_ids[event.index] = f"rsn_{uuid.uuid4().hex[:12]}"
                            yield s.reasoning_start(block_ids[event.index])
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
                            yield s.reasoning_delta(bid, d.thinking)
                        elif d.type == "input_json_delta":
                            yield s.tool_input_delta(bid, d.partial_json)
                        elif d.type == "citations_delta":
                            c = d.citation
                            if c.type == "search_result_location":
                                yield s.data(
                                    "citation",
                                    {
                                        "textId": bid,
                                        "source": c.source,
                                        "title": c.title,
                                        "citedText": c.cited_text,
                                    },
                                )
                    elif event.type == "content_block_stop":
                        bid = block_ids.get(event.index)
                        if bid and bid.startswith("txt_"):
                            yield s.text_end(bid)
                        elif bid and bid.startswith("rsn_"):
                            yield s.reasoning_end(bid)
                final = await stream.get_final_message()
            emit(
                {
                    "kind": "llm",
                    "step": step,
                    "model": getattr(final, "model", model) or model,
                    "latency_ms": round((time.monotonic() - started) * 1000),
                    **_usage(final),
                }
            )

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
                started = time.monotonic()
                if tool is None:
                    output, is_error = {"error": f"unknown tool {b.name}"}, True
                    content: str | list[dict[str, Any]] = json.dumps(output)
                else:
                    output, is_error = await tool.run(b.input)
                    content = tool.result_content(output, is_error)
                emit(
                    {
                        "kind": "tool",
                        "step": step,
                        "tool_name": b.name,
                        "latency_ms": round((time.monotonic() - started) * 1000),
                        "is_error": is_error,
                    }
                )
                yield s.tool_output_available(b.id, output)
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": b.id,
                        "content": content,
                        "is_error": is_error,
                    }
                )
            messages.append({"role": "assistant", "content": final.content})
            messages.append({"role": "user", "content": results})
            yield s.finish_step()
    except anthropic.APIError as e:
        yield s.error(f"Model API error: {e.__class__.__name__}")
    yield s.finish()
