from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from time import monotonic

from ai_dev_tools.runners.check_models import CheckTask
from ai_dev_tools.utils.subprocess import CommandResult


@dataclass(frozen=True, slots=True)
class ScheduleResult:
    tasks: list[CheckTask]
    results: list[CommandResult]
    cancelled: list[CheckTask]
    wall_seconds: float
    aggregate_seconds: float
    time_to_first_failure_seconds: float | None


def schedule_checks(
    tasks: list[CheckTask],
    jobs: int,
    policy: str,
    execute: Callable[[CheckTask], CommandResult],
) -> ScheduleResult:
    started = monotonic()
    completed_tasks: list[CheckTask] = []
    results: list[CommandResult] = []
    cancelled: list[CheckTask] = []
    first_failure_at: float | None = None
    successful: set[str] = set()
    failed: set[str] = set()
    groups = [tasks] if policy == "complete" else _feedback_groups(tasks)
    for group_index, group in enumerate(groups):
        remaining = list(group)
        blocking = False
        while remaining:
            dependency_blocked = [task for task in remaining if set(task.depends_on) & failed]
            if dependency_blocked:
                cancelled.extend(dependency_blocked)
                remaining = [task for task in remaining if task not in dependency_blocked]
                continue
            ready = [task for task in remaining if set(task.depends_on) <= successful]
            if not ready:
                cancelled.extend(remaining)
                break
            wave_results = _execute_group(ready, jobs, execute)
            completed_tasks.extend(ready)
            results.extend(wave_results)
            remaining = [task for task in remaining if task not in ready]
            for task, result in zip(ready, wave_results, strict=True):
                if result.exit_code == 0 and not result.flaky:
                    successful.add(task.name)
                else:
                    failed.add(task.name)
                    if first_failure_at is None:
                        first_failure_at = monotonic() - started
                    if task.required:
                        blocking = True
        if policy == "feedback-first" and blocking:
            cancelled.extend(task for later in groups[group_index + 1 :] for task in later)
            break
    wall = monotonic() - started
    return ScheduleResult(
        completed_tasks,
        results,
        cancelled,
        round(wall, 3),
        round(sum(result.duration_seconds for result in results), 3),
        round(first_failure_at, 3) if first_failure_at is not None else None,
    )


def schedule_graph(tasks: list[CheckTask], policy: str) -> dict[str, object]:
    waves = _feedback_groups(tasks) if policy == "feedback-first" else [tasks]
    return {
        "policy": policy,
        "waves": [
            {
                "index": index,
                "cost": wave[0].cost if wave else "none",
                "checks": [task.name for task in wave],
                "workspaces": sorted({task.workspace for task in wave}),
                "dependencies": {task.name: list(task.depends_on) for task in wave},
                "resources": {task.name: _resource_class(task) for task in wave},
            }
            for index, wave in enumerate(waves)
        ],
        "fail_fast": policy == "feedback-first",
        "deterministic_order": True,
        "resource_limits": {
            "total": "--jobs",
            "memory": "max(1, jobs // 2)",
            "exclusive": 1,
        },
    }


def _feedback_groups(tasks: list[CheckTask]) -> list[list[CheckTask]]:
    costs = ("fast", "medium", "slow")
    return [
        [task for task in tasks if task.cost == cost]
        for cost in costs
        if any(task.cost == cost for task in tasks)
    ]


def _execute_group(
    tasks: list[CheckTask],
    jobs: int,
    execute: Callable[[CheckTask], CommandResult],
) -> list[CommandResult]:
    if not tasks:
        return []
    limit = max(1, jobs)
    completed: dict[int, CommandResult] = {}
    for batch in _resource_batches(tasks, limit):
        workers = min(limit, len(batch))
        if workers == 1:
            batch_results = [execute(batch[0])]
        else:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                batch_results = list(executor.map(execute, batch))
        completed.update(
            (id(task), result) for task, result in zip(batch, batch_results, strict=True)
        )
    return [completed[id(task)] for task in tasks]


def _resource_batches(tasks: list[CheckTask], jobs: int) -> list[list[CheckTask]]:
    batches: list[list[CheckTask]] = []
    current: list[CheckTask] = []
    used = 0
    for task in tasks:
        resource = _resource_class(task)
        units = jobs if resource == "exclusive" else 2 if resource == "memory" else 1
        if current and (used + units > jobs or resource == "exclusive"):
            batches.append(current)
            current = []
            used = 0
        current.append(task)
        used += units
        if resource == "exclusive":
            batches.append(current)
            current = []
            used = 0
    if current:
        batches.append(current)
    return batches


def _resource_class(task: CheckTask) -> str:
    if task.resource != "auto":
        return task.resource
    if task.category == "build":
        return "exclusive"
    if task.category in {"typecheck", "unit_tests", "integration_tests"}:
        return "memory"
    return "cpu"
