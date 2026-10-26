# Project structure

```
nimbus-helpdesk-agent/
├── api/                          Python backend (FastAPI, uv)
│   ├── app/
│   │   ├── main.py               HTTP routes, startup wiring, system prompt, rate limiting
│   │   ├── agent.py              Streaming tool-use loop over Claude; UI messages ⇄ Claude messages
│   │   ├── streaming.py          Encoder for the Vercel AI SDK UI message stream (SSE)
│   │   ├── config.py             Typed settings from env vars (.env)
│   │   ├── db.py                 Connection pool and schema (pgvector extension, chunks, HNSW + GIN indexes)
│   │   ├── ratelimit.py          Per-IP sliding-window limiter to cap API spend
│   │   ├── tools/base.py         Tool type: JSON schema from Pydantic + validated execution
│   │   ├── rag/                  Retrieval-augmented generation
│   │   │   ├── chunking.py       Recursive splitter (paragraph → line → sentence → word) with overlap
│   │   │   ├── embeddings.py     OpenAI embedder + offline hash embedder for tests
│   │   │   └── store.py          Ingest documents; hybrid search (vector + full-text, RRF fusion)
│   │   └── helpdesk/             The Nimbus support domain
│   │       ├── schema.py         Tables: customers, invoices, refunds, tickets
│   │       ├── repo.py           Data access + refund policy guardrails (14 days, $500 cap, no over-refund)
│   │       ├── tools.py          The 5 agent tools: search_help_center, lookup_customer, get_invoice,
│   │       │                     propose_refund, escalate_to_human
│   │       ├── triage.py         Structured output: Claude → validated TicketTriage (Pydantic)
│   │       ├── seed.py           Resets demo data (customers, invoices dated relative to today, articles)
│   │       └── docs/*.md         9 help-center articles that get chunked and embedded
│   ├── evals/
│   │   ├── retrieval.py          hit@1, hit@3 and MRR for help-center search
│   │   └── retrieval_cases.json  20 labelled question → expected article pairs
│   ├── tests/                    pytest, run against a real Postgres + pgvector
│   │   ├── fakes.py              Scripted stand-in for the Claude streaming client
│   │   ├── test_agent.py         Stream protocol order, tool loop, message conversion
│   │   ├── test_api.py           Endpoints, admin auth, rate limiting
│   │   ├── test_helpdesk.py      Refund policy cases, lookups, tickets
│   │   ├── test_store.py         Hybrid search ranking
│   │   ├── test_chunking.py      Chunk sizes and overlap
│   │   ├── test_ratelimit.py     Sliding window
│   │   └── test_retrieval_eval.py  Regression floor for the retrieval eval
│   ├── Dockerfile                Production image (used by Render)
│   └── pyproject.toml, uv.lock   Dependencies
│
├── web/                          Next.js 16 frontend (TypeScript, Tailwind, AI SDK 7)
│   └── src/
│       ├── app/page.tsx          Chat page
│       ├── app/tickets/page.tsx  Ticket queue (server component, sorted by triage priority)
│       ├── app/layout.tsx        Shell and header
│       ├── components/Chat.tsx   useChat, streaming messages, suggestions, input, stop
│       ├── components/ToolPart.tsx  Generative UI: maps each tool call to a card, with loading states
│       ├── components/cards/     CustomerCard, RefundCard (approve / deny), TicketCard, Sources, Card
│       └── lib/types.ts          Typed tool inputs and outputs shared by the UI (mirrors api tools)
│
├── docs/                         Screenshots and this file
├── .github/workflows/ci.yml      CI: ruff + pytest (with a pgvector service), eslint + tsc + next build
├── docker-compose.yml            Local Postgres 16 + pgvector
├── render.yaml                   Render blueprint for the API
└── README.md                     Overview, setup, deploy steps, demo script
```

## How one chat message flows

1. **Browser.** `Chat.tsx` calls `sendMessage()`. The AI SDK's `useChat` POSTs every message so far, as UI messages, to `POST /api/chat` on FastAPI.
2. **FastAPI** (`main.py`) checks the rate limit, converts the UI messages to Claude's format (`agent.ui_to_anthropic`), and builds the five tools for this request.
3. **Agent loop** (`agent.py`) calls `client.messages.stream()` on Claude with the system prompt and tools. While Claude streams, each event is translated straight into an SSE part: thinking becomes `reasoning-*`, text becomes `text-*`, and tool arguments become `tool-input-*`.
4. **Tools.** When Claude stops to use tools, each call is validated with Pydantic and run:
   - `search_help_center` embeds the question, then one SQL query runs pgvector cosine search and Postgres full-text search and fuses them with Reciprocal Rank Fusion.
   - `lookup_customer` and `get_invoice` read Postgres.
   - `propose_refund` checks the policy in `repo.py` and only ever creates a pending refund.
   - `escalate_to_human` asks Claude for a structured `TicketTriage` and saves a ticket.

   Results stream to the browser as `tool-output-available` and go back to Claude as `tool_result` blocks. The loop repeats until Claude answers without calling a tool (at most 8 steps).
5. **Browser again.** `useChat` assembles the parts into the message. `ToolPart.tsx` renders each tool part as a card while it streams: a skeleton first, then the customer card, refund card, ticket card or sources.
6. **Human in the loop.** The refund card's Approve and Deny buttons call `POST /api/refunds/{id}/decision` directly. The agent sees the new status the next time it calls `lookup_customer`.

```
Browser (useChat) ──POST /api/chat──▶ FastAPI ──messages.stream()──▶ Claude
      ▲                                  │  ◀── tool_use ────────────────┘
      │      SSE: text / reasoning /     ├─▶ tools ─▶ Postgres (customers, invoices, refunds, tickets)
      └──── tool-input / tool-output ────┤            pgvector + full-text (help-center chunks)
                                         └─▶ OpenAI embeddings (search queries)
```
