# BugHound — Implementation Plan

**AI Bug Investigation Agent.** Multi-agent orchestration on LangGraph. Stateless, free-first,
Railway-ready, security-conscious.

This document is the build specification. Every architectural decision is resolved: where more
than one option existed, one was chosen and the reason is stated. A coding agent should be able
to implement the whole system from this file without redesigning anything.

The reference implementation in this repository follows the plan exactly, so each phase also
notes the files that realise it.

---

## 0. Decisions taken up front

| Question | Decision | Why |
|---|---|---|
| Orchestration | LangGraph `StateGraph` with two conditional edges, **default**; CrewAI available behind `ORCHESTRATOR=crewai` | The confidence gate and the review gate are real branches with loops; a sequential chain cannot express them. Both engines implement one contract so the choice is a variable |
| CrewAI shape | Two classic sequential crews + a deterministic Python controller | `Process.sequential` runs each task once, so one crew cannot express either loop. Crews as units of work, Python owning the routing, keeps the CrewAI idiom and the behaviour |
| CrewAI memory | `memory=False` on every crew | CrewAI's memory backend is ChromaDB, and the no-database constraint is non-negotiable |
| CrewAI dependency | Optional, in `requirements-crewai.txt` | It pulls chromadb and onnxruntime, taking the install from ~150 MB to ~880 MB. The default image stays slim |
| State schema | `TypedDict` (`InvestigationState`) | A plain `dict` schema gives last-value semantics for the whole state, so partial node updates overwrite each other and counters never increment. A `TypedDict` gives one channel per key. **This is the single most important implementation detail in the project** |
| Node naming | No node may share a name with a state key | LangGraph raises `'<name>' is already being used as a state key` at `add_node`. The report node is therefore `compose_report`, while the key it writes is `final_response`. Guarded by `tests/test_graph_structure.py` |
| Persistence | None. No checkpointer | The spec forbids a database; a checkpointer is persistence by another name |
| LLM provider | OpenRouter via `langchain-openai`'s OpenAI-compatible client | One key, many free models, drop-in interface |
| Model strategy | Configurable primary + ordered fallback chain + **live discovery** from OpenRouter's public catalog | Free models appear and disappear weekly, so any hard-coded ID eventually 404s. Discovery is what makes the free tier survivable |
| Structured output | Prompt-enforced JSON + Pydantic validation + one repair round-trip | Free models are inconsistent with native tool-calling; a compact schema in the prompt plus a repair pass is more reliable and cheaper |
| Web search | DuckDuckGo HTML endpoint | Keyless, no quota, no signup. Tavily/SerpAPI/Bing/Exa are all excluded |
| GitHub | Public REST API, anonymous by default | 60 req/h is enough for the MVP; `GITHUB_TOKEN` is optional and only raises limits |
| Package facts | PyPI and npm registry JSON | Free, keyless and authoritative for "what version exists and what moved" |
| Validation | Static only | Executing untrusted patches on Railway is unacceptable. `ast.parse` analyses without running |
| RAG | Not in MVP | See §29 |
| UI | A bundled zero-build dashboard served by FastAPI, plus a Streamlit client | One container on the free tier; Streamlit stays available as the spec requires |
| Deployment | Single Docker container on Railway | Simplest thing that fits the free allowance |

---

## 1. Architecture

```
                              ┌──────────────┐
                              │    Client    │  dashboard · Streamlit · curl
                              └──────┬───────┘
                                     │ HTTP / SSE
                              ┌──────▼───────┐
                              │   FastAPI    │  /health /api/investigate
                              └──────┬───────┘
                                     │
                              ┌──────▼───────┐
                              │   LangGraph  │  typed state, 2 conditional edges
                              └──────┬───────┘
              ┌──────────┬───────────┼───────────┬──────────┐
              ▼          ▼           ▼           ▼          ▼
           Debug     Research    Root Cause     Fix      Reviewer → Validation
              │          │           │           │          │
              └──────────┴─────┬─────┴───────────┴──────────┘
                               ▼
                    ┌──────────────────────┐
                    │        Tools         │
                    │ web · github · docs  │
                    │ registries · static  │
                    └──────────┬───────────┘
                               ▼
                    ┌──────────────────────┐
                    │  Hardened HTTP client │  SSRF guard, timeouts, size caps
                    └──────────────────────┘
```

Nothing writes to disk. Nothing survives the request.

---

## 2. Repository layout

```
bughound/
├── app/
│   ├── agents/          debug · research · root_cause · fix · reviewer · validation
│   ├── graph/           nodes.py · graph.py
│   ├── state/           state.py
│   ├── tools/           http_client.py · web_search.py · github.py · documentation.py · validation.py
│   ├── prompts/         debug · research · root_cause · fix · reviewer
│   ├── models/          schemas.py
│   ├── services/        llm.py · report.py · activity.py · samples.py
│   ├── config/          settings.py
│   ├── api/             routes.py
│   └── main.py
├── frontend/
│   ├── web/             index.html · assets/{css,js,img}
│   └── streamlit_app.py
├── tests/
├── .env.example · .gitignore · requirements.txt
├── Dockerfile · docker-compose.yml · railway.json · Makefile
├── README.md · implementation-plan.md
```

---

## 3. LangGraph state

`app/state/state.py`. Every field, who writes it and who reads it:

| Field | Type | Written by | Read by |
|---|---|---|---|
| `investigation_id` | str | entry point | response, logs |
| `started_at` | float | entry point | duration reporting |
| `error_message` | str | input | every agent |
| `stack_trace` | str? | input | debug, root cause |
| `logs` | str? | input | debug |
| `source_code` | str? | input | debug, root cause, fix, reviewer |
| `repository_url` | str? | input, cleared by `validate_input` if unsafe | research |
| `language`, `framework`, `environment` | str? | input | all |
| `dependencies` | list[str] | input | debug, research, fix, validation |
| `debug_analysis` | dict? | `debug_agent` | research, root cause, fix |
| `research` | dict? | `research_agent` (accumulates) | root cause, fix, reviewer, report |
| `research_iterations` | int | `research_agent` | `confidence_router` |
| `root_cause` | dict? | `root_cause_agent` | fix, reviewer, report |
| `confidence` | float | `root_cause_agent` | `confidence_router`, report |
| `proposed_fix` | dict? | `fix_agent` | reviewer, validation, report |
| `review_result` | dict? | `code_reviewer` | `review_router`, fix retry, report |
| `review_iterations` | int | `code_reviewer` | `review_router` |
| `validation_result` | dict? | `validation_agent` | report |
| `citations` | list[dict] | `compose_report` | response |
| `trace` | list[dict] | every node | UI, response |
| `warnings` | list[str] | any node | report, response |
| `status` | str | `validate_input`, `compose_report` | response |
| `final_response` | str | `compose_report` | UI |

`trace` entries are public stage records: node, label, status, duration, one-line detail.
They never carry chain-of-thought.

---

## 4. Nodes and routers

`app/graph/nodes.py`. Each node returns a **partial** state update and never raises: on failure
it appends a warning and lets the graph continue, so the user always gets a report.

| Node | Input | Output | Failure behaviour |
|---|---|---|---|
| `validate_input` | raw input | cleaned input, warnings, status | Empty error → status `failed`, routed straight to `final_response` |
| `debug_agent` | raw input | `debug_analysis` | Falls back to the deterministic parser |
| `research_agent` | debug analysis, prior research | `research`, `research_iterations` | Empty result set with `degraded=true` |
| `root_cause_agent` | debug + research + code | `root_cause`, `confidence` | Confidence 0.0 with an explanatory summary |
| `fix_agent` | root cause + evidence + code + reviewer feedback | `proposed_fix` | Empty patch, risk HIGH |
| `code_reviewer` | fix + root cause + evidence | `review_result`, `review_iterations` | REJECTED with the error as the reason |
| `validation_agent` | patch | `validation_result` | SKIPPED when there is no patch |
| `compose_report` | everything | `citations`, `status`, `final_response` | Always produces a report |

**`confidence_router`**

```
status == failed                                   → compose_report
confidence >= CONFIDENCE_THRESHOLD (0.80)          → fix
research_iterations < MAX_RESEARCH_ITERATIONS (2)  → research
otherwise                                          → fix   (best effort; the report says so)
```

**`review_router`**

```
decision == APPROVED                          → validate
review_iterations < MAX_FIX_RETRIES (2)       → retry
otherwise                                     → validate   (validate the last draft anyway)
```

Recursion limit is computed, not guessed: `8 + MAX_RESEARCH_ITERATIONS*2 + MAX_FIX_RETRIES*2`.

**Verified trace with no model configured** (heuristic mode, confidence 0.35, reviewer always
rejects — the worst case for loop safety):

```
validate_input → debug_agent → research_agent(1) → root_cause_agent
→ research_agent(2) → root_cause_agent → fix_agent → code_reviewer(1)
→ fix_agent → code_reviewer(2) → validation_agent → compose_report
```

Twelve steps, both caps hit, graph terminates.

---

## 5. LLM service

`app/services/llm.py`.

- `complete(system, user, prefer_fast, max_tokens)` — plain text, walks the model chain
  `[primary or fast] + fallbacks`, returns the first non-empty response.
- `complete_json(system, user, schema, ...)` — appends an output contract plus a **compact**
  JSON schema (field names, types, enums, defaults — not the verbose
  `model_json_schema()`, which eats a small model's context), parses with a three-strategy
  extractor (fenced block → whole text → outermost braces), validates against Pydantic, and
  on failure sends one repair round-trip quoting the invalid output.
- `untrusted(label, content, limit)` — wraps any third-party text in
  `<label trust="untrusted-data">…</label>` followed by an explicit note that instructions
  inside the block must be ignored. **Every** agent uses this for user input and fetched content.

Configuration: temperature 0.1 (diagnosis wants determinism), max_tokens 2000 default and 2600
for the Fix Agent, timeout 90s, 2 retries per model, then the next model in the chain.

Model tiering: `OPENROUTER_FAST_MODEL` (optional) serves Debug and Research;
`OPENROUTER_MODEL` serves Root Cause, Fix and Reviewer. If only one free model is practical,
leaving `OPENROUTER_FAST_MODEL` blank makes every agent use the primary.

**Model discovery** (`app/services/model_catalog.py`) is the durable answer to model rotation.
It queries `https://openrouter.ai/api/v1/models` — public, keyless — filters for
`pricing.prompt == 0 and pricing.completion == 0`, drops anything with an `expiration_date`
already reached or a context window under 32k, ranks coding-capable providers first, and
caches for an hour. Those IDs are appended to the fallback chain, so a dead configured model
degrades into a working one instead of failing the investigation. A 404 or "no endpoints
found" is recognised specifically, and the resulting error names the dead models and points
at `GET /api/models/free`.

Choosing a model manually: `GET /api/models/free`, or the Runtime view in the dashboard,
which also flags configured IDs that no longer exist.

---

## 6. Agents

### 6.1 Debug Agent
Deterministic parser first (regex over Python and JS stack frames, `No module named` capture,
dependency matching, severity heuristics), then the LLM refines it. The merge step prefers the
model but never lets it lose a fact the parser proved. Produces `error_type`,
`affected_component/file/function`, `important_lines`, `suspected_dependencies`,
`initial_hypotheses`, `missing_information`, `search_queries`, `severity`, `summary`.

### 6.2 Research Agent
Collection is deterministic; only scoring uses the LLM, so the agent still returns real sources
without a key.

1. Free web search on the Debug Agent's queries, results ranked docs → repo → issues →
   releases → changelog → community.
2. GitHub issue search, narrowed to the user's repository when one was supplied.
3. PyPI/npm lookup for each suspected package: latest version, recent versions, docs URL.
4. Release notes from each package's own repository.

The LLM then scores and summarises. **Hallucinated URLs are filtered out** by intersecting the
model's results with the set actually fetched. Results merge with previous passes and
de-duplicate, so a second research loop adds rather than replaces.

### 6.3 Root Cause Agent
Receives debug analysis, the evidence table, source and environment. Produces `root_cause`,
calibrated `confidence`, `evidence`, `alternative_hypotheses`, `reasoning_summary` (public,
max 4 sentences), `recommended_direction`, `missing_information` — the last of which feeds the
next research pass as extra queries. The prompt gives explicit confidence bands and states that
low confidence is a useful answer, which is what makes the gate meaningful.

### 6.4 Fix Agent
Receives the root cause, evidence, source, dependencies and — on a retry — the reviewer's
required changes and the previous patch. Produces `explanation`, `recommended_fix`, unified
diff `patch`, `dependency_changes` (pinned), `configuration_changes`, `migration_steps`,
`alternative_fix`, `assumptions`, `risk`. The prompt forbids inventing APIs, packages, versions
and config keys, and requires uncertainty to be declared in `assumptions`.

### 6.5 Code Reviewer
A separate agent with an adversarial prompt, ideally a different model. Assesses correctness,
compatibility, security, dependency versions, API changes, breaking changes, regression risk,
edge cases and quality. Post-processing keeps decision and score consistent, forces a rejection
when the patch is empty, and guarantees a rejected review carries at least one concrete
required change — vague feedback would waste the retry budget.

### 6.6 Validation Agent
Static only, no model. Checks: unified-diff shape, `ast.parse` of the added lines, import
analysis against declared dependencies, dangerous-construct scan (`eval`, `exec`, `os.system`,
`shell=True`, `pickle.loads`, `verify=False`), dependency pin consistency. Statuses fold to
FAILED > WARNING > PASSED > SKIPPED.

---

## 7. Tools

All tools take Pydantic-typed input, return typed output, and return `None` or an empty list on
failure rather than raising.

| Tool | Purpose | Timeout | Security |
|---|---|---|---|
| `fetch_text` / `fetch_json` | All outbound HTTP | `TOOL_TIMEOUT_SECONDS` (15) | SSRF guard, 3 redirects max, size cap, binary rejected |
| `search_web` | Keyless DuckDuckGo search | 15s | Result URLs re-validated before fetching |
| `search_repositories` / `search_issues` / `get_readme` / `get_file` / `get_latest_releases` | GitHub | 15s | Anonymous by default |
| `pypi_package` / `npm_package` / `inspect_dependency` | Registry facts | 15s | Name sanitised before use in the path |
| `fetch_documentation` | Doc page → readable text | 15s | Tag stripping without a heavy parser |
| `validate_patch` | Static analysis | n/a | Never executes |

**SSRF guard** (`assert_safe_url`): scheme must be http/https; host must not be `localhost`,
`.local` or `.internal`; the host is resolved and **every** returned address is checked against
loopback, link-local (`169.254.0.0/16`, which covers cloud metadata), private, CGNAT and IPv6
ULA ranges. Resolving before checking is what stops DNS rebinding through a public hostname.

---

## 8. Security requirements

1. **Prompt injection** — untrusted envelopes on all external text; system instructions never
   accept overrides from data.
2. **SSRF** — as above, one enforcement point.
3. **Secrets** — environment variables only; `.env` git-ignored; secrets never logged, never
   returned by the API, never placed in a prompt.
4. **Arbitrary code execution** — none, anywhere, in the MVP.
5. **Resource abuse** — input caps (error 4k, trace 20k, logs 20k, source 30k, deps 60),
   tool timeouts, LLM timeouts, output token caps, capped research and fix loops, computed
   recursion limit.
6. **Output hygiene** — the report renderer emits only whitelisted fields; chain-of-thought is
   never stored and never rendered.
7. **Container** — non-root user, slim base, no build tools in the final image.

---

## 9. API

```
GET    /health                    { status }                        Railway health check
GET    /api/health                config summary, no secrets
POST   /api/investigate           InvestigationRequest → InvestigationResponse
POST   /api/investigate/stream    SSE: {type: stage|result|error|done}
GET    /api/samples               benchmark bugs
GET    /api/dashboard/metrics     rolling in-process counters + feed
DELETE /api/dashboard/metrics     clear them
```

Request: `error_message` required; `stack_trace`, `logs`, `source_code`, `language`,
`framework`, `repository_url`, `dependencies`, `environment` optional. Over-long fields are
truncated, not rejected.

Response: status, error type, severity, root cause, confidence, debug analysis, research
report, alternatives, proposed fix, review, validation, citations, risk, trace, warnings,
duration, demo flag, rendered report. No internal reasoning.

---

## 10. Frontend

**Dashboard** (`frontend/web/`) — one HTML file, one CSS file, one JS file, no build step, no
CDN dependency beyond fonts. Charts are hand-drawn SVG so the page works offline. Views:
Dashboard (KPIs, confidence-over-time line chart with the gate drawn on it, error-type donut,
live feed, agent notes), New investigation (form + sample loader + **the live pipeline rail**,
which lights up node by node from the SSE stream and marks a step as looped when the graph
revisits it), Bug traffic, Agent graph, Evidence & sources, Runtime.

**Streamlit** (`frontend/streamlit_app.py`) — the spec-required client. Talks to the API and
falls back to running the graph in-process, so `streamlit run` works on its own. Tabs: Report,
Stages, Sources, Raw JSON.

Neither UI displays chain-of-thought.

---

## 11. Implementation phases

Each phase lists objective, files, dependencies, tasks, expected output, tests and acceptance.

### Phase 1 — Project setup
**Objective** Runnable skeleton.
**Create** repo tree, `requirements.txt`, `.gitignore`, `.env.example`, `Makefile`.
**Tasks** Pin the dependency set below; create every package with `__init__.py`.
**Dependencies** `fastapi`, `uvicorn[standard]`, `pydantic`, `pydantic-settings`,
`python-dotenv`, `httpx`, `langgraph`, `langchain-core`, `langchain-openai`, `streamlit`,
`pytest`. Nothing else without justification.
**Expected** `pip install -r requirements.txt` succeeds.
**Tests** — **Accept** Tree matches §2; `.env` is ignored by git.

### Phase 2 — Configuration
**Objective** One typed source of truth for every knob.
**Create** `app/config/settings.py`.
**Tasks** `BaseSettings` with aliases for all variables in `.env.example`; derived properties
`fallback_models`, `fast_model`, `cors_origins`, `llm_available`, `effective_demo_mode`;
`lru_cache`d accessor.
**Expected** Importing `settings` anywhere gives validated config.
**Tests** Defaults load with no `.env`; `effective_demo_mode` is true when the key is empty.
**Accept** No literal secret anywhere in the source.

### Phase 3 — State and schemas
**Objective** Typed contracts.
**Create** `app/models/schemas.py`, `app/state/state.py`.
**Tasks** Enums (severity, source type, review decision, validation status, risk, investigation
status); `InvestigationRequest` with truncating validators; one model per agent output;
`InvestigationResponse`; `InvestigationState` as a `TypedDict` with `initial_state()` zeroing
the counters.
**Expected** Every inter-component contract is a Pydantic model or a TypedDict field.
**Tests** `tests/test_schemas.py` — required field, truncation, dependency cleaning, clamping.
**Accept** Over-long input truncates rather than 500s; scores clamp to range.

### Phase 4 — LLM service
**Objective** Reliable structured output from free models.
**Create** `app/services/llm.py`. **Depends on** Phases 2–3.
**Tasks** Model chain, `complete`, `complete_json` with compact schema + repair pass, JSON
extractor, `untrusted()` helper, `LLMUnavailable`.
**Expected** `complete_json` returns a validated model or raises exactly one typed error.
**Tests** Extractor handles fenced, bare and prose-wrapped JSON (mock the client);
`tests/test_model_catalog.py` covers free/paid filtering, expiring models, context floor,
ranking, caching, an unreachable catalog, chain extension and the discovery off-switch.
**Accept** No agent imports `langchain_openai` directly.

### Phase 5 — Debug Agent
**Objective** Structured triage that works without a model.
**Create** `app/prompts/debug.py`, `app/agents/debug_agent.py`. **Depends on** Phase 4.
**Tasks** `heuristic_analysis()` (Python and JS frames, module capture, severity, query
generation, missing-info detection); LLM refinement; `_merge()` preferring the model but
retaining proven facts.
**Expected** `DebugAnalysis` in every path.
**Tests** `tests/test_debug_agent.py` — ModuleNotFoundError, KeyError with no trace, JS frame.
**Accept** Correct `error_type` and `affected_file` with the key unset.

### Phase 6 — Research tools
**Objective** Free, safe evidence collection.
**Create** `app/tools/http_client.py`, `web_search.py`, `github.py`, `documentation.py`.
**Tasks** SSRF guard; `fetch_text`/`fetch_json`; `html_to_text`; DuckDuckGo parser with
redirect unwrapping and source classification; GitHub repo/issue/readme/file/release helpers;
PyPI and npm lookups.
**Expected** Every tool returns empty rather than raising.
**Tests** `tests/test_url_safety.py` — the full blocklist; public HTTPS allowed.
**Accept** With the network stubbed out, no tool raises.

### Phase 7 — Research Agent
**Objective** Judged evidence, not a link dump.
**Create** `app/prompts/research.py`, `app/agents/research_agent.py`. **Depends on** Phase 6.
**Tasks** Four-source collection; LLM scoring; **URL whitelist filter**; merge with previous
passes; `degraded` flag.
**Expected** `ResearchReport` with de-duplicated, ranked results.
**Tests** Degrades to an empty report when every source fails.
**Accept** A model cannot introduce a URL that was not fetched.

### Phase 8 — Root Cause Agent
**Objective** A cause and an honest confidence.
**Create** `app/prompts/root_cause.py`, `app/agents/root_cause_agent.py`.
**Tasks** Assemble debug + evidence + code + environment; explicit confidence bands in the
prompt; deterministic low-confidence fallback with no model.
**Expected** `RootCauseAnalysis`, confidence in [0,1].
**Tests** Fallback returns confidence < threshold so the gate behaves.
**Accept** No chain-of-thought in `reasoning_summary`.

### Phase 9 — Fix Agent
**Objective** A minimal, grounded, applicable patch.
**Create** `app/prompts/fix.py`, `app/agents/fix_agent.py`.
**Tasks** Retry block carrying the reviewer's required changes and the previous patch; unified
diff format; anti-invention rules; risk rating.
**Expected** `ProposedFix`.
**Tests** With no model, returns an explanatory empty fix rather than raising.
**Accept** A retry visibly addresses the required changes.

### Phase 10 — Code Reviewer
**Objective** An independent gate that can say no.
**Create** `app/prompts/reviewer.py`, `app/agents/reviewer_agent.py`.
**Tasks** Adversarial prompt; decision/score consistency; empty patch forces rejection;
guarantee at least one concrete required change on rejection.
**Expected** `ReviewResult`.
**Tests** Empty patch → REJECTED with score ≤ 40.
**Accept** The reviewer does not rubber-stamp the Fix Agent.

### Phase 11 — LangGraph orchestration
**Objective** The graph, with the loops actually capped.
**Create** `app/graph/nodes.py`, `app/graph/graph.py`. **Depends on** Phases 5–10.
**Tasks** Eight nodes returning partial updates and appending trace entries; the two routers;
`StateGraph(InvestigationState)` — **not `StateGraph(dict)`**; node names that do not collide
with state keys; computed recursion limit;
`run_investigation` and `stream_investigation`.
**Expected** START → … → END on every input.
**Tests** `tests/test_routing.py` (both routers, both caps, failed-input short circuit),
`tests/test_graph_e2e.py` (full run, unsafe repo URL dropped, empty error handled),
`tests/test_graph_structure.py` (node/key collision, compilation, labels).
**Accept** In the worst case — permanently low confidence and a permanently rejecting reviewer
— the graph terminates and `research_iterations`/`review_iterations` reach exactly their caps.

### Phase 11b — CrewAI backend (optional)
**Objective** A second orchestrator behind one environment variable.
**Create** `app/crew/{tools,agents,orchestrator}.py`, `app/services/orchestrator.py`,
`requirements-crewai.txt`.
**Depends on** Phases 5–11 (the agents, prompts and tools are reused unchanged).
**Tasks** Wrap the existing tools with CrewAI's `@tool`; define five agents whose
backstories are the existing system prompts; build DiagnosisCrew and RemediationCrew with
`output_pydantic` on every task and `memory=False` on every crew; write the controller that
re-runs each crew within the same caps and emits the same `(node, partial state)` stream;
write the dispatcher, which degrades to LangGraph when crewai is absent or no model is
configured.
**Expected** Identical `InvestigationResponse` from either backend.
**Tests** `tests/test_orchestrator.py` (selection, both fallbacks, result tagging, and a
subprocess check that the default path never imports crewai),
`tests/test_crew_backend.py` (stubbed crews: high-confidence short circuit, capped diagnosis
retries carrying prior context, capped fix retries carrying reviewer feedback, the stage
sequence, refusal without a model, and a guard that no crew enables memory).
**Accept** `pytest` passes with and without the extra installed; nothing above the dispatcher
references either engine by name.

**Note on shared invariants.** Building this surfaced a real defect: the guard that keeps a
review's decision, score and feedback coherent lived inside the LangGraph reviewer node, so
the crew path could hand the Fix Agent a rejection with an empty `required_changes` list and
waste a retry. It now lives in `app/agents/reviewer_agent.normalize()` and both backends call
it. Any invariant that matters must sit below the orchestrator, not inside one of them.

### Phase 11c — Local knowledge base / RAG for repeated errors (optional)
**Objective** Skip the model entirely for errors the system already knows.
**Create** `data/error_knowledge_seed.py`, `scripts/build_knowledge_pdf.py`,
`scripts/build_knowledge_index.py`, `app/services/knowledge_base.py`.
**Depends on** Phases 3–5 (schemas, state, the debug agent's heuristic parser) and
Phase 11b (both orchestrators must call the same lookup).
**Tasks** Write ~30+ seed entries covering the languages/frameworks the benchmark set
already exercises; render them to a real PDF with reportlab, using explicit
`=== ENTRY <id> === … === END <id> ===` markers; extract that PDF's text with `pdfplumber`
and parse it back into JSON — prove the round trip, don't just trust the seed source; build
a TF-IDF + cosine-similarity index (`scikit-learn`) held in memory; strip a leading
`"<type>: "` prefix from the message before signature-building to avoid double-counting the
error type against the query; add a `knowledge_base_agent` node + `kb_router` to the
LangGraph (skips to `validation_agent` on a hit) and an equivalent early-return in the CrewAI
controller (skips constructing either crew on a hit); fold a learn step into
`compose_report`/the controller's tail, gated on approved + high confidence; add
`/api/knowledge-base/{stats,search,entries}`; add a "Knowledge base" dashboard view with a
live search preview, a cache-hit-rate KPI, and a rail state (`is-skipped`) for the stages a
hit bypasses so the UI doesn't look stuck.
**Expected** A seed-matching error completes with zero LLM calls in both orchestrators; a
novel error runs the full pipeline unchanged; a fresh, approved, high-confidence diagnosis is
retrievable on the next occurrence.
**Tests** `tests/test_knowledge_base.py` (signature construction, seed retrieval across
paraphrased repeats, unrelated-error rejection, learn/recall, disabling, pruning, the seed
data untouched by clearing learned cases, both orchestrators' short-circuit and fall-through,
and a fabricated high-confidence approval actually getting learned);
`tests/test_crew_backend.py` gained the CrewAI-side mirror of the same short-circuit tests.
**Accept** `pytest` passes with the knowledge base disabled by default for every *other* test
in the suite (an autouse fixture in `conftest.py` turns it off, since the seed data
intentionally covers fixtures used elsewhere and would otherwise silently change what those
tests exercise) and enabled explicitly wherever the feature itself is under test.

**Note on a real bug found while building this.** The first version of the signature builder
concatenated `error_type` with the raw error message. Standard tracebacks already embed the
type in the message ("ModuleNotFoundError: No module named …"), so that concatenation
double-counted the token and mis-ranked a generic seed entry over a materially more specific
one for the same query. Caught by comparing scores across the top candidates by hand, not by
the count of entries returned — a lookup can return *a* match while still returning the
*wrong* match, and only a per-case relevance check catches that.

### Phase 12 — Validation
**Objective** Confidence in the patch without running it.
**Create** `app/tools/validation.py`, `app/agents/validation_agent.py`.
**Tasks** The six checks in §6.6; SKIPPED short-circuit when there is no patch; status folding.
**Expected** `ValidationResult` with a per-check breakdown.
**Tests** `tests/test_validation_tool.py` — valid diff, `eval` rejection, empty patch,
unpinned dependency warning.
**Accept** No `exec`, `eval`, `subprocess` or `importlib` on user content anywhere.

### Phase 13 — FastAPI
**Objective** The HTTP surface.
**Create** `app/api/routes.py`, `app/services/report.py`, `app/services/activity.py`,
`app/services/samples.py`, `app/main.py`.
**Tasks** State → response mapper; the seven endpoints; SSE generator; markdown report
renderer; bounded in-memory feed; lifespan handler; CORS; static mount for the dashboard.
**Expected** `/api/docs` documents everything.
**Tests** `tests/test_api.py`, `tests/test_report.py`.
**Accept** `/health` returns 200 with no key configured; no secret appears in any response.

### Phase 14 — Frontends
**Objective** Two ways in.
**Create** `frontend/web/index.html`, `assets/css/app.css`, `assets/js/app.js`,
`assets/img/{logo,favicon}.svg`, `frontend/streamlit_app.py`.
**Tasks** Six dashboard views; SSE consumption driving the pipeline rail; hand-drawn SVG
charts; safe markdown rendering with diff highlighting and HTML escaping; Streamlit client with
API-then-local fallback.
**Expected** Both UIs run an investigation end to end.
**Tests** Manual: run a sample, watch stages arrive, confirm the report and sources render.
**Accept** Keyboard focus is visible, reduced motion is respected, layout holds at 360px, and
neither UI shows chain-of-thought.

### Phase 15 — Testing
**Objective** A suite that needs no key and no network.
**Create** `tests/conftest.py` and the eight test modules.
**Tasks** Autouse fixtures stubbing every fetch function and forcing demo mode; unit,
integration, end-to-end and failure tests.
**Expected** `pytest -q` → all green offline.
**Accept** The suite passes on a machine with no internet and no `.env`.

### Phase 16 — Docker
**Objective** A small, safe image.
**Create** `Dockerfile`, `docker-compose.yml`.
**Tasks** `python:3.11-slim`; requirements layer before source for cache reuse; copy `app/` and
`frontend/` only; non-root UID 10001; `HEALTHCHECK` on `/health`; CMD binding
`0.0.0.0:${PORT:-8000}`.
**Accept** The container starts with only `OPENROUTER_API_KEY` set and never runs as root.

### Phase 17 — Railway deployment
**Objective** Free-tier deployment.
**Create** `railway.json`.
**Tasks** Dockerfile builder; start command using `$PORT`; health check path `/health` with a
60s timeout; restart `ON_FAILURE` with 3 retries; document the variables to set in the Railway
UI; note that Streamlit, if wanted, is a second service pointed at the API via
`BUGHOUND_API_URL`.
**Accept** `PORT` is never hard-coded; the deployment goes healthy; logs show the startup line.

### Phase 18 — Documentation
**Objective** A repo someone else can pick up.
**Create** `README.md`, this file.
**Tasks** Quick start, configuration table, free/optional/paid tiering, API reference, security
section, no-database statement, deployment steps, layout, non-goals.
**Accept** A new contributor can run it locally and deploy it without asking a question.

---

## 12. Worked example

Input:

```
ModuleNotFoundError: No module named 'langchain.chat_models'
source: from langchain.chat_models import ChatOpenAI
deps:   langchain==0.3.7
```

| Stage | Receives | Produces |
|---|---|---|
| `validate_input` | raw request | cleaned input; warning if no trace |
| `debug_agent` | error, trace, source, deps | `error_type=ModuleNotFoundError`, `affected_file=app/main.py`, `suspected_dependencies=[langchain]`, queries about the import and the migration guide |
| `research_agent` | those queries | LangChain docs, the package-split GitHub issue, PyPI metadata for `langchain` and `langchain-openai`, release notes |
| `root_cause_agent` | debug + evidence + source | "`ChatOpenAI` moved to the `langchain-openai` package during the 0.1 → 0.2 split", confidence ≈ 0.92, evidence list |
| `confidence_router` | 0.92 ≥ 0.80 | → `fix_agent` |
| `fix_agent` | root cause + evidence + source | diff replacing the import; `dependency_changes=[langchain-openai>=0.2.0]`; risk LOW |
| `code_reviewer` | patch + root cause + evidence | APPROVED, score ~88, note that the package must be installed |
| `validation_agent` | patch | diff shape PASSED, syntax PASSED, imports PASSED, security PASSED |
| `compose_report` | all | report + citations, status `completed` |

Report shape:

```
Bug Investigation Report
Error type: ModuleNotFoundError   Severity: MAJOR   Status: COMPLETED
Root cause: …                     Confidence: 92%
Evidence: 1 docs · 2 issue · 3 release notes
Recommended fix + unified diff
Code review: APPROVED (88/100)
Validation: PASSED
Risk: LOW
Sources: linked
```

---

## 13. Evaluation

Benchmark set (`app/services/samples.py`, extend as needed): Python
(`ModuleNotFoundError`, `ImportError`, `TypeError`, `KeyError`, `AttributeError`), FastAPI (422
validation, dependency injection, Pydantic errors), LangChain (deprecated imports, version
compatibility, package restructuring), JavaScript/Node (module not found, npm conflicts,
`TypeError`).

Metrics: root-cause accuracy (human-labelled), fix accuracy, reviewer accuracy (does it catch a
deliberately broken patch), citation quality (share of cited sources that are official),
validation success, false-positive rate (approved fixes that are wrong), latency per stage, and
token cost per investigation.

Method: run each case three times, record the median, keep a CSV. Free models are noisy; a
single run proves nothing.

---

## 14. RAG decision (revised)

**Not in the original MVP, added deliberately afterward for one narrow purpose: recognising
repeated errors.** The reasoning against RAG for live package documentation still holds —
documentation for fast-moving packages goes stale the moment an index is built, so that
retrieval stays live (§7-8). What changed is the target: a *fixed* catalogue of common,
previously-solved error patterns is exactly the kind of corpus that doesn't go stale, because
the pattern ("this exception, from this kind of package restructure") is stable even as the
exact package version isn't.

**Implementation** (`app/services/knowledge_base.py`):

- **Ingestion is a real PDF, not a database dump.** `data/error_knowledge_base.pdf` is
  generated from `data/error_knowledge_seed.py` (32 seed entries) via
  `scripts/build_knowledge_pdf.py`, then `scripts/build_knowledge_index.py` extracts its text
  with `pdfplumber` and parses it back into structured entries using the
  `=== ENTRY <id> === … === END <id> ===` markers laid down at generation time. The cached
  result, `data/knowledge_base_seed.json`, is what the running app loads — re-parsing PDF text
  on every process start would be wasteful, but the PDF is what a human edits and what the
  index is verifiably built from.
- **Retrieval is TF-IDF + cosine similarity (`scikit-learn`), held in memory.** This is the
  "in-memory vector store" option this section always permitted — no embedding model, no GPU,
  no network call, no vector database service. For matching short error signatures against a
  few hundred known patterns it is more than adequate, and it needs no extra dependency beyond
  what a lightweight ML stack already provides.
- **The query signature strips noise deliberately**: quoted values, numbers, file paths and hex
  addresses are removed so that `KeyError: 'order_id'` and `KeyError: 'session_token'` are
  recognised as the same *kind* of problem. A real bug surfaced during testing here: naively
  concatenating the error type with the raw message double-counts that token when the message
  already contains it (as most tracebacks do), which mis-ranked a generic entry over a more
  specific one. Fixed by stripping a leading `"<type>: "` prefix from the message before
  building the signature (`_strip_type_prefix`).
- **A strong match (similarity ≥ `KB_MATCH_THRESHOLD`, default 0.55) skips every LLM call for
  that investigation.** In both orchestrators, the check runs immediately after
  `validate_input`/input acceptance, before any agent — LangGraph via a dedicated
  `knowledge_base_agent` node and `kb_router` conditional edge; CrewAI via an equivalent check
  at the top of the controller that, on a hit, never constructs either crew. Verified live with
  an LLM-call counter: a known error completes the full investigation with zero model calls.
- **Learning is opt-in persistence to a flat file**, `data/learned_cases.jsonl` — append-only,
  no SQL, no server, no migrations, but genuine persistence across restarts. This is the one
  deliberate exception to the "no persistent memory" principle elsewhere in this document,
  made because remembering *is* the feature. It triggers only when a fresh (non-cached)
  diagnosis is both APPROVED and at or above `KB_LEARN_MIN_CONFIDENCE` (default 0.80) — a shaky
  diagnosis must not become tomorrow's confidently-served "known pattern." Confidence is stored
  reduced by 0.05 from the original, since a future match is generic pattern-matching against
  a different codebase, not a fresh look at this one. The file is capped at
  `KB_MAX_LEARNED_ENTRIES` (default 500) and pruned oldest-first.
- **Both orchestrators call the exact same service.** The lesson from the CrewAI backend build
  (§Phase 11b) generalises: any behaviour that must hold regardless of which engine runs sits
  in a module neither engine owns, never duplicated inside one of them.

**What this is not**: a general-purpose document retrieval system, embeddings for arbitrary
text, or a replacement for the live research agent. It answers exactly one question — "have we
seen this kind of error before?" — and falls through to the full pipeline for anything else.

RAG for **private** documentation remains a V2 idea: an internal design doc or runbook that no
public source can supply, using FAISS or Chroma with local embeddings if the corpus grows
past what TF-IDF handles well. Not needed yet.

---

## 15. MVP scope and acceptance criteria

The MVP requires no database, no authentication, no paid API, no persistent memory, no code
execution and no complex infrastructure.

- [x] A user can submit an error
- [x] The Debug Agent analyses it
- [x] The Research Agent finds real technical evidence
- [x] The Root Cause Agent produces a calibrated confidence score
- [x] The Fix Agent produces a grounded fix
- [x] The Reviewer independently approves or rejects it
- [x] Rejected fixes return to the Fix Agent
- [x] Research repeats when confidence is low
- [x] Infinite loops are prevented, and the caps are tested
- [x] The final response carries evidence and citations
- [x] No database is required (the optional learned-cases file is a flat, append-only JSONL —
      no SQL, no server, no ORM, no migrations; the one deliberate persistence exception,
      made because remembering repeated errors is the point of that feature)
- [x] No paid API is required
- [x] The application runs locally
- [x] The application runs under Docker
- [x] FastAPI works
- [x] Streamlit works
- [x] Railway deployment is supported
- [x] Secrets live only in environment variables
- [x] Arbitrary user code is never executed on Railway
- [x] Tests run with no paid external service

---

## 16. V2 and V3

**V2** — sandboxed test execution in an isolated worker (never the web process), GitHub
repository integration for fetching real file context, PR generation, private-documentation
RAG, structured observability (LangSmith or OpenTelemetry), multiple LLM providers.

**V3** — automatic patch application behind human approval, CI/CD integration, Slack and
Discord entry points, team accounts, investigation history (which is the first feature that
would justify a database, and therefore the first departure from this plan's constraints).

None of it is required for the MVP.

---

## 17. Engineering principles

Prefer simple solutions. Avoid unnecessary dependencies and unnecessary agents. Use structured
outputs and typed state. Keep agents independent and tools separate from agents. Never expose
chain-of-thought. Treat all web and GitHub content as untrusted. Prevent infinite loops. Fail
gracefully — a degraded report beats a stack trace. Keep the MVP stateless. Prefer free and
open infrastructure, and make every external service optional where possible. Keep model
selection configurable. Design for Railway from the first commit.
