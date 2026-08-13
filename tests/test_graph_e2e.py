"""End to end: a known bug reaches a final report without network or LLM."""

from app.graph.graph import run_investigation
from app.models.schemas import InvestigationRequest


def test_investigation_completes(langchain_bug):
    state = run_investigation(InvestigationRequest(**langchain_bug))

    assert state["status"] in {"completed", "inconclusive"}
    assert state["final_response"].startswith("# Bug Investigation Report")
    assert state["debug_analysis"]["error_type"] == "ModuleNotFoundError"
    assert state["research_iterations"] <= 2
    assert state["review_iterations"] <= 2
    assert "trace" in state and len(state["trace"]) >= 5


def test_empty_error_is_rejected_gracefully():
    request = InvestigationRequest(error_message="   x   ")
    state = run_investigation(request)
    assert state["final_response"]


def test_unsafe_repository_url_is_dropped():
    state = run_investigation(
        InvestigationRequest(
            error_message="KeyError: 'x'", repository_url="http://169.254.169.254/"
        )
    )
    assert state.get("repository_url") in (None, "")
    assert any("URL safety" in w for w in state["warnings"])
