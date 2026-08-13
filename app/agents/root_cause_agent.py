"""Root Cause Agent — decides what is actually broken, and how sure it is."""

from __future__ import annotations

import logging
from typing import Any, Dict

from app.config.settings import settings
from app.models.schemas import RootCauseAnalysis
from app.prompts import ROOT_CAUSE_SYSTEM
from app.services.llm import llm_service, untrusted

logger = logging.getLogger(__name__)


def _evidence_block(state: Dict[str, Any]) -> str:
    research = state.get("research") or {}
    lines = []
    for i, item in enumerate(research.get("results", [])[:8], start=1):
        lines.append(
            f"[{i}] {item.get('title')} ({item.get('source_type')}) - {item.get('url')}\n"
            f"    evidence: {(item.get('relevant_evidence') or '')[:500]}"
        )
    findings = research.get("key_findings") or []
    if findings:
        lines.append("Key findings: " + "; ".join(findings[:6]))
    return "\n".join(lines) or "No external evidence was retrieved."


def run(state: Dict[str, Any]) -> RootCauseAnalysis:
    debug = state.get("debug_analysis") or {}

    if not settings.llm_available:
        # Deterministic fallback: honest low confidence, never a fake certainty.
        return RootCauseAnalysis(
            root_cause=(
                f"{debug.get('error_type', 'The error')} originates in "
                f"{debug.get('affected_file') or 'the failing module'}. "
                "No model was available to confirm the mechanism."
            ),
            confidence=0.35,
            evidence=[
                f"{r.get('title')} - {r.get('url')}"
                for r in (state.get("research") or {}).get("results", [])[:3]
            ],
            alternative_hypotheses=["Dependency version mismatch", "Renamed or moved API"],
            reasoning_summary="Heuristic analysis only; configure OPENROUTER_API_KEY for a model-backed root cause.",
            recommended_direction="Verify the installed package version against the official documentation.",
            missing_information=debug.get("missing_information") or [],
        )

    user = "\n".join(
        part
        for part in [
            f"Iteration: research pass {state.get('research_iterations', 0)}",
            f"Language: {state.get('language')} / Framework: {state.get('framework')}",
            f"Dependencies: {', '.join(state.get('dependencies') or []) or 'unknown'}",
            f"Environment: {state.get('environment') or 'unknown'}",
            "",
            "DEBUG ANALYSIS:",
            f"error_type={debug.get('error_type')}, file={debug.get('affected_file')}, "
            f"function={debug.get('affected_function')}",
            f"hypotheses: {debug.get('initial_hypotheses')}",
            f"suspected packages: {debug.get('suspected_dependencies')}",
            "",
            "RESEARCH EVIDENCE:",
            _evidence_block(state),
            "",
            untrusted("error_message", state.get("error_message", ""), 3000),
            untrusted("stack_trace", state.get("stack_trace") or "", 6000),
            untrusted("source_code", state.get("source_code") or "", 8000),
            "",
            "Decide the root cause and calibrate the confidence honestly.",
        ]
        if part is not None
    )

    try:
        return llm_service.complete_json(ROOT_CAUSE_SYSTEM, user, RootCauseAnalysis)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Root Cause Agent failed: %s", exc)
        return RootCauseAnalysis(
            root_cause="The root cause could not be determined; the model call failed.",
            confidence=0.0,
            reasoning_summary=f"Model error: {exc}",
        )
