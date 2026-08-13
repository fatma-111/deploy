"""Debug Agent — parses the raw failure into a structured triage record."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict

from app.config.settings import settings
from app.models.schemas import DebugAnalysis, Severity
from app.prompts import DEBUG_SYSTEM
from app.services.llm import llm_service, untrusted

logger = logging.getLogger(__name__)

ERROR_TYPE = re.compile(r"\b([A-Z][A-Za-z0-9_]*(?:Error|Exception|Warning|Fault))\b")
PY_FRAME = re.compile(r'File "(?P<file>[^"]+)", line (?P<line>\d+), in (?P<func>\S+)')
MODULE_NAME = re.compile(r"No module named ['\"]([\w.]+)['\"]")
JS_FRAME = re.compile(r"at\s+(?P<func>[\w.<>]+)\s+\((?P<file>[^):]+):(?P<line>\d+)")

CRITICAL_HINTS = ("segmentation fault", "out of memory", "data loss", "corrupt", "deadlock")


def heuristic_analysis(state: Dict[str, Any]) -> DebugAnalysis:
    """Deterministic parsing used as a floor under the LLM (and in demo mode)."""
    error_message = state.get("error_message") or ""
    stack_trace = state.get("stack_trace") or ""
    blob = f"{error_message}\n{stack_trace}"

    match = ERROR_TYPE.search(blob)
    error_type = match.group(1) if match else "UnknownError"

    frames = list(PY_FRAME.finditer(stack_trace)) or list(JS_FRAME.finditer(stack_trace))
    affected_file = frames[-1].group("file") if frames else None
    affected_function = frames[-1].group("func") if frames else None
    important_lines = [f.group(0).strip() for f in frames[-3:]]
    if not important_lines and error_message:
        important_lines = [error_message.strip().splitlines()[0][:200]]

    suspected = []
    module = MODULE_NAME.search(blob)
    if module:
        suspected.append(module.group(1).split(".")[0])
    for dep in state.get("dependencies") or []:
        name = dep.split("==")[0].strip()
        if name and name.lower() in blob.lower() and name not in suspected:
            suspected.append(name)

    severity = Severity.MAJOR
    low = blob.lower()
    if any(hint in low for hint in CRITICAL_HINTS):
        severity = Severity.CRITICAL
    elif error_type.endswith("Warning"):
        severity = Severity.MINOR

    package = suspected[0] if suspected else (state.get("framework") or "")
    queries = [q for q in [
        f"{error_type} {error_message.strip()[:90]}",
        f"{package} {error_type} documentation" if package else "",
        f"{package} migration guide changelog" if package else "",
    ] if q.strip()]

    missing = []
    if not stack_trace:
        missing.append("Full stack trace")
    if not state.get("source_code"):
        missing.append("Source of the failing file")
    if not state.get("dependencies"):
        missing.append("Installed dependency versions")

    return DebugAnalysis(
        error_type=error_type,
        severity=severity,
        affected_component=state.get("framework") or state.get("language") or None,
        affected_file=affected_file,
        affected_function=affected_function,
        important_lines=important_lines,
        suspected_dependencies=suspected,
        initial_hypotheses=[],
        missing_information=missing,
        search_queries=queries,
        summary=f"{error_type} detected in {affected_file or 'an unknown location'}.",
    )


def _merge(llm: DebugAnalysis, floor: DebugAnalysis) -> DebugAnalysis:
    """Prefer the model, but never lose a fact the parser proved."""
    data = llm.model_dump()
    if not data.get("error_type") or data["error_type"] in {"Unknown", "UnknownError"}:
        data["error_type"] = floor.error_type
    for field in ("affected_file", "affected_function"):
        if not data.get(field):
            data[field] = getattr(floor, field)
    for field in ("important_lines", "suspected_dependencies", "search_queries"):
        if not data.get(field):
            data[field] = getattr(floor, field)
    return DebugAnalysis(**data)


def run(state: Dict[str, Any]) -> DebugAnalysis:
    floor = heuristic_analysis(state)
    if not settings.llm_available:
        floor.initial_hypotheses = [
            f"{floor.error_type} is raised before the module finishes loading.",
            "A dependency version does not match what the code expects.",
        ]
        return floor

    user = "\n".join(
        part
        for part in [
            f"Language: {state.get('language') or 'unknown'}",
            f"Framework: {state.get('framework') or 'unknown'}",
            f"Environment: {state.get('environment') or 'unknown'}",
            f"Declared dependencies: {', '.join(state.get('dependencies') or []) or 'none'}",
            untrusted("error_message", state.get("error_message", ""), 4000),
            untrusted("stack_trace", state.get("stack_trace") or "", 8000),
            untrusted("logs", state.get("logs") or "", 6000),
            untrusted("source_code", state.get("source_code") or "", 10000),
            "Deterministic pre-parse (already verified, keep it consistent): "
            f"error_type={floor.error_type}, file={floor.affected_file}, "
            f"function={floor.affected_function}",
        ]
        if part
    )

    try:
        result = llm_service.complete_json(
            DEBUG_SYSTEM, user, DebugAnalysis, prefer_fast=True
        )
        return _merge(result, floor)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Debug Agent fell back to heuristics: %s", exc)
        return floor
