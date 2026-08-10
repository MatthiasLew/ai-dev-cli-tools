from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ai_dev_tools.cli import main
from ai_dev_tools.runners import coordination
from ai_dev_tools.runners.coordination import coordinate_agents


def test_agents_claim_blocks_overlapping_paths_and_allows_release(tmp_path: Path) -> None:
    added = coordinate_agents(tmp_path, "add", task_id="api", title="API", paths=["src/api"])
    coordinate_agents(tmp_path, "add", task_id="docs", title="Docs", paths=["docs"])
    coordinate_agents(
        tmp_path, "add", task_id="nested", title="Nested", paths=["src/api/routes.py"]
    )

    claimed = coordinate_agents(tmp_path, "claim", task_id="api", agent_id="agent-a")
    blocked = coordinate_agents(tmp_path, "claim", task_id="nested", agent_id="agent-b")
    independent = coordinate_agents(tmp_path, "claim", task_id="docs", agent_id="agent-b")
    released = coordinate_agents(tmp_path, "release", task_id="api", agent_id="agent-a")

    assert added.summary["reason_code"] == "TASK_ADDED"
    assert claimed.summary["reason_code"] == "TASK_CLAIMED"
    assert blocked.status == "blocked"
    assert blocked.summary["reason_code"] == "PATH_CONFLICT"
    assert independent.status == "success"
    assert released.summary["reason_code"] == "TASK_RELEASED"


def test_agents_dependencies_and_ownership_are_enforced(tmp_path: Path) -> None:
    coordinate_agents(tmp_path, "add", task_id="base", title="Base", paths=["src/base.py"])
    coordinate_agents(
        tmp_path,
        "add",
        task_id="next",
        title="Next",
        paths=["src/next.py"],
        dependencies=["base"],
    )

    blocked = coordinate_agents(tmp_path, "claim", task_id="next", agent_id="agent-b")
    coordinate_agents(tmp_path, "claim", task_id="base", agent_id="agent-a")
    wrong = coordinate_agents(tmp_path, "complete", task_id="base", agent_id="agent-b")
    coordinate_agents(tmp_path, "complete", task_id="base", agent_id="agent-a")
    ready = coordinate_agents(tmp_path, "claim", task_id="next", agent_id="agent-b")

    assert blocked.summary["reason_code"] == "DEPENDENCIES_INCOMPLETE"
    assert wrong.summary["reason_code"] == "CLAIM_NOT_OWNED"
    assert ready.status == "success"


def test_expired_claim_is_pruned_and_can_be_reclaimed(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    current = datetime(2026, 1, 1, tzinfo=UTC)
    monkeypatch.setattr(coordination, "_now", lambda: current)
    coordinate_agents(tmp_path, "add", task_id="task", title="Task", paths=["src"])
    coordinate_agents(tmp_path, "claim", task_id="task", agent_id="agent-a", lease_seconds=30)
    monkeypatch.setattr(coordination, "_now", lambda: current + timedelta(seconds=31))

    reclaimed = coordinate_agents(tmp_path, "claim", task_id="task", agent_id="agent-b")

    assert reclaimed.status == "success"
    assert reclaimed.summary["expired_claims_pruned"] == 1
    assert reclaimed.summary["active_claims"][0]["claim"]["agent_id"] == "agent-b"


def test_agents_reject_unsafe_paths_and_cli_status(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    invalid = coordinate_agents(tmp_path, "add", task_id="bad", title="Bad", paths=["../outside"])
    exit_code = main(["--project", str(tmp_path), "--json", "agents", "status"])

    assert invalid.status == "invalid_configuration"
    assert invalid.summary["reason_code"] == "INVALID_TASK_PATH"
    assert exit_code == 0
    assert '"reason_code": "COORDINATION_STATUS"' in capsys.readouterr().out


def test_concurrent_claim_has_exactly_one_owner(tmp_path: Path) -> None:
    coordinate_agents(tmp_path, "add", task_id="shared", title="Shared", paths=["src"])

    with ThreadPoolExecutor(max_workers=2) as pool:
        reports = list(
            pool.map(
                lambda agent: coordinate_agents(
                    tmp_path, "claim", task_id="shared", agent_id=agent
                ),
                ["agent-a", "agent-b"],
            )
        )

    assert sorted(report.status for report in reports) == ["blocked", "success"]
    status = coordinate_agents(tmp_path, "status")
    assert len(status.summary["active_claims"]) == 1
