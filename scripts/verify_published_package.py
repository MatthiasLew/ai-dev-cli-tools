from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import venv
from pathlib import Path

PACKAGE_NAME = "ai-dev-cli-tools"


def entrypoint_path(environment: Path) -> Path:
    if os.name == "nt":
        return environment / "Scripts" / "ai-dev.exe"
    return environment / "bin" / "ai-dev"


def run_checked(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        shell=False,
        timeout=180,
    )
    if result.returncode != 0:
        rendered = " ".join(command)
        raise RuntimeError(
            f"command failed ({result.returncode}): {rendered}\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return result.stdout


def smoke(entrypoint: Path, project: Path, version: str) -> None:
    output = run_checked([str(entrypoint), "--version"], project).strip()
    if output != f"ai-dev {version}":
        raise RuntimeError(f"unexpected version output: {output!r}")
    for command in ("doctor", "capabilities", "scan"):
        payload = json.loads(run_checked([str(entrypoint), command, "--json"], project))
        if payload.get("tool_version") != version:
            raise RuntimeError(f"{command} reported version {payload.get('tool_version')!r}")


def install_with_venv(root: Path, spec: str, index_url: str) -> Path:
    environment = root / "venv"
    venv.EnvBuilder(with_pip=True, clear=True).create(environment)
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    run_checked(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--no-cache-dir",
            "--no-deps",
            "--index-url",
            index_url,
            spec,
        ],
        root,
    )
    return entrypoint_path(environment)


def install_with_pipx(root: Path, spec: str, index_url: str) -> Path:
    tooling = root / "pipx-tooling"
    venv.EnvBuilder(with_pip=True, clear=True).create(tooling)
    python = tooling / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    run_checked([str(python), "-m", "pip", "install", "--no-cache-dir", "pipx"], root)
    pipx_home = root / "pipx-home"
    pipx_bin = root / "pipx-bin"
    env = os.environ.copy()
    env.update(
        {
            "PIPX_HOME": str(pipx_home),
            "PIPX_BIN_DIR": str(pipx_bin),
            "PIP_INDEX_URL": index_url,
            "PIP_NO_CACHE_DIR": "1",
        }
    )
    run_checked([str(python), "-m", "pipx", "install", spec], root, env)
    return pipx_bin / ("ai-dev.exe" if os.name == "nt" else "ai-dev")


def verify_published_package(
    version: str,
    index_url: str,
    installer: str,
    attempts: int,
    retry_delay: float,
) -> None:
    spec = f"{PACKAGE_NAME}=={version}"
    last_error: RuntimeError | None = None
    temp_root = Path(tempfile.mkdtemp(prefix="ai-dev published smoke "))
    try:
        project = temp_root / "project with spaces"
        project.mkdir()
        (project / "README.md").write_text("published smoke\n", encoding="utf-8")
        for attempt in range(1, attempts + 1):
            install_root = temp_root / f"attempt-{attempt}"
            install_root.mkdir()
            try:
                if installer == "pipx":
                    entrypoint = install_with_pipx(install_root, spec, index_url)
                else:
                    entrypoint = install_with_venv(install_root, spec, index_url)
                smoke(entrypoint, project, version)
                print(f"Published package smoke passed: {spec} via {installer}")
                return
            except RuntimeError as exc:
                last_error = exc
                if attempt < attempts:
                    time.sleep(retry_delay)
        message = f"publication was not installable after {attempts} attempts: {last_error}"
        raise RuntimeError(message)
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Install and smoke-test a published ai-dev release."
    )
    parser.add_argument("--version", required=True)
    parser.add_argument("--index-url", required=True)
    parser.add_argument("--installer", choices=("venv", "pipx"), default="venv")
    parser.add_argument("--attempts", type=int, default=8)
    parser.add_argument("--retry-delay", type=float, default=15.0)
    args = parser.parse_args(argv)
    if args.attempts < 1:
        parser.error("--attempts must be at least 1")
    try:
        verify_published_package(
            args.version,
            args.index_url,
            args.installer,
            args.attempts,
            args.retry_delay,
        )
    except (RuntimeError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
