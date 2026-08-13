"""CrewAI tool wrappers.

The underlying tools are unchanged: the same SSRF-guarded HTTP client, the same
free research sources, the same static validator. This module only adapts their
signatures to CrewAI's decorator so agents can call them.

Keeping the implementations in ``app/tools`` means both orchestrators share one
security boundary rather than two that can drift apart.
"""

from __future__ import annotations

from typing import List

from crewai.tools import tool

from app.tools import github as gh
from app.tools.documentation import fetch_documentation, inspect_dependency
from app.tools.validation import validate_patch as _validate_patch
from app.tools.web_search import rank_hits, search_web


@tool("Search the web")
def search_web_tool(query: str) -> str:
    """Search the public web for technical information about an error.

    Returns ranked results with official documentation first. Never raises:
    an empty result means no source was reachable.
    """
    hits = rank_hits(search_web(query))
    if not hits:
        return "No web results were reachable for this query."
    return "\n\n".join(
        f"[{h.source_type.value}] {h.title}\nURL: {h.url}\n{h.snippet[:400]}" for h in hits
    )


@tool("Search GitHub issues")
def search_github_issues_tool(query: str, repository: str = "") -> str:
    """Find public GitHub issues matching an error. `repository` is `owner/name`."""
    issues = gh.search_issues(query, limit=4, repo=repository or None)
    if not issues:
        return "No matching GitHub issues were found."
    return "\n\n".join(
        f"[{i.state}] {i.title}\nURL: {i.url}\n{i.body[:600]}" for i in issues
    )


@tool("Inspect a package")
def inspect_dependency_tool(name: str, language: str = "Python") -> str:
    """Look up a package on PyPI or npm: latest version, recent releases, docs URL."""
    info = inspect_dependency(name, language)
    if not info:
        return f"No registry entry was found for '{name}'."
    return (
        f"{info.name} ({info.registry})\nLatest: {info.latest_version}\n"
        f"Recent versions: {', '.join(info.recent_versions[-5:])}\n"
        f"Docs: {info.docs_url or info.homepage or 'unknown'}\n"
        f"Repository: {info.repository or 'unknown'}\n{info.summary}"
    )


@tool("Read release notes")
def release_notes_tool(repository_url: str) -> str:
    """Read the most recent releases of a GitHub repository."""
    parsed = gh.parse_repo_url(repository_url)
    if not parsed:
        return "That is not a recognisable GitHub repository URL."
    releases = gh.get_latest_releases(parsed[0], parsed[1], limit=3)
    if not releases:
        return "No releases were published for that repository."
    return "\n\n".join(
        f"{r['tag']} ({r['published_at'][:10]})\nURL: {r['url']}\n{r['body'][:800]}"
        for r in releases
    )


@tool("Fetch a documentation page")
def fetch_documentation_tool(url: str) -> str:
    """Fetch a documentation page and return its readable text.

    URLs are validated against the same SSRF guard used everywhere else, so
    private and internal addresses are refused.
    """
    text = fetch_documentation(url, limit=6000)
    return text or f"Could not fetch {url}."


@tool("Validate a patch statically")
def validate_patch_tool(patch: str, language: str = "Python") -> str:
    """Check a unified diff without executing it.

    Runs syntax parsing, import analysis, a dangerous-construct scan and
    dependency pin checks. No code is ever run.
    """
    result = _validate_patch(patch, language=language)
    lines = [f"{result.status.value}: {result.summary}"]
    lines += [f"- [{c.status.value}] {c.name}: {c.detail}" for c in result.checks]
    return "\n".join(lines)


RESEARCH_TOOLS: List = [
    search_web_tool,
    search_github_issues_tool,
    inspect_dependency_tool,
    release_notes_tool,
    fetch_documentation_tool,
]

REVIEW_TOOLS: List = [validate_patch_tool]
