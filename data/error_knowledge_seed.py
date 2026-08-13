"""The single source of truth for BugHound's seed knowledge base.

Every entry here becomes one card in ``data/error_knowledge_base.pdf`` (via
``scripts/build_knowledge_pdf.py``) and one row in the searchable index (via
``scripts/build_knowledge_index.py``, which re-extracts the text from that same
PDF — the PDF is the actual ingestion source, not a decorative export).

Edit this file, then run:
    python scripts/build_knowledge_pdf.py
    python scripts/build_knowledge_index.py

Confidence is deliberately capped below what a fresh, code-specific LLM
diagnosis could reach: these are generic patterns, not verified against any
particular repository, so the pipeline always says so when it serves one.
"""

from __future__ import annotations

from typing import Any, Dict, List

ENTRIES: List[Dict[str, Any]] = [
    # ---------------------------------------------------------------- Python
    {
        "id": "E001",
        "title": "ModuleNotFoundError after a package restructure",
        "language": "Python",
        "framework": "General",
        "tags": ["import", "packaging", "module-not-found"],
        "error_pattern": "ModuleNotFoundError: No module named",
        "root_cause": (
            "The import path points at a module that a newer version of the package "
            "moved, renamed, or removed. This is common right after upgrading a "
            "fast-moving library — the old top-level module becomes a thin shim for a "
            "few releases, then disappears entirely."
        ),
        "fix": (
            "Check the package's changelog for the release that introduced the "
            "restructure and update the import to the new location. If the package "
            "was split into sub-packages, install the specific sub-package."
        ),
        "patch": (
            "--- a/app/main.py\n"
            "+++ b/app/main.py\n"
            "@@\n"
            "-from langchain.chat_models import ChatOpenAI\n"
            "+from langchain_openai import ChatOpenAI\n"
        ),
        "confidence": 0.88,
    },
    {
        "id": "E002",
        "title": "ImportError: cannot import name X from partially initialized module",
        "language": "Python",
        "framework": "General",
        "tags": ["import", "circular-import"],
        "error_pattern": "ImportError: cannot import name",
        "root_cause": (
            "Two modules import each other at module load time (a circular import). "
            "Python starts executing module A, which imports module B, which tries to "
            "import a name from A before A has finished defining it."
        ),
        "fix": (
            "Move the shared import to function scope (import inside the function that "
            "needs it), or extract the shared symbol into a third module that both A "
            "and B import from, breaking the cycle."
        ),
        "patch": (
            "--- a/app/services/a.py\n"
            "+++ b/app/services/a.py\n"
            "@@\n"
            "-from app.services.b import helper\n"
            " \n"
            " def run():\n"
            "+    from app.services.b import helper\n"
            "     return helper()\n"
        ),
        "confidence": 0.75,
    },
    {
        "id": "E003",
        "title": "TypeError: missing N required positional argument",
        "language": "Python",
        "framework": "General",
        "tags": ["typeerror", "function-signature"],
        "error_pattern": "TypeError: .* missing .* required positional argument",
        "root_cause": (
            "A function or method is being called with fewer arguments than its "
            "signature requires. Frequently happens after adding a new parameter "
            "without a default, or forgetting `self` on an instance method mistakenly "
            "called as if it were a static function."
        ),
        "fix": (
            "Pass the missing argument at the call site, or give the parameter a "
            "default value if it is genuinely optional."
        ),
        "patch": "",
        "confidence": 0.7,
    },
    {
        "id": "E004",
        "title": "KeyError on a dictionary access",
        "language": "Python",
        "framework": "General",
        "tags": ["keyerror", "dict"],
        "error_pattern": "KeyError:",
        "root_cause": (
            "Code indexes a dictionary with `d[key]` for a key that is not guaranteed "
            "to exist — typically a field missing from an API payload, a config file, "
            "or an environment mapping."
        ),
        "fix": (
            "Use `d.get(key, default)` when a missing key is expected, or validate the "
            "input shape up front (a Pydantic model or an explicit check) so the "
            "failure is caught with a clear message before it reaches this line."
        ),
        "patch": (
            "--- a/app/handlers.py\n"
            "+++ b/app/handlers.py\n"
            "@@\n"
            "-user_id = payload['user_id']\n"
            "+user_id = payload.get('user_id')\n"
            "+if user_id is None:\n"
            "+    raise ValueError(\"payload is missing 'user_id'\")\n"
        ),
        "confidence": 0.72,
    },
    {
        "id": "E005",
        "title": "AttributeError: NoneType has no attribute X",
        "language": "Python",
        "framework": "General",
        "tags": ["attributeerror", "none"],
        "error_pattern": "AttributeError: 'NoneType' object has no attribute",
        "root_cause": (
            "A function that can return `None` — a dict `.get()`, a failed lookup, an "
            "ORM query with no match — is being used as if it always returns an "
            "object, and the `None` case was never handled."
        ),
        "fix": (
            "Check for `None` immediately after the call that can produce it, and "
            "either return early, raise a clear error, or supply a default."
        ),
        "patch": "",
        "confidence": 0.68,
    },
    {
        "id": "E006",
        "title": "RecursionError: maximum recursion depth exceeded",
        "language": "Python",
        "framework": "General",
        "tags": ["recursion", "stack"],
        "error_pattern": "RecursionError: maximum recursion depth exceeded",
        "root_cause": (
            "A recursive function has no base case that is ever reached for the given "
            "input, or two functions call each other indefinitely (mutual recursion "
            "without a terminating condition)."
        ),
        "fix": (
            "Add or fix the base case so recursion terminates, or convert the "
            "function to an iterative loop with an explicit stack if the recursion "
            "depth is expected to be legitimately large."
        ),
        "patch": "",
        "confidence": 0.65,
    },
    {
        "id": "E007",
        "title": "UnicodeDecodeError while reading a file",
        "language": "Python",
        "framework": "General",
        "tags": ["encoding", "unicode", "file-io"],
        "error_pattern": "UnicodeDecodeError: 'utf-8' codec can't decode byte",
        "root_cause": (
            "A file is opened with the default or an assumed UTF-8 encoding, but its "
            "actual bytes are in a different encoding (commonly Latin-1/cp1252 on "
            "files that came from Windows tools)."
        ),
        "fix": (
            "Open the file with the correct encoding, or detect it (e.g. with "
            "`charset-normalizer`) instead of assuming UTF-8. As a last resort, decode "
            "with `errors=\"replace\"` if some data loss is acceptable."
        ),
        "patch": (
            "--- a/app/importer.py\n"
            "+++ b/app/importer.py\n"
            "@@\n"
            "-with open(path) as f:\n"
            "+with open(path, encoding=\"utf-8-sig\") as f:\n"
        ),
        "confidence": 0.7,
    },
    {
        "id": "E008",
        "title": "IndentationError: unexpected indent",
        "language": "Python",
        "framework": "General",
        "tags": ["syntax", "indentation"],
        "error_pattern": "IndentationError:",
        "root_cause": (
            "Tabs and spaces are mixed in the same block, or an editor auto-indented a "
            "line to a level Python does not accept relative to its enclosing block."
        ),
        "fix": (
            "Re-indent the file consistently (spaces only, 4 per level is the PEP 8 "
            "convention) and configure the editor to insert spaces for Tab."
        ),
        "patch": "",
        "confidence": 0.8,
    },
    {
        "id": "E009",
        "title": "ZeroDivisionError: division by zero",
        "language": "Python",
        "framework": "General",
        "tags": ["arithmetic", "zerodivision"],
        "error_pattern": "ZeroDivisionError: division by zero",
        "root_cause": (
            "A denominator that is computed from input data — a count, a duration, an "
            "average's sample size — reaches zero for an edge case, such as an empty "
            "list, that the calling code did not anticipate."
        ),
        "fix": (
            "Guard the division with a check for a zero denominator and return a "
            "sensible default (0, None, or skip the calculation) for that case."
        ),
        "patch": "",
        "confidence": 0.75,
    },
    {
        "id": "E010",
        "title": "json.decoder.JSONDecodeError: Expecting value",
        "language": "Python",
        "framework": "General",
        "tags": ["json", "parsing"],
        "error_pattern": "json.decoder.JSONDecodeError: Expecting value",
        "root_cause": (
            "`json.loads()` is called on a string that is empty, is HTML (often an "
            "error page from an API that returned a non-JSON response), or is `None` "
            "coerced to the literal text 'None'."
        ),
        "fix": (
            "Check the HTTP status code and content-type before parsing, and log the "
            "raw response body when parsing fails so the real cause is visible."
        ),
        "patch": "",
        "confidence": 0.7,
    },
    # -------------------------------------------------------------- FastAPI
    {
        "id": "E011",
        "title": "FastAPI 422 Unprocessable Entity on a POST request",
        "language": "Python",
        "framework": "FastAPI",
        "tags": ["validation", "pydantic", "422"],
        "error_pattern": "422 Unprocessable Entity.*Field required",
        "root_cause": (
            "The request body is missing a field the Pydantic model declares as "
            "required, or the client's JSON key does not match the model's attribute "
            "name (e.g. camelCase from a JS client vs snake_case in the model)."
        ),
        "fix": (
            "Make the field Optional with a default if it truly is optional, add "
            "`Field(alias=\"...\")` to match the client's key name, or fix the client "
            "payload to match the schema."
        ),
        "patch": (
            "--- a/app/models.py\n"
            "+++ b/app/models.py\n"
            "@@\n"
            "-    user_id: str\n"
            "+    user_id: str = Field(..., alias=\"userId\")\n"
            "+\n"
            "+    class Config:\n"
            "+        populate_by_name = True\n"
        ),
        "confidence": 0.85,
    },
    {
        "id": "E012",
        "title": "FastAPI dependency injection: 'Depends object has no attribute'",
        "language": "Python",
        "framework": "FastAPI",
        "tags": ["dependency-injection", "depends"],
        "error_pattern": "AttributeError.*Depends",
        "root_cause": (
            "A dependency function is called directly in normal Python code instead "
            "of being resolved by FastAPI's injection system, so the parameter holds "
            "the `Depends(...)` sentinel object rather than the value it produces."
        ),
        "fix": (
            "Only call the dependency-producing function through a route parameter "
            "typed as `Annotated[X, Depends(get_x)]` (or the equivalent "
            "`x: X = Depends(get_x)`); never call it as a plain function outside a "
            "request handler."
        ),
        "patch": "",
        "confidence": 0.78,
    },
    {
        "id": "E013",
        "title": "FastAPI CORS: 'No Access-Control-Allow-Origin header'",
        "language": "Python",
        "framework": "FastAPI",
        "tags": ["cors", "middleware"],
        "error_pattern": "No 'Access-Control-Allow-Origin' header",
        "root_cause": (
            "`CORSMiddleware` is missing, or is configured with an `allow_origins` "
            "list that does not include the calling frontend's exact origin "
            "(scheme + host + port must match precisely)."
        ),
        "fix": (
            "Add `CORSMiddleware` with the frontend's origin in `allow_origins`, and "
            "set `allow_credentials=True` if the frontend sends cookies."
        ),
        "patch": (
            "--- a/app/main.py\n"
            "+++ b/app/main.py\n"
            "@@\n"
            "+from fastapi.middleware.cors import CORSMiddleware\n"
            "+\n"
            "+app.add_middleware(\n"
            "+    CORSMiddleware,\n"
            "+    allow_origins=[\"http://localhost:3000\"],\n"
            "+    allow_methods=[\"*\"],\n"
            "+    allow_headers=[\"*\"],\n"
            "+)\n"
        ),
        "confidence": 0.9,
    },
    {
        "id": "E014",
        "title": "Pydantic v2 migration: 'BaseSettings has been moved'",
        "language": "Python",
        "framework": "FastAPI",
        "tags": ["pydantic", "migration", "settings"],
        "error_pattern": "BaseSettings.*has been moved|pydantic.errors.PydanticUserError",
        "root_cause": (
            "Pydantic v2 moved `BaseSettings` out of the core package into the "
            "separate `pydantic-settings` package. Code written for Pydantic v1 "
            "imports it from `pydantic` directly, which no longer works."
        ),
        "fix": "Install `pydantic-settings` and import `BaseSettings` from it instead.",
        "patch": (
            "--- a/app/config.py\n"
            "+++ b/app/config.py\n"
            "@@\n"
            "-from pydantic import BaseSettings\n"
            "+from pydantic_settings import BaseSettings\n"
        ),
        "confidence": 0.92,
    },
    {
        "id": "E015",
        "title": "FastAPI background task never seems to run",
        "language": "Python",
        "framework": "FastAPI",
        "tags": ["background-tasks", "async"],
        "error_pattern": "BackgroundTasks",
        "root_cause": (
            "The `BackgroundTasks` parameter was added to the route but never had "
            "`.add_task(...)` called on it, or the task was added to a locally "
            "created `BackgroundTasks()` instance instead of the one injected by "
            "FastAPI, so it is discarded when the response is returned."
        ),
        "fix": (
            "Accept `background_tasks: BackgroundTasks` as a route parameter and call "
            "`background_tasks.add_task(fn, *args)` on that exact instance."
        ),
        "patch": "",
        "confidence": 0.7,
    },
    # ------------------------------------------------------------- LangChain
    {
        "id": "E016",
        "title": "LangChain: No module named 'langchain.chat_models'",
        "language": "Python",
        "framework": "LangChain",
        "tags": ["langchain", "import", "packaging"],
        "error_pattern": "No module named 'langchain.chat_models'",
        "root_cause": (
            "LangChain split provider integrations into standalone packages "
            "(`langchain-openai`, `langchain-anthropic`, etc.) during the 0.1 -> 0.2 "
            "restructure. `langchain.chat_models.ChatOpenAI` no longer exists in "
            "current releases."
        ),
        "fix": (
            "Install the provider-specific package and import the chat model class "
            "from it directly."
        ),
        "patch": (
            "--- a/app/main.py\n"
            "+++ b/app/main.py\n"
            "@@\n"
            "-from langchain.chat_models import ChatOpenAI\n"
            "+from langchain_openai import ChatOpenAI\n"
        ),
        "confidence": 0.93,
    },
    {
        "id": "E017",
        "title": "LangChain: LangChainDeprecationWarning on memory classes",
        "language": "Python",
        "framework": "LangChain",
        "tags": ["langchain", "deprecation", "memory"],
        "error_pattern": "LangChainDeprecationWarning.*memory",
        "root_cause": (
            "Classes like `ConversationBufferMemory` are deprecated in favour of "
            "LangGraph's persistence layer or explicit message-list state. The old "
            "classes still work but will be removed in a future release."
        ),
        "fix": (
            "For new code, hold conversation state as a plain list of messages, or "
            "use a LangGraph checkpointer if persistence is required. For a "
            "short-term fix, the deprecated class still functions — the warning is "
            "not yet a hard failure."
        ),
        "patch": "",
        "confidence": 0.6,
    },
    {
        "id": "E018",
        "title": "LangChain: OutputParserException on structured output",
        "language": "Python",
        "framework": "LangChain",
        "tags": ["langchain", "output-parser", "json"],
        "error_pattern": "OutputParserException",
        "root_cause": (
            "The model's raw text response could not be parsed into the expected "
            "structure — usually because a smaller or free-tier model added "
            "commentary, markdown fences, or explanatory text around the JSON instead "
            "of returning only the JSON object."
        ),
        "fix": (
            "Tighten the prompt to demand JSON only with no surrounding text, add a "
            "one-shot repair step that re-asks the model to fix invalid output, or "
            "switch to a model with reliable structured-output support."
        ),
        "patch": "",
        "confidence": 0.65,
    },
    {
        "id": "E019",
        "title": "LangChain: tool calling schema mismatch with a free model",
        "language": "Python",
        "framework": "LangChain",
        "tags": ["langchain", "tool-calling", "free-model"],
        "error_pattern": "does not support tools|tool_choice",
        "root_cause": (
            "The selected model does not support native function/tool calling, or "
            "supports a different calling convention than the one LangChain's "
            "`bind_tools` assumes for that provider — common with smaller free-tier "
            "models on OpenRouter."
        ),
        "fix": (
            "Check the model's `supported_parameters` on the provider's model listing "
            "for `tools`; if absent, fall back to prompt-based JSON output instead of "
            "native tool calling for that model."
        ),
        "patch": "",
        "confidence": 0.6,
    },
    {
        "id": "E020",
        "title": "openai.NotFoundError: 404 No endpoints found for <model>:free",
        "language": "Python",
        "framework": "LangChain",
        "tags": ["openrouter", "free-model", "404"],
        "error_pattern": "No endpoints found for.*:free|404.*model",
        "root_cause": (
            "The configured free model ID has been removed or renamed by its "
            "provider on OpenRouter. Free-tier model availability rotates without "
            "notice; an ID that worked last month can disappear entirely."
        ),
        "fix": (
            "Query OpenRouter's public model catalog for models currently priced at "
            "zero and switch to one of them; do not hard-code a single free model ID "
            "as a permanent default."
        ),
        "patch": "",
        "confidence": 0.85,
    },
    # ------------------------------------------------------- JavaScript / Node
    {
        "id": "E021",
        "title": "Node.js: Cannot find module 'X'",
        "language": "JavaScript",
        "framework": "Node.js",
        "tags": ["node", "module-not-found", "npm"],
        "error_pattern": "Error: Cannot find module",
        "root_cause": (
            "The package is listed in `package.json` but was never installed (no "
            "`node_modules` entry), or the import path has a typo, or the package "
            "was installed as a devDependency but is required at runtime in "
            "production where devDependencies are pruned."
        ),
        "fix": (
            "Run `npm install`, verify the exact package name and path, and move the "
            "dependency out of devDependencies if it is needed at runtime."
        ),
        "patch": "",
        "confidence": 0.8,
    },
    {
        "id": "E022",
        "title": "Node.js: ERR_REQUIRE_ESM importing an ES Module with require()",
        "language": "JavaScript",
        "framework": "Node.js",
        "tags": ["esm", "commonjs", "require"],
        "error_pattern": "ERR_REQUIRE_ESM",
        "root_cause": (
            "The target package ships only as an ES Module (`\"type\": \"module\"` or "
            "`.mjs`), but the calling code uses CommonJS `require()`, which cannot "
            "load ESM synchronously."
        ),
        "fix": (
            "Switch the calling file to ESM (`import`) and set `\"type\": \"module\"` in "
            "`package.json`, or use a dynamic `await import(...)` from CommonJS code."
        ),
        "patch": (
            "--- a/server.js\n"
            "+++ b/server.js\n"
            "@@\n"
            "-const chalk = require('chalk');\n"
            "+const { default: chalk } = await import('chalk');\n"
        ),
        "confidence": 0.78,
    },
    {
        "id": "E023",
        "title": "TypeError: X is not a function",
        "language": "JavaScript",
        "framework": "General",
        "tags": ["typeerror", "undefined"],
        "error_pattern": "TypeError: .* is not a function",
        "root_cause": (
            "A value that used to be a function in an older version of a library is "
            "now an object, or a default export is being called as a named export "
            "(or vice versa), which is common after a major version bump."
        ),
        "fix": (
            "Check the library's current changelog for the exact call signature and "
            "update the import/usage to match; log `typeof x` at the call site while "
            "debugging to confirm what the value actually is."
        ),
        "patch": "",
        "confidence": 0.62,
    },
    {
        "id": "E024",
        "title": "npm ERESOLVE: unable to resolve dependency tree",
        "language": "JavaScript",
        "framework": "npm",
        "tags": ["npm", "peer-dependency", "eresolve"],
        "error_pattern": "ERESOLVE unable to resolve dependency tree",
        "root_cause": (
            "Two installed packages require incompatible versions of the same peer "
            "dependency (commonly React or a shared framework), and npm 7+ enforces "
            "peer dependency resolution strictly by default."
        ),
        "fix": (
            "Upgrade the outdated package to a version compatible with the shared "
            "peer dependency; `--legacy-peer-deps` or `--force` unblock the install "
            "but leave the underlying incompatibility unresolved."
        ),
        "patch": "",
        "confidence": 0.68,
    },
    {
        "id": "E025",
        "title": "Fetch/CORS: 'has been blocked by CORS policy' in the browser console",
        "language": "JavaScript",
        "framework": "General",
        "tags": ["cors", "fetch", "browser"],
        "error_pattern": "has been blocked by CORS policy",
        "root_cause": (
            "The browser blocked the response because the server did not send an "
            "`Access-Control-Allow-Origin` header matching the page's origin. This "
            "is enforced by the browser, not the server, so the request often "
            "succeeds when tested from curl or Postman, which is a common source of "
            "confusion."
        ),
        "fix": (
            "Configure CORS on the server to allow the frontend's exact origin; a "
            "browser-side workaround (a proxy, disabling security) is not a real fix "
            "for anything beyond local development."
        ),
        "patch": "",
        "confidence": 0.82,
    },
    {
        "id": "E026",
        "title": "UnhandledPromiseRejectionWarning / unhandled promise rejection",
        "language": "JavaScript",
        "framework": "Node.js",
        "tags": ["promise", "async", "error-handling"],
        "error_pattern": "UnhandledPromiseRejectionWarning|unhandled promise rejection",
        "root_cause": (
            "An `async` function throws or a Promise rejects, and nothing in the call "
            "chain has a `.catch()` or a surrounding `try/catch` on the `await`."
        ),
        "fix": (
            "Wrap the `await` in `try/catch` at the boundary where the error should be "
            "handled (a route handler, a job runner), and add a process-level "
            "`unhandledRejection` listener as a safety net, not as the primary fix."
        ),
        "patch": "",
        "confidence": 0.72,
    },
    # ------------------------------------------------------------------ Docker
    {
        "id": "E027",
        "title": "Docker: 'permission denied' writing inside the container",
        "language": "General",
        "framework": "Docker",
        "tags": ["docker", "permissions", "non-root"],
        "error_pattern": "PermissionError|EACCES.*permission denied",
        "root_cause": (
            "The container runs as a non-root user (a good security practice) but "
            "the application tries to write to a directory still owned by root from "
            "the image build step, such as a log or upload folder created before the "
            "`USER` instruction switched accounts."
        ),
        "fix": (
            "`chown` the specific writable directories to the non-root user before "
            "the `USER` instruction in the Dockerfile, or create them as that user "
            "from the start."
        ),
        "patch": (
            "--- a/Dockerfile\n"
            "+++ b/Dockerfile\n"
            "@@\n"
            "+RUN mkdir -p /app/logs && chown -R appuser:appuser /app/logs\n"
            " USER appuser\n"
        ),
        "confidence": 0.75,
    },
    {
        "id": "E028",
        "title": "Docker: 'port is already allocated'",
        "language": "General",
        "framework": "Docker",
        "tags": ["docker", "networking", "port"],
        "error_pattern": "port is already allocated|address already in use",
        "root_cause": (
            "Another container, or a process on the host, is already bound to the "
            "port this container is trying to publish — frequently a previous run of "
            "the same container that was not removed."
        ),
        "fix": (
            "Stop the conflicting container (`docker ps` then `docker stop`), or "
            "publish on a different host port with `-p 8001:8000`."
        ),
        "patch": "",
        "confidence": 0.85,
    },
    {
        "id": "E029",
        "title": "Docker: 'exec format error' running a built image",
        "language": "General",
        "framework": "Docker",
        "tags": ["docker", "architecture", "arm", "amd64"],
        "error_pattern": "exec.*exec format error",
        "root_cause": (
            "The image was built for a different CPU architecture than the host is "
            "running — typically an amd64 image built on an Apple Silicon (arm64) "
            "machine without cross-platform build flags, then run on an amd64 server "
            "or vice versa."
        ),
        "fix": (
            "Build with `docker buildx build --platform linux/amd64,linux/arm64` and "
            "push a multi-arch manifest, or specify the correct target platform "
            "explicitly at build and run time."
        ),
        "patch": "",
        "confidence": 0.8,
    },
    {
        "id": "E030",
        "title": "Docker Compose: 'service healthcheck failed' loop / restart loop",
        "language": "General",
        "framework": "Docker",
        "tags": ["docker-compose", "healthcheck", "restart"],
        "error_pattern": "unhealthy|restarting.*container",
        "root_cause": (
            "The health check hits an endpoint before the application has finished "
            "starting (no `start_period`), or checks a path that does not exist, or "
            "the app is crashing immediately on boot due to a missing environment "
            "variable and the health check is correctly reporting that."
        ),
        "fix": (
            "Confirm the app starts cleanly with `docker logs`, add a `start_period` "
            "to the health check to allow for startup time, and double-check the "
            "health check path matches an endpoint that actually exists."
        ),
        "patch": "",
        "confidence": 0.65,
    },
    {
        "id": "E031",
        "title": "Railway: application failed the health check and was rolled back",
        "language": "General",
        "framework": "Railway",
        "tags": ["railway", "deployment", "port"],
        "error_pattern": "health check failed|failed to respond",
        "root_cause": (
            "The application is listening on a hard-coded port instead of the "
            "`$PORT` Railway injects at runtime, so the platform's health check "
            "cannot reach it even though the app is running correctly."
        ),
        "fix": (
            "Bind the server to `0.0.0.0:$PORT` using the environment variable, never "
            "a literal port number, in both the Dockerfile CMD and any code that "
            "constructs the listen address."
        ),
        "patch": (
            "--- a/Dockerfile\n"
            "+++ b/Dockerfile\n"
            "@@\n"
            "-CMD [\"uvicorn\", \"app.main:app\", \"--port\", \"8000\"]\n"
            "+CMD [\"sh\", \"-c\", \"uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}\"]\n"
        ),
        "confidence": 0.88,
    },
    # ------------------------------------------------------------------- Git
    {
        "id": "E032",
        "title": "Git: 'fatal: refusing to merge unrelated histories'",
        "language": "General",
        "framework": "Git",
        "tags": ["git", "merge"],
        "error_pattern": "refusing to merge unrelated histories",
        "root_cause": (
            "Two branches (often a freshly initialised local repo and an existing "
            "remote one) do not share a common commit ancestor, so Git refuses the "
            "merge as a safety measure against accidentally combining unrelated "
            "projects."
        ),
        "fix": (
            "If the histories genuinely should be combined, pull with "
            "`--allow-unrelated-histories`; if not, the correct fix is to clone the "
            "remote instead of re-initialising a new local repository."
        ),
        "patch": "",
        "confidence": 0.8,
    },
]

__all__ = ["ENTRIES"]
