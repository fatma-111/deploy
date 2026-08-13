"""The LangGraph orchestration.

    START
      -> validate_input
      -> knowledge_base_agent
           HIT  -> validation_agent (skips every LLM call for this run)
           MISS -> debug_agent
      -> research_agent
      -> root_cause_agent
      -> confidence_router
           LOW  -> research_agent   (capped by MAX_RESEARCH_ITERATIONS)
           HIGH -> fix_agent
                     -> code_reviewer
                     -> review_router
                          REJECTED -> fix_agent   (capped by MAX_FIX_RETRIES)
                          APPROVED -> validation_agent
                                        -> compose_report (also saves a new
                                           pattern here when this was a fresh,
                                           approved, high-confidence diagnosis)
                                        -> END

No checkpointer is attached, so the state is discarded when the run ends.

Note: LangGraph forbids a node from sharing a name with a state key, so the node
that renders the report is called ``compose_report`` while the state key it
writes stays ``final_response``.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, Optional

from langgraph.graph import END, START, StateGraph

from app.config.settings import settings
from app.graph.nodes import (
    confidence_router,
    debug_node,
    final_node,
    fix_node,
    kb_router,
    knowledge_base_node,
    research_node,
    review_router,
    reviewer_node,
    root_cause_node,
    validate_input,
    validation_node,
)
from app.models.schemas import InvestigationRequest
from app.state.state import InvestigationState, initial_state

logger = logging.getLogger(__name__)

_compiled = None


def build_graph():
    graph = StateGraph(InvestigationState)

    graph.add_node("validate_input", validate_input)
    graph.add_node("knowledge_base_agent", knowledge_base_node)
    graph.add_node("debug_agent", debug_node)
    graph.add_node("research_agent", research_node)
    graph.add_node("root_cause_agent", root_cause_node)
    graph.add_node("fix_agent", fix_node)
    graph.add_node("code_reviewer", reviewer_node)
    graph.add_node("validation_agent", validation_node)
    graph.add_node("compose_report", final_node)

    graph.add_edge(START, "validate_input")
    graph.add_edge("validate_input", "knowledge_base_agent")

    graph.add_conditional_edges(
        "knowledge_base_agent",
        kb_router,
        {
            "validate": "validation_agent",
            "diagnose": "debug_agent",
            "final": "compose_report",
        },
    )

    graph.add_edge("debug_agent", "research_agent")
    graph.add_edge("research_agent", "root_cause_agent")

    graph.add_conditional_edges(
        "root_cause_agent",
        confidence_router,
        {"research": "research_agent", "fix": "fix_agent", "final": "compose_report"},
    )

    graph.add_edge("fix_agent", "code_reviewer")

    graph.add_conditional_edges(
        "code_reviewer",
        review_router,
        {"retry": "fix_agent", "validate": "validation_agent"},
    )

    graph.add_edge("validation_agent", "compose_report")
    graph.add_edge("compose_report", END)

    return graph.compile()


def get_graph():
    """Compile once per process; the graph itself holds no state."""
    global _compiled
    if _compiled is None:
        _compiled = build_graph()
    return _compiled


def _recursion_budget() -> int:
    # research loops + fix/review loops + fixed nodes, with headroom.
    return 8 + settings.max_research_iterations * 2 + settings.max_fix_retries * 2


def run_investigation(
    request: InvestigationRequest, investigation_id: Optional[str] = None
) -> Dict[str, Any]:
    """Execute one full investigation and return the final state."""
    started = time.perf_counter()
    state = initial_state(
        investigation_id=investigation_id or str(uuid.uuid4()),
        started_at=started,
        error_message=request.error_message,
        stack_trace=request.stack_trace,
        logs=request.logs,
        source_code=request.source_code,
        repository_url=request.repository_url,
        language=request.language,
        framework=request.framework,
        dependencies=request.dependencies,
        environment=request.environment,
    )

    result = get_graph().invoke(
        state, config={"recursion_limit": _recursion_budget()}
    )
    result["duration_ms"] = int((time.perf_counter() - started) * 1000)
    return result


def stream_investigation(
    request: InvestigationRequest, investigation_id: Optional[str] = None
):
    """Yield ``(node_name, partial_state)`` as each node finishes."""
    started = time.perf_counter()
    state = initial_state(
        investigation_id=investigation_id or str(uuid.uuid4()),
        started_at=started,
        error_message=request.error_message,
        stack_trace=request.stack_trace,
        logs=request.logs,
        source_code=request.source_code,
        repository_url=request.repository_url,
        language=request.language,
        framework=request.framework,
        dependencies=request.dependencies,
        environment=request.environment,
    )
    for chunk in get_graph().stream(
        state, config={"recursion_limit": _recursion_budget()}, stream_mode="updates"
    ):
        for node, update in chunk.items():
            yield node, update
