"""Shared fixtures. No test may touch a paid API or the public internet."""

import pytest

from app.services import activity


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Cut every outbound call. Tools must degrade, not crash."""
    monkeypatch.setattr("app.tools.http_client.fetch_text", lambda *a, **k: None)
    monkeypatch.setattr("app.tools.http_client.fetch_json", lambda *a, **k: None)
    monkeypatch.setattr("app.tools.web_search.fetch_text", lambda *a, **k: None)
    monkeypatch.setattr("app.tools.github.fetch_json", lambda *a, **k: None)
    monkeypatch.setattr("app.tools.github.fetch_text", lambda *a, **k: None)
    monkeypatch.setattr("app.tools.documentation.fetch_json", lambda *a, **k: None)
    monkeypatch.setattr("app.tools.documentation.fetch_text", lambda *a, **k: None)


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    """Force heuristic mode so tests never need an API key.

    Patch the raw settings fields: the public accessors are read-only properties
    that resolve LLM_* over OPENROUTER_*.
    """
    monkeypatch.setattr("app.config.settings.settings.openrouter_api_key_raw", "")
    monkeypatch.setattr("app.config.settings.settings.llm_api_key_raw", "")
    monkeypatch.setattr("app.config.settings.settings.demo_mode", True)


@pytest.fixture(autouse=True)
def _no_knowledge_base(monkeypatch):
    """Disable the RAG short-circuit by default.

    The seed knowledge base intentionally covers common fixtures used
    elsewhere in this suite (e.g. the LangChain ModuleNotFoundError bug), so
    leaving it on would make unrelated tests silently exercise the KB
    short-circuit instead of the pipeline they're meant to test. Tests that
    specifically exercise the knowledge base re-enable it themselves.
    """
    monkeypatch.setattr("app.config.settings.settings.kb_enabled", False)


@pytest.fixture(autouse=True)
def _clean_feed():
    activity.clear()
    yield
    activity.clear()


@pytest.fixture
def langchain_bug():
    return {
        "error_message": "ModuleNotFoundError: No module named 'langchain.chat_models'",
        "stack_trace": (
            'Traceback (most recent call last):\n'
            '  File "app/main.py", line 3, in <module>\n'
            "    from langchain.chat_models import ChatOpenAI\n"
            "ModuleNotFoundError: No module named 'langchain.chat_models'"
        ),
        "source_code": "from langchain.chat_models import ChatOpenAI\n",
        "language": "Python",
        "framework": "LangChain",
        "dependencies": ["langchain==0.3.7"],
    }
