from __future__ import annotations

import re
from pathlib import Path

from ai_dev_tools.config import load_settings
from ai_dev_tools.git.symbol_diff import analyze_symbol_diff
from ai_dev_tools.models.report import Report
from ai_dev_tools.reporters.writer import write_json, write_markdown
from ai_dev_tools.security.secrets import scan_paths_for_secrets
from ai_dev_tools.utils.subprocess import run_command

CONFLICT_CODES = {"UU", "AA", "DD", "AU", "UA", "DU", "UD"}


def inspect_git(
    project_root: Path, detailed: bool = False, *, write_reports: bool = True
) -> Report:
    settings = load_settings(project_root)
    report = Report(
        command="git inspect" if detailed else "git status", project_root=settings.project_root
    )
    inside = run_command(["git", "rev-parse", "--is-inside-work-tree"], settings.project_root, 20)
    if inside.exit_code != 0:
        report.status = "warning"
        report.summary = {"state": "NOT_A_GIT_REPOSITORY"}
        return report

    branch = _text(["git", "branch", "--show-current"], settings.project_root) or None
    upstream = _upstream(settings.project_root)
    porcelain = _text(["git", "status", "--porcelain=v1", "--branch"], settings.project_root)
    ahead_count, behind_count = _ahead_behind_counts(porcelain)
    staged_entries = _name_status(
        ["git", "diff", "--cached", "--name-status", "-z"], settings.project_root
    )
    unstaged_entries = _name_status(["git", "diff", "--name-status", "-z"], settings.project_root)
    untracked_files = _nul_output(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"], settings.project_root
    )
    conflicted_files = _conflicted_files(porcelain)
    staged_files = _entry_paths(staged_entries)
    unstaged_files = _entry_paths(unstaged_entries)
    changed = sorted({*staged_files, *unstaged_files, *untracked_files, *conflicted_files})
    states = _states(
        porcelain=porcelain,
        upstream=upstream,
        detached=branch is None,
        has_changes=bool(changed),
        has_conflicts=bool(conflicted_files),
    )
    deleted_files = [
        entry["path"]
        for entry in [*staged_entries, *unstaged_entries]
        if entry["status"].startswith("D")
    ]
    summary: dict[str, object] = {
        "state": states[0],
        "states": states,
        "branch": branch,
        "upstream": upstream,
        "ahead": ahead_count,
        "behind": behind_count,
        "diverged": ahead_count > 0 and behind_count > 0,
        "detached_head": branch is None,
        "changed_files": changed,
        "staged_files": staged_files,
        "unstaged_files": unstaged_files,
        "untracked_files": untracked_files,
        "conflicted_files": conflicted_files,
        "conflicts": conflicted_files,
        "renamed_files": [
            entry
            for entry in [*staged_entries, *unstaged_entries]
            if entry["status"].startswith("R")
        ],
        "deleted_files": deleted_files,
        "stash_count": len(
            [
                line
                for line in _text(["git", "stash", "list"], settings.project_root).splitlines()
                if line
            ]
        ),
    }
    if detailed:
        upstream_diff_bytes = (
            _diff_bytes(settings.project_root, ["git", "diff", upstream + "...HEAD"])
            if upstream
            else 0
        )
        scan_paths = [settings.project_root / item for item in changed]
        symbol_diff = analyze_symbol_diff(
            settings.project_root,
            changed,
            untracked_files=untracked_files,
            deleted_files=deleted_files,
        )
        summary.update(
            {
                "changed_symbols": symbol_diff["symbols"],
                "symbol_diff_summary": symbol_diff["summary"],
                "symbol_diff_fallbacks": symbol_diff["fallbacks"],
                "recent_commits": _text(
                    ["git", "log", "--oneline", "-5"], settings.project_root
                ).splitlines(),
                "diff_stat": _text(["git", "diff", "--stat"], settings.project_root),
                "diff_size_bytes": _diff_bytes(settings.project_root, ["git", "diff"]),
                "unstaged_diff_bytes": _diff_bytes(settings.project_root, ["git", "diff"]),
                "staged_diff_bytes": _diff_bytes(
                    settings.project_root, ["git", "diff", "--cached"]
                ),
                "upstream_diff_bytes": upstream_diff_bytes,
                "large_changed_files": _large_files(settings.project_root, changed),
                "secret_findings": [
                    finding.masked_dict()
                    for finding in scan_paths_for_secrets(settings.project_root, scan_paths)
                ],
            }
        )
    report.summary = summary
    report.status = (
        "warning"
        if any(s in states for s in ("DIRTY", "CONFLICT", "DIVERGED", "DETACHED_HEAD"))
        else "success"
    )
    report.finish()
    if write_reports:
        suffix = "inspect" if detailed else "status"
        write_markdown(report, settings.reports_directory / f"git-{suffix}.md")
        write_json(report, settings.reports_directory / f"git-{suffix}.json")
    return report


def _upstream(root: Path) -> str | None:
    value = _text(["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], root)
    return value or None


def _text(command: list[str], root: Path) -> str:
    result = run_command(command, root, 30)
    return result.stdout.strip() if result.exit_code == 0 else ""


def _nul_output(command: list[str], root: Path) -> list[str]:
    result = run_command(command, root, 30)
    if result.exit_code != 0:
        return []
    return [item for item in result.stdout.split("\0") if item]


def _name_status(command: list[str], root: Path) -> list[dict[str, str]]:
    items = _nul_output(command, root)
    entries: list[dict[str, str]] = []
    index = 0
    while index < len(items):
        status = items[index]
        index += 1
        if status.startswith("R") or status.startswith("C"):
            if index + 1 > len(items):
                break
            old_path = items[index]
            new_path = items[index + 1]
            index += 2
            entries.append({"status": status, "path": new_path, "old_path": old_path})
            continue
        if index > len(items):
            break
        path = items[index]
        index += 1
        entries.append({"status": status, "path": path})
    return entries


def _entry_paths(entries: list[dict[str, str]]) -> list[str]:
    return sorted({entry["path"] for entry in entries})


def _ahead_behind_counts(porcelain: str) -> tuple[int, int]:
    header = porcelain.splitlines()[0] if porcelain else ""
    ahead = re.search(r"ahead (\d+)", header)
    behind = re.search(r"behind (\d+)", header)
    return (int(ahead.group(1)) if ahead else 0, int(behind.group(1)) if behind else 0)


def _states(
    porcelain: str,
    upstream: str | None,
    detached: bool,
    has_changes: bool,
    has_conflicts: bool,
) -> list[str]:
    states: list[str] = []
    if detached:
        states.append("DETACHED_HEAD")
    if upstream is None:
        states.append("NO_UPSTREAM")
    ahead_count, behind_count = _ahead_behind_counts(porcelain)
    if ahead_count and behind_count:
        states.append("DIVERGED")
    elif ahead_count:
        states.append("AHEAD")
    elif behind_count:
        states.append("BEHIND")
    if has_conflicts:
        states.append("CONFLICT")
    if has_changes:
        states.append("DIRTY")
    if not states:
        states.append("UP_TO_DATE")
    return states


def _conflicted_files(porcelain: str) -> list[str]:
    return sorted(
        line[3:]
        for line in porcelain.splitlines()[1:]
        if len(line) > 3 and line[:2] in CONFLICT_CODES
    )


def _diff_bytes(root: Path, command: list[str]) -> int:
    result = run_command(command, root, 60)
    return len(result.stdout.encode("utf-8")) if result.exit_code == 0 else 0


def _large_files(root: Path, files: list[str]) -> list[str]:
    return [
        item
        for item in files
        if (root / item).exists()
        and (root / item).is_file()
        and (root / item).stat().st_size > 1_000_000
    ]
