from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from ai_dev_tools import __version__

Status = Literal[
    "success",
    "failed",
    "partial",
    "warning",
    "not_implemented",
    "invalid_configuration",
    "environment_error",
    "blocked",
]
Severity = Literal["info", "warning", "error", "critical"]


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class Artifact:
    path: str
    kind: str
    description: str


@dataclass(slots=True)
class Issue:
    severity: Severity | str
    message: str
    location: str | None = None
    code: str | None = None
    tool: str | None = None
    file: str | None = None
    line: int | None = None
    column: int | None = None
    masked: bool = False


@dataclass(slots=True)
class Report:
    command: str
    project_root: Path
    status: Status = "success"
    started_at: datetime = field(default_factory=utc_now)
    finished_at: datetime | None = None
    summary: dict[str, Any] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)
    schema_version: str = "1.1"
    tool_version: str = __version__
    exit_code: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def finish(self, status: Status | None = None) -> Report:
        if status is not None:
            self.status = status
        self.finished_at = utc_now()
        if self.exit_code == 0 and self.status not in {"success", "partial", "warning"}:
            self.exit_code = 1
        return self

    @property
    def duration_seconds(self) -> float:
        finished = self.finished_at or utc_now()
        return round((finished - self.started_at).total_seconds(), 3)

    def to_dict(self) -> dict[str, Any]:
        from ai_dev_tools.reporters.progressive import add_progressive_metadata

        finished = self.finished_at or utc_now()
        status = "partial" if self.status == "warning" else self.status
        payload = {
            "schema_version": self.schema_version,
            "tool_version": self.tool_version,
            "command": self.command,
            "status": status,
            "exit_code": self.exit_code,
            "started_at": self.started_at.isoformat(),
            "finished_at": finished.isoformat(),
            "duration_seconds": self.duration_seconds,
            "project_root": str(self.project_root),
            "summary": self.summary,
            "issues": [asdict(issue) for issue in self.issues],
            "artifacts": [asdict(artifact) for artifact in self.artifacts],
            "metadata": dict(self.metadata),
        }
        return add_progressive_metadata(payload)
