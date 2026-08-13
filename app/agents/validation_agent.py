"""Validation Agent — static checks only. No user code is ever executed."""

from __future__ import annotations

from typing import Any, Dict

from app.models.schemas import ValidationResult, ValidationStatus
from app.tools.validation import validate_patch


def run(state: Dict[str, Any]) -> ValidationResult:
    fix = state.get("proposed_fix") or {}
    patch = fix.get("patch") or ""
    if not patch.strip():
        return ValidationResult(
            status=ValidationStatus.SKIPPED,
            summary="No patch was produced, so there was nothing to validate.",
        )
    return validate_patch(
        patch,
        language=state.get("language"),
        dependencies=state.get("dependencies") or [],
        dependency_changes=fix.get("dependency_changes") or [],
        original_code=state.get("source_code"),
    )
