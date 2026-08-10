from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ai_dev_tools.config import load_settings
from ai_dev_tools.models.report import Artifact, Issue, Report
from ai_dev_tools.reporters.writer import write_json, write_markdown
from ai_dev_tools.runners.bootstrap_models import BootstrapPlan

STATE_SCHEMA = "1.0"
STATE_PATH = Path(".ai/cache/environment-state.json")
_INPUT_NAMES = {
    ".ai-dev-tools.toml",
    ".nvmrc",
    ".python-version",
    "Cargo.lock",
    "Cargo.toml",
    "build.gradle",
    "build.gradle.kts",
    "composer.json",
    "composer.lock",
    "gradle.properties",
    "package-lock.json",
    "package.json",
    "pnpm-lock.yaml",
    "poetry.lock",
    "pom.xml",
    "pyproject.toml",
    "requirements.txt",
    "rust-toolchain",
    "rust-toolchain.toml",
    "uv.lock",
    "yarn.lock",
}


def inspect_environment_state(root: Path, plan: BootstrapPlan) -> dict[str, Any]:
    state_path = root / STATE_PATH
    current_inputs = _input_fingerprints(root)
    current_plan = _plan_fingerprint(plan)
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        state = {}
    reasons: list[str] = []
    if state.get("schema_version") != STATE_SCHEMA:
        reasons.append("STATE_MISSING_OR_UNSUPPORTED")
    if state.get("input_fingerprints") != current_inputs:
        reasons.append("INPUT_FINGERPRINT_CHANGED")
    if state.get("plan_fingerprint") != current_plan:
        reasons.append("BOOTSTRAP_PLAN_CHANGED")

    tools = state.get("tools", {})
    if not isinstance(tools, dict):
        reasons.append("TOOL_STATE_INVALID")
        tools = {}
    for name, value in tools.items():
        if not isinstance(value, dict):
            reasons.append(f"TOOL_STATE_INVALID:{name}")
            continue
        recorded = value.get("path")
        executable = value.get("executable")
        if not isinstance(recorded, str) or not Path(recorded).exists():
            reasons.append(f"TOOL_MISSING:{name}")
        elif isinstance(executable, str):
            executable_path = Path(executable)
            resolved = (
                str(executable_path.resolve())
                if executable_path.exists()
                else shutil.which(executable)
            )
            if resolved is None or Path(resolved).resolve() != Path(recorded).resolve():
                reasons.append(f"TOOL_PATH_CHANGED:{name}")

    venv = state.get("virtual_environment")
    if isinstance(venv, str) and venv and not (root / venv).exists():
        reasons.append("VIRTUAL_ENVIRONMENT_MISSING")
    return {
        "reusable": not reasons,
        "reason_codes": sorted(set(reasons)),
        "state_path": str(state_path),
        "state": state,
        "current_input_fingerprints": current_inputs,
        "current_plan_fingerprint": current_plan,
    }


def capture_environment_state(
    root: Path,
    plan: BootstrapPlan,
    doctor_summary: dict[str, object],
) -> Path:
    tools = _tool_state(root, plan, doctor_summary)
    settings = load_settings(root)
    venv_path = settings.bootstrap.python_venv
    state = {
        "schema_version": STATE_SCHEMA,
        "captured_at": datetime.now(UTC).isoformat(),
        "project_root": str(root.resolve()),
        "input_fingerprints": _input_fingerprints(root),
        "plan_fingerprint": _plan_fingerprint(plan),
        "plan": plan.to_dict(),
        "tools": tools,
        "virtual_environment": venv_path if (root / venv_path).exists() else None,
        "dependency_markers": _dependency_markers(root),
        "last_successful_bootstrap": True,
    }
    path = root / STATE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + chr(10), encoding="utf-8")
    return path


def run_environment_explain(project_root: Path) -> Report:
    from ai_dev_tools.runners.bootstrap import BootstrapOptions, build_bootstrap_plan

    settings = load_settings(project_root)
    plan = build_bootstrap_plan(settings, BootstrapOptions(explain=True))
    inspection = inspect_environment_state(settings.project_root, plan)
    report = Report(command="environment explain", project_root=settings.project_root)
    report.status = "success" if inspection["reusable"] else "partial"
    state = inspection["state"]
    report.summary = {
        "reusable": inspection["reusable"],
        "reason_codes": inspection["reason_codes"],
        "state_path": inspection["state_path"],
        "captured_at": state.get("captured_at") if isinstance(state, dict) else None,
        "tools": state.get("tools", {}) if isinstance(state, dict) else {},
        "virtual_environment": (
            state.get("virtual_environment") if isinstance(state, dict) else None
        ),
        "dependency_markers": (
            state.get("dependency_markers", {}) if isinstance(state, dict) else {}
        ),
        "plan_fingerprint_matches": (
            state.get("plan_fingerprint") == inspection["current_plan_fingerprint"]
            if isinstance(state, dict)
            else False
        ),
        "input_fingerprints_match": (
            state.get("input_fingerprints") == inspection["current_input_fingerprints"]
            if isinstance(state, dict)
            else False
        ),
    }
    if not inspection["reusable"]:
        report.issues.append(
            Issue(
                "info",
                "Warm environment state cannot be reused",
                code="ENVIRONMENT_STATE_STALE",
            )
        )
    path = Path(str(inspection["state_path"]))
    if path.exists():
        report.artifacts.append(Artifact(str(path), "environment-state", "Warm environment state"))
    report.finish()
    output = settings.reports_directory / "environment-explain.json"
    write_json(report, output)
    write_markdown(report, output.with_suffix(".md"))
    return report


def _input_fingerprints(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    ignored = {".ai", ".git", ".venv", "node_modules", "build", "dist", "venv"}
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
                if any(
                    relative == prefix or relative.startswith(prefix + "/")
                    for prefix in ignored
                ):
                    continue
                if path.is_symlink():
                    continue
                if path.is_dir():
                    stack.append(path)
                elif path.name in _INPUT_NAMES:
                    result[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                continue
    return result


def _plan_fingerprint(plan: BootstrapPlan) -> str:
    payload = json.dumps(plan.to_dict(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _tool_state(
    root: Path,
    plan: BootstrapPlan,
    doctor_summary: dict[str, object],
) -> dict[str, dict[str, str | None]]:
    doctor_tools = doctor_summary.get("tools", {})
    by_path: dict[str, dict[str, object]] = {}
    if isinstance(doctor_tools, dict):
        by_path = {
            str(name): value
            for name, value in doctor_tools.items()
            if isinstance(value, dict)
        }
    executables = {
        step.command[0]
        for step in [*plan.steps, *plan.smoke_steps]
        if step.command and step.action != "copy_env"
    }
    state: dict[str, dict[str, str | None]] = {}
    for executable in sorted(executables):
        local = root / executable
        resolved = str(local.resolve()) if local.exists() else shutil.which(executable)
        if resolved is None:
            continue
        doctor_value = next(
            (
                value
                for value in by_path.values()
                if value.get("path")
                and Path(str(value["path"])).resolve() == Path(resolved).resolve()
            ),
            {},
        )
        state[executable] = {
            "executable": executable,
            "path": str(Path(resolved).resolve()),
            "version": (
                str(doctor_value.get("version"))
                if doctor_value.get("version") is not None
                else None
            ),
        }
    return state


def _dependency_markers(root: Path) -> dict[str, bool]:
    markers = (".venv", "node_modules", "vendor", "target")
    return {name: (root / name).exists() for name in markers}