"""Conditional edges and loop caps."""

from app.config.settings import settings
from app.graph.nodes import confidence_router, review_router


def test_high_confidence_goes_to_fix():
    assert confidence_router({"confidence": 0.93, "research_iterations": 1}) == "fix"


def test_low_confidence_buys_more_research():
    assert confidence_router({"confidence": 0.4, "research_iterations": 0}) == "research"


def test_research_loop_is_capped():
    state = {"confidence": 0.1, "research_iterations": settings.max_research_iterations}
    assert confidence_router(state) == "fix"


def test_approved_review_goes_to_validation():
    state = {"review_result": {"decision": "APPROVED"}, "review_iterations": 1}
    assert review_router(state) == "validate"


def test_rejected_review_retries():
    state = {"review_result": {"decision": "REJECTED"}, "review_iterations": 0}
    assert review_router(state) == "retry"


def test_fix_retries_are_capped():
    state = {
        "review_result": {"decision": "REJECTED"},
        "review_iterations": settings.max_fix_retries,
    }
    assert review_router(state) == "validate"


def test_failed_input_short_circuits():
    assert confidence_router({"status": "failed"}) == "final"
