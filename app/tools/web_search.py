"""Free web research.

No paid search API is required. We query DuckDuckGo's public HTML endpoint,
which needs no key, and classify each hit by source type so the Research Agent
can prefer official documentation over forum noise.

If the endpoint is unreachable the tool returns an empty list and the caller
degrades gracefully instead of failing the investigation.
"""

from __future__ import annotations

import logging
import re
from typing import List
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

from pydantic import BaseModel

from app.config.settings import settings
from app.models.schemas import SourceType
from app.tools.http_client import fetch_text, html_to_text

logger = logging.getLogger(__name__)

DDG_ENDPOINT = "https://html.duckduckgo.com/html/?q={query}"

_RESULT = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>'
    r'(?:.*?<a[^>]+class="result__snippet"[^>]*>(?P<snippet>.*?)</a>)?',
    re.DOTALL,
)

OFFICIAL_DOC_HINTS = (
    "docs.",
    "/docs/",
    "readthedocs",
    "developer.",
    "documentation",
    "/reference/",
    "/api/",
)
COMMUNITY_HINTS = ("stackoverflow", "reddit", "medium", "dev.to", "discourse")


class SearchHit(BaseModel):
    title: str
    url: str
    snippet: str = ""
    source_type: SourceType = SourceType.OTHER


def classify(url: str) -> SourceType:
    low = url.lower()
    if "github.com" in low and "/issues/" in low:
        return SourceType.GITHUB_ISSUE
    if "github.com" in low and "/releases" in low:
        return SourceType.RELEASE_NOTES
    if "changelog" in low:
        return SourceType.CHANGELOG
    if "github.com" in low:
        return SourceType.GITHUB_REPO
    if any(hint in low for hint in OFFICIAL_DOC_HINTS):
        return SourceType.OFFICIAL_DOCS
    if any(hint in low for hint in COMMUNITY_HINTS):
        return SourceType.COMMUNITY
    return SourceType.OTHER


def _clean_url(href: str) -> str:
    """DuckDuckGo wraps results in a redirect: /l/?uddg=<encoded>."""
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [])
        if target:
            return unquote(target[0])
    return href


def search_web(query: str, limit: int | None = None) -> List[SearchHit]:
    """Run one free web search. Never raises."""
    if not settings.web_search_enabled or not query.strip():
        return []

    cap = limit or settings.max_search_results
    html = fetch_text(
        DDG_ENDPOINT.format(query=quote_plus(query)),
        max_chars=180_000,
        headers={"Accept": "text/html"},
    )
    if not html:
        logger.info("Web search unavailable for query: %s", query)
        return []

    hits: List[SearchHit] = []
    seen: set[str] = set()
    for match in _RESULT.finditer(html):
        url = _clean_url(match.group("href"))
        if not url.startswith("http") or url in seen:
            continue
        seen.add(url)
        hits.append(
            SearchHit(
                title=html_to_text(match.group("title") or "", 200) or url,
                url=url,
                snippet=html_to_text(match.group("snippet") or "", 400),
                source_type=classify(url),
            )
        )
        if len(hits) >= cap:
            break
    return hits


def rank_hits(hits: List[SearchHit]) -> List[SearchHit]:
    """Official docs and GitHub outrank community posts."""
    weight = {
        SourceType.OFFICIAL_DOCS: 0,
        SourceType.GITHUB_REPO: 1,
        SourceType.GITHUB_ISSUE: 2,
        SourceType.RELEASE_NOTES: 3,
        SourceType.CHANGELOG: 4,
        SourceType.COMMUNITY: 5,
        SourceType.OTHER: 6,
    }
    return sorted(hits, key=lambda h: weight.get(h.source_type, 9))
