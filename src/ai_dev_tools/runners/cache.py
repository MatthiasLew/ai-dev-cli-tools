from __future__ import annotations

from pathlib import Path

from ai_dev_tools.cache.validation import (
    clear_validation_cache,
    prune_validation_cache,
    validation_cache_stats,
)
from ai_dev_tools.models.report import Report


def run_cache(project_root: Path, action: str) -> Report:
    root = project_root.resolve()
    report = Report(command=f"cache {action}", project_root=root)
    if action == "status":
        result = validation_cache_stats(root)
    elif action == "prune":
        result = prune_validation_cache(root)
    else:
        result = clear_validation_cache(root)
    report.summary = {"validation_cache": result}
    return report
