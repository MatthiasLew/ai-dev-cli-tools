from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True, slots=True)
class RuntimeRequirement:
    runtime: str
    constraint: str
    source: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Workspace:
    workspace_id: str
    root: str
    kind: str
    technologies: tuple[str, ...]
    package_manager: str | None = None
    config_files: tuple[str, ...] = ()
    commands: dict[str, str] = field(default_factory=dict)
    runtime_requirements: tuple[RuntimeRequirement, ...] = ()

    def owns(self, relative_path: str) -> bool:
        normalized = relative_path.replace("\\", "/").strip("/")
        workspace_root = self.root.replace("\\", "/").strip("/")
        return (
            not workspace_root
            or normalized == workspace_root
            or normalized.startswith(workspace_root + "/")
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.workspace_id,
            "root": self.root,
            "kind": self.kind,
            "technologies": list(self.technologies),
            "package_manager": self.package_manager,
            "config_files": list(self.config_files),
            "commands": dict(self.commands),
            "runtime_requirements": [
                requirement.to_dict() for requirement in self.runtime_requirements
            ],
        }
