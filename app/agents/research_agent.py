"""Research Agent — gathers external evidence, then judges it.

Collection is deterministic (web search, GitHub, package registries). Only the
judging step uses the LLM, so the agent still returns useful raw sources when no
API key is configured.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from app.config.settings import settings
from app.models.schemas import ResearchReport, ResearchResult, SourceType
from app.prompts import RESEARCH_SYSTEM
from app.services.llm import llm_service, untrusted
from app.tools import github as gh
from app.tools.documentation import inspect_dependency
from app.tools.web_search import rank_hits, search_web

logger = logging.getLogger(__name__)


def _collect(
    queries: List[str], state: Dict[str, Any], seen_urls: set[str]
) -> tuple[List[ResearchResult], List[str]]:
    """Pull raw material from every free source. Never raises."""
    raw: List[ResearchResult] = []
    notes: List[str] = []

    # 1. Free web search
    web_ok = False
    for query in queries[:3]:
        hits = rank_hits(search_web(query))
        if hits:
            web_ok = True
        for hit in hits:
            if hit.url in seen_urls:
                continue
            seen_urls.add(hit.url)
            raw.append(
                ResearchResult(
                    title=hit.title,
                    url=hit.url,
                    source_type=hit.source_type,
                    summary=hit.snippet,
                    relevant_evidence=hit.snippet,
                    relevance_score=0.5,
                )
            )
    if not web_ok:
        notes.append("Web search returned nothing; relying on GitHub and registries.")

    debug = state.get("debug_analysis") or {}
    error_type = debug.get("error_type") or ""
    packages = debug.get("suspected_dependencies") or []
    package = packages[0] if packages else (state.get("framework") or "")

    # 2. GitHub issues — the fastest route to "someone already hit this"
    issue_query = " ".join(
        p for p in [error_type, package, state.get("error_message", "")[:60]] if p
    )
    repo_filter = None
    parsed = gh.parse_repo_url(state.get("repository_url") or "")
    if parsed:
        repo_filter = f"{parsed[0]}/{parsed[1]}"
    for issue in gh.search_issues(issue_query, limit=4, repo=repo_filter):
        if issue.url in seen_urls:
            continue
        seen_urls.add(issue.url)
        raw.append(
            ResearchResult(
                title=f"[{issue.state}] {issue.title}",
                url=issue.url,
                source_type=SourceType.GITHUB_ISSUE,
                summary=issue.body[:600],
                relevant_evidence=issue.body[:900],
                relevance_score=0.55,
            )
        )

    # 3. Package registry — authoritative versions and docs links
    for name in packages[:2]:
        info = inspect_dependency(name, state.get("language"))
        if not info:
            continue
        url = info.docs_url or info.homepage or info.repository
        if url and url not in seen_urls:
            seen_urls.add(url)
            raw.append(
                ResearchResult(
                    title=f"{info.name} {info.latest_version} ({info.registry})",
                    url=url,
                    source_type=SourceType.OFFICIAL_DOCS,
                    summary=info.summary,
                    relevant_evidence=(
                        f"Latest published version is {info.latest_version}. "
                        f"Recent releases: {', '.join(info.recent_versions[-5:])}."
                    ),
                    relevance_score=0.7,
                )
            )
        # 4. Release notes from the package's own repository
        repo = gh.parse_repo_url(info.repository or "")
        if repo:
            for release in gh.get_latest_releases(repo[0], repo[1], limit=2):
                if not release["url"] or release["url"] in seen_urls:
                    continue
                seen_urls.add(release["url"])
                raw.append(
                    ResearchResult(
                        title=f"{info.name} release {release['tag']}",
                        url=release["url"],
                        source_type=SourceType.RELEASE_NOTES,
                        summary=release["body"][:500],
                        relevant_evidence=release["body"][:900],
                        relevance_score=0.6,
                    )
                )

    return raw, notes


def _judge(raw: List[ResearchResult], state: Dict[str, Any]) -> ResearchReport | None:
    """Ask the LLM to score and summarise the collected material."""
    if not settings.llm_available or not raw:
        return None

    material = "\n\n".join(
        f"[{i}] {r.title}\nURL: {r.url}\nType: {r.source_type.value}\n"
        + untrusted("content", r.relevant_evidence, 1200)
        for i, r in enumerate(raw[:12], start=1)
    )
    user = (
        f"Error: {state.get('error_message', '')[:400]}\n"
        f"Error type: {(state.get('debug_analysis') or {}).get('error_type')}\n"
        f"Language: {state.get('language')} / Framework: {state.get('framework')}\n\n"
        "Collected material:\n" + material + "\n\n"
        "Return the evidence table. Keep the URLs exactly as given; do not invent new ones."
    )
    try:
        report = llm_service.complete_json(
            RESEARCH_SYSTEM, user, ResearchReport, prefer_fast=True, max_tokens=2500
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Research judging failed: %s", exc)
        return None

    # Guard against hallucinated URLs: keep only sources we actually fetched.
    allowed = {r.url for r in raw}
    report.results = [r for r in report.results if r.url in allowed]
    return report


def run(state: Dict[str, Any], extra_queries: List[str] | None = None) -> ResearchReport:
    debug = state.get("debug_analysis") or {}
    queries: List[str] = list(debug.get("search_queries") or [])
    if extra_queries:
        queries = extra_queries + queries
    if not queries:
        queries = [state.get("error_message", "")[:120]]

    previous = state.get("research") or {}
    seen_urls = {r.get("url") for r in previous.get("results", []) if r.get("url")}

    raw, notes = _collect(queries, state, seen_urls)  # type: ignore[arg-type]
    judged = _judge(raw, state)

    if judged:
        results = judged.results or raw[: settings.max_search_results]
        findings = judged.key_findings
        gaps = judged.gaps + notes
    else:
        results = raw[: settings.max_search_results]
        findings = [f"{r.source_type.value}: {r.title}" for r in results[:4]]
        gaps = notes + (
            ["Evidence was not scored by a model; sources are raw."]
            if not settings.llm_available
            else []
        )

    # Merge with anything a previous research pass already found.
    merged: List[ResearchResult] = [
        ResearchResult(**r) for r in previous.get("results", [])
    ] + results
    merged.sort(key=lambda r: r.relevance_score, reverse=True)

    return ResearchReport(
        query_used=list(dict.fromkeys(previous.get("query_used", []) + queries)),
        results=merged[:10],
        key_findings=list(dict.fromkeys(previous.get("key_findings", []) + findings))[:8],
        gaps=list(dict.fromkeys(gaps))[:6],
        degraded=not merged,
    )
