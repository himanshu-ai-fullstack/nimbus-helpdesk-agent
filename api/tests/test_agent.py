from pydantic import BaseModel

from app.agent import run_agent, ui_to_anthropic
from app.tools.base import Tool

from .fakes import FakeClient, text_turn, tool_turn


class EchoIn(BaseModel):
    text: str


async def echo(args: EchoIn) -> dict:
    return {"echoed": args.text}


async def collect(client, tools, **kw):
    return [
        p
        async for p in run_agent(
            client, "m", "sys", [{"role": "user", "content": "go"}], tools, **kw
        )
    ]


async def test_tool_loop_streams_ai_sdk_parts():
    client = FakeClient([tool_turn(), text_turn("done")])
    parts = await collect(client, [Tool("echo", "Echo text", EchoIn, echo)])

    assert [p["type"] for p in parts] == [
        "start",
        "start-step",
        "tool-input-start",
        "tool-input-delta",
        "tool-input-available",
        "tool-output-available",
        "finish-step",
        "start-step",
        "text-start",
        "text-delta",
        "text-end",
        "finish-step",
        "finish",
    ]
    assert parts[5]["output"] == {"echoed": "hi"}
    # the second model call saw the tool result
    second = client.calls[1]
    assert second[-1]["content"][0]["tool_use_id"] == "toolu_1"


async def test_request_caches_prompt_and_enables_fallbacks():
    client = FakeClient([text_turn("hi")])
    await collect(client, [], effort="low")
    kw = client.kwargs[0]
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert kw["cache_control"] == {"type": "ephemeral"}
    assert kw["fallbacks"] == "default"
    assert kw["output_config"] == {"effort": "low"}


async def test_events_report_usage_and_tool_latency():
    events: list[dict] = []
    client = FakeClient([tool_turn(), text_turn("done")])
    await collect(client, [Tool("echo", "Echo text", EchoIn, echo)], on_event=events.append)
    assert [e["kind"] for e in events] == ["llm", "tool", "llm"]
    assert events[0]["input_tokens"] == 100 and events[0]["model"] == "claude-opus-5-5"
    assert events[1]["tool_name"] == "echo" and events[1]["is_error"] is False
    assert events[2]["cache_read_tokens"] == 80


async def test_citations_become_data_parts():
    cite = {"source": "doc:1#chunk:7", "title": "Refund policy", "cited_text": "14 days"}
    parts = await collect(FakeClient([text_turn("Within 14 days.", citation=cite)]), [])
    [c] = [p for p in parts if p["type"] == "data-citation"]
    text_id = next(p["id"] for p in parts if p["type"] == "text-start")
    assert c["data"] == {
        "textId": text_id,
        "source": "doc:1#chunk:7",
        "title": "Refund policy",
        "citedText": "14 days",
    }


async def test_tool_can_render_rich_content_for_the_model():
    tool = Tool(
        "search",
        "Search",
        EchoIn,
        echo,
        to_content=lambda out: [{"type": "search_result", "source": out["echoed"]}],
    )
    client = FakeClient([tool_turn("search"), text_turn("ok")])
    await collect(client, [tool])
    result = client.calls[1][-1]["content"][0]
    assert result["content"] == [{"type": "search_result", "source": "hi"}]


async def test_invalid_tool_input_is_reported_not_raised():
    tool = Tool("echo", "Echo text", EchoIn, echo)
    out, is_error = await tool.run({"wrong": 1})
    assert is_error and out["error"] == "invalid input"


def test_ui_messages_round_trip_tool_steps():
    ui = [
        {"role": "user", "parts": [{"type": "text", "text": "find it"}]},
        {
            "role": "assistant",
            "parts": [
                {"type": "step-start"},
                {
                    "type": "tool-search_knowledge",
                    "toolCallId": "t1",
                    "state": "output-available",
                    "input": {"query": "x"},
                    "output": {"results": []},
                },
                {"type": "step-start"},
                {
                    "type": "dynamic-tool",
                    "toolName": "get_invoice",
                    "toolCallId": "t2",
                    "state": "output-available",
                    "input": {"invoice_id": "INV-1"},
                    "output": {},
                },
                {"type": "step-start"},
                {"type": "text", "text": "Nothing found."},
                {"type": "data-citation", "data": {"source": "doc:1"}},
            ],
        },
        {"role": "user", "parts": [{"type": "text", "text": "ok"}]},
    ]
    msgs = ui_to_anthropic(ui)
    assert [m["role"] for m in msgs] == [
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
    ]
    assert msgs[3]["content"][0]["name"] == "get_invoice"
    assert msgs[1]["content"][0]["type"] == "tool_use"
    assert msgs[2]["content"][0]["tool_use_id"] == "t1"
    assert msgs[5]["content"] == [{"type": "text", "text": "Nothing found."}]
