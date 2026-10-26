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
    """Stands in for AsyncAnthropic: `client.beta.messages.stream(...)` replays
    scripted turns and records the messages each call received."""

    def __init__(self, turns):
        self._turns = list(turns)
        self.calls = []
        self.kwargs = []
        self.messages = self
        self.beta = self

    def stream(self, **kwargs):
        self.kwargs.append(kwargs)
        self.calls.append(json.loads(json.dumps(kwargs["messages"], default=lambda o: o.__dict__)))
        return FakeStream(*self._turns.pop(0))


def usage(inp=100, out=20, read=0, write=0):
    return NS(
        input_tokens=inp,
        output_tokens=out,
        cache_read_input_tokens=read,
        cache_creation_input_tokens=write,
    )


def tool_turn(name="echo", input=None, call_id="toolu_1"):
    input = {"text": "hi"} if input is None else input
    tool_block = NS(type="tool_use", id=call_id, name=name, input=input)
    events = [
        NS(type="content_block_start", index=0, content_block=tool_block),
        NS(
            type="content_block_delta",
            index=0,
            delta=NS(type="input_json_delta", partial_json=json.dumps(input)),
        ),
        NS(type="content_block_stop", index=0),
    ]
    return events, NS(
        stop_reason="tool_use", content=[tool_block], model="claude-opus-5-5", usage=usage()
    )


def text_turn(text, citation=None):
    events = [NS(type="content_block_start", index=0, content_block=NS(type="text"))]
    if citation:
        events.append(
            NS(
                type="content_block_delta",
                index=0,
                delta=NS(
                    type="citations_delta", citation=NS(type="search_result_location", **citation)
                ),
            )
        )
    events += [
        NS(type="content_block_delta", index=0, delta=NS(type="text_delta", text=text)),
        NS(type="content_block_stop", index=0),
    ]
    return events, NS(
        stop_reason="end_turn",
        content=[NS(type="text", text=text)],
        model="claude-opus-5-5",
        usage=usage(read=80),
    )


def make_pdf(pages: list[str]) -> bytes:
    """A minimal valid PDF with one line of Helvetica text per page."""
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids ["
        + " ".join(f"{4 + 2 * i} 0 R" for i in range(len(pages)))
        + f"] /Count {len(pages)} >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for i, text in enumerate(pages):
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET"
        objs.append(
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * i} 0 R >>"
        )
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    out = b"%PDF-1.4\n"
    offsets = []
    for n, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n{obj}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{off:010d} 00000 n \n".encode() for off in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out
