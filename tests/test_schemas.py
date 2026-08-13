"""Input validation, size caps and score clamping."""

import pytest
from pydantic import ValidationError

from app.models.schemas import (
    InvestigationRequest,
    ResearchResult,
    ReviewResult,
    RootCauseAnalysis,
)


def test_error_message_is_required():
    with pytest.raises(ValidationError):
        InvestigationRequest(error_message="")


def test_long_input_is_truncated_not_rejected():
    request = InvestigationRequest(error_message="x" * 99_000, stack_trace="y" * 99_000)
    assert len(request.error_message) <= 4000
    assert len(request.stack_trace) <= 20_000


def test_dependencies_are_cleaned():
    request = InvestigationRequest(
        error_message="boom", dependencies=["  fastapi==0.115.6 ", "", "  "]
    )
    assert request.dependencies == ["fastapi==0.115.6"]


@pytest.mark.parametrize("value,expected", [(1.7, 1.0), (-3, 0.0), (0.42, 0.42)])
def test_confidence_is_clamped(value, expected):
    assert RootCauseAnalysis(confidence=value).confidence == expected


def test_relevance_is_clamped():
    assert ResearchResult(title="t", url="u", relevance_score=9).relevance_score == 1.0


def test_review_score_is_clamped():
    assert ReviewResult(score=1000).score == 100
