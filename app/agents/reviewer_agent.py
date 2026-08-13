"""Code Reviewer Agent — an independent, adversarial check on the fix."""

from __future__ import annotations

import logging
from typing import Any, Dict

from app.config.settings import settings
from app.models.schemas import ReviewDecision, ReviewResult, RiskLevel
from app.prompts import REVIEWER_SYSTEM
from app.services.llm import llm_service, untrusted

logger = logging.getLogger(__name__)


def normalize(result: ReviewResult, patch: str) -> ReviewResult:
    """Keep decision, score and feedback coherent.

    Shared by both orchestrators. A rejection with no required changes wastes the
    Fix Agent's retry, and an empty patch must never be approved, so both are
    corrected here rather than trusted from the model.
    """
    if result.decision == ReviewDecision.APPROVED and result.score < 70:
        result.score = 70
    if result.decision == ReviewDecision.REJECTED and result.score >= 70:
        result.score = 65
    if result.decision == ReviewDecision.REJECTED and not result.required_changes:
        result.required_changes = [
            "Ground the fix in the cited evidence and address the issues listed."
        ]
    if not (patch or "").strip():
        result.decision = ReviewDecision.REJECTED
        result.score = min(result.score, 40)
        result.required_changes.append("Produce an actual patch; none was provided.")
    return result


def run(state: Dict[str, Any]) -> ReviewResult:
    fix = state.get("proposed_fix") or {}
    root = state.get("root_cause") or {}

    if not settings.llm_available:
        return ReviewResult(
            decision=ReviewDecision.REJECTED,
            score=0,
            summary="No model configured, so the fix could not be independently reviewed.",
            required_changes=["Configure OPENROUTER_API_KEY and rerun the investigation."],
            regression_risk=RiskLevel.MEDIUM,
        )

    evidence = "\n".join(
        f"- {r.get('title')} ({r.get('url')})"
        for r in (state.get("research") or {}).get("results", [])[:6]
    )

    user = "\n".join(
        part
        for part in [
            f"ROOT CAUSE UNDER TEST: {root.get('root_cause')}",
            f"Root cause confidence: {root.get('confidence')}",
            "",
            "PROPOSED FIX:",
            f"explanation: {fix.get('explanation')}",
            f"recommended_fix: {fix.get('recommended_fix')}",
            f"dependency_changes: {fix.get('dependency_changes')}",
            f"configuration_changes: {fix.get('configuration_changes')}",
            f"assumptions: {fix.get('assumptions')}",
            f"self-declared risk: {fix.get('risk')}",
            "",
            "PATCH:",
            (fix.get("patch") or "(no patch produced)")[:6000],
            "",
            "AVAILABLE EVIDENCE:",
            evidence or "None - be strict about unsupported claims.",
            "",
            untrusted("original_source_code", state.get("source_code") or "", 8000),
            "",
            "Review independently. Reject anything the evidence does not support.",
        ]
        if part
    )

    try:
        result = llm_service.complete_json(
            REVIEWER_SYSTEM, user, ReviewResult, max_tokens=2000
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Reviewer failed: %s", exc)
        return ReviewResult(
            decision=ReviewDecision.REJECTED,
            score=0,
            summary=f"Review could not complete: {exc}",
            regression_risk=RiskLevel.HIGH,
        )

    return normalize(result, fix.get("patch") or "")
