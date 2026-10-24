import json

from pydantic import BaseModel

from app.agent import run_agent, ui_to_anthropic
from app.tools.base import Tool

from .fakes import FakeClient, text_turn, tool_turn


class EchoIn(BaseModel):
    text: str


async def echo(args: EchoIn) -> dict:
    return {"echoed": args.text}


def parse(sse_lines):
    parts = []
    for line in sse_lines:
        payload = line.removeprefix("data: ").strip()
        parts.append(payload if payload == "[DONE]" else json.loads(payload))
    return parts


async def test_tool_loop_streams_ai_sdk_parts():
    client = FakeClient([tool_turn(), text_turn("done")])
    tools = [Tool("echo", "Echo text", EchoIn, echo)]
    parts = parse(
        [
            chunk
            async for chunk in run_agent(
                client, "m", "sys", [{"role": "user", "content": "go"}], tools
            )
        ]
    )

    types = [p if p == "[DONE]" else p["type"] for p in parts]
    assert types == [
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
        "[DONE]",
    ]
    assert parts[5]["output"] == {"echoed": "hi"}
    # the second model call saw the tool result
    second = client.calls[1]
    assert second[-1]["content"][0]["tool_use_id"] == "toolu_1"


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
