"""Typed contracts shared by the agents, the graph and the API layer."""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from app.config.settings import settings


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #
class Severity(str, Enum):
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"
    INFO = "info"


class SourceType(str, Enum):
    OFFICIAL_DOCS = "official_docs"
    GITHUB_REPO = "github_repo"
    GITHUB_ISSUE = "github_issue"
    RELEASE_NOTES = "release_notes"
    CHANGELOG = "changelog"
    COMMUNITY = "community"
    OTHER = "other"


class ReviewDecision(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ValidationStatus(str, Enum):
    PASSED = "PASSED"
    WARNING = "WARNING"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class InvestigationStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    INCONCLUSIVE = "inconclusive"
    FAILED = "failed"


# --------------------------------------------------------------------------- #
# Request / input
# --------------------------------------------------------------------------- #
class InvestigationRequest(BaseModel):
    """What the user submits. Everything except ``error_message`` is optional."""

    error_message: str = Field(..., min_length=3)
    stack_trace: Optional[str] = None
    logs: Optional[str] = None
    source_code: Optional[str] = None
    language: Optional[str] = Field(default=None, examples=["Python"])
    framework: Optional[str] = Field(default=None, examples=["FastAPI"])
    repository_url: Optional[str] = None
    dependencies: List[str] = Field(default_factory=list)
    environment: Optional[str] = None

    @field_validator("error_message")
    @classmethod
    def _cap_error(cls, v: str) -> str:
        return v.strip()[: settings.max_error_message_chars]

    @field_validator("stack_trace")
    @classmethod
    def _cap_trace(cls, v: Optional[str]) -> Optional[str]:
        return v[: settings.max_stack_trace_chars] if v else v

    @field_validator("logs")
    @classmethod
    def _cap_logs(cls, v: Optional[str]) -> Optional[str]:
        return v[: settings.max_logs_chars] if v else v

    @field_validator("source_code")
    @classmethod
    def _cap_code(cls, v: Optional[str]) -> Optional[str]:
        return v[: settings.max_source_code_chars] if v else v

    @field_validator("dependencies")
    @classmethod
    def _cap_deps(cls, v: List[str]) -> List[str]:
        return [d.strip() for d in v if d and d.strip()][:60]


# --------------------------------------------------------------------------- #
# Agent outputs
# --------------------------------------------------------------------------- #
class DebugAnalysis(BaseModel):
    error_type: str = "Unknown"
    severity: Severity = Severity.MAJOR
    affected_component: Optional[str] = None
    affected_file: Optional[str] = None
    affected_function: Optional[str] = None
    important_lines: List[str] = Field(default_factory=list)
    suspected_dependencies: List[str] = Field(default_factory=list)
    initial_hypotheses: List[str] = Field(default_factory=list)
    missing_information: List[str] = Field(default_factory=list)
    search_queries: List[str] = Field(default_factory=list)
    summary: str = ""


class ResearchResult(BaseModel):
    title: str
    url: str
    source_type: SourceType = SourceType.OTHER
    summary: str = ""
    relevant_evidence: str = ""
    relevance_score: float = 0.5

    @field_validator("relevance_score")
    @classmethod
    def _clamp(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))


class ResearchReport(BaseModel):
    query_used: List[str] = Field(default_factory=list)
    results: List[ResearchResult] = Field(default_factory=list)
    key_findings: List[str] = Field(default_factory=list)
    gaps: List[str] = Field(default_factory=list)
    degraded: bool = False  # true when every external source failed


class RootCauseAnalysis(BaseModel):
    root_cause: str = ""
    confidence: float = 0.0
    evidence: List[str] = Field(default_factory=list)
    alternative_hypotheses: List[str] = Field(default_factory=list)
    reasoning_summary: str = ""
    recommended_direction: str = ""
    missing_information: List[str] = Field(default_factory=list)

    @field_validator("confidence")
    @classmethod
    def _clamp(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))


class ProposedFix(BaseModel):
    explanation: str = ""
    recommended_fix: str = ""
    patch: str = ""  # unified diff preferred
    dependency_changes: List[str] = Field(default_factory=list)
    configuration_changes: List[str] = Field(default_factory=list)
    migration_steps: List[str] = Field(default_factory=list)
    alternative_fix: Optional[str] = None
    assumptions: List[str] = Field(default_factory=list)
    risk: RiskLevel = RiskLevel.MEDIUM


class ReviewIssue(BaseModel):
    severity: Severity = Severity.MINOR
    category: str = "correctness"
    detail: str = ""


class ReviewResult(BaseModel):
    decision: ReviewDecision = ReviewDecision.REJECTED
    score: int = 0
    issues: List[ReviewIssue] = Field(default_factory=list)
    required_changes: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    regression_risk: RiskLevel = RiskLevel.MEDIUM
    summary: str = ""

    @field_validator("score")
    @classmethod
    def _clamp(cls, v: int) -> int:
        return max(0, min(100, int(v)))


class ValidationCheck(BaseModel):
    name: str
    status: ValidationStatus = ValidationStatus.SKIPPED
    detail: str = ""


class ValidationResult(BaseModel):
    status: ValidationStatus = ValidationStatus.SKIPPED
    checks: List[ValidationCheck] = Field(default_factory=list)
    summary: str = ""


class Citation(BaseModel):
    index: int
    title: str
    url: str
    source_type: SourceType = SourceType.OTHER


class StageTrace(BaseModel):
    """A public, non-chain-of-thought record of what each node did."""

    node: str
    label: str
    status: str = "completed"
    duration_ms: int = 0
    detail: str = ""


# --------------------------------------------------------------------------- #
# API response
# --------------------------------------------------------------------------- #
class InvestigationResponse(BaseModel):
    investigation_id: str
    status: InvestigationStatus = InvestigationStatus.COMPLETED
    error_type: str = "Unknown"
    severity: Severity = Severity.MAJOR
    root_cause: str = ""
    confidence: float = 0.0
    debug_analysis: Optional[DebugAnalysis] = None
    research: Optional[ResearchReport] = None
    alternative_hypotheses: List[str] = Field(default_factory=list)
    proposed_fix: Optional[ProposedFix] = None
    review: Optional[ReviewResult] = None
    validation: Optional[ValidationResult] = None
    citations: List[Citation] = Field(default_factory=list)
    risk: RiskLevel = RiskLevel.MEDIUM
    trace: List[StageTrace] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    duration_ms: int = 0
    demo_mode: bool = False
    orchestrator: str = "langgraph"
    kb_hit: bool = False
    final_response: str = ""


class HealthResponse(BaseModel):
    status: str = "ok"
    app: str = settings.app_name
    version: str = settings.version
    environment: str = settings.environment
    llm_configured: bool = False
    github_token_configured: bool = False
    demo_mode: bool = False
    model: str = ""
    provider: str = "openrouter"
    orchestrator: dict = Field(default_factory=dict)
    knowledge_base_seed_entries: int = 0
