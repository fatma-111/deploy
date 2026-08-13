"""Central configuration for BugHound.

Every knob lives here and is driven by environment variables so that no secret
ever touches source control. Import ``settings`` anywhere in the app.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import List

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


def _split(value: str) -> List[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ---------------------------------------------------------------- app
    app_name: str = "BugHound"
    app_tagline: str = "AI Bug Investigation Agent"
    version: str = "1.0.0"
    environment: str = Field(default="development", alias="ENVIRONMENT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    port: int = Field(default=8000, alias="PORT")

    # ------------------------------------------------------------- llm
    # Any OpenAI-compatible endpoint works. LLM_* wins when set; the OPENROUTER_*
    # names remain for the default provider.
    llm_api_key_raw: str = Field(default="", alias="LLM_API_KEY")
    llm_base_url_raw: str = Field(default="", alias="LLM_BASE_URL")
    openrouter_api_key_raw: str = Field(default="", alias="OPENROUTER_API_KEY")
    openrouter_base_url_raw: str = Field(
        default="https://openrouter.ai/api/v1", alias="OPENROUTER_BASE_URL"
    )
    # Primary model. Keep it configurable: free models on OpenRouter come and go.
    openrouter_model: str = Field(
        default="poolside/laguna-s-2.1:free", alias="OPENROUTER_MODEL"
    )
    # Comma separated fallback chain, tried in order when the primary fails.
    openrouter_fallback_models_raw: str = Field(
        default=(
            "nvidia/nemotron-3.5-lightning:free,"
            "poolside/laguna-xs-2.1:free,"
            "cohere/north-mini-code:free"
        ),
        alias="OPENROUTER_FALLBACK_MODELS",
    )
    # When every configured model fails, ask OpenRouter what is free right now.
    model_discovery_enabled_raw: bool = Field(default=True, alias="MODEL_DISCOVERY_ENABLED")
    # Cheap model used by low-stakes agents (debug / research summarisation).
    openrouter_fast_model: str = Field(default="", alias="OPENROUTER_FAST_MODEL")

    llm_temperature: float = Field(default=0.1, alias="LLM_TEMPERATURE")
    llm_max_tokens: int = Field(default=2000, alias="LLM_MAX_TOKENS")
    llm_timeout_seconds: int = Field(default=90, alias="LLM_TIMEOUT_SECONDS")
    llm_max_retries: int = Field(default=2, alias="LLM_MAX_RETRIES")

    # ------------------------------------------------------- orchestration
    # "langgraph" (default, no extra deps) or "crewai" (needs requirements-crewai.txt)
    orchestrator: str = Field(default="langgraph", alias="ORCHESTRATOR")
    confidence_threshold: float = Field(default=0.80, alias="CONFIDENCE_THRESHOLD")
    max_research_iterations: int = Field(default=2, alias="MAX_RESEARCH_ITERATIONS")
    max_fix_retries: int = Field(default=2, alias="MAX_FIX_RETRIES")
    investigation_timeout_seconds: int = Field(
        default=300, alias="INVESTIGATION_TIMEOUT_SECONDS"
    )

    # ---------------------------------------------------- knowledge base / RAG
    # Local, in-memory TF-IDF retrieval over data/knowledge_base_seed.json
    # (extracted from data/error_knowledge_base.pdf) plus anything learned at
    # runtime. A strong match skips every LLM call for the investigation.
    kb_enabled: bool = Field(default=True, alias="KB_ENABLED")
    kb_match_threshold: float = Field(default=0.55, alias="KB_MATCH_THRESHOLD")
    kb_learning_enabled: bool = Field(default=True, alias="KB_LEARNING_ENABLED")
    kb_max_learned_entries: int = Field(default=500, alias="KB_MAX_LEARNED_ENTRIES")
    # Only learn from a run whose review approved at at least this confidence -
    # a shaky diagnosis should not become tomorrow's cached "known pattern".
    kb_learn_min_confidence: float = Field(default=0.80, alias="KB_LEARN_MIN_CONFIDENCE")

    # -------------------------------------------------- email via n8n webhook
    # BugHound never touches SMTP directly. It POSTs the finished report to an
    # n8n workflow's webhook; n8n's own Send Email node (SMTP credentials
    # configured inside n8n, never here) delivers it. See n8n/README.md.
    n8n_webhook_enabled: bool = Field(default=False, alias="N8N_WEBHOOK_ENABLED")
    n8n_webhook_url: str = Field(default="", alias="N8N_WEBHOOK_URL")
    n8n_webhook_timeout_seconds: int = Field(default=10, alias="N8N_WEBHOOK_TIMEOUT_SECONDS")
    # Used when a request doesn't specify notify_email. Leave blank to require
    # the caller to supply an address every time.
    notify_default_email: str = Field(default="", alias="NOTIFY_DEFAULT_EMAIL")

    # ------------------------------------------------------------- tools
    github_token: str = Field(default="", alias="GITHUB_TOKEN")
    github_api_url: str = "https://api.github.com"
    web_search_enabled: bool = Field(default=True, alias="WEB_SEARCH_ENABLED")
    tool_timeout_seconds: int = Field(default=15, alias="TOOL_TIMEOUT_SECONDS")
    max_search_results: int = Field(default=6, alias="MAX_SEARCH_RESULTS")
    max_fetch_chars: int = Field(default=8000, alias="MAX_FETCH_CHARS")

    # ------------------------------------------------------------ limits
    max_error_message_chars: int = Field(default=4000, alias="MAX_ERROR_MESSAGE_CHARS")
    max_stack_trace_chars: int = Field(default=20000, alias="MAX_STACK_TRACE_CHARS")
    max_logs_chars: int = Field(default=20000, alias="MAX_LOGS_CHARS")
    max_source_code_chars: int = Field(default=30000, alias="MAX_SOURCE_CODE_CHARS")

    # ------------------------------------------------------------- misc
    demo_mode: bool = Field(default=False, alias="DEMO_MODE")
    cors_origins_raw: str = Field(default="*", alias="CORS_ORIGINS")

    @property
    def openrouter_api_key(self) -> str:
        """The active API key, whichever provider it belongs to."""
        return self.llm_api_key_raw or self.openrouter_api_key_raw

    @property
    def openrouter_base_url(self) -> str:
        return self.llm_base_url_raw or self.openrouter_base_url_raw

    @property
    def is_openrouter(self) -> bool:
        return "openrouter.ai" in self.openrouter_base_url

    @property
    def provider_name(self) -> str:
        if self.is_openrouter:
            return "openrouter"
        if "api.openai.com" in self.openrouter_base_url:
            return "openai"
        return "custom"

    @property
    def fallback_models(self) -> List[str]:
        return _split(self.openrouter_fallback_models_raw)

    @property
    def fast_model(self) -> str:
        return self.openrouter_fast_model or self.openrouter_model

    @property
    def cors_origins(self) -> List[str]:
        return _split(self.cors_origins_raw) or ["*"]

    @property
    def model_discovery_enabled(self) -> bool:
        """Only OpenRouter publishes a free-model catalog worth discovering."""
        return self.model_discovery_enabled_raw and self.is_openrouter

    @property
    def llm_available(self) -> bool:
        """True when a real LLM call is possible."""
        return bool(self.openrouter_api_key) and not self.demo_mode

    @property
    def effective_demo_mode(self) -> bool:
        """Demo mode is forced on when no API key is configured."""
        return self.demo_mode or not self.openrouter_api_key


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

__all__ = ["settings", "get_settings", "Settings", "os"]
