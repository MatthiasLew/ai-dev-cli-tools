from __future__ import annotations

import json
from pathlib import Path

from ai_dev_tools.reporters.progressive import run_explain
from ai_dev_tools.runners.observations import MAX_REFERENCES, update_observation_lifecycle


def _observation(status: str, marker: str) -> dict[str, object]:
    failed = status == "failed"
    return {
        "command": "feedback",
        "task": f"repair auth {marker}",
        "status": status,
        "changed_files": ["src/auth.py"],
        "failure_signatures": [f"failure:{marker}"] if failed else [],
        "unresolved_warnings": [],
        "validation": {
            "checks_total": 1,
            "checks_failed": 1 if failed else 0,
            "first_failure": marker if failed else None,
            "results": [{"name": "pytest", "exit_code": 1 if failed else 0}],
        },
    }


def test_lifecycle_references_superseded_failure_and_keeps_final_verification(
    tmp_path: Path,
) -> None:
    first, _ = update_observation_lifecycle(tmp_path, _observation("failed", "boom"))
    failure_id = first["current"]["evidence_id"]

    second, path = update_observation_lifecycle(tmp_path, _observation("success", "green"))

    assert path == tmp_path / ".ai" / "cache" / "observations.json"
    assert first["current_retained_reasons"] == ["current_failure"]
    assert second["current_retained_reasons"] == ["final_verification"]
    assert second["referenced"][0]["evidence_id"] == failure_id
    assert second["referenced"][0]["reason_code"] == "SUPERSEDED_OBSERVATION_REFERENCED"
    assert second["referenced_chars_avoided"] > 0
    assert second["current"]["validation"]["checks_failed"] == 0

    expanded = run_explain(tmp_path, failure_id)
    assert expanded.status == "success"
    assert expanded.summary["evidence"]["status"] == "failed"
    assert expanded.summary["evidence"]["validation"]["first_failure"] == "boom"


def test_duplicate_observations_are_suppressed_without_duplicate_archive(tmp_path: Path) -> None:
    observation = _observation("success", "same")

    update_observation_lifecycle(tmp_path, observation)
    lifecycle, _ = update_observation_lifecycle(tmp_path, observation)

    assert lifecycle["referenced"] == []
    assert lifecycle["duplicate_observations_suppressed"] == 1
    assert list((tmp_path / ".ai" / "cache" / "evidence").glob("*.json")) == []


def test_lifecycle_retains_warning_reason_and_masks_secrets(tmp_path: Path) -> None:
    secret = "sk-" + "a" * 30
    observation = _observation("partial", "warning")
    observation["unresolved_warnings"] = ["FLAKY_PASS"]
    observation["task"] = secret

    lifecycle, path = update_observation_lifecycle(tmp_path, observation)

    assert lifecycle["current_retained_reasons"] == ["unresolved_warning"]
    serialized = path.read_text(encoding="utf-8")
    assert secret not in serialized
    assert "***MASKED_OPENAI_KEY***" in serialized


def test_lifecycle_rejects_tampered_evidence_paths(tmp_path: Path) -> None:
    path = tmp_path / ".ai" / "cache" / "observations.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "current": {
                    "evidence_id": "observation:../../escape",
                    "status": "success",
                },
                "referenced": [],
            }
        ),
        encoding="utf-8",
    )

    lifecycle, _ = update_observation_lifecycle(tmp_path, _observation("failed", "new"))

    reference = lifecycle["referenced"][0]
    assert reference["evidence_id"].startswith("observation:")
    assert ".." not in reference["evidence_id"]
    assert not (tmp_path / ".ai" / "cache" / "escape.json").exists()


def test_lifecycle_bounds_references_and_recovers_invalid_manifest(tmp_path: Path) -> None:
    path = tmp_path / ".ai" / "cache" / "observations.json"
    path.parent.mkdir(parents=True)
    path.write_text("not-json", encoding="utf-8")

    lifecycle, _ = update_observation_lifecycle(tmp_path, _observation("success", "0"))
    assert lifecycle["schema_version"] == "1"

    for index in range(MAX_REFERENCES + 3):
        lifecycle, _ = update_observation_lifecycle(
            tmp_path, _observation("success", str(index + 1))
        )

    assert len(lifecycle["referenced"]) == MAX_REFERENCES
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert len(payload["referenced"]) == MAX_REFERENCES
