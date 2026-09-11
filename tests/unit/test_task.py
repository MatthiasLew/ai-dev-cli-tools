from __future__ import annotations

import json
from pathlib import Path

from ai_dev_tools.runners.task import TaskOptions, run_prepare_task
from ai_dev_tools.token_efficiency import load_acknowledged_state


def _project(root: Path) -> None:
    (root / "pyproject.toml").write_text(
        "[project]\nname='task-fixture'\nversion='0.0.0'\n", encoding="utf-8"
    )
    (root / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")


def test_prepare_task_defaults_to_expandable_references_and_records_receipt(
    tmp_path: Path,
) -> None:
    _project(tmp_path)

    report = run_prepare_task(
        tmp_path, TaskOptions(task="change run safely", client="codex")
    )

    assert report.status in {"success", "partial"}
    assert report.summary["constraints"]["content_default"] == "references"
    selected = report.summary["context"]["selected_files"]
    assert selected
    assert "content" not in selected[0]
    assert selected[0]["content_reference"]["command"].startswith("ai-dev explain file:")
    receipt = report.summary["token_savings"]
    assert receipt["delivery"]["estimated_tokens_avoided"] > 0
    assert receipt["saved_tokens"] > 0
    assert receipt["input_tokens"] > 0
    assert receipt["original_input_tokens"] == receipt["input_tokens"] + receipt["saved_tokens"]
    assert receipt["saved_percent"] < 100
    assert "repository_map" not in report.summary["context"]
    assert (tmp_path / ".ai/token-efficiency/latest.json").is_file()
    assert (tmp_path / ".ai/reports/task-latest.json").is_file()


def test_prepare_task_persists_only_explicit_ack_and_reuses_it(tmp_path: Path) -> None:
    _project(tmp_path)
    first = run_prepare_task(tmp_path, TaskOptions(task="inspect run", client="cursor"))
    state = first.summary["state"]["fingerprint"]

    assert load_acknowledged_state(tmp_path, "cursor") is None
    second = run_prepare_task(
        tmp_path,
        TaskOptions(task="inspect run", client="cursor", acknowledged_state=state),
    )
    third = run_prepare_task(tmp_path, TaskOptions(task="inspect run", client="cursor"))

    assert second.summary["state"]["reused"] is True
    assert load_acknowledged_state(tmp_path, "cursor") == state
    assert third.summary["state"]["acknowledgement_source"] == "persisted"
    assert third.summary["context"]["context_receipt"]["unchanged"] is True


def test_prepare_task_requires_description(tmp_path: Path) -> None:
    report = run_prepare_task(tmp_path, TaskOptions(task=""))

    assert report.status == "invalid_configuration"
    assert report.summary["reason_code"] == "TASK_REQUIRED"


def test_token_efficiency_client_profile_and_helpers(tmp_path: Path) -> None:
    from ai_dev_tools.token_efficiency import (
        _compact_evidence,
        _selected_fields,
        client_profile,
        persist_acknowledged_state,
    )

    prof = client_profile("codex")
    assert prof["content_default"] == "references"

    try:
        client_profile("non_existent_client")
    except ValueError as exc:
        assert "unknown AI client" in str(exc)

    compact_non_dict = _compact_evidence("string", include_content=True)
    assert compact_non_dict == {}

    fields_non_dict = _selected_fields("string", ("path",))
    assert fields_non_dict == {}

    # State file without acknowledged_states dict
    state_file = tmp_path / ".ai" / "token-efficiency" / "generic-state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({"acknowledged_states": "corrupted"}), encoding="utf-8")
    persist_acknowledged_state(tmp_path, "generic", "new_hash")
    assert load_acknowledged_state(tmp_path, "generic") == "new_hash"

