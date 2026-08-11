from __future__ import annotations

from pathlib import Path

from ai_dev_tools.cache.prompt_layout import write_cache_layout_manifest
from ai_dev_tools.cache.validation import (
    clear_validation_cache,
    prune_validation_cache,
    validation_cache_stats,
)
from ai_dev_tools.models.report import Artifact, Report


def run_cache(project_root: Path, action: str) -> Report:
    root = project_root.resolve()
    report = Report(command=f"cache {action}", project_root=root)
    if action == "layout":
        layout, path = write_cache_layout_manifest(root)
        report.summary = {"cache_layout": layout}
        report.artifacts.append(
            Artifact(str(path), "cache-layout", "Deterministic prompt cache layout manifest")
        )
        return report
    if action == "status":
        result = validation_cache_stats(root)
    elif action == "prune":
        result = prune_validation_cache(root)
    else:
        result = clear_validation_cache(root)
    report.summary = {"validation_cache": result}
    return report
