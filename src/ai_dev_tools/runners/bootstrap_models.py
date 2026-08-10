from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

BootstrapStatus = Literal["planned", "executed", "skipped", "failed"]


@dataclass(frozen=True, slots=True)
class BootstrapOptions:
    dry_run: bool = False
    explain: bool = False
    create_env: bool = False


@dataclass(frozen=True, slots=True)
class BootstrapStep:
    name: str
    command: list[str]
    reason: str
    source: str
    modifies_project: bool = True
    required_tool: str | None = None
    action: str = "command"
    workspace: str = ""

    def to_dict(self) -> dict[str, object]:
        return {**asdict(self), "reason_code": _bootstrap_reason_code(self)}


def _bootstrap_reason_code(step: BootstrapStep) -> str:
    if step.action == "create_venv":
        return "CREATE_VIRTUAL_ENVIRONMENT"
    if step.action == "copy_env":
        return "CREATE_ENVIRONMENT_FILE"
    if step.workspace:
        return "WORKSPACE_BOOTSTRAP"
    if "smoke" in step.name.lower() or "verify" in step.reason.lower():
        return "SMOKE_VALIDATION"
    return "PROJECT_BOOTSTRAP"


@dataclass(frozen=True, slots=True)
class BootstrapPlan:
    project_type: str
    package_manager: str | None
    steps: list[BootstrapStep]
    smoke_steps: list[BootstrapStep]
    required_tools: list[str]
    env_available: bool = False
    env_will_create: bool = False
    monorepo_subprojects: list[str] | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "project_type": self.project_type,
            "package_manager": self.package_manager,
            "steps": [step.to_dict() for step in self.steps],
            "smoke_steps": [step.to_dict() for step in self.smoke_steps],
            "required_tools": self.required_tools,
            "env_available": self.env_available,
            "env_will_create": self.env_will_create,
            "monorepo_subprojects": self.monorepo_subprojects or [],
        }
