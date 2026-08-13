"""The single typed state object that flows through the LangGraph.

The state lives only for the duration of one execution. Nothing is persisted:
no checkpointer, no database, no disk. Every field below is documented so a
coding agent knows exactly who writes it and who reads it.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


class InvestigationState(TypedDict, total=False):
    # ---- identity ---------------------------------------------------------
    investigation_id: str  # uuid4, generated at entry, echoed in the response
    started_at: float  # perf_counter reference for duration reporting

    # ---- raw user input (written by validate_input, read by every agent) ---
    error_message: str
    stack_trace: Optional[str]
    logs: Optional[str]
    source_code: Optional[str]
    repository_url: Optional[str]
    language: Optional[str]
    framework: Optional[str]
    dependencies: List[str]
    environment: Optional[str]

    # ---- knowledge_base_agent (RAG lookup) --------------------------------
    kb_match: Optional[Dict[str, Any]]  # KnowledgeMatch dump, or None
    kb_hit: bool  # True when the investigation was served from the KB
    kb_learned: bool  # True when this run's result was saved for next time

    # ---- debug_agent ------------------------------------------------------
    debug_analysis: Optional[Dict[str, Any]]  # DebugAnalysis dump

    # ---- research_agent ---------------------------------------------------
    research: Optional[Dict[str, Any]]  # ResearchReport dump (accumulated)
    research_iterations: int  # guard against infinite research loops

    # ---- root_cause_agent -------------------------------------------------
    root_cause: Optional[Dict[str, Any]]  # RootCauseAnalysis dump
    confidence: float

    # ---- fix_agent --------------------------------------------------------
    proposed_fix: Optional[Dict[str, Any]]  # ProposedFix dump

    # ---- code_reviewer ----------------------------------------------------
    review_result: Optional[Dict[str, Any]]  # ReviewResult dump
    review_iterations: int  # guard against infinite fix/review loops

    # ---- validation_agent -------------------------------------------------
    validation_result: Optional[Dict[str, Any]]  # ValidationResult dump

    # ---- output -----------------------------------------------------------
    citations: List[Dict[str, Any]]
    trace: List[Dict[str, Any]]  # public stage log (never chain-of-thought)
    warnings: List[str]  # degraded tools, truncated input, capped loops
    status: str  # InvestigationStatus value
    final_response: str  # rendered markdown report


def initial_state(**payload: Any) -> InvestigationState:
    """Build a fresh state with all counters zeroed."""
    base: InvestigationState = {
        "research_iterations": 0,
        "review_iterations": 0,
        "confidence": 0.0,
        "citations": [],
        "trace": [],
        "warnings": [],
        "dependencies": [],
        "status": "running",
        "final_response": "",
        "kb_hit": False,
        "kb_learned": False,
    }
    base.update(payload)  # type: ignore[typeddict-item]
    return base
