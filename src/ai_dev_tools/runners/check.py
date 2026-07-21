from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from ai_dev_tools.config import load_settings
from ai_dev_tools.models.report import Report
from ai_dev_tools.parsers.logs import summarize_output
from ai_dev_tools.reporters.writer import write_json, write_markdown
from ai_dev_tools.utils.subprocess import CommandResult, run_command, split_command


def run_check(project_root: Path, mode: str = "fast") -> Report:
    settings = load_settings(project_root)
    commands = _commands_for_project(settings.project_root, settings.commands, mode)
    changed_context = _changed_mode_context(settings.project_root) if mode == "changed" else None
    report = Report(command=f"check --mode {mode}", project_root=settings.project_root)
    if not commands:
        report.status = "warning"
        report.summary = {"mode": mode, "message": "No configured checks detected"}
        if changed_context is not None:
            report.summary["changed_analysis"] = changed_context
        report.finish()
        _write_check_reports(report, mode)
        return report
    results = [
        _run_logged(command, settings.project_root, settings.logs_directory) for command in commands
    ]
    failed = [result for result in results if result.exit_code != 0]
    report.status = "failed" if failed else "success"
    report.summary = {
        "mode": mode,
        "commands": [" ".join(r.command) for r in results],
        "exit_codes": [r.exit_code for r in results],
        "results": [_result_summary(result) for result in results],
    }
    if changed_context is not None:
        report.summary["changed_analysis"] = changed_context
    report.finish()
    _write_check_reports(report, mode)
    return report


def _changed_mode_context(root: Path) -> dict[str, object]:
    git_status = run_command(["git", "status", "--porcelain=v1"], root, 30)
    if git_status.exit_code != 0:
        return {
            "strategy": "broad_fallback",
            "confidence": "low",
            "reason": "Git status is unavailable; running the normal detected check set.",
            "changed_files": [],
        }
    changed_files = [line[3:] for line in git_status.stdout.splitlines() if len(line) > 3]
    reason = (
        "Changed files were detected, but no reliable test dependency map is available yet."
        if changed_files
        else "No changed files were detected; running the normal detected check set."
    )
    return {
        "strategy": "broad_fallback",
        "confidence": "medium" if changed_files else "high",
        "reason": reason,
        "changed_files": changed_files,
    }


def _commands_for_project(root: Path, configured: dict[str, str], mode: str) -> list[list[str]]:
    if configured:
        keys = ["lint", "typecheck", "test"] if mode != "full" else ["test", "lint", "typecheck"]
        return [split_command(configured[key]) for key in keys if key in configured]
    commands: list[list[str]] = []
    if (root / "pyproject.toml").exists() or (root / "requirements.txt").exists():
        text = (
            (root / "pyproject.toml").read_text(encoding="utf-8", errors="replace")
            if (root / "pyproject.toml").exists()
            else ""
        )
        if "ruff" in text:
            commands.append([sys.executable, "-m", "ruff", "check", "."])
        if "mypy" in text:
            commands.append([sys.executable, "-m", "mypy", "src", "tests"])
        if "black" in text:
            commands.append([sys.executable, "-m", "black", "--check", "."])
        if (root / "tests").exists():
            commands.append([sys.executable, "-m", "pytest"])
    if (root / "package.json").exists():
        package = (root / "package.json").read_text(encoding="utf-8", errors="replace")
        if "eslint" in package:
            commands.append(["npm", "run", "lint"])
        if "typescript" in package or "tsc" in package:
            commands.append(["npm", "run", "typecheck"])
        if '"test"' in package:
            commands.append(["npm", "test"])
    if (root / "Cargo.toml").exists():
        commands.extend([["cargo", "fmt", "--check"], ["cargo", "clippy"], ["cargo", "test"]])
    if (root / "pom.xml").exists():
        commands.append(["mvn", "test"])
    if (root / "build.gradle").exists() or (root / "build.gradle.kts").exists():
        commands.append(["gradle", "test"])
    if (root / "composer.json").exists():
        commands.append(["composer", "test"])
    return commands[:2] if mode == "fast" else commands[:3] if mode == "changed" else commands


def _run_logged(command: list[str], root: Path, logs_dir: Path) -> CommandResult:
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"check-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.log"
    result = run_command(command, root)
    log_path.write_text(result.combined_output + "\n", encoding="utf-8")
    result.stdout += f"\nFULL_LOG: {log_path}"
    return result


def _result_summary(result: CommandResult) -> dict[str, object]:
    return {
        "command": " ".join(result.command),
        "exit_code": result.exit_code,
        "duration_seconds": result.duration_seconds,
        "timed_out": result.timed_out,
        "full_log": _full_log_from_output(result.stdout),
        **summarize_output(result.combined_output),
    }


def _full_log_from_output(output: str) -> str | None:
    for line in output.splitlines():
        if line.startswith("FULL_LOG:"):
            return line.split(":", 1)[1].strip()
    return None


def _write_check_reports(report: Report, mode: str) -> None:
    settings = load_settings(report.project_root)
    write_markdown(report, settings.reports_directory / f"check-{mode}-latest.md")
    write_json(report, settings.reports_directory / f"check-{mode}-latest.json")
