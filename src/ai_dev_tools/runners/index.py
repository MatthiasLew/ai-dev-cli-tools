from __future__ import annotations

from pathlib import Path

from ai_dev_tools.cache.repository import (
    INDEX_RELATIVE_PATH,
    read_repository_index,
    update_repository_index,
)
from ai_dev_tools.models.report import Artifact, Report


def run_index(project_root: Path, action: str) -> Report:
    root = project_root.resolve()
    report = Report(command=f"index {action}", project_root=root)
    if action == "status":
        index = read_repository_index(root)
        if not index:
            report.status = "partial"
            report.summary = {
                "indexed": False,
                "message": "Repository index does not exist. Run `ai-dev index update`.",
            }
            return report
    else:
        index = update_repository_index(root, rebuild=action == "rebuild")

    index_path = root / INDEX_RELATIVE_PATH
    report.summary = {
        "indexed": True,
        "schema_version": index.get("schema_version"),
        "generated_at": index.get("generated_at"),
        **_summary(index.get("summary")),
    }
    report.artifacts.append(Artifact(str(index_path), "repository-index", "Repository file index"))
    return report


def _summary(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    allowed = {"files", "hashed", "reused", "removed"}
    return {str(key): item for key, item in value.items() if key in allowed}
