"""Fix Agent — turns a confirmed root cause into an applicable patch."""

from __future__ import annotations

import logging
from typing import Any, Dict

from app.config.settings import settings
from app.models.schemas import ProposedFix, RiskLevel
from app.prompts import FIX_SYSTEM
from app.services.llm import llm_service, untrusted

logger = logging.getLogger(__name__)


def run(state: Dict[str, Any]) -> ProposedFix:
    root = state.get("root_cause") or {}
    review = state.get("review_result") or {}
    previous = state.get("proposed_fix") or {}

    if not settings.llm_available:
        return ProposedFix(
            explanation=(
                "No model is configured, so BugHound cannot generate a grounded patch. "
                "Set OPENROUTER_API_KEY to enable the Fix Agent."
            ),
            recommended_fix=root.get("recommended_direction", ""),
            patch="",
            risk=RiskLevel.MEDIUM,
            assumptions=["Generated without model support."],
        )

    retry_block = ""
    if review.get("required_changes"):
        retry_block = (
            "A previous attempt was REJECTED by the reviewer. "
            "Address every point below in this revision.\n"
            f"Reviewer score: {review.get('score')}\n"
            f"Required changes: {review.get('required_changes')}\n"
            f"Issues: {[i.get('detail') for i in review.get('issues', [])]}\n\n"
            f"Previous patch:\n{(previous.get('patch') or '')[:2500]}\n"
        )

    evidence = "\n".join(
        f"- {r.get('title')} ({r.get('url')}): {(r.get('relevant_evidence') or '')[:300]}"
        for r in (state.get("research") or {}).get("results", [])[:6]
    )

    user = "\n".join(
        part
        for part in [
            retry_block,
            f"ROOT CAUSE: {root.get('root_cause')}",
            f"Confidence: {root.get('confidence')}",
            f"Reasoning: {root.get('reasoning_summary')}",
            f"Direction: {root.get('recommended_direction')}",
            "",
            "EVIDENCE:",
            evidence or "No external evidence available - stay conservative.",
            "",
            f"Language: {state.get('language')} / Framework: {state.get('framework')}",
            f"Dependencies: {', '.join(state.get('dependencies') or []) or 'unknown'}",
            f"Affected file: {(state.get('debug_analysis') or {}).get('affected_file')}",
            "",
            untrusted("source_code", state.get("source_code") or "", 12000),
            untrusted("error_message", state.get("error_message", ""), 2000),
            "",
            "Produce the minimal correct fix as a unified diff.",
        ]
        if part
    )

    try:
        return llm_service.complete_json(FIX_SYSTEM, user, ProposedFix, max_tokens=2600)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Fix Agent failed: %s", exc)
        return ProposedFix(
            explanation=f"The Fix Agent could not produce a patch: {exc}",
            risk=RiskLevel.HIGH,
        )
