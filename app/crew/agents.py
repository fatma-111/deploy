"""CrewAI agent definitions.

The role/goal/backstory triple is CrewAI's idiom for what BugHound already
expressed as system prompts, so the existing prompts are reused verbatim as
backstories. Behaviour stays identical across both orchestrators.
"""

from __future__ import annotations

from crewai import LLM, Agent

from app.config.settings import settings
from app.crew.tools import RESEARCH_TOOLS, REVIEW_TOOLS
from app.prompts import (
    DEBUG_SYSTEM,
    FIX_SYSTEM,
    RESEARCH_SYSTEM,
    REVIEWER_SYSTEM,
    ROOT_CAUSE_SYSTEM,
)


def build_llm(fast: bool = False) -> LLM:
    """One LLM factory, driven by the same settings as the LangGraph path."""
    model_id = settings.fast_model if fast else settings.openrouter_model
    # litellm needs a provider prefix to know how to route the call.
    prefix = "openrouter" if settings.is_openrouter else "openai"
    return LLM(
        model=f"{prefix}/{model_id}",
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        timeout=settings.llm_timeout_seconds,
    )


def debug_agent() -> Agent:
    return Agent(
        role="Debug Analyst",
        goal=(
            "Turn a raw failure into a structured triage record: error type, affected "
            "file and function, suspected packages, and what information is missing."
        ),
        backstory=DEBUG_SYSTEM,
        llm=build_llm(fast=True),
        allow_delegation=False,
        verbose=False,
        max_iter=3,
    )


def research_agent() -> Agent:
    return Agent(
        role="Technical Researcher",
        goal=(
            "Collect evidence from official documentation, GitHub and package "
            "registries, and judge each source instead of trusting search ranking."
        ),
        backstory=RESEARCH_SYSTEM,
        tools=RESEARCH_TOOLS,
        llm=build_llm(fast=True),
        allow_delegation=False,
        verbose=False,
        max_iter=6,
    )


def root_cause_agent() -> Agent:
    return Agent(
        role="Root Cause Analyst",
        goal=(
            "Name the mechanism that is actually broken and attach an honest, "
            "calibrated confidence to it. Low confidence is a valid answer."
        ),
        backstory=ROOT_CAUSE_SYSTEM,
        llm=build_llm(),
        allow_delegation=False,
        verbose=False,
        max_iter=3,
    )


def fix_agent() -> Agent:
    return Agent(
        role="Fix Engineer",
        goal=(
            "Produce the smallest correct patch as a unified diff, grounded in the "
            "evidence, inventing no API, package, version or configuration option."
        ),
        backstory=FIX_SYSTEM,
        llm=build_llm(),
        allow_delegation=False,
        verbose=False,
        max_iter=3,
    )


def reviewer_agent() -> Agent:
    return Agent(
        role="Independent Code Reviewer",
        goal=(
            "Find the failure in the proposed fix. Approve only what is correct, "
            "minimal and supported by the evidence."
        ),
        backstory=REVIEWER_SYSTEM,
        tools=REVIEW_TOOLS,
        llm=build_llm(),
        # Independence is the point: the reviewer must not delegate back to the
        # agent whose work it is checking.
        allow_delegation=False,
        verbose=False,
        max_iter=4,
    )
