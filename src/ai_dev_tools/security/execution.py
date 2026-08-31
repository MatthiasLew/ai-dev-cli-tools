from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ExecutionPolicy:
    mode: str = "audit"
    allow_prefixes: tuple[str, ...] = ()
    deny_prefixes: tuple[str, ...] = ()
    maximum_impact: str = "high"


@dataclass(frozen=True, slots=True)
class CommandAssessment:
    allowed: bool
    impact: str
    reason_code: str
    reasons: tuple[str, ...]
    command: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "allowed": self.allowed,
            "impact": self.impact,
            "reason_code": self.reason_code,
            "reasons": list(self.reasons),
            "command": list(self.command),
        }


_IMPACT_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}
_DESTRUCTIVE = {
    "rm",
    "rmdir",
    "del",
    "erase",
    "remove-item",
    "format",
    "shutdown",
    "reboot",
}
_NETWORK = {"curl", "wget", "invoke-webrequest", "ssh", "scp", "ftp"}
_INSTALL = {"pip", "pipx", "npm", "pnpm", "yarn", "cargo", "composer", "mvn", "gradle"}


def assess_command(
    command: list[str], project_root: Path, policy: ExecutionPolicy
) -> CommandAssessment:
    if not command:
        return CommandAssessment(False, "critical", "EMPTY_COMMAND", ("command is empty",), ())
    normalized = tuple(str(item) for item in command)
    rendered = " ".join(normalized).lower()
    executable = _canonical_executable(normalized[0])
    reasons: list[str] = []
    impact = "low"
    if executable in _DESTRUCTIVE or _destructive_git(normalized):
        impact = "critical"
        reasons.append("destructive command family")
    elif executable in _NETWORK:
        impact = "high"
        reasons.append("external network access")
    elif executable in _INSTALL and any(item in rendered for item in ("install", "add", "update")):
        impact = "high"
        reasons.append("dependency or system state mutation")
    elif any(item in rendered for item in (" test", "pytest", "check", "lint", "mypy")):
        impact = "medium"
        reasons.append("bounded validation execution")
    else:
        reasons.append("no known high-impact marker")

    prefix = " ".join(normalized)
    canonical_prefix = " ".join((_canonical_executable(normalized[0]), *normalized[1:]))
    candidates = (prefix, canonical_prefix)
    denied = any(
        _prefix_matches(candidate, item)
        for item in policy.deny_prefixes
        for candidate in candidates
    )
    allowlisted = not policy.allow_prefixes or any(
        _prefix_matches(candidate, item)
        for item in policy.allow_prefixes
        for candidate in candidates
    )
    over_limit = _IMPACT_RANK.get(impact, 3) > _IMPACT_RANK.get(policy.maximum_impact, 2)
    enforced = policy.mode == "enforce"
    allowed = not enforced or (not denied and allowlisted and not over_limit)
    if denied:
        reason_code = "COMMAND_DENYLISTED"
        reasons.append("matches configured deny prefix")
    elif not allowlisted:
        reason_code = "COMMAND_NOT_ALLOWLISTED"
        reasons.append("does not match configured allow prefix")
    elif over_limit:
        reason_code = "COMMAND_IMPACT_EXCEEDS_POLICY"
        reasons.append("impact exceeds configured maximum")
    else:
        reason_code = "COMMAND_ALLOWED" if allowed else "COMMAND_BLOCKED"
    return CommandAssessment(allowed, impact, reason_code, tuple(reasons), normalized)


def _prefix_matches(command: str, prefix: str) -> bool:
    normalized = prefix.strip().lower()
    command = command.lower()
    return bool(normalized) and (command == normalized or command.startswith(normalized + " "))


def _canonical_executable(executable: str) -> str:
    name = Path(executable).name.lower()
    for suffix in (".exe", ".cmd", ".bat"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    if name == "py" or name.startswith("python"):
        return "python"
    return name


def _destructive_git(command: tuple[str, ...]) -> bool:
    lowered = tuple(item.lower() for item in command)
    return len(lowered) >= 2 and _canonical_executable(lowered[0]) == "git" and lowered[1] in {
        "reset",
        "clean",
        "checkout",
        "restore",
    }
