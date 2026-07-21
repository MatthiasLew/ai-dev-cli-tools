from __future__ import annotations

import re
from pathlib import Path

from ai_dev_tools.config import load_settings
from ai_dev_tools.models.report import Report
from ai_dev_tools.reporters.writer import write_json, write_markdown
from ai_dev_tools.security.secrets import scan_paths_for_secrets
from ai_dev_tools.utils.subprocess import run_command


def inspect_git(project_root: Path, detailed: bool = False) -> Report:
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
    upstream = (
        _text(
            ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
            settings.project_root,
        )
        or None
    )
    porcelain = _text(["git", "status", "--porcelain=v1", "--branch"], settings.project_root)
    states = _states(porcelain, upstream, branch is None)
    changed = _changed_files(porcelain)
    summary: dict[str, object] = {
        "state": states[0],
        "states": states,
        "branch": branch,
        "upstream": upstream,
        "detached_head": branch is None,
        "changed_files": changed,
        "staged_files": [
            item[3:] for item in porcelain.splitlines() if item and item[0] not in {" ", "?", "#"}
        ],
        "untracked_files": [item[3:] for item in porcelain.splitlines() if item.startswith("?? ")],
        "conflicts": [
            item[3:]
            for item in porcelain.splitlines()
            if item[:2] in {"UU", "AA", "DD", "AU", "UA", "DU", "UD"}
        ],
        "stash_count": len(
            [
                line
                for line in _text(["git", "stash", "list"], settings.project_root).splitlines()
                if line
            ]
        ),
    }
    if detailed:
        summary.update(
            {
                "recent_commits": _text(
                    ["git", "log", "--oneline", "-5"], settings.project_root
                ).splitlines(),
                "diff_stat": _text(["git", "diff", "--stat"], settings.project_root),
                "diff_size_bytes": len(
                    _text(["git", "diff"], settings.project_root).encode("utf-8")
                ),
                "large_changed_files": _large_files(settings.project_root, changed),
                "secret_findings": [
                    finding.masked_dict()
                    for finding in scan_paths_for_secrets(
                        settings.project_root, [settings.project_root / p for p in changed]
                    )
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
    suffix = "inspect" if detailed else "status"
    write_markdown(report, settings.reports_directory / f"git-{suffix}.md")
    write_json(report, settings.reports_directory / f"git-{suffix}.json")
    return report


def _text(command: list[str], root: Path) -> str:
    result = run_command(command, root, 30)
    return result.stdout.strip() if result.exit_code == 0 else ""


def _states(porcelain: str, upstream: str | None, detached: bool) -> list[str]:
    states: list[str] = []
    header = porcelain.splitlines()[0] if porcelain else ""
    if detached:
        states.append("DETACHED_HEAD")
    if upstream is None:
        states.append("NO_UPSTREAM")
    ahead = re.search(r"ahead (\d+)", header)
    behind = re.search(r"behind (\d+)", header)
    if ahead and behind:
        states.append("DIVERGED")
    elif ahead:
        states.append("AHEAD")
    elif behind:
        states.append("BEHIND")
    body = porcelain.splitlines()[1:]
    if any(line[:2] in {"UU", "AA", "DD", "AU", "UA", "DU", "UD"} for line in body):
        states.append("CONFLICT")
    if body:
        states.append("DIRTY")
    if not states:
        states.append("UP_TO_DATE")
    return states


def _changed_files(porcelain: str) -> list[str]:
    return [line[3:] for line in porcelain.splitlines()[1:] if len(line) > 3]


def _large_files(root: Path, files: list[str]) -> list[str]:
    return [
        item
        for item in files
        if (root / item).exists()
        and (root / item).is_file()
        and (root / item).stat().st_size > 1_000_000
    ]
