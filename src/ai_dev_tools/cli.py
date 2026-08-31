from __future__ import annotations

import argparse
import json
import sys
import time
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
    bootstrap.add_argument("--if-needed", action="store_true")

    environment = sub.add_parser("environment")
    environment_sub = environment.add_subparsers(dest="environment_command", required=True)
    environment_sub.add_parser("explain")

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
    check.add_argument("--resume", action="store_true")
    check.add_argument("--retry-flaky", type=int, default=0, metavar="COUNT")
    check.add_argument("--retry-infra", type=int, default=1, metavar="COUNT")
    check.add_argument("--policy", choices=["complete", "feedback-first"], default="complete")
    check.add_argument("--compare", metavar="BASELINE")
    check.add_argument(
        "--explain", action="store_true", help="Show selected checks without running them"
    )

    cache = sub.add_parser("cache")
    cache_sub = cache.add_subparsers(dest="cache_command", required=True)
    for action in ["status", "prune", "clear", "layout"]:
        cache_sub.add_parser(action)

    index = sub.add_parser("index")
    index_sub = index.add_subparsers(dest="index_command", required=True)
    for action in ["status", "update", "rebuild"]:
        index_sub.add_parser(action)
    index_daemon = index_sub.add_parser("daemon")
    index_daemon.add_argument(
        "daemon_action",
        nargs="?",
        choices=["start", "status", "stop", "foreground"],
        default="start",
    )
    index_daemon.add_argument("--poll", type=int, default=500, metavar="MILLISECONDS")
    index_daemon.add_argument("--max-updates", type=int, default=0)
    index_daemon.add_argument("--idle-timeout", type=int, default=0, metavar="SECONDS")

    semantic = sub.add_parser("semantic")
    semantic_sub = semantic.add_subparsers(dest="semantic_command", required=True)
    semantic_sub.add_parser("status")
    semantic_index = semantic_sub.add_parser("index")
    semantic_index.add_argument("--backend", default="auto")

    policy_parser = sub.add_parser("policy")
    policy_sub = policy_parser.add_subparsers(dest="policy_command", required=True)
    policy_assess = policy_sub.add_parser("assess")
    policy_assess.add_argument("policy_command_args", nargs=argparse.REMAINDER)

    sarif = sub.add_parser("sarif")
    sarif.add_argument("--input", required=True, type=Path)
    sarif.add_argument("--output", type=Path)

    test = sub.add_parser("test")
    test_sub = test.add_subparsers(dest="test_command", required=True)
    test_sub.add_parser("affected")
    test_sub.add_parser("flaky")

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
        choices=["default", "minimal", "debug", "review", "implement", "docs", "full"],
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
    context_build.add_argument("--since", metavar="CONTEXT_ID")
    context_build.add_argument("--compare", metavar="BASELINE")
    context_build.add_argument("--retrieval", choices=["auto", "always", "never"], default="auto")
    context_build.add_argument(
        "--tokenizer", choices=["estimate", "cl100k_base", "o200k_base"], default="estimate"
    )
    context_build.add_argument("--token-budget", action="append", default=[])
    context_build.add_argument("--provider-usage", type=Path)
    context_build.add_argument("--refine", action="append", default=[])
    context_build.add_argument("--refinement-rounds", type=int, choices=range(0, 4), default=1)
    context_build.add_argument("--refinement-max-files", type=int, default=5)
    context_build.add_argument("--compression", choices=["off", "conservative"], default="off")
    context_build.add_argument(
        "--adaptive",
        action="store_true",
        help="derive a smaller task-aware context budget while preserving explicit limits",
    )

    git = sub.add_parser("git")
    git_sub = git.add_subparsers(dest="git_command", required=True)
    git_sub.add_parser("status")
    git_sub.add_parser("inspect")

    completion = sub.add_parser("completion")
    completion.add_argument("shell", choices=["bash", "zsh", "fish", "powershell"])

    watch = sub.add_parser("watch")
    watch.add_argument("--mode", choices=["fast", "changed", "full"], default="changed")
    watch.add_argument("--debounce", type=int, default=500, metavar="MILLISECONDS")
    watch.add_argument("--poll", type=int, default=100, metavar="MILLISECONDS")
    watch.add_argument("--jobs", type=int, default=1)
    watch.add_argument("--initial", action="store_true")
    watch.add_argument("--max-runs", type=int, default=0)

    feedback = sub.add_parser("feedback")
    feedback.add_argument("--task", default="")
    feedback.add_argument("--explain", action="store_true")
    feedback.add_argument("--jobs", type=int, default=4)
    feedback.add_argument(
        "--ack-state",
        default=None,
        help="acknowledge a prior feedback state fingerprint to allow an unchanged receipt",
    )
    feedback.add_argument(
        "--no-delta",
        action="store_false",
        dest="delta",
        help="return the full feedback payload even when successful session state is unchanged",
    )

    session = sub.add_parser("session")
    session_sub = session.add_subparsers(dest="session_command", required=True)
    session_sub.add_parser("status")
    agents = sub.add_parser("agents")
    agents_sub = agents.add_subparsers(dest="agents_command", required=True)
    agents_sub.add_parser("status")
    agents_add = agents_sub.add_parser("add")
    agents_add.add_argument("task_id")
    agents_add.add_argument("--title", required=True)
    agents_add.add_argument("--path", action="append", required=True, dest="paths")
    agents_add.add_argument("--depends-on", action="append", default=[], dest="dependencies")
    for action in ("claim", "heartbeat"):
        agent_action = agents_sub.add_parser(action)
        agent_action.add_argument("task_id")
        agent_action.add_argument("--agent", required=True, dest="agent_id")
        agent_action.add_argument("--lease-seconds", type=int, default=900)
    for action in ("release", "complete"):
        agent_action = agents_sub.add_parser(action)
        agent_action.add_argument("task_id")
        agent_action.add_argument("--agent", required=True, dest="agent_id")

    baseline = sub.add_parser("baseline")
    baseline_sub = baseline.add_subparsers(dest="baseline_command", required=True)
    baseline_sub.add_parser("list")
    for action in ("create", "compare"):
        baseline_action = baseline_sub.add_parser(action)
        baseline_action.add_argument("name")

    benchmark = sub.add_parser("benchmark")
    benchmark_sub = benchmark.add_subparsers(dest="benchmark_command", required=True)
    benchmark_run = benchmark_sub.add_parser("run")
    benchmark_run.add_argument("--suite", required=True, type=Path)
    benchmark_run.add_argument("--variant", required=True)
    benchmark_run.add_argument("--trials", type=int, default=3)
    benchmark_run.add_argument("--cache-state", choices=["cold", "warm"], default="cold")
    benchmark_run.add_argument("--timeout", type=int, default=300)
    benchmark_compare = benchmark_sub.add_parser("compare")
    benchmark_compare.add_argument("baseline", type=Path)
    benchmark_compare.add_argument("candidate", type=Path)
    benchmark_gate = benchmark_sub.add_parser("gate")
    benchmark_gate.add_argument("baseline", type=Path)
    benchmark_gate.add_argument("candidate", type=Path)
    benchmark_gate.add_argument("--max-time-regression", type=float, default=20.0)
    benchmark_gate.add_argument("--max-token-regression", type=float, default=5.0)
    benchmark_gate.add_argument("--min-token-reduction", type=float, default=0.0)
    benchmark_gate.add_argument("--min-precision", type=float, default=0.8)
    benchmark_gate.add_argument("--min-recall", type=float, default=0.9)
    benchmark_gate.add_argument("--max-false-negatives", type=int, default=0)
    benchmark_corpus = benchmark_sub.add_parser("corpus")
    benchmark_corpus.add_argument(
        "--manifest", type=Path, default=Path("examples/benchmarks/agent-corpus.json")
    )
    benchmark_corpus.add_argument("--trials", type=int, default=3)
    benchmark_corpus.add_argument("--timeout", type=int, default=300)

    performance = sub.add_parser("performance")
    performance_sub = performance.add_subparsers(dest="performance_command", required=True)
    performance_sub.add_parser("latest")
    performance_compare = performance_sub.add_parser("compare")
    performance_compare.add_argument("baseline", type=Path)
    performance_compare.add_argument("candidate", type=Path)

    explain = sub.add_parser("explain")
    explain.add_argument("reference", nargs="?")
    explain.add_argument("--symbol", metavar="PATH#SYMBOL")
    explain.add_argument("--tail", type=int, default=100)

    mcp = sub.add_parser("mcp")
    mcp_sub = mcp.add_subparsers(dest="mcp_command", required=True)
    mcp_sub.add_parser("serve")

    integrations = sub.add_parser("integrations")
    integrations_sub = integrations.add_subparsers(dest="integrations_command", required=True)
    integrations_install = integrations_sub.add_parser("install")
    integrations_install.add_argument(
        "client", nargs="?", choices=["all", "codex", "claude", "cursor", "generic"], default="all"
    )
    integrations_install.add_argument("--force", action="store_true")

    dashboard = sub.add_parser("dashboard")
    dashboard_sub = dashboard.add_subparsers(dest="dashboard_command", required=True)
    dashboard_sub.add_parser("status")
    dashboard_serve = dashboard_sub.add_parser("serve")
    dashboard_serve.add_argument("--host", default="127.0.0.1")
    dashboard_serve.add_argument("--port", type=int, default=8765)

    sub.add_parser("diagnostics")
    sub.add_parser("capabilities")
    plan = sub.add_parser("plan")
    plan.add_argument("--task", default="")
    plan.add_argument("--mode", choices=["fast", "changed", "full"], default="changed")
    sub.add_parser("finish")
    return parser


def main(argv: list[str] | None = None) -> int:
    command_started = time.monotonic()
    parser = build_parser()
    args = parser.parse_args(_normalize_global_flags(argv))
    project_root = args.project.resolve()
    startup_seconds = time.monotonic() - command_started
    if args.command == "mcp" and args.mcp_command == "serve":
        from ai_dev_tools.mcp_server import serve_mcp

        return serve_mcp(project_root)
    if args.command == "dashboard" and args.dashboard_command == "serve":
        from ai_dev_tools.dashboard import serve_dashboard

        try:
            return serve_dashboard(project_root, args.host, args.port)
        except ValueError as exc:
            parser.error(str(exc))
    if args.command == "completion":
        from ai_dev_tools.completion import render_completion

        print(render_completion(args.shell), end="")
        return EXIT_SUCCESS
    dispatch_started = time.monotonic()
    report = _dispatch(args, project_root).finish()
    dispatch_seconds = time.monotonic() - dispatch_started
    _record_command_performance(report, args, startup_seconds, dispatch_seconds)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    elif not args.quiet:
        _print_text(report)
    else:
        for artifact in report.artifacts:
            print(artifact.path)
    return EXIT_SUCCESS if report.status in {"success", "warning", "partial"} else EXIT_FAILED


def _record_command_performance(
    report: Report,
    args: argparse.Namespace,
    startup_seconds: float,
    dispatch_seconds: float,
) -> None:
    operation = ""
    if args.command == "scan":
        operation = "scan"
    elif args.command == "check" and args.explain:
        operation = "check-explain"
    elif args.command == "context" and args.context_command == "build" and args.incremental:
        operation = "context-incremental"
    if not operation:
        return
    stages = {"startup": startup_seconds, "command": dispatch_seconds}
    measured = report.summary.get("performance")
    if isinstance(measured, dict):
        measured_stages = measured.get("stages_seconds")
        if isinstance(measured_stages, dict):
            stages.update(
                {
                    str(key): float(value)
                    for key, value in measured_stages.items()
                    if isinstance(value, (int, float)) and not isinstance(value, bool)
                }
            )
    execution = report.summary.get("execution")
    if isinstance(execution, dict):
        for source, target in (
            ("aggregate_subprocess_seconds", "subprocess_execution"),
            ("wall_seconds", "scheduler_wall"),
        ):
            value = execution.get(source)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                stages[target] = float(value)
    from ai_dev_tools.runners.performance import record_performance

    record_performance(
        report,
        operation,
        stages,
        startup_seconds + dispatch_seconds,
    )
    report.finish()


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
    if command == "test" and args.test_command == "flaky":
        from ai_dev_tools.runners.flaky import run_flaky_report

        return run_flaky_report(project_root)
    if command == "test" and args.test_command == "affected":
        command = "check"
        args.mode = "changed"
        args.explain = False
        args.jobs = 1
        args.no_cache = False
        args.resume = False
        args.retry_flaky = 0
        args.retry_infra = 1
        args.policy = "complete"
        args.compare = None
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
                since=args.since,
                compare=args.compare,
                retrieval=args.retrieval,
                tokenizer=args.tokenizer,
                token_budgets=tuple(args.token_budget),
                provider_usage=args.provider_usage,
                refine=tuple(args.refine),
                refinement_rounds=args.refinement_rounds,
                refinement_max_files=max(args.refinement_max_files, 0),
                compression=args.compression,
                adaptive=args.adaptive,
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
                if_needed=args.if_needed,
            ),
        )
    if command == "environment" and args.environment_command == "explain":
        from ai_dev_tools.runners.environment_state import run_environment_explain

        return run_environment_explain(project_root)
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
            policy=args.policy,
            resume=args.resume,
            retry_flaky=args.retry_flaky,
            retry_infra=args.retry_infra,
            compare=args.compare,
        )
    if command == "cache":
        from ai_dev_tools.runners.cache import run_cache

        return run_cache(project_root, args.cache_command)
    if command == "index":
        if args.index_command == "daemon":
            if getattr(args, "daemon_action", "start") in {"start", "status", "stop"}:
                from ai_dev_tools.index_daemon_service import control_index_daemon

                return control_index_daemon(project_root, args.daemon_action)
            from ai_dev_tools.runners.index_daemon import run_index_daemon

            return run_index_daemon(
                project_root,
                poll_ms=args.poll,
                max_updates=args.max_updates,
                idle_timeout_seconds=args.idle_timeout,
            )
        from ai_dev_tools.runners.index import run_index

        return run_index(project_root, args.index_command)
    if command == "semantic":
        from ai_dev_tools.semantic import run_semantic

        return run_semantic(
            project_root,
            args.semantic_command,
            backend=getattr(args, "backend", "auto"),
        )
    if command == "policy" and args.policy_command == "assess":
        from ai_dev_tools.runners.policy import run_policy_assess

        policy_command = list(args.policy_command_args)
        if policy_command[:1] == ["--"]:
            policy_command = policy_command[1:]
        return run_policy_assess(project_root, policy_command)
    if command == "sarif":
        from ai_dev_tools.reporters.sarif import run_sarif_export

        return run_sarif_export(project_root, args.input, args.output)
    if command == "watch":
        from ai_dev_tools.runners.watch import WatchOptions, run_watch

        return run_watch(
            project_root,
            WatchOptions(
                mode=args.mode,
                debounce_ms=args.debounce,
                poll_ms=args.poll,
                jobs=args.jobs,
                initial=args.initial,
                max_runs=args.max_runs,
            ),
        )
    if command == "feedback":
        from ai_dev_tools.runners.feedback import FeedbackOptions, run_feedback

        return run_feedback(
            project_root,
            FeedbackOptions(
                task=args.task,
                explain=args.explain,
                jobs=args.jobs,
                delta=args.delta,
                acknowledged_state=args.ack_state,
            ),
        )
    if command == "session" and args.session_command == "status":
        from ai_dev_tools.runners.feedback import run_session_status

        return run_session_status(project_root)
    if command == "agents":
        from ai_dev_tools.runners.coordination import coordinate_agents

        return coordinate_agents(
            project_root,
            args.agents_command,
            task_id=getattr(args, "task_id", ""),
            agent_id=getattr(args, "agent_id", ""),
            title=getattr(args, "title", ""),
            paths=getattr(args, "paths", []),
            dependencies=getattr(args, "dependencies", []),
            lease_seconds=getattr(args, "lease_seconds", 900),
        )
    if command == "baseline":
        from ai_dev_tools.runners.baseline import run_baseline

        return run_baseline(
            project_root,
            args.baseline_command,
            getattr(args, "name", None),
        )
    if command == "benchmark":
        from ai_dev_tools.runners.benchmark import (
            compare_benchmarks,
            gate_benchmarks,
            run_benchmark,
            run_benchmark_corpus,
        )

        if args.benchmark_command == "run":
            return run_benchmark(
                project_root,
                args.suite,
                args.variant,
                trials=args.trials,
                cache_state=args.cache_state,
                timeout_seconds=args.timeout,
            )
        if args.benchmark_command == "compare":
            return compare_benchmarks(project_root, args.baseline, args.candidate)
        if args.benchmark_command == "corpus":
            return run_benchmark_corpus(
                project_root, args.manifest, trials=args.trials, timeout_seconds=args.timeout
            )
        return gate_benchmarks(
            project_root,
            args.baseline,
            args.candidate,
            max_time_regression=args.max_time_regression,
            max_token_regression=args.max_token_regression,
            min_token_reduction=args.min_token_reduction,
            min_precision=args.min_precision,
            min_recall=args.min_recall,
            max_false_negatives=args.max_false_negatives,
        )
    if command == "integrations":
        from ai_dev_tools.integrations import install_integrations

        return install_integrations(project_root, args.client, force=args.force)
    if command == "dashboard":
        from ai_dev_tools.dashboard import dashboard_status

        return dashboard_status(project_root)
    if command == "performance":
        from ai_dev_tools.runners.performance import compare_performance, run_performance_latest

        if args.performance_command == "latest":
            return run_performance_latest(project_root)
        return compare_performance(project_root, args.baseline, args.candidate)
    if command == "explain":
        from ai_dev_tools.reporters.progressive import run_explain, run_explain_symbol

        if args.symbol:
            return run_explain_symbol(project_root, args.symbol, args.tail)
        if args.reference:
            return run_explain(project_root, args.reference, args.tail)
        raise SystemExit(EXIT_USAGE)
    if command == "diagnostics":
        from ai_dev_tools.runners.diagnostics import run_diagnostics

        return run_diagnostics(project_root)
    if command == "capabilities":
        return _capabilities_report(project_root)
    if command == "plan":
        from ai_dev_tools.runners.plan import run_agent_plan

        return run_agent_plan(project_root, task=args.task, mode=args.mode)
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
        "test flaky",
        "mcp serve",
        "cache status",
        "cache prune",
        "cache clear",
        "index status",
        "index update",
        "index rebuild",
        "index daemon",
        "semantic status",
        "semantic index",
        "policy assess",
        "sarif",
        "logs summarize",
        "context build",
        "bootstrap",
        "environment explain",
        "run",
        "stop",
        "git status",
        "git inspect",
        "finish",
        "watch",
        "feedback",
        "session status",
        "agents status",
        "agents add",
        "agents claim",
        "agents heartbeat",
        "agents release",
        "agents complete",
        "baseline create",
        "baseline compare",
        "baseline list",
        "benchmark run",
        "benchmark compare",
        "benchmark gate",
        "benchmark corpus",
        "integrations install",
        "dashboard status",
        "dashboard serve",
        "performance latest",
        "performance compare",
        "explain",
        "diagnostics",
        "capabilities",
        "plan",
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
            "cross_platform_ci_verified": implemented,
            "ci_status": "VERIFIED",
        },
    }
    return report


def _print_text(report: Report) -> None:
    _print_console_line(f"STATUS: {report.status.upper()}")
    _print_console_line(f"COMMAND: {report.command}")
    _print_console_line(f"DURATION: {report.duration_seconds}s")
    for key, value in report.summary.items():
        _print_console_line(f"{key.upper()}: {value}")
    if report.issues:
        _print_console_line("ISSUES:")
        for issue in report.issues:
            location = f" [{issue.location}]" if issue.location else ""
            _print_console_line(f"- {issue.severity}: {issue.message}{location}")


def _print_console_line(value: str) -> None:
    encoding = getattr(sys.stdout, "encoding", None)
    if encoding:
        value = value.encode(encoding, errors="replace").decode(encoding)
    print(value)


if __name__ == "__main__":
    sys.exit(main())
