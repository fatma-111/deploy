"""The CrewAI backend, exercised with stubbed crews.

Skipped when crewai is not installed, so the default test run stays dependency
free. When it is installed, the crews are replaced by fakes: the point is to
verify the controller's routing, the loop caps and the output contract, not to
spend model quota.
"""

import pytest

crewai = pytest.importorskip("crewai", reason="optional CrewAI backend not installed")

from app.models.schemas import InvestigationRequest  # noqa: E402


class FakeTaskOutput:
    def __init__(self, model):
        self.pydantic = model
        self.json_dict = None


class FakeCrewResult:
    def __init__(self, *models):
        self.tasks_output = [FakeTaskOutput(m) for m in models]


class FakeCrew:
    def __init__(self, result):
        self._result = result

    def kickoff(self, *a, **k):
        return self._result


@pytest.fixture
def crew_module(monkeypatch):
    from app.crew import orchestrator as crew

    monkeypatch.setattr("app.config.settings.settings.llm_api_key_raw", "sk-test")
    monkeypatch.setattr("app.config.settings.settings.demo_mode", False)
    return crew


def _diagnosis(crew, confidence):
    from app.models.schemas import (
        DebugAnalysis,
        ResearchReport,
        ResearchResult,
        RootCauseAnalysis,
    )

    return FakeCrewResult(
        DebugAnalysis(error_type="ModuleNotFoundError", affected_file="app/main.py"),
        ResearchReport(
            results=[
                ResearchResult(
                    title="Migration guide",
                    url="https://docs.example.dev/migrate",
                    relevant_evidence="The class moved packages in 0.2.",
                    relevance_score=0.9,
                )
            ]
        ),
        RootCauseAnalysis(
            root_cause="ChatOpenAI moved to langchain_openai.",
            confidence=confidence,
            missing_information=["installed version"],
        ),
    )


def _remediation(decision, score):
    from app.models.schemas import ProposedFix, ReviewResult

    return FakeCrewResult(
        ProposedFix(
            recommended_fix="Update the import.",
            patch="--- a/app/main.py\n+++ b/app/main.py\n@@\n-from langchain.chat_models import ChatOpenAI\n+from langchain_openai import ChatOpenAI\n",
        ),
        ReviewResult(decision=decision, score=score, summary="Checked."),
    )


def test_high_confidence_and_approval_completes(crew_module, monkeypatch, langchain_bug):
    monkeypatch.setattr(
        crew_module, "diagnosis_crew", lambda *a, **k: FakeCrew(_diagnosis(crew_module, 0.93))
    )
    monkeypatch.setattr(
        crew_module, "remediation_crew", lambda *a, **k: FakeCrew(_remediation("APPROVED", 88))
    )

    state = crew_module.run_investigation(InvestigationRequest(**langchain_bug))

    assert state["status"] == "completed"
    assert state["confidence"] == 0.93
    assert state["research_iterations"] == 1, "high confidence must not re-run diagnosis"
    assert state["review_iterations"] == 1
    assert state["final_response"].startswith("# Bug Investigation Report")
    assert state["citations"][0]["url"] == "https://docs.example.dev/migrate"
    assert state["validation_result"]["status"] in {"PASSED", "WARNING"}


def test_low_confidence_repeats_diagnosis_within_the_cap(
    crew_module, monkeypatch, langchain_bug
):
    calls = []

    def fake_diagnosis(request, previous=None):
        calls.append(previous)
        return FakeCrew(_diagnosis(crew_module, 0.30))

    monkeypatch.setattr(crew_module, "diagnosis_crew", fake_diagnosis)
    monkeypatch.setattr(
        crew_module, "remediation_crew", lambda *a, **k: FakeCrew(_remediation("APPROVED", 80))
    )

    from app.config.settings import settings

    state = crew_module.run_investigation(InvestigationRequest(**langchain_bug))

    assert len(calls) == settings.max_research_iterations
    assert calls[0] is None and calls[1] is not None, "a retry must carry prior context"
    assert state["research_iterations"] == settings.max_research_iterations
    assert any("Confidence stayed below" in w for w in state["warnings"])


def test_rejected_review_retries_then_stops(crew_module, monkeypatch, langchain_bug):
    rejections = []

    def fake_remediation(request, root_cause, evidence, rejection=None):
        rejections.append(rejection)
        return FakeCrew(_remediation("REJECTED", 40))

    monkeypatch.setattr(
        crew_module, "diagnosis_crew", lambda *a, **k: FakeCrew(_diagnosis(crew_module, 0.9))
    )
    monkeypatch.setattr(crew_module, "remediation_crew", fake_remediation)

    from app.config.settings import settings

    state = crew_module.run_investigation(InvestigationRequest(**langchain_bug))

    assert len(rejections) == settings.max_fix_retries, "the retry loop must be capped"
    assert rejections[1]["required_changes"], "feedback must reach the next attempt"
    assert state["status"] == "inconclusive"
    assert any("retry budget" in w for w in state["warnings"])


def test_streamed_stages_match_the_langgraph_contract(
    crew_module, monkeypatch, langchain_bug
):
    monkeypatch.setattr(
        crew_module, "diagnosis_crew", lambda *a, **k: FakeCrew(_diagnosis(crew_module, 0.9))
    )
    monkeypatch.setattr(
        crew_module, "remediation_crew", lambda *a, **k: FakeCrew(_remediation("APPROVED", 90))
    )

    nodes = [
        node
        for node, _ in crew_module.stream_investigation(
            InvestigationRequest(**langchain_bug)
        )
    ]
    assert nodes == [
        "validate_input",
        "knowledge_base_agent",
        "debug_agent",
        "research_agent",
        "root_cause_agent",
        "fix_agent",
        "code_reviewer",
        "validation_agent",
        "compose_report",
    ]


def test_crew_backend_refuses_to_run_without_a_model(monkeypatch, langchain_bug):
    from app.crew import orchestrator as crew

    monkeypatch.setattr("app.config.settings.settings.llm_api_key_raw", "")
    monkeypatch.setattr("app.config.settings.settings.openrouter_api_key_raw", "")
    with pytest.raises(crew.CrewUnavailable):
        crew.run_investigation(InvestigationRequest(**langchain_bug))


def test_no_crew_enables_memory(crew_module):
    """CrewAI memory is backed by ChromaDB; this project promises no database."""
    import inspect

    source = inspect.getsource(crew_module)
    assert "memory=False" in source
    assert "memory=True" not in source


# --------------------------------------------------------------------------- #
# knowledge base short-circuit (CrewAI backend)
# --------------------------------------------------------------------------- #
def test_kb_hit_skips_both_crews_entirely(crew_module, monkeypatch, langchain_bug):
    """The core promise, mirrored for the CrewAI backend: zero crew kickoffs."""
    monkeypatch.setattr("app.config.settings.settings.kb_enabled", True)

    def boom(*a, **k):
        raise AssertionError("a crew must not run when the knowledge base has a match")

    monkeypatch.setattr(crew_module, "diagnosis_crew", boom)
    monkeypatch.setattr(crew_module, "remediation_crew", boom)

    state = crew_module.run_investigation(InvestigationRequest(**langchain_bug))

    nodes = [e["node"] for e in state["trace"]]
    assert nodes == [
        "validate_input",
        "knowledge_base_agent",
        "validation_agent",
        "compose_report",
    ]
    assert state["confidence"] > 0
    assert any("knowledge base" in w.lower() for w in state["warnings"])


def test_kb_miss_runs_both_crews_as_before(crew_module, monkeypatch, langchain_bug):
    monkeypatch.setattr("app.config.settings.settings.kb_enabled", True)
    # A message nothing in the seed KB resembles.
    langchain_bug = {**langchain_bug, "error_message": "QuantumFluxDesyncError: drift"}

    monkeypatch.setattr(
        crew_module, "diagnosis_crew", lambda *a, **k: FakeCrew(_diagnosis(crew_module, 0.9))
    )
    monkeypatch.setattr(
        crew_module, "remediation_crew", lambda *a, **k: FakeCrew(_remediation("APPROVED", 88))
    )

    state = crew_module.run_investigation(InvestigationRequest(**langchain_bug))
    nodes = [e["node"] for e in state["trace"]]
    assert "debug_agent" in nodes
    assert "fix_agent" in nodes


def test_kb_disabled_ignores_a_known_error(crew_module, monkeypatch, langchain_bug):
    monkeypatch.setattr("app.config.settings.settings.kb_enabled", False)
    monkeypatch.setattr(
        crew_module, "diagnosis_crew", lambda *a, **k: FakeCrew(_diagnosis(crew_module, 0.9))
    )
    monkeypatch.setattr(
        crew_module, "remediation_crew", lambda *a, **k: FakeCrew(_remediation("APPROVED", 88))
    )

    state = crew_module.run_investigation(InvestigationRequest(**langchain_bug))
    nodes = [e["node"] for e in state["trace"]]
    assert "debug_agent" in nodes, "disabling the KB must not silently skip real diagnosis"


def test_fresh_high_confidence_approval_is_learned(crew_module, monkeypatch, langchain_bug):
    from app.services.knowledge_base import knowledge_base

    monkeypatch.setattr("app.config.settings.settings.kb_enabled", True)
    monkeypatch.setattr("app.config.settings.settings.kb_learn_min_confidence", 0.80)
    langchain_bug = {
        **langchain_bug,
        "error_message": "GizmoDesyncError: the crew-side gizmo lost sync",
    }
    knowledge_base.clear_learned()

    monkeypatch.setattr(
        crew_module, "diagnosis_crew", lambda *a, **k: FakeCrew(_diagnosis(crew_module, 0.93))
    )
    monkeypatch.setattr(
        crew_module, "remediation_crew", lambda *a, **k: FakeCrew(_remediation("APPROVED", 90))
    )

    state = crew_module.run_investigation(InvestigationRequest(**langchain_bug))
    assert state.get("kb_learned") is True

    match = knowledge_base.lookup(
        "GizmoDesyncError", "the crew-side gizmo lost sync", langchain_bug["framework"]
    )
    assert match is not None
    assert match.entry.source == "learned"
    knowledge_base.clear_learned()
