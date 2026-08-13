"""Backend selection and the CrewAI path.

The dispatcher must never leave the app broken: asking for a backend that is not
installed or not configured degrades to LangGraph with a warning rather than
failing the request.
"""

import pytest

from app.services import orchestrator as dispatcher


def test_langgraph_is_the_default(monkeypatch):
    monkeypatch.setattr("app.config.settings.settings.orchestrator", "langgraph")
    assert dispatcher.active_backend() == dispatcher.LANGGRAPH


def test_unknown_backend_falls_back(monkeypatch):
    monkeypatch.setattr("app.config.settings.settings.orchestrator", "autogen")
    assert dispatcher.active_backend() == dispatcher.LANGGRAPH


def test_crewai_without_the_package_falls_back(monkeypatch):
    monkeypatch.setattr("app.config.settings.settings.orchestrator", "crewai")
    monkeypatch.setattr(dispatcher, "crewai_installed", lambda: False)
    assert dispatcher.active_backend() == dispatcher.LANGGRAPH
    status = dispatcher.backend_status()
    assert status["requested"] == "crewai"
    assert status["active"] == "langgraph"
    assert "not installed" in status["reason"]


def test_crewai_without_a_model_falls_back(monkeypatch):
    """CrewAI agents cannot run heuristically; LangGraph can."""
    monkeypatch.setattr("app.config.settings.settings.orchestrator", "crewai")
    monkeypatch.setattr(dispatcher, "crewai_installed", lambda: True)
    # conftest already forces demo mode / no key
    assert dispatcher.active_backend() == dispatcher.LANGGRAPH
    assert "no model" in dispatcher.backend_status()["reason"]


def test_crewai_selected_when_installed_and_configured(monkeypatch):
    monkeypatch.setattr("app.config.settings.settings.orchestrator", "crewai")
    monkeypatch.setattr(dispatcher, "crewai_installed", lambda: True)
    monkeypatch.setattr("app.config.settings.settings.llm_api_key_raw", "sk-test")
    monkeypatch.setattr("app.config.settings.settings.demo_mode", False)
    assert dispatcher.active_backend() == dispatcher.CREWAI


def test_dispatcher_tags_the_result(monkeypatch, langchain_bug):
    from app.models.schemas import InvestigationRequest

    monkeypatch.setattr("app.config.settings.settings.orchestrator", "langgraph")
    state = dispatcher.run_investigation(InvestigationRequest(**langchain_bug))
    assert state["orchestrator"] == "langgraph"


def test_langgraph_backend_never_imports_crewai():
    """The default path must not touch the optional dependency.

    Checked in a fresh subprocess: within this test session other modules may
    have imported crewai already, so `sys.modules` here proves nothing.
    """
    import subprocess
    import sys

    script = (
        "import sys;"
        "from app.main import app;"
        "from app.services.orchestrator import run_investigation;"
        "from app.models.schemas import InvestigationRequest;"
        "run_investigation(InvestigationRequest(error_message='KeyError: x'));"
        "print('crewai' in sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "DEMO_MODE": "true", "ORCHESTRATOR": "langgraph"},
    )
    assert result.returncode == 0, result.stderr[-800:]
    assert result.stdout.strip().endswith("False"), "crewai was imported on the default path"
