# Architecture

## Project structure

```
helpdesk-agent/
├── api/                              Python backend (FastAPI, uv)
│   ├── app/
│   │   ├── main.py                   Startup wiring: tenants, pool, stores, routers
│   │   ├── agent.py                  Streaming tool-use loop over Claude; stored UI messages → Claude messages
│   │   ├── streaming.py              AI SDK UI message stream parts (SSE)
│   │   ├── config.py                 Settings from env; model prices for cost tracking
│   │   ├── db.py                     Schema, versioned migrations, runtime role, row-level security,
│   │   │                             tenant-scoped connections
│   │   ├── ratelimit.py              Per-IP sliding-window limiter
│   │   ├── tenants/
│   │   │   ├── models.py             TenantConfig: persona, prompt, action policies, triage, display, models
│   │   │   ├── loader.py             Loads tenants/<slug>/tenant.yaml, versions it by hash, admin-token hashes
│   │   │   ├── seed.py               Resets one tenant's demo data and knowledge base
│   │   │   └── new.py                Scaffolds a new tenant folder
│   │   ├── connectors/
│   │   │   ├── base.py               Connector protocol: the agent's only door into company records
│   │   │   └── demo.py               DemoConnector over each tenant's data.json
│   │   ├── platform/
│   │   │   ├── turn.py               One user turn: history → agent → persist (shared by API and evals)
│   │   │   ├── policy.py             Action policy engine (status, time window, caps, limits)
│   │   │   ├── repo.py               Actions (pending approval) and tickets
│   │   │   ├── prompt.py             System prompt = tenant persona + prompt + shared rules
│   │   │   ├── triage.py             Structured ticket triage with per-tenant categories (Haiku)
│   │   │   └── messages.py           Rebuilds the streamed UI message for storage; conversation outcome
│   │   ├── tools/
│   │   │   ├── base.py               Tool: Pydantic schema + validated execution + model-facing content
│   │   │   └── registry.py           The six tools, built per tenant and request
│   │   ├── rag/                      Chunking, embeddings, tenant-filtered hybrid search (pgvector + FTS + RRF)
│   │   ├── ingest/                   PDF / Markdown / text / HTML parsing; SSRF-safe URL fetching
│   │   ├── telemetry/
│   │   │   ├── store.py              Conversations, messages, agent events, feedback, knowledge gaps, spend
│   │   │   └── analytics.py          Per-tenant support metrics
│   │   └── routes/                   chat, knowledge, admin (approvals, tickets, analytics, reset), deps
│   ├── tenants/                      One folder per company: tenant.yaml, docs/*.md, data.json
│   │   ├── nimbus/                   SaaS billing
│   │   ├── cartwheel/                E-commerce orders and returns
│   │   └── northstar/                Internal IT and HR helpdesk
│   ├── evals/
│   │   ├── retrieval.py              hit@1 / hit@3 / MRR per tenant
│   │   ├── answers.py                End-to-end answer eval: deterministic checks + Claude judge
│   │   ├── <tenant>/retrieval.json   Labelled question → article pairs
│   │   ├── <tenant>/answers.json     Conversation cases, including red-team cases
│   │   └── results/                  Dated eval reports
│   └── tests/                        pytest against a real Postgres + pgvector
│
├── web/                              Next.js 16 (TypeScript, Tailwind, AI SDK 7)
│   └── src/
│       ├── app/page.tsx              Company picker
│       ├── app/t/[tenant]/           layout (loads tenant config on the server), chat, approvals,
│       │                             tickets, admin/knowledge, admin/analytics
│       ├── components/tenant.tsx     Tenant shell, header, admin-token gate
│       ├── components/Chat.tsx       useChat with server-owned history, citations, feedback
│       ├── components/ToolPart.tsx   Generative UI: one card per tool call
│       ├── components/cards/         Account, records, action request, sources and citations, ticket
│       └── lib/                      API client, types mirroring the tools, cached tenant loader
└── .github/workflows/ci.yml          ruff, mypy, pytest (+ RLS and retrieval floors); web lint, tsc, build;
                                      on-demand answer eval
```

## How one chat message flows

1. **Browser.** `Chat.tsx` calls `sendMessage()`. The transport sends only the conversation id
   and the new message to `POST /api/t/<tenant>/chat`. History lives on the server.
2. **Route** (`routes/chat.py`). Resolves the tenant (404 if unknown), applies the per-IP rate
   limit and the tenant's daily spend cap, and opens the conversation. A conversation id that
   belongs to another tenant is invisible under row-level security, so it is rejected.
3. **Turn** (`platform/turn.py`). Loads the stored history, saves the user message, builds the
   tenant's tools and system prompt, and converts stored UI messages into Claude messages. The
   model only ever sees tool results the server produced; a client can't forge them.
4. **Agent loop** (`agent.py`). Calls `client.beta.messages.stream` with adaptive thinking, the
   tenant's effort level, prompt caching (an explicit breakpoint on the system prompt plus
   automatic caching of the history) and server-side refusal fallbacks. Each Claude stream event
   is translated into an AI SDK part and streamed as SSE. When Claude calls tools, they run with
   validated input, results go back to Claude, and the loop continues (up to 8 steps).
5. **Tools** (`tools/registry.py`).
   - `search_knowledge_base` runs tenant-filtered hybrid search and returns the hits to Claude as
     `search_result` blocks, one text block per paragraph. Claude cites them natively; each
     `citations_delta` becomes a `data-citation` part with the quoted passage.
   - `lookup_account` / `get_record` read through the tenant's Connector. A conversation can
     access one account, and records only of that account.
   - `propose_action` checks the tenant's policy in code (`platform/policy.py`) inside a
     transaction with a per-record advisory lock, and can only create a *pending* action.
   - `escalate_to_human` triages the transcript into the tenant's categories with Haiku
     (structured output) and opens a ticket.
   - `flag_knowledge_gap` records a question the knowledge base couldn't answer.
6. **Persist.** The stream parts are rebuilt into the same UI message the browser rendered and
   stored, with one telemetry event per model call (latency, tokens, cache reads and writes) and
   per tool call, and the conversation's outcome (answered, action proposed, escalated).
7. **Browser.** `useChat` assembles the parts; `ToolPart` renders a card per tool call as it
   streams; citation chips open the cited passage; 👍/👎 posts feedback.

## Tenancy and isolation

- **Config is code.** `tenants/<slug>/tenant.yaml` is validated at startup by `TenantConfig`.
  Its hash is the config version stored on every conversation, so analytics can compare versions.
- **Row-level security.** Every tenant-owned table has a policy comparing `tenant_id` with the
  transaction setting `app.tenant_id`. The pool runs as `helpdesk_app`, a role without
  `BYPASSRLS`; `tenant_conn()` sets the tenant for one transaction. Queries also filter by
  `tenant_id` explicitly for the indexes, but a missing filter returns nothing rather than another
  company's rows. Tests check this with queries that have no `WHERE` clause at all.
- **Admin access.** Approvals, tickets, the knowledge base and analytics need that tenant's admin
  token (from `TENANT_ADMIN_TOKENS`; only SHA-256 hashes are kept). Another tenant's token is
  rejected. Platform operations use `ADMIN_TOKEN`.
- **Identity (demo limit).** The agent trusts the email a person types. A real deployment would
  embed the chat with a customer token signed by the company's site, and `lookup_account` would
  only return that customer. The one-account-per-conversation rule limits the damage meanwhile.

## Knowledge ingestion

Uploads (PDF, Markdown, text, HTML) and public URLs are parsed into pages, stored with status
`processing`, and indexed in a background task (chunk → embed → insert), ending `ready` or
`failed` with the reason. PDF page numbers survive into chunks and citations. Content is
de-duplicated per tenant by hash. URL fetching refuses non-public addresses on every redirect hop
(loopback, private ranges, link-local cloud metadata, IPv4-mapped IPv6), caps size and only
accepts HTML, text and PDF. Retrieved text reaches Claude as `search_result` blocks, and the shared
prompt says it is reference material, never instructions. The structural defence is that the policy
engine and human approval gate every action regardless.

## Evals

- **Retrieval** (`evals/retrieval.py`): hit@1, hit@3, MRR per tenant; CI enforces hit@3 ≥ 0.8
  with the offline embedder.
- **Answers** (`evals/answers.py`): runs each case through `run_turn`, the production path, then
  scores it with deterministic checks (tools called, action proposed or not, escalation,
  citations, gap flag, forbidden text) and a Haiku judge (grounded, expected facts, expected
  behaviour). Red-team cases cover prompt injection in an uploaded document, cross-tenant
  questions, pressure to break policy, and fishing for another person's account.

## Prompt caching note

The system prompt and tools are identical for every conversation of a tenant, and they are cached
with an explicit breakpoint. With steady traffic, both the first and the tool-continuation calls
of a turn read the cache. From a fully cold cache, the API's cache diagnostics report the
continuation call of the *first* turn as `messages_changed` and it re-writes the prefix. That
appears to be server-side rendering of tool continuations, not something request code changes
(tested without fallbacks, without automatic caching, and with delays).
