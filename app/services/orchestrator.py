"""Orchestrator selection.

Two backends implement the same contract:

    run_investigation(request, id)    -> final state dict
    stream_investigation(request, id) -> iterator of (node, partial state)

Everything above this module — the API, the SSE stream, the dashboard, the
Streamlit client, the report renderer — is unaware of which one ran. That is
what makes ``ORCHESTRATOR`` a one-variable switch rather than a rewrite.

The LangGraph backend is the default: it has no heavy dependencies and it works
without an API key. The CrewAI backend needs ``pip install -r
requirements-crewai.txt`` and a model.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterator, Optional, Tuple

from app.config.settings import settings
from app.models.schemas import InvestigationRequest

logger = logging.getLogger(__name__)

LANGGRAPH = "langgraph"
CREWAI = "crewai"


class OrchestratorUnavailable(RuntimeError):
    """The requested backend cannot run."""


def crewai_installed() -> bool:
    try:
        import crewai  # noqa: F401
    except Exception:  # noqa: BLE001 - ImportError, or a broken optional install
        return False
    return True


def active_backend() -> str:
    """Which backend will actually run, after availability checks."""
    requested = (settings.orchestrator or LANGGRAPH).strip().lower()
    if requested != CREWAI:
        return LANGGRAPH
    if not crewai_installed():
        logger.warning(
            "ORCHESTRATOR=crewai but crewai is not installed; using LangGraph. "
            "Install it with: pip install -r requirements-crewai.txt"
        )
        return LANGGRAPH
    if not settings.llm_available:
        logger.warning(
            "ORCHESTRATOR=crewai needs a model; no API key is configured, so the "
            "LangGraph backend will run in heuristic mode instead."
        )
        return LANGGRAPH
    return CREWAI


def backend_status() -> Dict[str, Any]:
    """Reported by /api/health so the active backend is never a guess."""
    requested = (settings.orchestrator or LANGGRAPH).strip().lower()
    active = active_backend()
    status = {
        "requested": requested,
        "active": active,
        "crewai_installed": crewai_installed(),
    }
    if requested != active:
        status["reason"] = (
            "crewai is not installed"
            if not crewai_installed()
            else "no model is configured"
            if not settings.llm_available
            else "unknown backend requested"
        )
    return status


def _module(backend: str):
    if backend == CREWAI:
        from app.crew import orchestrator as crew_orchestrator

        return crew_orchestrator
    from app.graph import graph as langgraph_orchestrator

    return langgraph_orchestrator


def run_investigation(
    request: InvestigationRequest, investigation_id: Optional[str] = None
) -> Dict[str, Any]:
    backend = active_backend()
    state = _module(backend).run_investigation(request, investigation_id)
    state["orchestrator"] = backend
    return state


def stream_investigation(
    request: InvestigationRequest, investigation_id: Optional[str] = None
) -> Iterator[Tuple[str, Dict[str, Any]]]:
    yield from _module(active_backend()).stream_investigation(request, investigation_id)
