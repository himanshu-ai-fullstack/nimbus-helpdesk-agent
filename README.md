# HelpDesk Agent Platform

A multi-tenant AI support agent. Each company (tenant) gets its own agent persona, knowledge
base, connected records, approval policies, ticket queue and analytics, isolated in Postgres with
row-level security. Three demo companies show the range:

| Company | Kind | The agent can | Needs human approval |
|---|---|---|---|
| **Nimbus** | Project management SaaS | Answer plan, SSO and billing questions; look up accounts and invoices | Refunds: paid, ≤14 days, ≤$500, never more than what's left on the invoice |
| **Cartwheel** | Online outdoor gear store | Track orders, explain shipping and returns | Return refunds (delivered, ≤30 days, ≤$200) and cancellations (still processing) |
| **Northstar Labs** | Internal IT and HR helpdesk | Answer VPN, device, leave and expense policy questions | Software access, laptop replacements |

**Live demo:** _add your Vercel URL here_

| Pick a company | Cited answer and a refund request awaiting approval |
|---|---|
| ![companies](docs/screenshot-companies.png) | ![chat](docs/screenshot-chat.png) |
| **Uploaded PDF, cited by page** | **Per-tenant analytics** |
| ![pdf citation](docs/screenshot-pdf-citation.png) | ![analytics](docs/screenshot-analytics.png) |

## What it does

- **Answers from the company's own documents, with citations.** Hybrid search (pgvector HNSW +
  Postgres full-text, fused with Reciprocal Rank Fusion) filtered to the tenant. Results go to
  Claude as `search_result` blocks, so answers carry native citations; the UI shows numbered
  source chips that open the quoted passage, with the page number for PDFs.
- **Acts, but only within policy and only with a person's approval.** A policy engine driven by
  each tenant's config checks status, time windows, amount limits and what's already been
  refunded, in code, under a per-record lock. The model can only create a *pending* request.
- **Escalates with a triaged ticket.** Claude Haiku turns the conversation into a validated
  ticket (the tenant's own categories, priority, sentiment, asks, next step).
- **Knows what it doesn't know.** When the knowledge base has no answer, the agent says so and
  flags a knowledge gap; the analytics page lists them so the team knows what to write next.
- **Admins manage their knowledge base.** Upload PDFs, Markdown, text or HTML, or add a public URL.
  Indexing runs in the background; duplicates are rejected; internal URLs are refused.
- **Measured.** Per-tenant dashboard: containment (resolved without a person), answer helpfulness
  from 👍/👎, escalation and approval rates, p50/p95 response time, cost per conversation,
  prompt-cache hit rate, most-cited sources, knowledge gaps, and metrics per config version.
- **Add a company in minutes.** `uv run python -m app.tenants.new acme --name "Acme" --industry "…"`
  scaffolds `tenants/acme/` (persona, prompt, actions, triage, docs, data).

## Architecture

Details and the request flow: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

```
Next.js 16 (Vercel)                     FastAPI (Render)                              Postgres + pgvector (Neon)
┌──────────────────────────┐            ┌───────────────────────────────────┐         ┌──────────────────────────┐
│ /t/<tenant> chat          │  new msg   │ tenant config (YAML, versioned)    │         │ RLS on every tenant table│
│  useChat, cards, sources ─┼──────────▶ │ run_turn: stored history → agent   │ ──────▶ │ documents / chunks       │
│  citations, 👍/👎          │ ◀── SSE ── │  Claude stream ⇄ tools ⇄ policy    │         │ conversations / messages │
│ approvals · tickets       │            │  Connector → company records       │         │ actions / tickets        │
│ knowledge · analytics ────┼─ admin ──▶ │ ingest · triage (Haiku) · metrics  │         │ agent_events / feedback  │
└──────────────────────────┘   token    └───────────────────────────────────┘         └──────────────────────────┘
```

Design decisions:

- **Isolation in the database, not just the code.** Every tenant-owned table has a row-level
  security policy and the app connects as a role that can't bypass it, so a query that forgets its
  tenant filter returns nothing instead of another company's data.
- **The server owns the conversation.** The browser sends only the new message. Tool results the
  model sees are ones the server produced, so they can't be forged from the client.
- **Policy in code, approval by a person.** Prompts are guidance; the policy engine is the
  guardrail. Uploaded documents are treated as reference material, never instructions, and even
  a successful prompt injection can't move money: it can at most create a pending request that a
  person reviews.
- **Connectors, not copies.** The agent reads company records through a `Connector` interface. The
  demo connector serves `data.json`; a real deployment swaps in the company's billing, store or
  HR API without touching the tools or the policy engine.
- **Cost-aware models.** Opus 5.5 for the conversation, Haiku 5.5 for triage and the eval judge,
  prompt caching on the per-tenant system prompt and tools, and a daily spend cap per tenant.
- **FastAPI speaks the AI SDK stream protocol directly**, so the frontend keeps `useChat`'s
  streaming, tool parts and stop button with no Node proxy.

## Run it locally

Prerequisites: Docker, [uv](https://docs.astral.sh/uv/), Node 22, an Anthropic API key, and
optionally an OpenAI API key for embeddings.

```bash
docker compose up -d                       # Postgres 16 + pgvector on :5432

cd api
cp .env.example .env                       # add ANTHROPIC_API_KEY; EMBEDDER=hash works offline
uv sync
uv run python -m app.tenants.seed          # all three demo companies
uv run uvicorn app.main:app --reload       # http://localhost:8000/docs

cd ../web
cp .env.example .env.local
npm install
npm run dev                                # http://localhost:3000
```

Admin pages (approvals, tickets, knowledge, analytics) ask for the tenant's admin token from
`TENANT_ADMIN_TOKENS` in `api/.env`. The example file uses `nimbus-admin`, `cartwheel-admin` and
`northstar-admin`.

## Tests and evals

```bash
cd api
uv run pytest                              # needs Postgres; TEST_DATABASE_URL defaults to localhost:5432/platform_test
uv run python -m evals.retrieval           # hit@1 / hit@3 / MRR per tenant
EVAL_DATABASE_URL=postgresql://app:app@localhost:5432/platform_eval \
  uv run python -m evals.answers           # real model calls, ~$1-2; resets demo data in that database
```

The test suite covers row-level-security isolation (including queries with no tenant filter),
every policy rule for every tenant, forged client history, cross-tenant conversation ids,
SSRF-safe URL ingestion, PDF page citations, the analytics aggregates, and a retrieval-quality
floor per tenant.

The answer eval runs each conversation through the production code path and grades it with
deterministic checks (right tools, action proposed or not, escalation, citations, knowledge-gap
flag, forbidden text) plus a Claude judge for groundedness, expected facts and expected behaviour.
It includes red-team cases: an uploaded document that tries to instruct the agent, questions about
another company, "my manager already approved it", and asking for another person's account.

Latest run ([evals/results/2026-10-26.md](api/evals/results/2026-10-26.md)), Opus 5.5 agent,
Haiku 5.5 judge, offline hash embedder:

| | Cases passed | Red-team | Containment | p95 turn | Cost / conversation | Prompt-cache hits |
|---|---|---|---|---|---|---|
| Nimbus | 9/9 | 3/3 | 89% | 12.9 s | $0.024 | 72% |
| Cartwheel | 5/7 | 1/1 | 100% | 7.5 s | $0.025 | 73% |
| Northstar | 6/7 | 1/1 | 86% | 9.4 s | $0.025 | 73% |
| **All** | **20/23 (87%)** | **5/5** | | | | |

What the eval runs found and changed:
- The agent learned a policy limit only when a request was refused, so it sometimes offered
  refunds above the cap. Each action's rules are now generated from the same config the policy
  engine enforces and put in the tool description; both over-limit refund cases then passed.
- A stalled response stream waited the SDK's default 10 minutes. The client now fails after
  60 s without data and retries, which brought one tenant's p95 from 367 s to 7.5 s.
- An ambiguous record date made the agent hedge on return windows; the tenant prompt now
  says what the date means.

The remaining failures are mostly judge strictness (e.g. "said a person approves it, not IT"),
and which cases fail varies between runs: the Haiku judge at low effort is noisy. A stronger
judge or majority voting is the next improvement to the eval.

## Demo script

1. **Nimbus:** "What's the difference between Pro and Business?" (cited answer), then "I'm
   priya@lumen.example. We added 3 seats by mistake this week, can I get that refunded?" and
   confirm. Approve it under **Approvals** with `nimbus-admin`.
2. **Nimbus:** "arjun@tinyfox.example here. I want a full refund of my annual plan." The $600 is
   blocked by the $500 policy limit, in code; the agent offers to escalate.
3. **Cartwheel:** "Do you ship to Canada?" (no), then ask about Nimbus pricing: the agent only
   knows Cartwheel.
4. **Northstar:** upload a PDF manual under **Knowledge**, then ask about it in chat and open the
   page-numbered citation.
5. **Analytics:** containment, helpfulness, cost per conversation, cache hits and knowledge gaps.

## Known limits

- Identity isn't verified: the agent trusts the email a person types. One conversation can only
  access one account, which limits fishing, but production needs the host site to pass a signed
  customer token (next step below).
- Admin access is a per-tenant shared token, not user accounts and roles.
- URL ingestion checks DNS before connecting, so DNS rebinding isn't fully closed.
- Scanned PDFs without a text layer aren't OCR'd.

## Next steps

- Embeddable chat widget for a company's own site, with signed customer identity
- MCP connector so a tenant can plug in its real systems
- Webhooks (Slack, email) when a ticket or approval request is created
- OpenTelemetry traces from the agent events
- A less noisy answer-eval judge (stronger model or majority vote)

## Deploy

1. **Database:** a [Neon](https://neon.tech) project (pgvector is built in). The API creates the
   schema, the runtime role and the RLS policies on startup.
2. **API:** a Render Blueprint from `render.yaml`. Set `DATABASE_URL`, `ANTHROPIC_API_KEY`,
   `OPENAI_API_KEY` (or `EMBEDDER=hash`), `CORS_ORIGINS` and `TENANT_ADMIN_TOKENS`. Seed once with
   `curl -X POST https://<api>/api/admin/reset -H "x-admin-token: <ADMIN_TOKEN>"`.
3. **Web:** import the repo on [Vercel](https://vercel.com) with root directory `web` and
   `NEXT_PUBLIC_API_URL=https://<api>.onrender.com`.
