from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from ai_dev_tools import __version__

Status = Literal["success", "warning", "failed"]


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class Artifact:
    path: str
    kind: str
    description: str


@dataclass(slots=True)
class Issue:
    severity: str
    message: str
    location: str | None = None
    code: str | None = None


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
    schema_version: str = "1.0"
    tool_version: str = __version__

    def finish(self, status: Status | None = None) -> Report:
        if status is not None:
            self.status = status
        self.finished_at = utc_now()
        return self

    @property
    def duration_seconds(self) -> float:
        finished = self.finished_at or utc_now()
        return round((finished - self.started_at).total_seconds(), 3)

    def to_dict(self) -> dict[str, Any]:
        finished = self.finished_at or utc_now()
        return {
            "schema_version": self.schema_version,
            "tool_version": self.tool_version,
            "status": self.status,
            "command": self.command,
            "started_at": self.started_at.isoformat(),
            "finished_at": finished.isoformat(),
            "duration_seconds": self.duration_seconds,
            "project_root": str(self.project_root),
            "summary": self.summary,
            "issues": [asdict(issue) for issue in self.issues],
            "artifacts": [asdict(artifact) for artifact in self.artifacts],
        }
