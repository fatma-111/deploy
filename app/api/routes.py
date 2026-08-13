"""HTTP surface: health, investigate, streaming, samples and dashboard data."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.config.settings import settings
from app.services.orchestrator import (
    backend_status,
    run_investigation,
    stream_investigation,
)
from app.graph.nodes import STAGE_LABELS
from app.models.schemas import (
    DebugAnalysis,
    HealthResponse,
    InvestigationRequest,
    InvestigationResponse,
    InvestigationStatus,
    ProposedFix,
    ResearchReport,
    ReviewResult,
    RiskLevel,
    Severity,
    ValidationResult,
)
from app.services import activity
from app.services.knowledge_base import knowledge_base
from app.services.model_catalog import catalog_summary
from app.services.notifications import notify_report
from app.services.samples import SAMPLES

logger = logging.getLogger(__name__)
router = APIRouter()


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def to_response(state: Dict[str, Any]) -> InvestigationResponse:
    debug = state.get("debug_analysis")
    root = state.get("root_cause") or {}
    fix = state.get("proposed_fix")
    review = state.get("review_result")
    validation = state.get("validation_result")
    research = state.get("research")

    return InvestigationResponse(
        investigation_id=state.get("investigation_id", str(uuid.uuid4())),
        status=InvestigationStatus(state.get("status", "completed")),
        error_type=(debug or {}).get("error_type", "Unknown"),
        severity=Severity((debug or {}).get("severity", "major")),
        root_cause=root.get("root_cause", ""),
        confidence=float(state.get("confidence") or 0.0),
        debug_analysis=DebugAnalysis(**debug) if debug else None,
        research=ResearchReport(**research) if research else None,
        alternative_hypotheses=root.get("alternative_hypotheses", []),
        proposed_fix=ProposedFix(**fix) if fix else None,
        review=ReviewResult(**review) if review else None,
        validation=ValidationResult(**validation) if validation else None,
        citations=state.get("citations", []),
        risk=RiskLevel((fix or {}).get("risk", "MEDIUM")),
        trace=state.get("trace", []),
        warnings=state.get("warnings", []),
        duration_ms=state.get("duration_ms", 0),
        demo_mode=settings.effective_demo_mode,
        orchestrator=state.get("orchestrator", "langgraph"),
        kb_hit=bool(state.get("kb_hit")),
        final_response=state.get("final_response", ""),
    )


# --------------------------------------------------------------------------- #
# routes
# --------------------------------------------------------------------------- #
@router.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        llm_configured=bool(settings.openrouter_api_key),
        github_token_configured=bool(settings.github_token),
        demo_mode=settings.effective_demo_mode,
        model=settings.openrouter_model,
        provider=settings.provider_name,
        orchestrator=backend_status(),
        knowledge_base_seed_entries=knowledge_base.stats()["seed_count"],
        email_notifications_configured=bool(
            settings.n8n_webhook_enabled and settings.n8n_webhook_url
        ),
    )


@router.post("/investigate", response_model=InvestigationResponse, tags=["investigation"])
def investigate(request: InvestigationRequest) -> InvestigationResponse:
    try:
        state = run_investigation(request)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Investigation failed")
        raise HTTPException(status_code=500, detail=f"Investigation failed: {exc}") from exc

    response = to_response(state)
    payload = response.model_dump(mode="json")
    payload["_language"] = request.language

    notified = notify_report(to=request.notify_email, response=payload)
    response.notified = notified
    payload["notified"] = notified

    activity.record(payload)
    return response


@router.post("/investigate/stream", tags=["investigation"])
def investigate_stream(request: InvestigationRequest) -> StreamingResponse:
    """Server-sent events: one message per completed node."""

    investigation_id = str(uuid.uuid4())

    def event_stream():
        # Seed the id so the streamed result and the recorded activity agree.
        final_state: Dict[str, Any] = {"investigation_id": investigation_id}
        try:
            for node, update in stream_investigation(request, investigation_id):
                final_state.update(update or {})
                trace = (update or {}).get("trace") or []
                detail = trace[-1]["detail"] if trace else ""
                event = {
                    "type": "stage",
                    "node": node,
                    "label": STAGE_LABELS.get(node, node),
                    "detail": detail,
                    "confidence": final_state.get("confidence", 0.0),
                }
                yield f"data: {json.dumps(event)}\n\n"

            response = to_response(final_state)
            payload = response.model_dump(mode="json")
            payload["_language"] = request.language

            notified = notify_report(to=request.notify_email, response=payload)
            payload["notified"] = notified

            activity.record(payload)
            yield f"data: {json.dumps({'type': 'result', 'result': payload})}\n\n"
        except Exception as exc:  # noqa: BLE001
            logger.exception("Streaming investigation failed")
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
        yield "data: {\"type\": \"done\"}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/models/free", tags=["system"])
def free_models() -> Dict[str, Any]:
    """What OpenRouter is currently serving at zero cost.

    Free model IDs rotate constantly, so this is the authoritative answer rather
    than anything hard-coded in the repo.
    """
    summary = catalog_summary()
    summary["configured"] = {
        "provider": settings.provider_name,
        "base_url": settings.openrouter_base_url,
        "primary": settings.openrouter_model,
        "fast": settings.fast_model,
        "fallbacks": settings.fallback_models,
        "discovery_enabled": settings.model_discovery_enabled,
    }
    return summary


@router.get("/knowledge-base/stats", tags=["knowledge-base"])
def knowledge_base_stats() -> Dict[str, Any]:
    """Seed vs learned counts, framework breakdown, and current configuration."""
    return knowledge_base.stats()


@router.get("/knowledge-base/search", tags=["knowledge-base"])
def knowledge_base_search(q: str = "") -> Dict[str, Any]:
    """Preview what the RAG lookup would return for a given error, without
    running a full investigation."""
    if not q.strip():
        return {"query": q, "match": None}
    match = knowledge_base.lookup(error_type="", error_message=q, framework="")
    return {
        "query": q,
        "match": match.model_dump(mode="json") if match else None,
    }


@router.get("/knowledge-base/entries", tags=["knowledge-base"])
def knowledge_base_entries() -> Dict[str, Any]:
    """Every entry currently in the index (seed + learned), for the dashboard."""
    entries = knowledge_base.all_entries()
    return {
        "total": len(entries),
        "entries": [e.model_dump(mode="json") for e in entries],
    }


@router.get("/samples", tags=["investigation"])
def samples() -> Dict[str, Any]:
    """Ready-made bugs for demos and evaluation."""
    return {"samples": SAMPLES}


@router.get("/dashboard/metrics", tags=["dashboard"])
def dashboard_metrics() -> Dict[str, Any]:
    data = activity.metrics()
    data["feed"] = activity.recent(12)
    data["knowledge_base"] = knowledge_base.stats()
    data["config"] = {
        "model": settings.openrouter_model,
        "provider": settings.provider_name,
        "orchestrator": backend_status()["active"],
        "demo_mode": settings.effective_demo_mode,
        "confidence_threshold": settings.confidence_threshold,
        "max_research_iterations": settings.max_research_iterations,
        "max_fix_retries": settings.max_fix_retries,
    }
    return data


@router.delete("/dashboard/metrics", tags=["dashboard"])
def reset_metrics() -> Dict[str, str]:
    activity.clear()
    return {"status": "cleared"}
