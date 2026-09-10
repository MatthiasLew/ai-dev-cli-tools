from __future__ import annotations

import re
from pathlib import Path
from typing import Any

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
    status_cmd = run_command(
        ["git", "status", "--porcelain=v2", "--branch", "-z"],
        settings.project_root,
        30,
    )
    if status_cmd.exit_code != 0:
        report.status = "warning"
        report.summary = {"state": "NOT_A_GIT_REPOSITORY"}
        return report

    parsed = _parse_porcelain_v2(status_cmd.stdout)
    branch = parsed["branch"]
    upstream = parsed["upstream"]
    ahead_count: int = parsed["ahead"]
    behind_count: int = parsed["behind"]
    staged_entries: list[dict[str, str]] = parsed["staged_entries"]
    unstaged_entries: list[dict[str, str]] = parsed["unstaged_entries"]
    untracked_files: list[str] = parsed["untracked_files"]
    conflicted_files: list[str] = parsed["conflicted_files"]

    staged_files = _entry_paths(staged_entries)
    unstaged_files = _entry_paths(unstaged_entries)
    changed = sorted({*staged_files, *unstaged_files, *untracked_files, *conflicted_files})
    states = _states(
        porcelain="",
        upstream=upstream,
        detached=branch is None,
        has_changes=bool(changed),
        has_conflicts=bool(conflicted_files),
        ahead_count=ahead_count,
        behind_count=behind_count,
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
        "stash_count": _stash_count(settings.project_root),
    }
    if detailed:
        upstream_diff_bytes = (
            _diff_bytes(settings.project_root, ["git", "diff", upstream + "...HEAD"])
            if (upstream and ahead_count > 0)
            else 0
        )
        scan_paths = [settings.project_root / item for item in changed]
        symbol_diff = analyze_symbol_diff(
            settings.project_root,
            changed,
            untracked_files=untracked_files,
            deleted_files=deleted_files,
        )
        unstaged_diff_bytes = _diff_bytes(settings.project_root, ["git", "diff"])
        diff_stat = (
            _text(["git", "diff", "--stat"], settings.project_root)
            if unstaged_diff_bytes > 0
            else ""
        )
        staged_diff_bytes = (
            _diff_bytes(settings.project_root, ["git", "diff", "--cached"])
            if staged_files
            else 0
        )
        summary.update(
            {
                "changed_symbols": symbol_diff["symbols"],
                "symbol_diff_summary": symbol_diff["summary"],
                "symbol_diff_fallbacks": symbol_diff["fallbacks"],
                "recent_commits": _text(
                    ["git", "log", "--oneline", "-5"], settings.project_root
                ).splitlines(),
                "diff_stat": diff_stat,
                "diff_size_bytes": unstaged_diff_bytes,
                "unstaged_diff_bytes": unstaged_diff_bytes,
                "staged_diff_bytes": staged_diff_bytes,
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


def _parse_porcelain_v2(output: str) -> dict[str, Any]:
    branch: str | None = None
    upstream: str | None = None
    ahead_count: int = 0
    behind_count: int = 0
    staged_entries: list[dict[str, str]] = []
    unstaged_entries: list[dict[str, str]] = []
    untracked_files: list[str] = []
    conflicted_files: list[str] = []

    tokens = output.split("\0")
    i = 0
    total = len(tokens)
    while i < total:
        tok = tokens[i]
        i += 1
        if not tok:
            continue
        if tok.startswith("# branch.head "):
            head = tok[14:]
            branch = None if head == "(detached)" else head
        elif tok.startswith("# branch.upstream "):
            upstream = tok[18:]
        elif tok.startswith("# branch.ab "):
            match = re.search(r"\+(\d+)\s+-(\d+)", tok[12:])
            if match:
                ahead_count = int(match.group(1))
                behind_count = int(match.group(2))
        elif tok.startswith("1 "):
            parts = tok.split(" ", 8)
            if len(parts) == 9:
                xy = parts[1]
                path = parts[8]
                x, y = xy[0], xy[1]
                if x != ".":
                    staged_entries.append({"status": x, "path": path})
                if y != ".":
                    unstaged_entries.append({"status": y, "path": path})
        elif tok.startswith("2 "):
            parts = tok.split(" ", 9)
            orig_path = tokens[i] if i < total else ""
            i += 1
            if len(parts) == 10:
                xy = parts[1]
                score = parts[8]
                path = parts[9]
                x, y = xy[0], xy[1]
                if x != ".":
                    staged_entries.append({"status": score, "path": path, "old_path": orig_path})
                if y != ".":
                    unstaged_entries.append({"status": y, "path": path})
        elif tok.startswith("u "):
            parts = tok.split(" ", 10)
            if len(parts) == 11:
                path = parts[10]
                conflicted_files.append(path)
                staged_entries.append({"status": "U", "path": path})
                unstaged_entries.append({"status": "U", "path": path})
        elif tok.startswith("? "):
            untracked_files.append(tok[2:])

    return {
        "branch": branch,
        "upstream": upstream,
        "ahead": ahead_count,
        "behind": behind_count,
        "staged_entries": staged_entries,
        "unstaged_entries": unstaged_entries,
        "untracked_files": sorted(untracked_files),
        "conflicted_files": sorted(conflicted_files),
    }


def _stash_count(root: Path) -> int:
    git_dir = root / ".git"
    if git_dir.is_file():
        try:
            content = git_dir.read_text(encoding="utf-8").strip()
            if content.startswith("gitdir:"):
                target = (root / content[7:].strip()).resolve()
                if not (target / "logs" / "refs" / "stash").is_file():
                    return 0
        except OSError:
            pass
    elif git_dir.is_dir() and not (git_dir / "logs" / "refs" / "stash").is_file():
        return 0

    stash_lines = _text(["git", "stash", "list"], root).splitlines()
    return len([line for line in stash_lines if line])


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
    *,
    ahead_count: int | None = None,
    behind_count: int | None = None,
) -> list[str]:
    states: list[str] = []
    if detached:
        states.append("DETACHED_HEAD")
    if upstream is None:
        states.append("NO_UPSTREAM")
    if ahead_count is None or behind_count is None:
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
    large: list[str] = []
    for item in files:
        target = root / item
        try:
            stat = target.stat()
            if stat.st_size > 1_000_000:
                large.append(item)
        except OSError:
            continue
    return large
