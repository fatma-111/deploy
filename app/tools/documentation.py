"""Documentation and package-registry lookups.

Both PyPI and the npm registry expose free, keyless JSON APIs. They are the
cheapest way to answer "does this package still ship that module?" style
questions, and they give the Research Agent an authoritative anchor.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from app.tools.http_client import fetch_json, fetch_text, html_to_text


class PackageInfo(BaseModel):
    name: str
    registry: str
    latest_version: str = ""
    summary: str = ""
    homepage: str = ""
    docs_url: str = ""
    repository: str = ""
    recent_versions: list[str] = []


def fetch_documentation(url: str, limit: int = 6000) -> Optional[str]:
    """Fetch a documentation page and return readable text."""
    html = fetch_text(url, max_chars=200_000)
    if not html:
        return None
    return html_to_text(html, limit)


def pypi_package(name: str) -> Optional[PackageInfo]:
    data = fetch_json(f"https://pypi.org/pypi/{name}/json")
    if not data or "info" not in data:
        return None
    info = data["info"]
    project_urls = info.get("project_urls") or {}
    versions = sorted(data.get("releases", {}).keys())[-8:]
    return PackageInfo(
        name=info.get("name", name),
        registry="pypi",
        latest_version=info.get("version", ""),
        summary=(info.get("summary") or "")[:400],
        homepage=info.get("home_page") or project_urls.get("Homepage", "") or "",
        docs_url=project_urls.get("Documentation", "") or "",
        repository=project_urls.get("Source", "")
        or project_urls.get("Repository", "")
        or "",
        recent_versions=versions,
    )


def npm_package(name: str) -> Optional[PackageInfo]:
    data = fetch_json(f"https://registry.npmjs.org/{name}")
    if not data or "name" not in data:
        return None
    latest = (data.get("dist-tags") or {}).get("latest", "")
    repo = data.get("repository")
    repo_url = repo.get("url", "") if isinstance(repo, dict) else (repo or "")
    versions = sorted((data.get("versions") or {}).keys())[-8:]
    return PackageInfo(
        name=data.get("name", name),
        registry="npm",
        latest_version=latest,
        summary=(data.get("description") or "")[:400],
        homepage=data.get("homepage", "") or "",
        repository=repo_url.replace("git+", "").replace(".git", ""),
        recent_versions=versions,
    )


def inspect_dependency(name: str, language: str | None = None) -> Optional[PackageInfo]:
    """Look up a dependency in the registry that matches the language."""
    clean = name.split("==")[0].split("@")[0].split(">")[0].split("<")[0].strip()
    if not clean:
        return None
    lang = (language or "").lower()
    if lang.startswith(("javascript", "typescript", "node")):
        return npm_package(clean) or pypi_package(clean)
    return pypi_package(clean) or npm_package(clean)
