"""Structural guards on the graph itself.

LangGraph refuses to compile when a node shares its name with a state key. That
is easy to reintroduce, and the failure only surfaces at runtime, so it gets a
test of its own.
"""

from app.graph.graph import build_graph
from app.graph.nodes import STAGE_LABELS
from app.state.state import InvestigationState

EXPECTED_NODES = {
    "validate_input",
    "debug_agent",
    "research_agent",
    "root_cause_agent",
    "fix_agent",
    "code_reviewer",
    "validation_agent",
    "compose_report",
}


def test_no_node_name_collides_with_a_state_key():
    state_keys = set(InvestigationState.__annotations__)
    assert EXPECTED_NODES.isdisjoint(state_keys)


def test_graph_compiles():
    assert build_graph() is not None


def test_every_node_has_a_public_label():
    assert EXPECTED_NODES <= set(STAGE_LABELS)
