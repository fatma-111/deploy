"""Live discovery of free OpenRouter models.

The free tier rotates constantly: models are added, pulled and repriced without
notice, and any ID hard-coded today will 404 within weeks. Rather than ship a
list that rots, BugHound asks OpenRouter what is free right now.

The catalog endpoint is public and needs no API key, so this works before the
user has configured anything.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from app.config.settings import settings
from app.tools.http_client import fetch_json

logger = logging.getLogger(__name__)

CATALOG_URL = "https://openrouter.ai/api/v1/models"
CACHE_TTL_SECONDS = 3600
MIN_CONTEXT = 32_000

# Providers whose free models have historically suited code diagnosis. Used only
# to break ties in the ranking — never to exclude anything.
PREFERRED_HINTS = ("code", "coder", "laguna", "nemotron", "qwen", "llama", "gpt-oss")

_lock = threading.Lock()
_cache: Dict[str, Any] = {"fetched_at": 0.0, "models": []}


class FreeModel(BaseModel):
    id: str
    name: str = ""
    context_length: int = 0
    max_completion_tokens: int = 0
    supports_tools: bool = False
    expires: Optional[str] = None


def _is_free(model: Dict[str, Any]) -> bool:
    pricing = model.get("pricing") or {}
    try:
        return float(pricing.get("prompt", 1)) == 0.0 and float(pricing.get("completion", 1)) == 0.0
    except (TypeError, ValueError):
        return False


def _expiring_today_or_earlier(model: Dict[str, Any]) -> bool:
    """Skip models OpenRouter has already flagged for removal."""
    expiry = model.get("expiration_date")
    if not expiry:
        return False
    return str(expiry) <= time.strftime("%Y-%m-%d")


def _score(model: FreeModel) -> tuple:
    """Rank: preferred providers first, then bigger context, then more output."""
    preferred = any(hint in model.id.lower() for hint in PREFERRED_HINTS)
    return (not preferred, -model.context_length, -model.max_completion_tokens)


def fetch_free_models(force: bool = False) -> List[FreeModel]:
    """Return the currently free models, cached for an hour. Never raises."""
    with _lock:
        fresh = time.time() - _cache["fetched_at"] < CACHE_TTL_SECONDS
        if fresh and _cache["models"] and not force:
            return list(_cache["models"])

    data = fetch_json(CATALOG_URL)
    if not data or "data" not in data:
        logger.info("Model catalog unavailable; keeping any previously cached list.")
        with _lock:
            return list(_cache["models"])

    models: List[FreeModel] = []
    for entry in data["data"]:
        if not _is_free(entry) or _expiring_today_or_earlier(entry):
            continue
        provider = entry.get("top_provider") or {}
        context = int(entry.get("context_length") or provider.get("context_length") or 0)
        if context < MIN_CONTEXT:
            continue
        models.append(
            FreeModel(
                id=entry.get("id", ""),
                name=entry.get("name", ""),
                context_length=context,
                max_completion_tokens=int(provider.get("max_completion_tokens") or 0),
                supports_tools="tools" in (entry.get("supported_parameters") or []),
                expires=entry.get("expiration_date"),
            )
        )

    models.sort(key=_score)
    with _lock:
        _cache["models"] = models
        _cache["fetched_at"] = time.time()

    logger.info("Discovered %d free OpenRouter models", len(models))
    return list(models)


def discovered_model_ids(limit: int = 4) -> List[str]:
    """Free model IDs to append to the fallback chain."""
    if not settings.model_discovery_enabled:
        return []
    return [m.id for m in fetch_free_models()[:limit]]


def catalog_summary() -> Dict[str, Any]:
    models = fetch_free_models()
    return {
        "count": len(models),
        "checked_at": _cache["fetched_at"],
        "models": [m.model_dump() for m in models[:12]],
        "source": CATALOG_URL,
    }
