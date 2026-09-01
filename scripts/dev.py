"""Deterministic, cross-platform launcher for repository development."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv"
LOCK = ROOT / "requirements-dev.lock"
MARKER = VENV / ".ai-dev-tools-fingerprint"
MINIMUM_PYTHON = (3, 11)


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def environment_fingerprint() -> str:
    digest = hashlib.sha256()
    digest.update(f"{sys.version_info.major}.{sys.version_info.minor}\n".encode())
    for path in (ROOT / "pyproject.toml", LOCK):
        digest.update(path.read_bytes())
    return digest.hexdigest()


def child_environment() -> dict[str, str]:
    environment = os.environ.copy()
    temporary = ROOT / ".ai" / "tmp" / "dev"
    temporary.mkdir(parents=True, exist_ok=True)
    for name in ("TMP", "TEMP", "TMPDIR"):
        environment[name] = str(temporary)
    environment["PYTHONNOUSERSITE"] = "1"
    return environment


def ensure_environment(*, allow_bootstrap: bool = True) -> Path:
    if sys.version_info < MINIMUM_PYTHON:
        raise RuntimeError("DEV_PYTHON_UNSUPPORTED: Python 3.11 or newer is required")
    fingerprint = environment_fingerprint()
    python = venv_python()
    current = MARKER.read_text(encoding="utf-8").strip() if MARKER.exists() else ""
    if python.exists() and current == fingerprint:
        return python
    if not allow_bootstrap:
        raise RuntimeError(
            "DEV_ENV_MISSING: run 'python scripts/dev.py --bootstrap-only' first"
        )
    print("[ai-dev] preparing isolated .venv from requirements-dev.lock", file=sys.stderr)
    venv.EnvBuilder(with_pip=True, clear=VENV.exists()).create(VENV)
    python = venv_python()
    command = [
        str(python),
        "-m",
        "pip",
        "install",
        "-c",
        str(LOCK),
        "-e",
        f"{ROOT}[dev]",
    ]
    completed = subprocess.run(command, cwd=ROOT, env=child_environment(), check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"DEV_BOOTSTRAP_FAILED: pip exited {completed.returncode}")
    MARKER.write_text(fingerprint + "\n", encoding="utf-8")
    return python


def _probe_path(path: Path, code: str) -> dict[str, object]:
    probe = path / f".ai-dev-write-probe-{os.getpid()}"
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe.write_text("probe\n", encoding="utf-8")
        probe.unlink()
        return {"code": code, "status": "ok", "path": str(path)}
    except OSError as exc:
        return {
            "code": code,
            "status": "blocked",
            "path": str(path),
            "error": f"{type(exc).__name__}: {exc}",
        }


def diagnose() -> dict[str, object]:
    checks: list[dict[str, object]] = [
        {
            "code": "DEV_PYTHON",
            "status": "ok" if sys.version_info >= MINIMUM_PYTHON else "blocked",
            "version": ".".join(str(value) for value in sys.version_info[:3]),
        },
        _probe_path(ROOT / ".ai" / "tmp" / "dev", "DEV_WORKSPACE_TEMP"),
    ]
    git_directory = ROOT / ".git"
    if git_directory.is_dir():
        checks.append(_probe_path(git_directory / "refs" / "heads", "DEV_GIT_METADATA"))
    else:
        checks.append({"code": "DEV_GIT_METADATA", "status": "not_applicable"})
    proxy = {
        name: os.environ[name]
        for name in ("ALL_PROXY", "HTTP_PROXY", "HTTPS_PROXY")
        if os.environ.get(name)
    }
    checks.append(
        {
            "code": "DEV_PROXY",
            "status": "warning" if proxy else "ok",
            "configured": sorted(proxy),
        }
    )
    overall = "blocked" if any(item.get("status") == "blocked" for item in checks) else "ok"
    return {"status": overall, "root": str(ROOT), "checks": checks}


def run_checks(python: Path) -> int:
    commands = [
        [str(python), "-m", "ruff", "check", "."],
        [str(python), "-m", "mypy", "src", "tests", "scripts"],
        [str(python), "-m", "coverage", "run", "-m", "pytest"],
        [str(python), "-m", "coverage", "report", "--fail-under=90"],
        [str(python), "-m", "build"],
        [str(python), "scripts/validate_ci.py"],
    ]
    environment = child_environment()
    for command in commands:
        completed = subprocess.run(command, cwd=ROOT, env=environment, check=False)
        if completed.returncode != 0:
            return completed.returncode
    return 0


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments == ["--diagnose"]:
        report = diagnose()
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["status"] == "ok" else 2
    no_bootstrap = "--no-bootstrap" in arguments
    if no_bootstrap:
        arguments.remove("--no-bootstrap")
    try:
        python = ensure_environment(allow_bootstrap=not no_bootstrap)
        if arguments == ["--bootstrap-only"]:
            return 0
        if arguments == ["--check"]:
            return run_checks(python)
        return subprocess.run(
            [str(python), "-m", "ai_dev_tools.cli", *arguments],
            cwd=ROOT,
            env=child_environment(),
            check=False,
        ).returncode
    except (OSError, RuntimeError) as exc:
        print(f"[ai-dev] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
