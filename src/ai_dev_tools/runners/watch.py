from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from ai_dev_tools.config import load_settings
from ai_dev_tools.models.report import Issue, Report
from ai_dev_tools.runners.check import run_check

_WATCH_REPORT = ".ai/reports/watch-latest.json"


@dataclass(frozen=True, slots=True)
class WatchOptions:
    mode: str = "changed"
    debounce_ms: int = 500
    poll_ms: int = 100
    jobs: int = 1
    initial: bool = False
    max_runs: int = 0


def run_watch(project_root: Path, options: WatchOptions) -> Report:
    report = Report(command=f"watch --mode {options.mode}", project_root=project_root.resolve())
    if options.debounce_ms < 0 or options.poll_ms < 10 or options.max_runs < 0:
        report.status = "invalid_configuration"
        report.summary = {
            "reason_code": "INVALID_WATCH_OPTIONS",
            "debounce_ms": options.debounce_ms,
            "poll_ms": options.poll_ms,
            "max_runs": options.max_runs,
        }
        return report.finish()

    settings = load_settings(project_root)
    ignored = _ignored_roots(settings.ignore_paths)
    observed = _snapshot(settings.project_root, ignored)
    pending_since = time.monotonic() if options.initial else None
    validations = 0
    coalesced_changes = 0
    queued_during_validation = 0
    latest: Report | None = None
    interrupted = False

    try:
        while options.max_runs == 0 or validations < options.max_runs:
            current = _snapshot(settings.project_root, ignored)
            if current != observed:
                if pending_since is not None:
                    coalesced_changes += 1
                pending_since = time.monotonic()
                observed = current
            if pending_since is None:
                time.sleep(options.poll_ms / 1000)
                continue
            elapsed_ms = (time.monotonic() - pending_since) * 1000
            if elapsed_ms < options.debounce_ms:
                time.sleep(min(options.poll_ms, options.debounce_ms - elapsed_ms) / 1000)
                continue

            before_validation = observed
            latest = run_check(
                settings.project_root,
                mode=options.mode,
                jobs=options.jobs,
                policy="feedback-first",
            )
            validations += 1
            pending_since = None
            after_validation = _snapshot(settings.project_root, ignored)
            if after_validation != before_validation:
                queued_during_validation += 1
                observed = after_validation
                pending_since = time.monotonic()
    except KeyboardInterrupt:
        interrupted = True

    report.status = latest.status if latest is not None else "partial"
    if latest is None:
        report.issues.append(
            Issue("info", "Watch stopped before a validation run", code="WATCH_NO_RUN")
        )
    else:
        report.issues.extend(latest.issues)
        report.artifacts.extend(latest.artifacts)
    report.summary = {
        "mode": options.mode,
        "foreground": True,
        "interrupted": interrupted,
        "validations": validations,
        "coalesced_changes": coalesced_changes,
        "queued_during_validation": queued_during_validation,
        "debounce_ms": options.debounce_ms,
        "poll_ms": options.poll_ms,
        "latest_status": latest.status if latest else None,
        "latest_command": latest.command if latest else None,
        "ignored_roots": sorted(ignored),
    }
    report.finish()
    from ai_dev_tools.reporters.writer import write_json, write_markdown

    output = settings.project_root / _WATCH_REPORT
    write_json(report, output)
    write_markdown(report, output.with_suffix(".md"))
    return report


def _ignored_roots(configured: set[str]) -> set[str]:
    roots = {
        ".git",
        ".ai",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "venv",
    }
    roots.update(path.replace(chr(92), "/").strip("/") for path in configured)
    return roots


def _snapshot(root: Path, ignored: set[str]) -> dict[str, tuple[int, int]]:
    result: dict[str, tuple[int, int]] = {}
    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            entries = sorted(directory.iterdir(), key=lambda item: item.name)
        except OSError:
            continue
        for path in entries:
            try:
                relative = path.relative_to(root).as_posix()
                if _is_ignored(relative, ignored):
                    continue
                if path.is_symlink():
                    continue
                if path.is_dir():
                    stack.append(path)
                elif path.is_file():
                    stat = path.stat()
                    result[relative] = (stat.st_mtime_ns, stat.st_size)
            except OSError:
                continue
    return result


def _is_ignored(relative: str, ignored: set[str]) -> bool:
    return any(relative == prefix or relative.startswith(prefix + "/") for prefix in ignored)