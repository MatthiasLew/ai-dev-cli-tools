from __future__ import annotations

import sys

from ai_dev_tools.runners.check_models import CheckTask


def focused_rerun(task: CheckTask, parsed: dict[str, object]) -> list[str] | None:
    parser = str(parsed.get("parser") or parsed.get("tool") or "").lower()
    path = _first_project_file(parsed)
    if not path:
        return None
    python_bin = (
        task.command[0]
        if task.command
        and ("python" in task.command[0].lower() or task.command[0].endswith(".exe"))
        else sys.executable
    )
    if task.category in {"lint", "typecheck", "format", "build"}:
        if task.name == "ruff" or "ruff" in parser:
            if "check" in task.command:
                idx = task.command.index("check")
                return [*task.command[: idx + 1], path]
            return [python_bin, "-m", "ruff", "check", path]
        if task.name == "mypy" or "mypy" in parser:
            if "-m" in task.command and "mypy" in task.command:
                idx = task.command.index("mypy")
                return [*task.command[: idx + 1], path]
            return [python_bin, "-m", "mypy", path]
        return None
    if "pytest" in parser or path.endswith(".py"):
        return [python_bin, "-m", "pytest", path]
    if any(name in parser for name in ("jest", "vitest")) or path.endswith(
        (".js", ".jsx", ".ts", ".tsx")
    ):
        return ["npm", "test", "--", path]
    if "phpunit" in parser or path.endswith(".php"):
        return ["vendor/bin/phpunit", path]
    if "maven" in parser and task.workspace:
        return ["mvn", "-pl", task.workspace, "test"]
    if "gradle" in parser and task.workspace:
        return ["gradle", f":{task.workspace.replace('/', ':')}:test"]
    return None


def _first_project_file(parsed: dict[str, object]) -> str | None:
    frames = parsed.get("project_frames")
    if not isinstance(frames, list):
        return None
    for frame in frames:
        if isinstance(frame, dict) and isinstance(frame.get("file"), str):
            return str(frame["file"])
        if isinstance(frame, str) and frame:
            return frame.split(":", 1)[0]
    return None
