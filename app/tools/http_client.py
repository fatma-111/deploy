"""Hardened HTTP access for every outbound tool call.

All external traffic goes through here so that SSRF protection, timeouts and
size caps are applied in exactly one place.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from typing import Optional
from urllib.parse import urlparse

import httpx

from app.config.settings import settings

logger = logging.getLogger(__name__)

USER_AGENT = f"{settings.app_name}/{settings.version} (+bug-investigation-agent)"

BLOCKED_HOSTS = {
    "localhost",
    "metadata.google.internal",
    "metadata",
    "instance-data",
}

# Cloud metadata endpoints and anything not routable on the public internet.
BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # includes 169.254.169.254
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


class UnsafeURLError(ValueError):
    """The URL points somewhere the agent is not allowed to reach."""


def is_safe_url(url: str) -> bool:
    try:
        assert_safe_url(url)
        return True
    except UnsafeURLError:
        return False


def assert_safe_url(url: str) -> str:
    """Validate scheme, host and every resolved IP. Returns the URL."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise UnsafeURLError(f"Blocked scheme: {parsed.scheme or 'none'}")
    host = (parsed.hostname or "").lower()
    if not host:
        raise UnsafeURLError("Missing host")
    if host in BLOCKED_HOSTS or host.endswith(".local") or host.endswith(".internal"):
        raise UnsafeURLError(f"Blocked host: {host}")

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"Host does not resolve: {host}") from exc

    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        for network in BLOCKED_NETWORKS:
            if address.version == network.version and address in network:
                raise UnsafeURLError(f"Blocked private address for {host}")
    return url


def fetch_text(
    url: str,
    *,
    headers: Optional[dict] = None,
    max_chars: Optional[int] = None,
    timeout: Optional[int] = None,
) -> Optional[str]:
    """GET a URL and return its body, or ``None`` on any failure."""
    try:
        assert_safe_url(url)
    except UnsafeURLError as exc:
        logger.warning("Refused unsafe URL %s: %s", url, exc)
        return None

    cap = max_chars or settings.max_fetch_chars
    request_headers = {"User-Agent": USER_AGENT, "Accept-Language": "en"}
    request_headers.update(headers or {})

    try:
        with httpx.Client(
            timeout=timeout or settings.tool_timeout_seconds,
            follow_redirects=True,
            max_redirects=3,
        ) as client:
            response = client.get(url, headers=request_headers)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if "image" in content_type or "octet-stream" in content_type:
                return None
            return response.text[:cap]
    except Exception as exc:  # noqa: BLE001 - tools must degrade, never crash
        logger.info("Fetch failed for %s: %s", url, exc)
        return None


def fetch_json(
    url: str, *, headers: Optional[dict] = None, params: Optional[dict] = None
):
    try:
        assert_safe_url(url)
    except UnsafeURLError as exc:
        logger.warning("Refused unsafe URL %s: %s", url, exc)
        return None

    request_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    request_headers.update(headers or {})
    try:
        with httpx.Client(
            timeout=settings.tool_timeout_seconds, follow_redirects=True
        ) as client:
            response = client.get(url, headers=request_headers, params=params)
            response.raise_for_status()
            return response.json()
    except Exception as exc:  # noqa: BLE001
        logger.info("JSON fetch failed for %s: %s", url, exc)
        return None


def html_to_text(html: str, limit: Optional[int] = None) -> str:
    """Strip tags without pulling in a heavy parser dependency."""
    import re
    from html import unescape

    text = re.sub(r"(?is)<(script|style|nav|footer|svg)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()[: (limit or settings.max_fetch_chars)]
