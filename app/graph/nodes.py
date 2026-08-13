"""LangGraph nodes.

Every node takes the state and returns a partial update. Nodes never raise: a
failure is recorded as a warning and the graph keeps moving so the user always
gets a report.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List

from app.agents import (
    debug_agent,
    fix_agent,
    research_agent,
    reviewer_agent,
    root_cause_agent,
    validation_agent,
)
from app.config.settings import settings
from app.models.schemas import (
    Citation,
    InvestigationStatus,
    ReviewDecision,
    SourceType,
)
from app.services.knowledge_base import knowledge_base
from app.services.report import render_report

logger = logging.getLogger(__name__)

STAGE_LABELS = {
    "validate_input": "Input check",
    "knowledge_base_agent": "Knowledge base",
    "learn_from_result": "Learning",
    "debug_agent": "Debug analysis",
    "research_agent": "Research",
    "root_cause_agent": "Root cause",
    "fix_agent": "Proposed fix",
    "code_reviewer": "Code review",
    "validation_agent": "Validation",
    "compose_report": "Final report",
}


def _trace(
    state: Dict[str, Any], node: str, started: float, detail: str, status: str = "completed"
) -> List[Dict[str, Any]]:
    entry = {
        "node": node,
        "label": STAGE_LABELS.get(node, node),
        "status": status,
        "duration_ms": int((time.perf_counter() - started) * 1000),
        "detail": detail[:400],
    }
    return list(state.get("trace") or []) + [entry]


# --------------------------------------------------------------------------- #
# Nodes
# --------------------------------------------------------------------------- #
def validate_input(state: Dict[str, Any]) -> Dict[str, Any]:
    started = time.perf_counter()
    warnings: List[str] = list(state.get("warnings") or [])

    if not (state.get("error_message") or "").strip():
        return {
            "status": InvestigationStatus.FAILED.value,
            "warnings": warnings + ["No error message was provided."],
            "trace": _trace(state, "validate_input", started, "Rejected: empty error", "failed"),
        }

    repo = state.get("repository_url")
    if repo:
        from app.tools.http_client import is_safe_url

        if not is_safe_url(repo):
            warnings.append("Repository URL was rejected by the URL safety check and ignored.")
            state = {**state, "repository_url": None}

    if not state.get("stack_trace"):
        warnings.append("No stack trace supplied; the analysis relies on the message alone.")
    if settings.effective_demo_mode:
        warnings.append("Demo mode: results come from deterministic analysis, not a model.")

    return {
        "repository_url": state.get("repository_url"),
        "warnings": warnings,
        "status": InvestigationStatus.RUNNING.value,
        "trace": _trace(state, "validate_input", started, "Input accepted."),
    }


def knowledge_base_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Check whether this kind of error has already been solved.

    Runs a heuristic parse (no model call) to get an error type, then searches
    the local TF-IDF index. A strong match short-circuits the entire diagnosis
    and remediation pipeline for this run — no LLM call happens at all.
    """
    started = time.perf_counter()

    if not settings.kb_enabled:
        return {
            "kb_hit": False,
            "trace": _trace(
                state, "knowledge_base_agent", started, "Knowledge base disabled."
            ),
        }

    from app.agents.debug_agent import heuristic_analysis

    floor = heuristic_analysis(state)
    match = knowledge_base.lookup(
        error_type=floor.error_type,
        error_message=state.get("error_message") or "",
        framework=state.get("framework") or "",
    )

    if not match:
        return {
            "kb_hit": False,
            "trace": _trace(
                state,
                "knowledge_base_agent",
                started,
                "No known pattern matched; running full analysis.",
            ),
        }

    entry = match.entry
    detail = (
        f"Matched '{entry.title}' ({match.score:.0%} similarity, source={entry.source}) "
        "- serving cached diagnosis without a model call."
    )
    return {
        "kb_hit": True,
        "kb_match": match.model_dump(mode="json"),
        "debug_analysis": floor.model_dump(mode="json"),
        "root_cause": {
            "root_cause": entry.root_cause,
            "confidence": entry.confidence,
            "evidence": [
                f"Matched a known pattern in the knowledge base: '{entry.title}' "
                f"({match.score:.0%} similarity)."
            ],
            "alternative_hypotheses": [],
            "reasoning_summary": (
                "Served from the knowledge base rather than a fresh model diagnosis "
                "because a sufficiently similar error has been seen before."
            ),
            "recommended_direction": entry.fix,
            "missing_information": [],
        },
        "confidence": entry.confidence,
        "proposed_fix": {
            "explanation": entry.fix,
            "recommended_fix": entry.fix,
            "patch": entry.patch,
            "dependency_changes": [],
            "configuration_changes": [],
            "migration_steps": [],
            "alternative_fix": None,
            "assumptions": [
                "This fix is a generic pattern from the knowledge base, not verified "
                "against this specific codebase - review before applying."
            ],
            "risk": "MEDIUM",
        },
        "review_result": {
            "decision": "APPROVED",
            "score": 75,
            "issues": [],
            "required_changes": [],
            "recommendations": [
                "This is a cached pattern match, not a fresh independent review - "
                "verify it fits your exact code before applying."
            ],
            "regression_risk": "MEDIUM",
            "summary": (
                f"Served from the knowledge base ({entry.source}); "
                "not independently re-reviewed this run."
            ),
        },
        "warnings": list(state.get("warnings") or [])
        + [
            f"Answered from the knowledge base (pattern '{entry.id}', "
            f"{match.score:.0%} similarity) instead of a live model diagnosis. "
            "Confidence and the fix are generic, not specific to your exact code."
        ],
        "trace": _trace(state, "knowledge_base_agent", started, detail),
    }


def kb_router(state: Dict[str, Any]) -> str:
    """A strong knowledge-base match skips straight to validation."""
    if state.get("status") == InvestigationStatus.FAILED.value:
        return "final"
    return "validate" if state.get("kb_hit") else "diagnose"


def debug_node(state: Dict[str, Any]) -> Dict[str, Any]:
    started = time.perf_counter()
    analysis = debug_agent.run(state)
    return {
        "debug_analysis": analysis.model_dump(mode="json"),
        "trace": _trace(
            state,
            "debug_agent",
            started,
            f"{analysis.error_type} in {analysis.affected_file or 'unknown file'}",
        ),
    }


def research_node(state: Dict[str, Any]) -> Dict[str, Any]:
    started = time.perf_counter()
    iteration = state.get("research_iterations", 0) + 1

    extra: List[str] = []
    root = state.get("root_cause") or {}
    if root.get("missing_information"):
        extra = [str(item)[:120] for item in root["missing_information"][:2]]

    report = research_agent.run(state, extra_queries=extra)
    warnings = list(state.get("warnings") or [])
    if report.degraded:
        warnings.append("No external sources were reachable; the diagnosis is unsupported.")

    return {
        "research": report.model_dump(mode="json"),
        "research_iterations": iteration,
        "warnings": list(dict.fromkeys(warnings)),
        "trace": _trace(
            state,
            "research_agent",
            started,
            f"Pass {iteration}: {len(report.results)} sources kept.",
        ),
    }


def root_cause_node(state: Dict[str, Any]) -> Dict[str, Any]:
    started = time.perf_counter()
    analysis = root_cause_agent.run(state)
    return {
        "root_cause": analysis.model_dump(mode="json"),
        "confidence": analysis.confidence,
        "trace": _trace(
            state,
            "root_cause_agent",
            started,
            f"Confidence {analysis.confidence:.0%}: {analysis.root_cause[:160]}",
        ),
    }


def fix_node(state: Dict[str, Any]) -> Dict[str, Any]:
    started = time.perf_counter()
    fix = fix_agent.run(state)
    attempt = state.get("review_iterations", 0) + 1
    return {
        "proposed_fix": fix.model_dump(mode="json"),
        "trace": _trace(
            state,
            "fix_agent",
            started,
            f"Attempt {attempt}: {fix.recommended_fix[:160] or fix.explanation[:160]}",
        ),
    }


def reviewer_node(state: Dict[str, Any]) -> Dict[str, Any]:
    started = time.perf_counter()
    review = reviewer_agent.run(state)
    iterations = state.get("review_iterations", 0) + 1
    return {
        "review_result": review.model_dump(mode="json"),
        "review_iterations": iterations,
        "trace": _trace(
            state,
            "code_reviewer",
            started,
            f"{review.decision.value} ({review.score}/100) - {review.summary[:140]}",
        ),
    }


def validation_node(state: Dict[str, Any]) -> Dict[str, Any]:
    started = time.perf_counter()
    result = validation_agent.run(state)
    return {
        "validation_result": result.model_dump(mode="json"),
        "trace": _trace(
            state, "validation_agent", started, f"{result.status.value}: {result.summary[:160]}"
        ),
    }


def final_node(state: Dict[str, Any]) -> Dict[str, Any]:
    started = time.perf_counter()

    citations: List[Dict[str, Any]] = []
    for i, item in enumerate(((state.get("research") or {}).get("results") or [])[:8], start=1):
        citations.append(
            Citation(
                index=i,
                title=item.get("title", "Source"),
                url=item.get("url", ""),
                source_type=SourceType(item.get("source_type", "other")),
            ).model_dump(mode="json")
        )

    review = state.get("review_result") or {}
    approved = review.get("decision") == ReviewDecision.APPROVED.value
    confidence = state.get("confidence", 0.0)

    if approved:
        status = InvestigationStatus.COMPLETED.value
    elif state.get("proposed_fix"):
        status = InvestigationStatus.INCONCLUSIVE.value
    else:
        status = InvestigationStatus.INCONCLUSIVE.value

    warnings = list(state.get("warnings") or [])
    if not approved and state.get("review_iterations", 0) >= settings.max_fix_retries:
        warnings.append(
            "Unable to produce a verified fix within the retry budget. "
            "Treat the patch below as a draft."
        )
    if (
        confidence < settings.confidence_threshold
        and state.get("research_iterations", 0) >= settings.max_research_iterations
    ):
        warnings.append(
            f"Confidence stayed below {settings.confidence_threshold:.0%} after "
            f"{state.get('research_iterations')} research passes."
        )

    kb_learned = False
    learn_detail = "Not eligible for learning this run."
    if (
        settings.kb_enabled
        and settings.kb_learning_enabled
        and not state.get("kb_hit")
        and approved
        and confidence >= settings.kb_learn_min_confidence
    ):
        debug = state.get("debug_analysis") or {}
        root = state.get("root_cause") or {}
        fix = state.get("proposed_fix") or {}
        knowledge_base.learn(
            error_type=debug.get("error_type", "UnknownError"),
            error_message=state.get("error_message") or "",
            framework=state.get("framework") or "",
            language=state.get("language") or "",
            root_cause=root.get("root_cause", ""),
            fix=fix.get("recommended_fix") or fix.get("explanation", ""),
            patch=fix.get("patch", ""),
            confidence=confidence,
        )
        kb_learned = True
        learn_detail = (
            f"Saved as a new pattern (confidence {confidence:.0%}) for faster answers "
            "next time this error appears."
        )

    merged = {**state, "citations": citations, "status": status, "warnings": warnings}
    report = render_report(merged)

    trace = list(state.get("trace") or [])
    if kb_learned:
        trace.append(
            {
                "node": "learn_from_result",
                "label": STAGE_LABELS["learn_from_result"],
                "status": "completed",
                "duration_ms": 0,
                "detail": learn_detail,
            }
        )
    trace = _trace({**state, "trace": trace}, "compose_report", started, f"Report ready ({status}).")

    return {
        "citations": citations,
        "status": status,
        "kb_learned": kb_learned,
        "warnings": list(dict.fromkeys(warnings)),
        "final_response": report,
        "trace": trace,
    }


# --------------------------------------------------------------------------- #
# Routers
# --------------------------------------------------------------------------- #
def confidence_router(state: Dict[str, Any]) -> str:
    """High confidence goes to the Fix Agent; low confidence buys more research."""
    if state.get("status") == InvestigationStatus.FAILED.value:
        return "final"
    confidence = state.get("confidence", 0.0)
    iterations = state.get("research_iterations", 0)
    if confidence >= settings.confidence_threshold:
        return "fix"
    if iterations < settings.max_research_iterations:
        return "research"
    return "fix"  # budget spent: attempt a best-effort fix rather than giving up


def review_router(state: Dict[str, Any]) -> str:
    """Approved fixes are validated; rejected ones go back, within a retry cap."""
    review = state.get("review_result") or {}
    if review.get("decision") == ReviewDecision.APPROVED.value:
        return "validate"
    if state.get("review_iterations", 0) < settings.max_fix_retries:
        return "retry"
    return "validate"  # still validate the last draft so the user sees the checks
