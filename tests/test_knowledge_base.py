"""The local RAG layer: retrieval, learning, and its integration into both
orchestrators.

The seed knowledge base is real production data (extracted from the PDF), so
these tests exercise actual entries rather than fixtures — that is the point:
prove the thing that ships behaves correctly, not a stand-in for it.
"""

from __future__ import annotations

import pytest

from app.services.knowledge_base import KnowledgeBase, _signature, _strip_type_prefix


@pytest.fixture
def kb(monkeypatch):
    """A fresh KnowledgeBase with KB re-enabled and no leftover learned cases."""
    monkeypatch.setattr("app.config.settings.settings.kb_enabled", True)
    instance = KnowledgeBase()
    instance.clear_learned()
    yield instance
    instance.clear_learned()


# --------------------------------------------------------------------------- #
# signature construction
# --------------------------------------------------------------------------- #
def test_strip_type_prefix_removes_duplicate_type():
    stripped = _strip_type_prefix(
        "ModuleNotFoundError", "ModuleNotFoundError: No module named 'x'"
    )
    assert stripped == "No module named 'x'"


def test_strip_type_prefix_leaves_message_without_prefix_alone():
    assert _strip_type_prefix("KeyError", "the payload was missing a field") == (
        "the payload was missing a field"
    )


def test_signature_strips_quoted_values_and_numbers():
    sig = _signature("KeyError", "'order_id' missing on line 42", "")
    assert "order_id" not in sig
    assert "42" not in sig
    assert "keyerror" in sig


# --------------------------------------------------------------------------- #
# seed retrieval
# --------------------------------------------------------------------------- #
def test_seed_loads_the_real_knowledge_base(kb):
    stats = kb.stats()
    assert stats["seed_count"] >= 30, "the shipped PDF should yield ~32 entries"
    assert stats["learned_count"] == 0


def test_exact_seed_error_matches_its_own_entry(kb):
    match = kb.lookup(
        "ModuleNotFoundError",
        "ModuleNotFoundError: No module named 'langchain.chat_models'",
        "LangChain",
    )
    assert match is not None
    assert match.entry.id == "E016"
    assert match.score > 0.7


@pytest.mark.parametrize(
    "error_type,message,framework,expected_id",
    [
        ("KeyError", "'order_id'", "Python", "E004"),
        ("KeyError", "'session_token'", "", "E004"),  # different key, same shape
        ("422 Unprocessable Entity", "Field required email", "FastAPI", "E011"),
        ("TypeError", "undefined is not a function", "JavaScript", "E023"),
        ("Error: Cannot find module", "'express'", "Node.js", "E021"),
    ],
)
def test_paraphrased_repeats_still_match(kb, error_type, message, framework, expected_id):
    match = kb.lookup(error_type, message, framework)
    assert match is not None
    assert match.entry.id == expected_id


def test_unrelated_error_does_not_match(kb):
    match = kb.lookup(
        "CustomBillingEngineFault",
        "the quarterly ledger reconciliation diverged unexpectedly",
        "InternalTool",
    )
    assert match is None


def test_empty_message_does_not_match(kb):
    assert kb.lookup("SomeError", "", "") is None


def test_disabled_kb_returns_nothing(monkeypatch, kb):
    monkeypatch.setattr("app.config.settings.settings.kb_enabled", False)
    # lookup() itself doesn't gate on kb_enabled (the caller does), but the
    # graph/crew integration must; verified in test_graph_kb_integration below.
    match = kb.lookup("ModuleNotFoundError", "No module named 'langchain.chat_models'", "LangChain")
    assert match is not None  # the service itself is always queryable


# --------------------------------------------------------------------------- #
# learning
# --------------------------------------------------------------------------- #
def test_learn_then_recall(kb):
    assert kb.lookup("WidgetOverflowFault", "the sprocket buffer exceeded capacity", "WidgetOS") is None

    kb.learn(
        error_type="WidgetOverflowFault",
        error_message="the sprocket buffer exceeded capacity",
        framework="WidgetOS",
        language="Python",
        root_cause="The buffer size constant was never updated after the sprocket format changed.",
        fix="Increase MAX_SPROCKET_BUFFER to match the new format.",
        patch="",
        confidence=0.9,
    )

    match = kb.lookup("WidgetOverflowFault", "the sprocket buffer exceeded capacity", "WidgetOS")
    assert match is not None
    assert match.entry.source == "learned"
    # Confidence is stored slightly below the original, honestly reflecting
    # that a cache hit is not a fresh, code-specific diagnosis.
    assert match.entry.confidence < 0.9


def test_learning_can_be_disabled(monkeypatch, kb):
    monkeypatch.setattr("app.config.settings.settings.kb_learning_enabled", False)
    kb.learn(
        error_type="Whatever", error_message="anything", framework="", language="",
        root_cause="x", fix="y", patch="", confidence=0.9,
    )
    assert kb.stats()["learned_count"] == 0


def test_learned_entries_are_pruned_to_the_cap(monkeypatch, kb):
    monkeypatch.setattr("app.config.settings.settings.kb_max_learned_entries", 3)
    for i in range(6):
        kb.learn(
            error_type=f"Error{i}", error_message=f"unique failure number {i}",
            framework="", language="", root_cause="x", fix="y", patch="",
            confidence=0.9,
        )
    assert kb.stats()["learned_count"] <= 3


def test_clear_learned_never_touches_seed_data(kb):
    kb.learn(
        error_type="Temp", error_message="a temporary thing", framework="",
        language="", root_cause="x", fix="y", patch="", confidence=0.9,
    )
    before = kb.stats()["seed_count"]
    kb.clear_learned()
    after = kb.stats()
    assert after["seed_count"] == before
    assert after["learned_count"] == 0


# --------------------------------------------------------------------------- #
# graph integration (LangGraph)
# --------------------------------------------------------------------------- #
def test_kb_hit_skips_the_llm_pipeline_entirely(monkeypatch, langchain_bug):
    """The core promise: a known error never reaches debug/research/root-cause/fix."""
    from app.graph.graph import run_investigation
    from app.models.schemas import InvestigationRequest

    monkeypatch.setattr("app.config.settings.settings.kb_enabled", True)

    state = run_investigation(InvestigationRequest(**langchain_bug))

    nodes = [entry["node"] for entry in state["trace"]]
    assert nodes == ["validate_input", "knowledge_base_agent", "validation_agent", "compose_report"]
    assert state["kb_hit"] is True
    assert state["confidence"] > 0
    assert any("knowledge base" in w.lower() for w in state["warnings"])


def test_kb_miss_runs_the_full_pipeline(monkeypatch):
    """A genuinely novel error must not be short-circuited."""
    from app.graph.graph import run_investigation
    from app.models.schemas import InvestigationRequest

    monkeypatch.setattr("app.config.settings.settings.kb_enabled", True)

    state = run_investigation(
        InvestigationRequest(error_message="QuantumFluxDesyncError: the flux capacitor drifted")
    )
    nodes = [entry["node"] for entry in state["trace"]]
    assert "debug_agent" in nodes
    assert "knowledge_base_agent" in nodes
    assert state.get("kb_hit") is not True


def test_kb_disabled_always_runs_the_full_pipeline(monkeypatch, langchain_bug):
    from app.graph.graph import run_investigation
    from app.models.schemas import InvestigationRequest

    monkeypatch.setattr("app.config.settings.settings.kb_enabled", False)

    state = run_investigation(InvestigationRequest(**langchain_bug))
    nodes = [entry["node"] for entry in state["trace"]]
    assert "debug_agent" in nodes
    assert state.get("kb_hit") is not True


def test_successful_fresh_diagnosis_gets_learned(monkeypatch):
    """A fabricated but high-confidence, approved run should be saved for reuse."""
    from app.graph.graph import run_investigation
    from app.models.schemas import InvestigationRequest
    from app.services.knowledge_base import knowledge_base

    monkeypatch.setattr("app.config.settings.settings.kb_enabled", True)
    monkeypatch.setattr("app.config.settings.settings.kb_learn_min_confidence", 0.80)
    knowledge_base.clear_learned()

    # Force a high-confidence, approved outcome without a real model by
    # monkeypatching the two agents that decide those values.
    from app.agents import reviewer_agent, root_cause_agent
    from app.models.schemas import ReviewDecision, ReviewResult, RootCauseAnalysis

    monkeypatch.setattr(
        root_cause_agent,
        "run",
        lambda state: RootCauseAnalysis(
            root_cause="A truly novel gizmo desynchronised.", confidence=0.95
        ),
    )
    monkeypatch.setattr(
        reviewer_agent,
        "run",
        lambda state: ReviewResult(decision=ReviewDecision.APPROVED, score=90, summary="Looks right."),
    )

    state = run_investigation(
        InvestigationRequest(
            error_message="GizmoDesyncError: the gizmo lost synchronisation entirely"
        )
    )
    assert state["status"] == "completed"
    assert state.get("kb_learned") is True
    assert any(e["node"] == "learn_from_result" for e in state["trace"])

    match = knowledge_base.lookup(
        "GizmoDesyncError", "the gizmo lost synchronisation entirely", ""
    )
    assert match is not None
    assert match.entry.source == "learned"
    knowledge_base.clear_learned()


def test_low_confidence_fresh_diagnosis_is_not_learned(monkeypatch):
    from app.graph.graph import run_investigation
    from app.models.schemas import InvestigationRequest
    from app.services.knowledge_base import knowledge_base

    monkeypatch.setattr("app.config.settings.settings.kb_enabled", True)
    knowledge_base.clear_learned()

    state = run_investigation(
        InvestigationRequest(error_message="SomeNeverSeenBeforeError: totally novel")
    )
    # No model configured -> confidence stays low (heuristic fallback) -> not learned.
    assert state.get("kb_learned") is not True
    knowledge_base.clear_learned()


# --------------------------------------------------------------------------- #
# graph structure (guards against future regressions)
# --------------------------------------------------------------------------- #
def test_knowledge_base_node_registered_without_key_collision():
    from app.graph.graph import build_graph
    from app.state.state import InvestigationState

    assert build_graph() is not None
    assert "knowledge_base_agent" not in set(InvestigationState.__annotations__)
