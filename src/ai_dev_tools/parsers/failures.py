from __future__ import annotations

from dataclasses import dataclass

from ai_dev_tools.utils.subprocess import CommandResult


@dataclass(frozen=True, slots=True)
class FailureClassification:
    category: str
    retryable: bool
    reason_code: str


_INFRASTRUCTURE_MARKERS = (
    "failed to resolve",
    "name resolution",
    "connection reset",
    "connection aborted",
    "connection refused",
    "remote end closed connection",
    "service unavailable",
    "bad gateway",
    "gateway timeout",
    "http 429",
    "too many requests",
    "runner lost communication",
)
_ENVIRONMENT_MARKERS = (
    "permission denied",
    "access is denied",
    "no space left on device",
    "disk quota exceeded",
    "could not find executable",
)
_CODE_MARKERS = (
    "assertionerror",
    "syntaxerror",
    "type error",
    "compilation failed",
    "test failed",
    "tests failed",
)


def classify_failure(result: CommandResult) -> FailureClassification:
    if result.exit_code == 126 and result.failure_class == "policy":
        return FailureClassification("policy", False, "COMMAND_BLOCKED_BY_POLICY")
    if result.exit_code == 0:
        return FailureClassification("success", False, "COMMAND_SUCCEEDED")
    if result.cancelled:
        return FailureClassification("cancelled", False, "COMMAND_CANCELLED")
    if result.timed_out or result.exit_code == 124:
        return FailureClassification("timeout", False, "COMMAND_TIMEOUT")
    if result.exit_code == 127:
        return FailureClassification("environment", False, "EXECUTABLE_MISSING")
    text = result.combined_output.lower()
    if any(marker in text for marker in _INFRASTRUCTURE_MARKERS):
        return FailureClassification("infrastructure", True, "TRANSIENT_INFRASTRUCTURE_FAILURE")
    if any(marker in text for marker in _ENVIRONMENT_MARKERS):
        return FailureClassification("environment", False, "LOCAL_ENVIRONMENT_FAILURE")
    if any(marker in text for marker in _CODE_MARKERS):
        return FailureClassification("code", False, "DETERMINISTIC_CODE_FAILURE")
    return FailureClassification("unknown", False, "UNCLASSIFIED_FAILURE")
