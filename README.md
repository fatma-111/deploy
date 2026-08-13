<div align="center">

<img src="frontend/web/assets/img/logo.svg" width="64" alt="BugHound" />

# BugHound

**AI Bug Investigation Agent** — hands it an error, it comes back with the root cause,
a grounded fix, an independent review and a static validation pass. Repeated errors are
answered from a local knowledge base instead of calling a model at all.

Multi-agent orchestration on LangGraph or CrewAI · Local RAG for known errors · No database
No paid APIs · Deploys free on Railway

</div>

---

## What it does

You paste an error, a stack trace, some logs and optionally the source. First, a local
knowledge base is checked — if this kind of error has been seen before, the answer comes
back immediately with **no model call at all**. Otherwise, six agents work the case:

| Agent | Job |
|---|---|
| **Debug** | Parses the failure: error type, affected file and function, suspected packages, what information is missing |
| **Research** | Collects evidence from official docs, the public GitHub API, GitHub issues, release notes, PyPI and npm — then scores each source instead of trusting the ranking |
| **Root Cause** | Names the mechanism and puts a calibrated confidence on it |
| **Fix** | Produces a minimal unified diff, grounded in the evidence |
| **Code Reviewer** | An independent, deliberately sceptical pass. Approves or rejects with required changes |
| **Validation** | Static checks only: syntax, imports, dependency pins, security scan. Your code is never executed |

The intelligence is in three conditional edges:

```
START → validate_input → knowledge_base_agent
                              │ hit (no model call)      │ miss
                              ▼                          ▼
                       validation_agent            debug_agent → research_agent → root_cause_agent
                              ▲                                       ▲                │
                              │                                       │        confidence gate
                              │                     LOW (max 2 loops) ┘         /            \
                              │                                                ▼              ▼
                              │                                         research_agent    fix_agent
                              │                                                               │
                              │                                                         code_reviewer
                              │                                                         /           \
                              │                                       REJECTED (max 2 retries)    APPROVED
                              │                                                │                     │
                              │                                            fix_agent                 │
                              └───────────────────────────────────────────────────────────────────────┘
                                                                            ▼
                                                                     compose_report → END
                                                          (a fresh, approved, high-confidence
                                                           result is learned for next time)
```

Below the confidence threshold the case goes back for more research rather than guessing.
A rejected fix goes back to the Fix Agent with concrete required changes. All loops are
capped, so the graph always terminates.

## Repeated errors skip the model

`data/error_knowledge_base.pdf` is a real PDF — 32 common error patterns across Python,
FastAPI, LangChain, JavaScript/Node.js, Docker and deployment, each with a root cause, a fix,
and a patch template where one makes sense. It's not decorative documentation: the app
extracts its text at build time (`scripts/build_knowledge_index.py`, via `pdfplumber`) and
indexes it for retrieval. Edit `data/error_knowledge_seed.py` and re-run
`build_knowledge_pdf.py` + `build_knowledge_index.py` to add more entries.

Retrieval is TF-IDF + cosine similarity (`scikit-learn`), held entirely in memory — no
embedding model, no GPU, no network call, no vector database service. It's the "in-memory
vector store" option this project's own RAG-decision section always allowed, just actually
built now that there's a concrete need for it.

When a new error is investigated and the pipeline approves a fix with confidence at or above
`KB_LEARN_MIN_CONFIDENCE` (default 0.80), that result is saved to `data/learned_cases.jsonl`
— a flat, append-only file, not a database engine — so the next occurrence of that error is
answered instantly too. Confidence on a served match is always reported honestly below what a
fresh diagnosis could reach, and every report says plainly when it came from the cache instead
of a live analysis.

```bash
KB_ENABLED=true                  # default
KB_MATCH_THRESHOLD=0.55          # cosine similarity required to serve from cache
KB_LEARNING_ENABLED=true         # save fresh, approved, high-confidence results
KB_LEARN_MIN_CONFIDENCE=0.80
KB_MAX_LEARNED_ENTRIES=500       # oldest entries are pruned past this cap
```

`GET /api/knowledge-base/stats` — or the **Knowledge base** view in the dashboard, which
includes a live search box — shows what's currently indexed and lets you preview whether a
given error would hit the cache before running a full investigation.

This is the one deliberate exception to the project's original "no persistent memory"
design: the entire point of the feature is to remember. Nothing else changed — still no SQL,
no ORM, no server-based database, no vector database service.

## Two orchestrators, one switch

The same knowledge-base check, the same six agents, the same tools, the same report — driven
by either engine:

```bash
ORCHESTRATOR=langgraph   # default
ORCHESTRATOR=crewai      # pip install -r requirements-crewai.txt first
```

Everything above `app/services/orchestrator.py` is unaware of which one ran, so
switching is a variable rather than a rewrite. `GET /api/health` reports the requested
backend, the active one, and why they differ if they do.

| | LangGraph | CrewAI |
|---|---|---|
| Extra dependencies | none | `crewai` (pulls chromadb + onnxruntime, ~880 MB installed) |
| Runs without an API key | yes, heuristic mode | no — agents need a model |
| Conditional routing | `add_conditional_edges` | Python controller between two crews |
| Loop caps | enforced in the routers | enforced in the controller |

**How the CrewAI version is structured.** `Process.sequential` runs each task exactly once,
so a single crew cannot express the confidence gate or the reviewer's rejection loop — and
those two branches are the substance of the system. Instead there are two classic crews:

- **DiagnosisCrew** — debug → research → root cause, re-run while confidence is below the
  threshold, capped by `MAX_RESEARCH_ITERATIONS`
- **RemediationCrew** — fix → independent review, re-run while the review rejects, capped by
  `MAX_FIX_RETRIES`

with a thin deterministic controller owning the routing between them.

**Every crew sets `memory=False`.** CrewAI's memory backend is ChromaDB, and this project
promises no database. The dependency ships either way, but nothing ever writes to it.

The CrewAI backend cannot run heuristically, so with no API key the dispatcher falls back to
LangGraph and logs why, rather than failing the request.

## Quick start

```bash
git clone <your-repo-url> && cd bughound
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # add OPENROUTER_API_KEY (free key, free models)
uvicorn app.main:app --reload
```

Open **http://localhost:8000** for the dashboard, or **/api/docs** for the API.

Want the Streamlit client instead?

```bash
streamlit run frontend/streamlit_app.py
```

### Free models rotate — the app handles it

Every free model ID on OpenRouter is temporary. Providers add, pull and reprice
them weekly, and an ID that works today will return `404 No endpoints found`
soon enough. BugHound treats that as normal:

1. It tries `OPENROUTER_MODEL`, then each entry in `OPENROUTER_FALLBACK_MODELS`.
2. If those are gone, it queries OpenRouter's public catalog, filters for models
   priced at zero with a usable context window, and appends them to the chain.
3. If everything fails, the error names the dead models and points at
   `/api/models/free` instead of failing silently.

`GET /api/models/free` — or the **Runtime** view in the dashboard — shows what is
live right now and flags any configured ID that no longer exists.

### Using OpenAI instead of the default

BugHound talks to any OpenAI-compatible endpoint, so switching providers is configuration,
not code.

| Goal | Configuration |
|---|---|
| An OpenAI model, still free | `OPENROUTER_MODEL=openai/gpt-oss-120b:free` — open-weight, 131k context, strong on code |
| OpenAI directly (**paid**) | `LLM_BASE_URL=https://api.openai.com/v1`, `LLM_API_KEY=sk-...`, `OPENROUTER_MODEL=gpt-5.6-luna` |
| Local Ollama / LM Studio | `LLM_BASE_URL=http://localhost:11434/v1`, `LLM_API_KEY=ollama` |

`LLM_BASE_URL` and `LLM_API_KEY` override the OpenRouter settings when present. Free-model
discovery turns itself off automatically for non-OpenRouter endpoints, since no other
provider publishes that catalog.

Going direct to OpenAI means the project no longer meets its own free-tier constraint. An
investigation makes 5–8 model calls, so budget accordingly.

### It runs without a key

With no `OPENROUTER_API_KEY`, BugHound drops into heuristic mode: deterministic stack-trace
parsing plus real web and GitHub research, with an honest low confidence and a clear note in
the report. Useful for demos, and it is how the test suite runs.

## Configuration

Everything lives in environment variables. See `.env.example` for the full list.

| Variable | Default | Notes |
|---|---|---|
| `OPENROUTER_API_KEY` | — | Free key from openrouter.ai/keys |
| `OPENROUTER_MODEL` | `poolside/laguna-s-2.1:free` | Verified free 2026-08-13 |
| `OPENROUTER_FALLBACK_MODELS` | 3 free models | Tried in order when the primary fails |
| `MODEL_DISCOVERY_ENABLED` | `true` | Appends currently-free models from OpenRouter's catalog to the chain |
| `OPENROUTER_FAST_MODEL` | primary | Cheaper model for the Debug and Research agents |
| `CONFIDENCE_THRESHOLD` | `0.80` | Below this, the case returns to research |
| `MAX_RESEARCH_ITERATIONS` | `2` | Hard cap on the research loop |
| `MAX_FIX_RETRIES` | `2` | Hard cap on the fix/review loop |
| `GITHUB_TOKEN` | — | Optional. Anonymous is 60 req/h, a token gives 5000 |
| `DEMO_MODE` | `false` | Force heuristic mode even with a key |

## Cost

| Tier | What |
|---|---|
| **Free / required** | Python, FastAPI, LangGraph, DuckDuckGo HTML search, public GitHub API, PyPI, npm, OpenRouter free models |
| **Free / optional** | `GITHUB_TOKEN` for higher rate limits, Railway free allowance |
| **Paid / not required** | Tavily, SerpAPI, Bing, Perplexity, Exa, any database, any vector database |

Nothing in the MVP requires a paid service.

## API

```
GET    /health                     Railway health check
GET    /api/health                 Detailed status
POST   /api/investigate            Full investigation, returns the report
POST   /api/investigate/stream     Server-sent events, one per completed node
GET    /api/samples                Benchmark bugs
GET    /api/models/free            What OpenRouter is serving free right now
GET    /api/knowledge-base/stats   Seed vs learned counts, framework breakdown
GET    /api/knowledge-base/search  Preview a match without running an investigation
GET    /api/knowledge-base/entries Every indexed entry (seed + learned)
GET    /api/dashboard/metrics      Rolling in-process counters + cache-hit rate
DELETE /api/dashboard/metrics      Clear them
```

```bash
curl -X POST localhost:8000/api/investigate \
  -H 'Content-Type: application/json' \
  -d '{
    "error_message": "ModuleNotFoundError: No module named '\''langchain.chat_models'\''",
    "source_code": "from langchain.chat_models import ChatOpenAI",
    "language": "Python",
    "dependencies": ["langchain==0.3.7"]
  }'
```

## Security

The system reads untrusted input by design: error messages, logs, source code, web pages
and GitHub content.

- **Prompt injection** — every external block is wrapped in an `untrusted-data` envelope with
  an explicit instruction that its contents are data, never orders.
- **SSRF** — all outbound requests pass one hardened client. Blocked: non-HTTP schemes,
  `localhost`, loopback, link-local (including `169.254.169.254`), private ranges, `.internal`
  and `.local`. DNS is resolved and every returned address is checked, so rebinding through a
  public hostname does not get through.
- **Code execution** — none. Validation uses `ast.parse`, which builds a tree without running
  anything. Executing a patch would need a sandbox that Railway's free tier cannot provide, so
  it is explicitly a V2 feature.
- **Secrets** — environment variables only. `.env` is git-ignored; only `.env.example` ships.
- **Resource limits** — caps on input size, tool timeouts, LLM timeouts, output tokens,
  research loops and fix retries.
- **Hallucinated sources** — the Research Agent's output is filtered against the URLs that
  were actually fetched, so a model cannot invent a citation.

## No database

There is no PostgreSQL, SQLite, MongoDB, Redis, ORM, migration or LangGraph checkpointer.
State exists for the duration of one graph execution and is then discarded. The dashboard's
live feed is a bounded in-memory `deque` in the API process: it is not shared between workers
and it is empty again after a restart.

## Deploy to Railway

1. Push to GitHub.
2. Railway → New Project → Deploy from GitHub repo. It detects the `Dockerfile`.
3. Add `OPENROUTER_API_KEY` (and optionally `GITHUB_TOKEN`) under Variables.
4. Railway injects `PORT`; the container already binds `0.0.0.0:$PORT`.
5. Health check is configured at `/health` in `railway.json`.

One container serves both the API and the dashboard, which keeps the free allowance going as
far as possible. Streamlit is a separate optional service — point it at the API with
`BUGHOUND_API_URL`.

```bash
docker build -t bughound . && docker run --rm -p 8000:8000 --env-file .env bughound
```

## Tests

```bash
pytest -q      # 83 tests (93 with the CrewAI extra installed), no network, no API key
```

Outbound calls and the LLM are stubbed in `conftest.py`, so the suite covers input validation,
SSRF blocking, static validation, both routers and their caps, deterministic parsing, the full
graph end to end, the graph's structure (no node name may collide with a state key — LangGraph
rejects that at compile time), the knowledge base (retrieval, learning, pruning, and the
short-circuit in both orchestrators), and the HTTP contract.

## Project layout

```
app/
  agents/     six agents, each a pure function: state in, Pydantic model out
  graph/      nodes.py (state updates + routers), graph.py (the LangGraph)
  crew/       optional CrewAI backend: agents.py, tools.py, orchestrator.py
  tools/      http_client.py (SSRF guard), web_search, github, documentation, validation
  services/   llm.py, orchestrator.py (backend dispatcher), model_catalog.py,
              report.py, activity.py, samples.py
  models/     schemas.py — every contract in the system
  state/      state.py — the typed graph state, field by field
  config/     settings.py — one place for every knob
  api/        routes.py
frontend/
  web/        the dashboard: one HTML file, one CSS file, one JS file, no build step
  streamlit_app.py
data/
  error_knowledge_seed.py    the single source of truth for seed entries
  error_knowledge_base.pdf   generated from it — the real ingestion source
  knowledge_base_seed.json   extracted from the PDF, loaded at runtime
  learned_cases.jsonl        appended to at runtime, git-ignored
scripts/
  build_knowledge_pdf.py     seed data -> PDF
  build_knowledge_index.py   PDF -> JSON (re-extracts the text, doesn't trust the seed directly)
tests/
implementation-plan.md
```

## What is deliberately not here

Sandboxed test execution, GitHub PR generation, automatic patch application, CI integration,
accounts, private-docs RAG.

RAG for known error *patterns* is now included (see above) — that's a narrow, deliberate
addition, not a general document-retrieval system. What's still excluded is RAG over live
package documentation: the corpus that matters there is documentation of packages that change
weekly, so live retrieval beats an index that goes stale the moment it's built. See
`implementation-plan.md`
for the reasoning and the V2 design.
