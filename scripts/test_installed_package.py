from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import venv
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
BUILD = ROOT / "build"


def main() -> int:
    temp_root: Path | None = None
    try:
        _remove_build_artifacts()
        _run([sys.executable, "-m", "build"], ROOT)
        wheel = _find_single_wheel()
        temp_root = Path(tempfile.mkdtemp(prefix="ai dev wheel smoke "))
        venv_dir = temp_root / "clean venv"
        project_dir = temp_root / "project with spaces"
        _create_sample_project(project_dir)
        venv.EnvBuilder(with_pip=True, clear=True).create(venv_dir)
        pip = _venv_python(venv_dir)
        _run([str(pip), "-m", "pip", "install", "--no-index", str(wheel)], project_dir)
        entrypoint = entrypoint_path(venv_dir)
        if not entrypoint.exists():
            raise SmokeError(f"missing installed entrypoint: {entrypoint}")
        _smoke_entrypoint(entrypoint, project_dir)
        print(f"Installed wheel smoke passed: {wheel.name}")
        return 0
    except SmokeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        if temp_root is not None and temp_root.exists():
            shutil.rmtree(temp_root, ignore_errors=True)


def entrypoint_path(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "ai-dev.exe"
    return venv_dir / "bin" / "ai-dev"


def _venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _remove_build_artifacts() -> None:
    for path in (DIST, BUILD):
        if path.exists():
            resolved = path.resolve()
            resolved.relative_to(ROOT.resolve())
            shutil.rmtree(resolved)


def _find_single_wheel() -> Path:
    wheels = sorted(DIST.glob("*.whl"))
    if len(wheels) != 1:
        raise SmokeError(f"expected exactly one wheel in {DIST}, found {len(wheels)}")
    return wheels[0]


def _create_sample_project(project_dir: Path) -> None:
    project_dir.mkdir(parents=True)
    (project_dir / "pyproject.toml").write_text(
        "[project]\nname = 'installed-wheel-smoke'\nversion = '0.0.0'\n",
        encoding="utf-8",
    )
    (project_dir / "README.md").write_text("installed wheel smoke\n", encoding="utf-8")


def _smoke_entrypoint(entrypoint: Path, cwd: Path) -> None:
    _run([str(entrypoint), "--version"], cwd)
    json_commands = [
        [str(entrypoint), "capabilities", "--json"],
        [str(entrypoint), "doctor", "--json"],
        [str(entrypoint), "scan", "--json"],
        [str(entrypoint), "bootstrap", "--explain", "--json"],
        [str(entrypoint), "map", "--json"],
    ]
    for command in json_commands:
        result = _run(command, cwd)
        _assert_report_json(result.stdout, command[1])
    _run([str(entrypoint), "check", "--mode", "changed", "--explain"], cwd)
    _run(
        [
            str(entrypoint),
            "context",
            "build",
            "--task",
            "installed wheel smoke",
            "--explain",
        ],
        cwd,
    )


def _assert_report_json(output: str, command: str) -> None:
    try:
        payload: dict[str, Any] = json.loads(output)
    except json.JSONDecodeError as exc:
        raise SmokeError(f"{command} did not return JSON: {exc}") from exc
    required = {"schema_version", "tool_version", "command", "status", "summary"}
    missing = required - set(payload)
    if missing:
        raise SmokeError(f"{command} JSON missing fields: {sorted(missing)}")
    if payload["status"] not in {"success", "partial", "warning"}:
        raise SmokeError(f"{command} returned unexpected status: {payload['status']}")


def _run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        shell=False,
        timeout=180,
    )
    if result.returncode != 0:
        rendered = " ".join(command)
        raise SmokeError(
            f"command failed ({result.returncode}): {rendered}\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return result


class SmokeError(RuntimeError):
    pass


if __name__ == "__main__":
    raise SystemExit(main())
