"""Public GitHub research.

Everything here works anonymously. ``GITHUB_TOKEN`` is optional and only raises
the rate limit from 60 to 5000 requests/hour.
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional
from urllib.parse import quote_plus

from pydantic import BaseModel

from app.config.settings import settings
from app.tools.http_client import fetch_json, fetch_text

logger = logging.getLogger(__name__)

REPO_URL = re.compile(r"github\.com/(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)")


def _headers() -> dict:
    headers = {"Accept": "application/vnd.github+json"}
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    return headers


class RepoHit(BaseModel):
    full_name: str
    url: str
    description: str = ""
    stars: int = 0


class IssueHit(BaseModel):
    title: str
    url: str
    state: str = "open"
    body: str = ""
    repository: str = ""
    comments: int = 0


def parse_repo_url(url: str) -> Optional[tuple[str, str]]:
    """Extract (owner, repo) from any GitHub URL, or None."""
    if not url:
        return None
    match = REPO_URL.search(url)
    if not match:
        return None
    return match.group("owner"), match.group("repo").removesuffix(".git")


def search_repositories(query: str, limit: int = 3) -> List[RepoHit]:
    data = fetch_json(
        f"{settings.github_api_url}/search/repositories",
        headers=_headers(),
        params={"q": query, "sort": "stars", "per_page": limit},
    )
    if not data or "items" not in data:
        return []
    return [
        RepoHit(
            full_name=item.get("full_name", ""),
            url=item.get("html_url", ""),
            description=(item.get("description") or "")[:400],
            stars=item.get("stargazers_count", 0),
        )
        for item in data["items"][:limit]
    ]


def search_issues(query: str, limit: int = 4, repo: str | None = None) -> List[IssueHit]:
    """Search public issues. ``repo`` narrows to ``owner/name``."""
    q = f"{query} repo:{repo}" if repo else query
    data = fetch_json(
        f"{settings.github_api_url}/search/issues",
        headers=_headers(),
        params={"q": q, "sort": "reactions", "per_page": limit},
    )
    if not data or "items" not in data:
        return []
    hits: List[IssueHit] = []
    for item in data["items"][:limit]:
        url = item.get("html_url", "")
        repo_name = ""
        parsed = parse_repo_url(url)
        if parsed:
            repo_name = f"{parsed[0]}/{parsed[1]}"
        hits.append(
            IssueHit(
                title=item.get("title", "")[:250],
                url=url,
                state=item.get("state", "open"),
                body=(item.get("body") or "")[:1200],
                repository=repo_name,
                comments=item.get("comments", 0),
            )
        )
    return hits


def get_readme(owner: str, repo: str) -> Optional[str]:
    data = fetch_json(
        f"{settings.github_api_url}/repos/{owner}/{repo}/readme",
        headers={**_headers(), "Accept": "application/vnd.github.raw"},
    )
    if isinstance(data, dict) and data.get("download_url"):
        return fetch_text(data["download_url"])
    return None


def get_file(owner: str, repo: str, path: str, ref: str = "HEAD") -> Optional[str]:
    return fetch_text(
        f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path.lstrip('/')}"
    )


def get_latest_releases(owner: str, repo: str, limit: int = 3) -> List[dict]:
    data = fetch_json(
        f"{settings.github_api_url}/repos/{owner}/{repo}/releases",
        headers=_headers(),
        params={"per_page": limit},
    )
    if not isinstance(data, list):
        return []
    return [
        {
            "name": item.get("name") or item.get("tag_name", ""),
            "tag": item.get("tag_name", ""),
            "url": item.get("html_url", ""),
            "body": (item.get("body") or "")[:1500],
            "published_at": item.get("published_at", ""),
        }
        for item in data[:limit]
    ]


def issue_search_query(error_type: str, package: str | None) -> str:
    base = quote_plus(error_type)[:120]
    return f"{error_type} {package or ''} in:title,body type:issue".strip()
