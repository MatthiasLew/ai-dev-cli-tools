from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path

from ai_dev_tools import __version__
from ai_dev_tools.models.report import Report

CommandHandler = Callable[[Path], Report]


EXIT_SUCCESS = 0
EXIT_FAILED = 1
EXIT_USAGE = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-dev")
    parser.add_argument("--version", action="version", version=f"ai-dev {__version__}")
    parser.add_argument("--project", type=Path, default=Path.cwd(), help="Project directory")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text")
    parser.add_argument("--quiet", action="store_true", help="Only print errors and artifact paths")

    sub = parser.add_subparsers(dest="command", required=True)
    for name in ["doctor", "scan"]:
        sub.add_parser(name)

    bootstrap = sub.add_parser("bootstrap")
    bootstrap.add_argument("--dry-run", action="store_true")
    bootstrap.add_argument("--explain", action="store_true")
    bootstrap.add_argument("--create-env", action="store_true")

    run = sub.add_parser("run")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--explain", action="store_true")
    run.add_argument("--foreground", action="store_true")
    run.add_argument("--timeout", type=int, default=300)
    run.add_argument("--ready-http")
    run.add_argument("--ready-tcp")
    run.add_argument("--startup-timeout", type=int, default=10)
    run.add_argument("--startup-log-lines", type=int, default=50)

    stop = sub.add_parser("stop")
    stop.add_argument("--explain", action="store_true")
    stop.add_argument("--timeout", type=int, default=10)
    map_parser = sub.add_parser("map")
    map_parser.add_argument("--max-files", type=int, default=500)
    map_parser.add_argument("--max-depth", type=int, default=6)

    check = sub.add_parser("check")
    check.add_argument("--mode", choices=["fast", "changed", "full"], default="fast")
    check.add_argument("--jobs", type=int, default=1)
    check.add_argument("--no-cache", action="store_true")
    check.add_argument(
        "--explain", action="store_true", help="Show selected checks without running them"
    )

    cache = sub.add_parser("cache")
    cache_sub = cache.add_subparsers(dest="cache_command", required=True)
    for action in ["status", "prune", "clear"]:
        cache_sub.add_parser(action)

    index = sub.add_parser("index")
    index_sub = index.add_subparsers(dest="index_command", required=True)
    for action in ["status", "update", "rebuild"]:
        index_sub.add_parser(action)

    test = sub.add_parser("test")
    test_sub = test.add_subparsers(dest="test_command", required=True)
    test_sub.add_parser("affected")

    logs = sub.add_parser("logs")
    logs_sub = logs.add_subparsers(dest="logs_command", required=True)
    logs_summary = logs_sub.add_parser("summarize")
    logs_summary.add_argument("log_path", nargs="?", type=Path)
    logs_summary.add_argument("--tool", default="auto")

    context = sub.add_parser("context")
    context_sub = context.add_subparsers(dest="context_command", required=True)
    context_build = context_sub.add_parser("build")
    context_build.add_argument("--task", default="")
    context_build.add_argument(
        "--profile",
        choices=["default", "minimal", "debug", "review", "full"],
        default="default",
    )
    context_build.add_argument("--max-chars", type=int, default=50_000)
    context_build.add_argument("--max-files", type=int, default=30)
    context_build.add_argument("--max-file-chars", type=int, default=8_000)
    context_build.add_argument("--max-diff-chars", type=int, default=15_000)
    context_build.add_argument("--include", action="append", default=[])
    context_build.add_argument("--exclude", action="append", default=[])
    context_build.add_argument("--changed-only", action="store_true")
    context_build.add_argument("--staged-only", action="store_true")
    context_build.add_argument("--no-git", action="store_true")
    context_build.add_argument("--format", choices=["markdown", "json", "both"], default="both")
    context_build.add_argument("--output", type=Path)
    context_build.add_argument("--explain", action="store_true")
    context_build.add_argument("--incremental", action="store_true")

    git = sub.add_parser("git")
    git_sub = git.add_subparsers(dest="git_command", required=True)
    git_sub.add_parser("status")
    git_sub.add_parser("inspect")

    sub.add_parser("diagnostics")
    sub.add_parser("capabilities")
    sub.add_parser("finish")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(_normalize_global_flags(argv))
    project_root = args.project.resolve()
    report = _dispatch(args, project_root).finish()
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    elif not args.quiet:
        _print_text(report)
    else:
        for artifact in report.artifacts:
            print(artifact.path)
    return EXIT_SUCCESS if report.status in {"success", "warning", "partial"} else EXIT_FAILED


def _normalize_global_flags(argv: list[str] | None) -> list[str] | None:
    if argv is None:
        argv = sys.argv[1:]
    normalized = list(argv)
    moved: list[str] = []
    for flag in ("--json", "--quiet"):
        if flag in normalized:
            normalized = [item for item in normalized if item != flag]
            moved.append(flag)
    if "--project" in normalized:
        index = normalized.index("--project")
        if index + 1 < len(normalized) and index != 0:
            project_pair = normalized[index : index + 2]
            del normalized[index : index + 2]
            moved.extend(project_pair)
    return [*moved, *normalized]


def _dispatch(args: argparse.Namespace, project_root: Path) -> Report:
    command = args.command
    if command == "run":
        from ai_dev_tools.runtime import RunOptions, run_application

        return run_application(
            project_root,
            RunOptions(
                explain=args.explain,
                dry_run=args.dry_run,
                foreground=args.foreground,
                timeout_seconds=args.timeout,
                readiness_http=args.ready_http,
                readiness_tcp=args.ready_tcp,
                startup_timeout_seconds=args.startup_timeout,
                startup_log_lines=args.startup_log_lines,
            ),
        )
    if command == "stop":
        from ai_dev_tools.runtime import stop_application

        return stop_application(
            project_root,
            explain=args.explain,
            timeout_seconds=args.timeout,
        )
    if command == "test" and args.test_command == "affected":
        command = "check"
        args.mode = "changed"
        args.explain = False
        args.jobs = 1
        args.no_cache = False
    if command == "logs" and args.logs_command == "summarize":
        from ai_dev_tools.parsers.logs import summarize_latest_log, summarize_log_file

        if args.log_path is not None:
            return summarize_log_file(project_root, args.log_path, tool=args.tool)
        return summarize_latest_log(project_root)
    if command == "context" and args.context_command == "build":
        from ai_dev_tools.context import ContextOptions, build_context

        return build_context(
            project_root,
            ContextOptions(
                task=args.task,
                profile=args.profile,
                max_chars=args.max_chars,
                max_files=args.max_files,
                max_file_chars=args.max_file_chars,
                max_diff_chars=args.max_diff_chars,
                include=tuple(args.include),
                exclude=tuple(args.exclude),
                changed_only=args.changed_only,
                staged_only=args.staged_only,
                no_git=args.no_git,
                output=args.output,
                format=args.format,
                explain=args.explain,
                incremental=args.incremental,
            ),
        )
    if command == "bootstrap":
        from ai_dev_tools.runners.bootstrap import BootstrapOptions, run_bootstrap

        return run_bootstrap(
            project_root,
            BootstrapOptions(
                dry_run=args.dry_run,
                explain=args.explain,
                create_env=args.create_env,
            ),
        )
    if command == "doctor":
        from ai_dev_tools.detectors.environment import run_doctor

        return run_doctor(project_root)
    if command == "scan":
        from ai_dev_tools.detectors.project import scan_project

        return scan_project(project_root)
    if command == "map":
        from ai_dev_tools.detectors.repository_map import map_repository

        return map_repository(project_root, max_files=args.max_files, max_depth=args.max_depth)
    if command == "check":
        from ai_dev_tools.runners.check import run_check

        return run_check(
            project_root,
            mode=args.mode,
            explain=args.explain,
            jobs=args.jobs,
            use_cache=not args.no_cache,
        )
    if command == "cache":
        from ai_dev_tools.runners.cache import run_cache

        return run_cache(project_root, args.cache_command)
    if command == "index":
        from ai_dev_tools.runners.index import run_index

        return run_index(project_root, args.index_command)
    if command == "diagnostics":
        from ai_dev_tools.runners.diagnostics import run_diagnostics

        return run_diagnostics(project_root)
    if command == "capabilities":
        return _capabilities_report(project_root)
    if command == "git":
        from ai_dev_tools.git.inspect import inspect_git

        return inspect_git(project_root, detailed=args.git_command == "inspect")
    if command == "finish":
        from ai_dev_tools.runners.finish import run_finish

        return run_finish(project_root)
    raise SystemExit(EXIT_USAGE)


def _capabilities_report(project_root: Path) -> Report:
    report = Report(command="capabilities", project_root=project_root)
    implemented = [
        "doctor",
        "scan",
        "map",
        "check",
        "test affected",
        "cache status",
        "cache prune",
        "cache clear",
        "index status",
        "index update",
        "index rebuild",
        "logs summarize",
        "context build",
        "bootstrap",
        "run",
        "stop",
        "git status",
        "git inspect",
        "finish",
        "diagnostics",
        "capabilities",
    ]
    planned: list[str] = []
    report.summary = {
        "implemented": implemented,
        "planned": planned,
        "deprecated": [],
        "commands": {name: "implemented" for name in implemented}
        | {name: "planned" for name in planned},
        "quality": {
            "implemented": implemented,
            "unit_tested": implemented,
            "integration_tested": ["scan", "git status", "git inspect", "context build"],
            "cross_platform_ci_verified": [],
            "ci_status": "BLOCKED_EXTERNAL",
        },
    }
    return report


def _print_text(report: Report) -> None:
    print(f"STATUS: {report.status.upper()}")
    print(f"COMMAND: {report.command}")
    print(f"DURATION: {report.duration_seconds}s")
    for key, value in report.summary.items():
        print(f"{key.upper()}: {value}")
    if report.issues:
        print("ISSUES:")
        for issue in report.issues:
            location = f" [{issue.location}]" if issue.location else ""
            print(f"- {issue.severity}: {issue.message}{location}")


if __name__ == "__main__":
    sys.exit(main())
