import json

import httpx
import pytest

from app.config import get_settings

from .fakes import FakeClient, text_turn


@pytest.fixture
async def api(database_url, monkeypatch, pool):
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("EMBEDDER", "hash")
    monkeypatch.setenv("EMBEDDING_DIM", "64")
    monkeypatch.setenv("ADMIN_TOKEN", "secret")
    monkeypatch.setenv("CHAT_RATE_LIMIT", "2")
    get_settings.cache_clear()
    from app.main import app

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield app, c
    get_settings.cache_clear()


async def test_health(api):
    _, c = api
    assert (await c.get("/health")).json() == {"status": "ok"}


async def test_reset_requires_token_and_seeds(api):
    _, c = api
    assert (await c.post("/api/admin/reset")).status_code == 403
    r = await c.post("/api/admin/reset", headers={"x-admin-token": "secret"})
    assert r.status_code == 200
    assert len((await c.get("/api/articles")).json()) == 9


async def test_chat_streams_ai_sdk_protocol_and_rate_limits(api):
    app, c = api
    app.state.llm = FakeClient([text_turn("Hi!"), text_turn("Again")])
    body = {"messages": [{"id": "1", "role": "user", "parts": [{"type": "text", "text": "hello"}]}]}

    r = await c.post("/api/chat", json=body)
    assert r.headers["x-vercel-ai-ui-message-stream"] == "v1"
    events = [line.removeprefix("data: ") for line in r.text.split("\n\n") if line]
    assert events[-1] == "[DONE]"
    assert {"type": "text-delta", "id": json.loads(events[3])["id"], "delta": "Hi!"} in [
        json.loads(e) for e in events[:-1]
    ]

    assert (await c.post("/api/chat", json=body)).status_code == 200
    assert (await c.post("/api/chat", json=body)).status_code == 429


async def test_refund_decision_on_unknown_refund_conflicts(api):
    _, c = api
    r = await c.post("/api/refunds/999/decision", json={"approve": True})
    assert r.status_code == 409
