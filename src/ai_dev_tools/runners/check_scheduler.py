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
    groups = [tasks] if policy == "complete" else _feedback_groups(tasks)
    for group_index, group in enumerate(groups):
        group_results = _execute_group(group, jobs, execute)
        completed_tasks.extend(group)
        results.extend(group_results)
        if first_failure_at is None and any(result.exit_code != 0 for result in group_results):
            first_failure_at = monotonic() - started
        blocking = any(
            task.required and result.exit_code != 0
            for task, result in zip(group, group_results, strict=True)
        )
        if policy == "feedback-first" and blocking:
            cancelled = [task for remaining in groups[group_index + 1 :] for task in remaining]
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
            }
            for index, wave in enumerate(waves)
        ],
        "fail_fast": policy == "feedback-first",
        "deterministic_order": True,
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
    workers = max(1, min(jobs, len(tasks)))
    if workers == 1:
        return [execute(task) for task in tasks]
    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(execute, tasks))
