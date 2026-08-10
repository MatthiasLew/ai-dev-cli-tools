from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

CheckCategory = Literal["format", "lint", "typecheck", "unit_tests", "integration_tests", "build"]
CheckCost = Literal["fast", "medium", "slow"]
CheckSource = Literal["detected", "configured"]
ChangedStrategy = Literal[
    "changed_test_direct",
    "direct_test_match",
    "module_match",
    "package_match",
    "workspace_match",
    "configured_mapping",
    "configuration_change",
    "broad_fallback",
    "no_changes",
]


@dataclass(frozen=True, slots=True)
class CheckTask:
    name: str
    category: CheckCategory
    command: list[str]
    cost: CheckCost
    source: CheckSource
    required: bool = True
    workspace: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ChangedSelection:
    strategy: ChangedStrategy
    confidence: str
    changed_files: list[str]
    selected_tests: list[str]
    selected_commands: list[list[str]]
    fallback_reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            **asdict(self),
            "fallback_reason_code": (
                f"CHANGED_{self.strategy.upper()}" if self.fallback_reason else None
            ),
        }
