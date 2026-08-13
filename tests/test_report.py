"""The rendered report is complete and leaks nothing private."""

from app.services.report import render_report

STATE = {
    "debug_analysis": {"error_type": "ModuleNotFoundError", "severity": "critical"},
    "root_cause": {
        "root_cause": "The class moved to langchain_openai in 0.2.",
        "evidence": ["Official migration guide"],
        "reasoning_summary": "Import path changed during the package split.",
    },
    "confidence": 0.92,
    "proposed_fix": {"recommended_fix": "Update the import.", "patch": "- old\n+ new", "risk": "LOW"},
    "review_result": {"decision": "APPROVED", "score": 88, "summary": "Minimal and correct."},
    "validation_result": {"status": "PASSED", "summary": "3/4 checks passed.", "checks": []},
    "citations": [{"index": 1, "title": "Docs", "url": "https://x.dev", "source_type": "official_docs"}],
    "status": "completed",
    "warnings": [],
}


def test_report_contains_every_section():
    report = render_report(STATE)
    for heading in ("Root cause", "Recommended fix", "Code review", "Validation", "Sources"):
        assert heading in report
    assert "92%" in report
    assert "```diff" in report


def test_report_handles_missing_pieces():
    report = render_report({"status": "inconclusive"})
    assert "Bug Investigation Report" in report
