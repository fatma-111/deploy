"""Deterministic parsing works with no model available."""

from app.agents.debug_agent import heuristic_analysis


def test_parses_module_not_found(langchain_bug):
    analysis = heuristic_analysis(langchain_bug)
    assert analysis.error_type == "ModuleNotFoundError"
    assert analysis.affected_file == "app/main.py"
    assert "langchain" in analysis.suspected_dependencies
    assert analysis.search_queries


def test_reports_missing_information():
    analysis = heuristic_analysis({"error_message": "KeyError: 'user_id'"})
    assert "Full stack trace" in analysis.missing_information
    assert analysis.error_type == "KeyError"


def test_javascript_stack_is_parsed():
    analysis = heuristic_analysis(
        {
            "error_message": "TypeError: undefined is not a function",
            "stack_trace": "    at handler (/app/server.js:12)",
            "language": "JavaScript",
        }
    )
    assert analysis.error_type == "TypeError"
    assert analysis.affected_function == "handler"
