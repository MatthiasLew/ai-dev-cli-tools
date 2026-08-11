from __future__ import annotations

import json
import math
from pathlib import Path

from ai_dev_tools.cache.prompt_layout import read_cache_layout_manifest
from ai_dev_tools.cache.repository import read_repository_index
from ai_dev_tools.cache.validation import validation_cache_stats
from ai_dev_tools.config import load_settings
from ai_dev_tools.models.report import Report


def run_diagnostics(project_root: Path) -> Report:
    settings = load_settings(project_root)
    root = settings.project_root
    report = Report(command="diagnostics", project_root=root)
    config_path = root / ".ai-dev-tools.toml"
    report.summary = {
        "cache": validation_cache_stats(root),
        "repository_index": _index_summary(read_repository_index(root)),
        "cache_layout": _cache_layout_summary(read_cache_layout_manifest(root)),
        "reports": _directory_stats(settings.reports_directory),
        "logs": _directory_stats(settings.logs_directory),
        "configuration": {
            "source": str(config_path) if config_path.exists() else "built-in defaults",
            "warnings": settings.warnings,
            "reports_directory": str(settings.reports_directory),
            "logs_directory": str(settings.logs_directory),
        },
        "efficiency_metrics": _efficiency_metrics(root),
        "privacy": "local-only; no repository contents or metrics are transmitted",
    }
    return report


def _directory_stats(directory: Path) -> dict[str, object]:
    files = [path for path in directory.rglob("*") if path.is_file()] if directory.exists() else []
    sizes = [_size(path) for path in files]
    ordered = sorted(files, key=_mtime)
    return {
        "files": len(files),
        "bytes": sum(sizes),
        "oldest": str(ordered[0]) if ordered else None,
        "newest": str(ordered[-1]) if ordered else None,
    }


def _index_summary(index: dict[str, object]) -> dict[str, object]:
    summary = index.get("summary")
    return {
        "available": bool(index),
        "schema_version": index.get("schema_version"),
        **(summary if isinstance(summary, dict) else {}),
    }


def _cache_layout_summary(layout: dict[str, object]) -> dict[str, object]:
    prefix = layout.get("stable_prefix")
    breakpoints = layout.get("provider_breakpoints")
    return {
        "available": bool(layout),
        "schema_version": layout.get("schema_version"),
        "stable_prefix_fingerprint": (
            prefix.get("fingerprint") if isinstance(prefix, dict) else None
        ),
        "provider_breakpoints": len(breakpoints) if isinstance(breakpoints, list) else 0,
    }


def _efficiency_metrics(root: Path) -> dict[str, int]:
    context_path = root / ".ai" / "context" / "context-latest.json"
    try:
        context = json.loads(context_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        context = {}
    summary = context.get("summary", {}) if isinstance(context, dict) else {}
    incremental = summary.get("incremental", {}) if isinstance(summary, dict) else {}
    reused = incremental.get("reused_files", []) if isinstance(incremental, dict) else []
    reused_paths = {str(item) for item in reused} if isinstance(reused, list) else set()
    index = read_repository_index(root)
    entries = index.get("entries", [])
    reused_bytes = 0
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, dict) and entry.get("path") in reused_paths:
                size = entry.get("size")
                reused_bytes += size if isinstance(size, int) else 0
    budget = summary.get("budget", {}) if isinstance(summary, dict) else {}
    used_chars = budget.get("used_chars", 0) if isinstance(budget, dict) else 0
    chars = used_chars if isinstance(used_chars, int) else 0
    return {
        "latest_context_chars": chars,
        "latest_context_token_estimate": math.ceil(chars / 4),
        "reused_context_bytes": reused_bytes,
        "estimated_tokens_avoided": math.ceil(reused_bytes / 4),
    }


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _mtime(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0
