"""Static validation of a proposed fix.

Nothing here executes user code. ``ast.parse`` builds a syntax tree without
running anything, and every other check is pure string analysis. Executing an
untrusted patch is deliberately out of scope for the MVP (see SECURITY.md).
"""

from __future__ import annotations

import ast
import re
from typing import List, Optional

from app.models.schemas import ValidationCheck, ValidationResult, ValidationStatus

DIFF_HEADER = re.compile(r"^(---|\+\+\+|@@|diff --git)", re.MULTILINE)
PY_IMPORT = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", re.MULTILINE)
STDLIB_HINT = {"os", "sys", "json", "re", "typing", "pathlib", "logging", "asyncio"}

DANGEROUS = (
    ("eval(", "Introduces eval() on dynamic input"),
    ("exec(", "Introduces exec() on dynamic input"),
    ("os.system(", "Shells out with os.system()"),
    ("subprocess.call(", "Spawns a subprocess"),
    ("shell=True", "Spawns a shell with shell=True"),
    ("pickle.loads(", "Deserialises untrusted data with pickle"),
    ("verify=False", "Disables TLS certificate verification"),
)


def _added_lines(patch: str) -> str:
    lines = []
    for line in patch.splitlines():
        if line.startswith("+++"):
            continue
        if line.startswith("+"):
            lines.append(line[1:])
    return "\n".join(lines)


def _check_python_syntax(code: str, label: str) -> Optional[ValidationCheck]:
    if not code.strip():
        return None
    try:
        ast.parse(code)
        return ValidationCheck(
            name=f"{label} syntax", status=ValidationStatus.PASSED, detail="Parses cleanly."
        )
    except SyntaxError as exc:
        # A partial diff hunk often fails on its own; report as a warning.
        return ValidationCheck(
            name=f"{label} syntax",
            status=ValidationStatus.WARNING,
            detail=f"Could not parse in isolation (line {exc.lineno}): {exc.msg}",
        )


def _check_diff_shape(patch: str) -> ValidationCheck:
    if not patch.strip():
        return ValidationCheck(
            name="Patch format",
            status=ValidationStatus.SKIPPED,
            detail="No patch was produced.",
        )
    if DIFF_HEADER.search(patch):
        added = sum(1 for line in patch.splitlines() if line.startswith("+"))
        removed = sum(1 for line in patch.splitlines() if line.startswith("-"))
        return ValidationCheck(
            name="Patch format",
            status=ValidationStatus.PASSED,
            detail=f"Unified diff detected: +{added} / -{removed} lines.",
        )
    return ValidationCheck(
        name="Patch format",
        status=ValidationStatus.WARNING,
        detail="Patch is not a unified diff; apply it manually.",
    )


def _check_dangerous(code: str) -> ValidationCheck:
    found = [reason for token, reason in DANGEROUS if token in code]
    if found:
        return ValidationCheck(
            name="Security scan",
            status=ValidationStatus.FAILED,
            detail="; ".join(found),
        )
    return ValidationCheck(
        name="Security scan",
        status=ValidationStatus.PASSED,
        detail="No dangerous constructs in the added lines.",
    )


def _check_imports(code: str, declared: List[str]) -> ValidationCheck:
    modules = {
        (m.group(1) or m.group(2) or "").split(".")[0] for m in PY_IMPORT.finditer(code)
    }
    modules.discard("")
    external = sorted(m for m in modules if m not in STDLIB_HINT)
    if not external:
        return ValidationCheck(
            name="Import analysis",
            status=ValidationStatus.SKIPPED,
            detail="No third-party imports added.",
        )
    declared_names = {d.split("==")[0].split("[")[0].replace("-", "_").lower() for d in declared}
    unknown = [m for m in external if m.lower() not in declared_names]
    if unknown and declared_names:
        return ValidationCheck(
            name="Import analysis",
            status=ValidationStatus.WARNING,
            detail=f"Not in the declared dependencies: {', '.join(unknown)}",
        )
    return ValidationCheck(
        name="Import analysis",
        status=ValidationStatus.PASSED,
        detail=f"Imports referenced: {', '.join(external)}",
    )


def _check_dependency_pins(changes: List[str]) -> ValidationCheck:
    if not changes:
        return ValidationCheck(
            name="Dependency consistency",
            status=ValidationStatus.SKIPPED,
            detail="No dependency changes requested.",
        )
    unpinned = [c for c in changes if not re.search(r"[=><~^]\s*\d", c)]
    if unpinned:
        return ValidationCheck(
            name="Dependency consistency",
            status=ValidationStatus.WARNING,
            detail=f"Unpinned version for: {', '.join(unpinned[:5])}",
        )
    return ValidationCheck(
        name="Dependency consistency",
        status=ValidationStatus.PASSED,
        detail="All dependency changes carry an explicit version.",
    )


def validate_patch(
    patch: str,
    *,
    language: Optional[str] = None,
    dependencies: Optional[List[str]] = None,
    dependency_changes: Optional[List[str]] = None,
    original_code: Optional[str] = None,
) -> ValidationResult:
    """Run every static check and fold the results into one status."""
    if not patch.strip():
        return ValidationResult(
            status=ValidationStatus.SKIPPED,
            checks=[_check_diff_shape(patch)],
            summary="No patch was produced, so there was nothing to validate.",
        )

    checks: List[ValidationCheck] = [_check_diff_shape(patch)]
    added = _added_lines(patch) or patch
    is_python = (language or "").lower().startswith("py") or "def " in added or "import " in added

    if is_python:
        syntax = _check_python_syntax(added, "Patched Python")
        if syntax:
            checks.append(syntax)
        checks.append(_check_imports(added, dependencies or []))
        if original_code:
            original = _check_python_syntax(original_code, "Original file")
            if original and original.status == ValidationStatus.PASSED:
                checks.append(
                    ValidationCheck(
                        name="Baseline parse",
                        status=ValidationStatus.PASSED,
                        detail="Original source parses, so the diff is the only change under test.",
                    )
                )

    checks.append(_check_dangerous(added))
    checks.append(_check_dependency_pins(dependency_changes or []))

    if any(c.status == ValidationStatus.FAILED for c in checks):
        status = ValidationStatus.FAILED
    elif any(c.status == ValidationStatus.WARNING for c in checks):
        status = ValidationStatus.WARNING
    elif any(c.status == ValidationStatus.PASSED for c in checks):
        status = ValidationStatus.PASSED
    else:
        status = ValidationStatus.SKIPPED

    passed = sum(1 for c in checks if c.status == ValidationStatus.PASSED)
    return ValidationResult(
        status=status,
        checks=checks,
        summary=f"{passed}/{len(checks)} static checks passed. No code was executed.",
    )
