from __future__ import annotations

import json
import time
from dataclasses import asdict, replace
from pathlib import Path

from ai_dev_tools.config import load_settings
from ai_dev_tools.context.incremental import (
    IncrementalSelection,
    save_incremental_manifest,
    select_incremental,
)
from ai_dev_tools.context.models import (
    DEFAULT_MAX_CHARS,
    DEFAULT_MAX_DIFF_CHARS,
    DEFAULT_MAX_FILE_CHARS,
    DEFAULT_MAX_FILES,
)
from ai_dev_tools.context.models import (
    ContextOptions as ContextOptions,
)
from ai_dev_tools.context.profiles import get_context_profile
from ai_dev_tools.context.selection import (
    ALWAYS_IGNORE,
    _dependency_files,
    _object_list,
    _read_selected_files,
    _rel,
    _select_candidates,
    _selection_reason_code,
    _truncate_text,
)
from ai_dev_tools.detectors.project import scan_project
from ai_dev_tools.detectors.repository_map import map_repository
from ai_dev_tools.git.inspect import inspect_git
from ai_dev_tools.models.report import Artifact, Issue, Report
from ai_dev_tools.runners.check import (
    ChangedSelection,
    CheckTask,
    build_validation_plan,
    select_changed_checks,
)
from ai_dev_tools.security.secrets import mask_text, scan_paths_for_secrets
from ai_dev_tools.utils.subprocess import run_command


def build_context(project_root: Path, options: ContextOptions) -> Report:
    stage_started = time.monotonic()
    timings: dict[str, float] = {}
    options = _apply_context_profile(options)
    settings = load_settings(project_root)
    root = settings.project_root
    report = Report(command="context build", project_root=root)
    timings["configuration"] = _elapsed(stage_started)

    stage_started = time.monotonic()
    scan = scan_project(root)
    timings["project_detection"] = _elapsed(stage_started)
    stage_started = time.monotonic()
    repo_map = map_repository(root, max_files=max(options.max_files * 4, 100), max_depth=8)
    timings["repository_mapping"] = _elapsed(stage_started)
    stage_started = time.monotonic()
    git_report = None if options.no_git else inspect_git(root, detailed=True)
    timings["git_inspection"] = _elapsed(stage_started)
    stage_started = time.monotonic()
    git_available = (
        git_report is not None and git_report.summary.get("state") != "NOT_A_GIT_REPOSITORY"
    )
    plan = build_validation_plan(settings)
    changed_analysis = None
    if git_available:
        changed_analysis = select_changed_checks(settings, plan)
    timings["validation_planning"] = _elapsed(stage_started)
    stage_started = time.monotonic()

    changed_files = _changed_files(git_report, staged_only=options.staged_only)
    candidates, rejected = _select_candidates(
        root=root,
        options=options,
        changed_files=changed_files,
        scan_summary=scan.summary,
        map_summary=repo_map.summary,
        related_tests=_related_tests(changed_analysis),
    )
    dependency_files = _dependency_files(root, candidates)
    for path, reason in dependency_files.items():
        if path not in candidates:
            candidates[path] = reason

    ordered_paths = sorted(candidates, key=lambda item: _candidate_sort_key(item, candidates[item]))
    if options.changed_only or options.staged_only:
        ordered_paths = [path for path in ordered_paths if _rel(root, path) in set(changed_files)]
    incremental_state: IncrementalSelection | None = None
    if options.incremental:
        incremental_state = select_incremental(root, ordered_paths)
        ordered_paths = incremental_state.selected
    ordered_paths = ordered_paths[: max(options.max_files, 0)]

    secret_findings = scan_paths_for_secrets(root, ordered_paths)
    timings["context_selection"] = _elapsed(stage_started)
    if options.explain:
        summary = _base_summary(
            options,
            scan.summary,
            repo_map.summary,
            git_report.summary if git_report else None,
            plan,
            changed_analysis,
        )
        summary.update(
            {
                "explain_only": True,
                "selected_files": [
                    {
                        "path": _rel(root, path),
                        "reason": candidates[path],
                        "reason_code": _selection_reason_code(candidates[path]),
                    }
                    for path in ordered_paths
                ],
                "rejected_files": [item.to_dict() for item in rejected],
                "secret_findings": [finding.masked_dict() for finding in secret_findings],
                "budget": _budget_summary(options, 0, False),
                "incremental": _incremental_summary(incremental_state),
                "performance": {"stages_seconds": timings},
            }
        )
        report.summary = summary
        report.finish()
        return report

    stage_started = time.monotonic()
    selected, snippet_rejections = _read_selected_files(root, ordered_paths, candidates, options)
    rejected.extend(snippet_rejections)
    diffs = (
        []
        if not git_available or git_report is None
        else _context_diffs(root, options, git_report.summary)
    )
    latest_errors = _latest_error_reports(root)
    timings["content_collection"] = _elapsed(stage_started)
    stage_started = time.monotonic()
    summary = _base_summary(
        options,
        scan.summary,
        repo_map.summary,
        git_report.summary if git_report else None,
        plan,
        changed_analysis,
    )
    summary.update(
        {
            "incremental": _incremental_summary(incremental_state, len(selected)),
            "selected_files": [item.to_dict() for item in selected],
            "rejected_files": [item.to_dict() for item in rejected],
            "diffs": diffs,
            "latest_errors": latest_errors,
            "secret_findings": [finding.masked_dict() for finding in secret_findings],
            "recent_commits": (git_report.summary.get("recent_commits", []) if git_report else []),
        }
    )

    markdown = _render_markdown(report, summary)
    markdown, markdown_truncated = _truncate_text(markdown, options.max_chars)
    json_payload = _context_payload(report, summary, markdown_truncated, len(markdown))
    json_payload, json_truncated = _cap_json_payload(json_payload, options.max_chars)
    summary["budget"] = _budget_summary(
        options,
        max(len(markdown), len(json.dumps(json_payload, ensure_ascii=False))),
        markdown_truncated or json_truncated,
    )
    if markdown_truncated or json_truncated:
        summary["truncated"] = True
        report.status = "partial"
        report.issues.append(
            Issue(
                severity="warning",
                message="Context pack was truncated to respect configured character budget.",
                code="CONTEXT_BUDGET_TRUNCATED",
            )
        )
    else:
        summary["truncated"] = any(item.truncated for item in selected)
        report.status = "partial" if summary["truncated"] else "success"
    timings["report_generation"] = _elapsed(stage_started)
    summary["performance"] = {"stages_seconds": timings}
    stage_started = time.monotonic()
    manifest_artifact: Artifact | None = None
    if incremental_state is not None:
        manifest_path, context_id = save_incremental_manifest(
            root,
            incremental_state,
            [item.path for item in selected],
        )
        incremental = summary.get("incremental")
        if isinstance(incremental, dict):
            incremental["context_id"] = context_id
            incremental["manifest"] = str(manifest_path)
        manifest_artifact = Artifact(
            str(manifest_path), "context-manifest", "Incremental context state"
        )

    report.summary = summary
    report.finish()

    output_dir = options.output or (root / ".ai" / "context")
    output_dir.mkdir(parents=True, exist_ok=True)
    md_path = output_dir / "context-latest.md"
    json_path = output_dir / "context-latest.json"
    if options.format in {"markdown", "both"}:
        report.artifacts.append(Artifact(str(md_path), "markdown", "Bounded AI context package"))
    if options.format in {"json", "both"}:
        report.artifacts.append(Artifact(str(json_path), "json", "Bounded AI context package"))
    if manifest_artifact is not None:
        report.artifacts.append(manifest_artifact)
    if options.format in {"markdown", "both"}:
        md_path.write_text(mask_text(_render_markdown(report, report.summary)), encoding="utf-8")
    if options.format in {"json", "both"}:
        json_text = mask_text(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        json_path.write_text(json_text, encoding="utf-8")
    timings["output_write"] = _elapsed(stage_started)
    summary["performance"] = {"stages_seconds": timings}
    return report


def _elapsed(started: float) -> float:
    return round(time.monotonic() - started, 6)


def _apply_context_profile(options: ContextOptions) -> ContextOptions:
    profile = get_context_profile(options.profile)
    if profile is None:
        return options
    return replace(
        options,
        max_chars=(
            profile.max_chars if options.max_chars == DEFAULT_MAX_CHARS else options.max_chars
        ),
        max_files=(
            profile.max_files if options.max_files == DEFAULT_MAX_FILES else options.max_files
        ),
        max_file_chars=(
            profile.max_file_chars
            if options.max_file_chars == DEFAULT_MAX_FILE_CHARS
            else options.max_file_chars
        ),
        max_diff_chars=(
            profile.max_diff_chars
            if options.max_diff_chars == DEFAULT_MAX_DIFF_CHARS
            else options.max_diff_chars
        ),
        changed_only=options.changed_only or profile.changed_only,
    )


def _base_summary(
    options: ContextOptions,
    scan_summary: dict[str, object],
    map_summary: dict[str, object],
    git_summary: dict[str, object] | None,
    plan: list[CheckTask],
    changed_analysis: ChangedSelection | None,
) -> dict[str, object]:
    validation_plan = [task.to_dict() for task in plan]
    changed_dict = changed_analysis.to_dict() if changed_analysis is not None else None
    return {
        "task": options.task,
        "technologies": {
            "languages": scan_summary.get("languages", []),
            "frameworks": scan_summary.get("frameworks", []),
            "package_managers": scan_summary.get("package_managers", []),
            "entrypoints": scan_summary.get("entrypoints", []),
            "runtime_requirements": scan_summary.get("runtime_requirements", []),
            "workspaces": scan_summary.get("workspaces", []),
        },
        "git_state": git_summary,
        "changed_files": _extract_changed_files(git_summary),
        "changed_symbols": git_summary.get("changed_symbols", []) if git_summary else [],
        "symbol_diff_summary": git_summary.get("symbol_diff_summary", {}) if git_summary else {},
        "related_tests": changed_dict.get("selected_tests", []) if changed_dict else [],
        "validation_plan": validation_plan,
        "changed_analysis": changed_dict,
        "repository_map": {
            "important_files": map_summary.get("important_files", []),
            "tests": map_summary.get("tests", []),
            "ci_workflows": map_summary.get("ci_workflows", []),
            "documentation": map_summary.get("documentation", []),
            "generated_or_lock_files": map_summary.get("generated_or_lock_files", []),
        },
        "options": _options_dict(options),
    }


def _context_diffs(
    root: Path, options: ContextOptions, git_summary: dict[str, object]
) -> list[dict[str, object]]:
    symbols = _dict_list(git_summary.get("changed_symbols", []))
    fallbacks = _dict_list(git_summary.get("symbol_diff_fallbacks", []))
    if options.profile not in {"minimal", "review"} or not symbols or fallbacks:
        return _limited_diffs(root, options)
    if options.staged_only:
        staged = set(_object_list(git_summary.get("staged_files", [])))
        symbols = [item for item in symbols if item.get("path") in staged]
    if not symbols:
        return _limited_diffs(root, options)
    payload = json.dumps(
        {
            "selection": "changed top-level symbols",
            "symbols": symbols,
            "raw_diff_omitted": True,
        },
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    content, truncated = _truncate_text(mask_text(payload), max(options.max_diff_chars, 0))
    return [
        {
            "name": "symbol-aware-working-tree",
            "content": content,
            "truncated": truncated,
            "chars": len(content),
            "selection_strategy": "symbol-diff",
            "omitted_content": True,
            "reason_code": "SYMBOL_DIFF_COMPACTION",
        }
    ]


def _limited_diffs(root: Path, options: ContextOptions) -> list[dict[str, object]]:
    commands: list[tuple[str, list[str]]] = []
    if not options.staged_only:
        commands.append(("unstaged", ["git", "diff", "--", "."]))
    commands.append(("staged", ["git", "diff", "--cached", "--", "."]))
    remaining = max(options.max_diff_chars, 0)
    diffs: list[dict[str, object]] = []
    for name, command in commands:
        if remaining <= 0:
            diffs.append({"name": name, "content": "", "truncated": True, "chars": 0})
            continue
        result = run_command(command, root, timeout_seconds=60)
        if result.exit_code != 0:
            diffs.append(
                {"name": name, "error": result.stderr.strip(), "truncated": False, "chars": 0}
            )
            continue
        text, truncated = _truncate_text(mask_text(result.stdout), remaining)
        remaining -= len(text)
        diffs.append({"name": name, "content": text, "truncated": truncated, "chars": len(text)})
    return diffs


def _latest_error_reports(root: Path) -> list[dict[str, object]]:
    reports_dir = root / ".ai" / "reports"
    if not reports_dir.exists():
        return []
    found: list[dict[str, object]] = []
    latest_paths = sorted(
        reports_dir.glob("check-*-latest.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )[:3]
    for path in latest_paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if data.get("status") == "failed" or data.get("summary", {}).get("first_failure"):
            found.append(
                {
                    "path": _rel(root, path),
                    "status": data.get("status"),
                    "first_failure": data.get("summary", {}).get("first_failure"),
                }
            )
    return found


def _render_markdown(report: Report, summary: dict[str, object]) -> str:
    lines = [
        "# AI Development Context",
        "",
        f"STATUS: {report.status.upper()}",
        f"COMMAND: {report.command}",
        f"PROJECT_ROOT: {report.project_root}",
        "",
        "## Task",
        str(summary.get("task") or "No task provided."),
        "",
        "## Technologies",
        _json_block(summary.get("technologies", {})),
        "",
        "## Git State",
        _json_block(summary.get("git_state", {"state": "SKIPPED"})),
        "",
        "## Changed Files",
        _bullet_list(_object_list(summary.get("changed_files"))),
        "",
        "## Changed Symbols",
        _json_block(summary.get("changed_symbols", [])),
        "",
        "## Related Tests",
        _bullet_list(_object_list(summary.get("related_tests"))),
        "",
        "## Validation Plan",
        _json_block(summary.get("validation_plan", [])),
        "",
        "## Latest Errors",
        _json_block(summary.get("latest_errors", [])),
        "",
        "## Context Budget",
        _json_block(summary.get("budget", {})),
        "",
        "## Selected Files",
    ]
    for item in _dict_list(summary.get("selected_files", [])):
        lines.extend(
            [
                "",
                f"### {item.get('path')}",
                f"Reason: {item.get('reason')}",
                f"Selection: {item.get('selection_strategy', 'file-prefix')}",
                f"Omitted content: {item.get('omitted_content', False)}",
                f"Truncated: {item.get('truncated')}",
                "```text",
                str(item.get("content", "")),
                "```",
            ]
        )
    lines.extend(["", "## Diffs"])
    for item in _dict_list(summary.get("diffs", [])):
        lines.extend(
            [
                "",
                f"### {item.get('name')}",
                f"Selection: {item.get('selection_strategy', 'file-prefix')}",
                f"Omitted content: {item.get('omitted_content', False)}",
                f"Truncated: {item.get('truncated')}",
                "```diff",
                str(item.get("content", item.get("error", ""))),
                "```",
            ]
        )
    lines.extend(["", "## Rejected Files", _json_block(summary.get("rejected_files", []))])
    return "\n".join(lines).strip() + "\n"


def _context_payload(
    report: Report, summary: dict[str, object], truncated: bool, markdown_chars: int
) -> dict[str, object]:
    return {
        "schema_version": report.schema_version,
        "tool_version": report.tool_version,
        "command": report.command,
        "status": report.status,
        "project_root": str(report.project_root),
        "summary": summary,
        "budget": {"markdown_chars": markdown_chars, "truncated": truncated},
    }


def _cap_json_payload(payload: dict[str, object], max_chars: int) -> tuple[dict[str, object], bool]:
    text = json.dumps(payload, ensure_ascii=False)
    if len(text) <= max_chars:
        return payload, False
    capped = dict(payload)
    summary = capped.get("summary")
    if isinstance(summary, dict):
        capped_summary = dict(summary)
        capped_summary["selected_files"] = []
        capped_summary["diffs"] = []
        capped_summary["json_payload_note"] = (
            "Large snippets and diffs omitted from JSON budget. See markdown artifact when enabled."
        )
        capped["summary"] = capped_summary
    return capped, True


def _changed_files(git_report: Report | None, staged_only: bool) -> list[str]:
    if git_report is None:
        return []
    key = "staged_files" if staged_only else "changed_files"
    return _visible_project_files(_object_list(git_report.summary.get(key)))


def _extract_changed_files(git_summary: dict[str, object] | None) -> list[str]:
    if not git_summary:
        return []
    return _visible_project_files(_object_list(git_summary.get("changed_files")))


def _incremental_summary(
    state: IncrementalSelection | None, emitted: int | None = None
) -> dict[str, object]:
    if state is None:
        return {"enabled": False}
    pending = len(state.selected)
    return {
        "enabled": True,
        "changed_candidates": pending,
        "emitted": emitted,
        "deferred": max(pending - emitted, 0) if emitted is not None else None,
        "reused": len(state.reused),
        "reused_files": state.reused[:100],
        "index": state.index_summary,
    }


def _options_dict(options: ContextOptions) -> dict[str, object]:
    data = asdict(options)
    output = data.get("output")
    if output is not None:
        data["output"] = str(output)
    return data


def _visible_project_files(files: list[str]) -> list[str]:
    return [item for item in files if not _is_context_generated_path(item)]


def _is_context_generated_path(rel: str) -> bool:
    normalized = rel.replace("\\", "/")
    parts = set(Path(normalized).parts)
    if normalized.startswith(".ai/"):
        return True
    return any(
        pattern in parts or normalized.startswith(f"{pattern}/") for pattern in ALWAYS_IGNORE
    )


def _related_tests(changed_analysis: ChangedSelection | None) -> list[str]:
    if changed_analysis is None:
        return []
    data = changed_analysis.to_dict()
    return _object_list(data.get("selected_tests"))


def _candidate_sort_key(path: Path, reason: str) -> tuple[int, str]:
    priority = 50
    if "changed" in reason:
        priority = 0
    elif "related" in reason:
        priority = 5
    elif "included" in reason:
        priority = 10
    elif "entrypoint" in reason:
        priority = 20
    elif "important" in reason:
        priority = 30
    elif "CI" in reason or "documentation" in reason:
        priority = 40
    return (priority, path.as_posix())


def _budget_summary(options: ContextOptions, used_chars: int, truncated: bool) -> dict[str, object]:
    return {
        "max_chars": options.max_chars,
        "max_files": options.max_files,
        "max_file_chars": options.max_file_chars,
        "max_diff_chars": options.max_diff_chars,
        "used_chars": used_chars,
        "truncated": truncated,
    }


def _dict_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _json_block(value: object) -> str:
    return "```json\n" + json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n```"


def _bullet_list(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "- none"
