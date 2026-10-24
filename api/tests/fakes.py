import json
from types import SimpleNamespace as NS


class FakeStream:
    def __init__(self, events, final):
        self._events, self._final = events, final

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        async def gen():
            for e in self._events:
                yield e

        return gen()

    async def get_final_message(self):
        return self._final


class FakeClient:
    def __init__(self, turns):
        self._turns = list(turns)
        self.calls = []
        self.messages = self

    def stream(self, **kwargs):
        self.calls.append(json.loads(json.dumps(kwargs["messages"], default=lambda o: o.__dict__)))
        return FakeStream(*self._turns.pop(0))


def tool_turn():
    tool_block = NS(type="tool_use", id="toolu_1", name="echo", input={"text": "hi"})
    events = [
        NS(type="content_block_start", index=0, content_block=tool_block),
        NS(
            type="content_block_delta",
            index=0,
            delta=NS(type="input_json_delta", partial_json='{"text":"hi"}'),
        ),
        NS(type="content_block_stop", index=0),
    ]
    return events, NS(stop_reason="tool_use", content=[tool_block])


def text_turn(text):
    events = [
        NS(type="content_block_start", index=0, content_block=NS(type="text")),
        NS(type="content_block_delta", index=0, delta=NS(type="text_delta", text=text)),
        NS(type="content_block_stop", index=0),
    ]
    return events, NS(stop_reason="end_turn", content=[NS(type="text", text=text)])
