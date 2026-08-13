"""Ephemeral in-process activity feed for the dashboard.

This is a bounded ``deque`` in RAM, not a database. It holds nothing on disk, it
is not shared between workers, and it is empty again after a restart. It exists
purely so the dashboard has a live feed and rolling counters; the investigation
pipeline itself never reads from it.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List

MAX_ENTRIES = 50

_lock = threading.Lock()
_feed: Deque[Dict[str, Any]] = deque(maxlen=MAX_ENTRIES)


def record(response: Dict[str, Any]) -> None:
    entry = {
        "id": response.get("investigation_id", "")[:8],
        "error_type": response.get("error_type", "Unknown"),
        "severity": response.get("severity", "major"),
        "status": response.get("status", "completed"),
        "confidence": response.get("confidence", 0.0),
        "root_cause": (response.get("root_cause") or "")[:140],
        "review": ((response.get("review") or {}).get("decision")) or "N/A",
        "risk": response.get("risk", "MEDIUM"),
        "duration_ms": response.get("duration_ms", 0),
        "language": response.get("_language") or "—",
        "kb_hit": bool(response.get("kb_hit")),
        "created_at": time.time(),
    }
    with _lock:
        _feed.appendleft(entry)


def recent(limit: int = 20) -> List[Dict[str, Any]]:
    with _lock:
        return list(_feed)[:limit]


def metrics() -> Dict[str, Any]:
    with _lock:
        items = list(_feed)

    total = len(items)
    resolved = sum(
        1 for i in items if i["status"] == "completed" and i["review"] == "APPROVED"
    )
    active = total - resolved
    by_type: Dict[str, int] = {}
    for item in items:
        by_type[item["error_type"]] = by_type.get(item["error_type"], 0) + 1

    avg_conf = round(sum(i["confidence"] for i in items) / total, 3) if total else 0.0
    avg_ms = int(sum(i["duration_ms"] for i in items) / total) if total else 0
    kb_hits = sum(1 for i in items if i.get("kb_hit"))
    kb_hit_rate = round(kb_hits / total, 3) if total else 0.0

    severity: Dict[str, int] = {}
    for item in items:
        severity[item["severity"]] = severity.get(item["severity"], 0) + 1

    return {
        "total": total,
        "resolved": resolved,
        "active": active,
        "resolution_rate": round(resolved / total, 3) if total else 0.0,
        "avg_confidence": avg_conf,
        "avg_duration_ms": avg_ms,
        "kb_hits": kb_hits,
        "kb_hit_rate": kb_hit_rate,
        "by_error_type": sorted(
            ({"label": k, "count": v} for k, v in by_type.items()),
            key=lambda x: x["count"],
            reverse=True,
        )[:6],
        "by_severity": severity,
        "timeline": [
            {"t": item["created_at"], "confidence": item["confidence"]}
            for item in reversed(items)
        ],
    }


def clear() -> None:
    with _lock:
        _feed.clear()
