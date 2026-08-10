from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Literal

from ai_dev_tools.config import load_settings
from ai_dev_tools.context.incremental import (
    IncrementalSelection,
    save_incremental_manifest,
    select_incremental,
)
from ai_dev_tools.context.profiles import get_context_profile
from ai_dev_tools.context.symbols import SymbolSnippet, select_python_symbols
from ai_dev_tools.detectors.project import scan_project
from ai_dev_tools.detectors.repository_map import BINARY_EXTENSIONS, map_repository
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

ContextFormat = Literal["markdown", "json", "both"]

DEFAULT_MAX_CHARS = 50_000
DEFAULT_MAX_FILES = 30
DEFAULT_MAX_FILE_CHARS = 8_000
DEFAULT_MAX_DIFF_CHARS = 15_000

BLOCKED_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    ".DS_Store",
}
BLOCKED_SUFFIXES = {".pyc", ".pyo", ".pem", ".key", ".p12", ".pfx"}
ALWAYS_IGNORE = {
    ".ai/logs",
    ".ai/reports",
    ".ai/context",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
}


@dataclass(frozen=True, slots=True)
class ContextOptions:
    task: str = ""
    max_chars: int = DEFAULT_MAX_CHARS
    max_files: int = DEFAULT_MAX_FILES
    max_file_chars: int = DEFAULT_MAX_FILE_CHARS
    max_diff_chars: int = DEFAULT_MAX_DIFF_CHARS
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    changed_only: bool = False
    staged_only: bool = False
    no_git: bool = False
    output: Path | None = None
    format: ContextFormat = "both"
    explain: bool = False
    incremental: bool = False
    profile: str = "default"


@dataclass(slots=True)
class SelectedFile:
    path: str
    reason: str
    reason_code: str
    chars: int
    truncated: bool
    content: str
    selection_strategy: str = "file-prefix"
    omitted_content: bool = False
    snippets: list[SymbolSnippet] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class RejectedFile:
    path: str
    reason: str
    reason_code: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def build_context(project_root: Path, options: ContextOptions) -> Report:
    options = _apply_context_profile(options)
    settings = load_settings(project_root)
    root = settings.project_root
    report = Report(command="context build", project_root=root)

    scan = scan_project(root)
    repo_map = map_repository(root, max_files=max(options.max_files * 4, 100), max_depth=8)
    git_report = None if options.no_git else inspect_git(root, detailed=True)
    git_available = (
        git_report is not None and git_report.summary.get("state") != "NOT_A_GIT_REPOSITORY"
    )
    plan = build_validation_plan(settings)
    changed_analysis = None
    if git_available:
        changed_analysis = select_changed_checks(settings, plan)

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
            }
        )
        report.summary = summary
        report.finish()
        return report

    selected, snippet_rejections = _read_selected_files(root, ordered_paths, candidates, options)
    rejected.extend(snippet_rejections)
    diffs = [] if not git_available else _limited_diffs(root, options)
    latest_errors = _latest_error_reports(root)
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
    return report


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


def _select_candidates(
    root: Path,
    options: ContextOptions,
    changed_files: list[str],
    scan_summary: dict[str, object],
    map_summary: dict[str, object],
    related_tests: list[str],
) -> tuple[dict[Path, str], list[RejectedFile]]:
    candidates: dict[Path, str] = {}
    rejected: list[RejectedFile] = []
    for pattern in options.include:
        for path in root.glob(pattern):
            _add_candidate(
                root, path, f"included by pattern: {pattern}", candidates, rejected, options
            )
    for rel in changed_files:
        _add_candidate(root, root / rel, "changed file", candidates, rejected, options)
    for rel in related_tests:
        _add_candidate(root, root / rel, "related affected test", candidates, rejected, options)
    for rel in _object_list(scan_summary.get("entrypoints")):
        if not rel.startswith("script:"):
            _add_candidate(root, root / rel, "detected entrypoint", candidates, rejected, options)
    for key, reason in (
        ("important_files", "important project file"),
        ("tests", "repository test file"),
        ("ci_workflows", "CI workflow"),
        ("documentation", "documentation"),
    ):
        for rel in _object_list(map_summary.get(key)):
            _add_candidate(root, root / rel, reason, candidates, rejected, options)
    return candidates, rejected


def _add_candidate(
    root: Path,
    path: Path,
    reason: str,
    candidates: dict[Path, str],
    rejected: list[RejectedFile],
    options: ContextOptions,
) -> None:
    if not path.exists() or not path.is_file():
        return
    try:
        resolved = path.resolve()
        resolved.relative_to(root.resolve())
    except ValueError:
        rejected.append(RejectedFile(str(path), "outside project root", "OUTSIDE_PROJECT_ROOT"))
        return
    rel = _rel(root, path)
    blocked = _blocked_reason(path, rel, options.exclude)
    if blocked:
        rejected.append(RejectedFile(rel, blocked, _rejection_reason_code(blocked)))
        return
    candidates[path] = reason


def _blocked_reason(path: Path, rel: str, excludes: tuple[str, ...]) -> str | None:
    normalized = rel.replace("\\", "/")
    parts = set(Path(normalized).parts)
    if path.name in BLOCKED_NAMES:
        return "environment or secret-bearing file"
    if path.suffix.lower() in BLOCKED_SUFFIXES or path.suffix.lower() in BINARY_EXTENSIONS:
        return "binary or sensitive file type"
    if any(pattern in parts or normalized.startswith(f"{pattern}/") for pattern in ALWAYS_IGNORE):
        return "ignored generated/cache path"
    if any(fnmatch.fnmatch(normalized, pattern.replace("\\", "/")) for pattern in excludes):
        return "excluded by user pattern"
    return None


def _read_selected_files(
    root: Path, paths: list[Path], reasons: dict[Path, str], options: ContextOptions
) -> tuple[list[SelectedFile], list[RejectedFile]]:
    selected: list[SelectedFile] = []
    rejected: list[RejectedFile] = []
    for path in paths:
        rel = _rel(root, path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            rejected.append(RejectedFile(rel, f"unreadable: {exc}", "UNREADABLE_FILE"))
            continue
        masked = mask_text(text)
        symbol_selection = (
            select_python_symbols(text, masked, options.task, options.max_file_chars)
            if path.suffix.lower() == ".py"
            else None
        )
        if symbol_selection is None:
            snippet, truncated = _truncate_text(masked, options.max_file_chars)
            strategy = "file-prefix"
            omitted_content = truncated
            snippets: list[SymbolSnippet] = []
        else:
            snippet = symbol_selection.content
            truncated = symbol_selection.truncated
            strategy = "python-ast"
            omitted_content = symbol_selection.omitted_content
            snippets = symbol_selection.snippets
        selected.append(
            SelectedFile(
                path=rel,
                reason=reasons[path],
                reason_code=_selection_reason_code(reasons[path]),
                chars=len(snippet),
                truncated=truncated,
                content=snippet,
                selection_strategy=strategy,
                omitted_content=omitted_content,
                snippets=snippets,
            )
        )
    return selected, rejected


def _selection_reason_code(reason: str) -> str:
    return {
        "included by user": "USER_INCLUDE",
        "changed file": "CHANGED_FILE",
        "related affected test": "RELATED_TEST",
        "detected entrypoint": "DETECTED_ENTRYPOINT",
        "important project file": "IMPORTANT_FILE",
        "repository test file": "TEST_FILE",
        "CI workflow": "CI_WORKFLOW",
        "documentation": "DOCUMENTATION",
        "Python dependency": "PYTHON_DEPENDENCY",
        "JavaScript/TypeScript dependency": "JS_TS_DEPENDENCY",
        "Rust dependency": "RUST_DEPENDENCY",
        "Java dependency": "JAVA_DEPENDENCY",
        "PHP dependency": "PHP_DEPENDENCY",
    }.get(reason, "SELECTED_FILE")


def _rejection_reason_code(reason: str) -> str:
    return {
        "environment or secret-bearing file": "SENSITIVE_OR_ENV_FILE",
        "binary or sensitive file type": "BINARY_OR_SENSITIVE_TYPE",
        "ignored generated/cache path": "IGNORED_GENERATED_PATH",
        "excluded by user pattern": "USER_EXCLUDED",
    }.get(reason, "REJECTED_FILE")


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


def _dependency_files(root: Path, candidates: dict[Path, str]) -> dict[Path, str]:
    discovered: dict[Path, str] = {}
    for path in list(candidates):
        rel = _rel(root, path)
        if path.suffix == ".py":
            for module in _python_imports(path):
                for dep in _python_module_paths(root, module):
                    if dep.exists():
                        discovered[dep] = f"local Python dependency imported by {rel}"
        if path.suffix.lower() in {".js", ".jsx", ".ts", ".tsx"}:
            for dep in _relative_js_imports(path):
                discovered[dep] = f"local JS/TS dependency imported by {rel}"
        if path.suffix == ".rs":
            for dep in _rust_mod_paths(path):
                discovered[dep] = f"local Rust module referenced by {rel}"
        if path.suffix == ".java":
            for dep in _java_same_package_paths(path):
                discovered[dep] = f"nearby Java package file related to {rel}"
        if path.suffix == ".php":
            for dep in _php_nearby_paths(path):
                discovered[dep] = f"nearby PHP file related to {rel}"
    return {path: reason for path, reason in discovered.items() if path.is_file()}


def _python_imports(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    names: set[str] = set()
    for line in text.splitlines():
        match = re.match(
            r"\s*(?:from\s+([A-Za-z_][\w.]*)\s+import|import\s+([A-Za-z_][\w.]*))",
            line,
        )
        if match:
            names.add(match.group(1) or match.group(2) or "")
    return {name for name in names if name}


def _python_module_paths(root: Path, module: str) -> list[Path]:
    parts = module.split(".")
    candidates = [
        root / Path(*parts).with_suffix(".py"),
        root / "src" / Path(*parts).with_suffix(".py"),
    ]
    candidates.extend(
        [root / Path(*parts) / "__init__.py", root / "src" / Path(*parts) / "__init__.py"]
    )
    return candidates


def _relative_js_imports(path: Path) -> list[Path]:
    text = path.read_text(encoding="utf-8", errors="replace")
    deps: list[Path] = []
    for match in re.finditer(r"(?:from\s+|require\()(['\"])(\.{1,2}/[^'\"]+)\1", text):
        base = (path.parent / match.group(2)).resolve()
        for suffix in ("", ".ts", ".tsx", ".js", ".jsx", "/index.ts", "/index.js"):
            candidate = Path(f"{base}{suffix}")
            if candidate.exists() and candidate.is_file():
                deps.append(candidate)
                break
    return deps


def _rust_mod_paths(path: Path) -> list[Path]:
    text = path.read_text(encoding="utf-8", errors="replace")
    deps: list[Path] = []
    for match in re.finditer(r"^\s*mod\s+([A-Za-z_][\w]*)\s*;", text, re.MULTILINE):
        name = match.group(1)
        deps.extend([path.parent / f"{name}.rs", path.parent / name / "mod.rs"])
    return deps


def _java_same_package_paths(path: Path) -> list[Path]:
    return sorted(path.parent.glob("*.java"))[:5]


def _php_nearby_paths(path: Path) -> list[Path]:
    return sorted(path.parent.glob("*.php"))[:5]


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


def _truncate_text(text: str, max_chars: int) -> tuple[str, bool]:
    if max_chars < 0:
        max_chars = 0
    if len(text) <= max_chars:
        return text, False
    marker = "\n[TRUNCATED]\n"
    keep = max(max_chars - len(marker), 0)
    return text[:keep] + marker, True


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


def _object_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _dict_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _json_block(value: object) -> str:
    return "```json\n" + json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n```"


def _bullet_list(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "- none"


def _rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()
