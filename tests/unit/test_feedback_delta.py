import json

from ai_dev_tools.runners.feedback_delta import apply_feedback_delta, feedback_state_fingerprint


def _summary(status: str = "success") -> dict[str, object]:
    return {
        "agent_protocol_version": "1",
        "decision": {"ready": status == "success", "status": status},
        "changes": {"files": ["src/app.py"], "count": 1},
        "validation": {
            "status": status,
            "checks_total": 20,
            "checks_failed": 0 if status == "success" else 1,
            "failure_signatures": [] if status == "success" else ["failure:one"],
            "results": [
                {
                    "name": f"check-{index}",
                    "command": ["python", "-m", "pytest", f"tests/test_{index}.py"],
                    "status": "success",
                    "exit_code": 0,
                    "reuse": "resumed",
                }
                for index in range(20)
            ],
            "execution": {"waves": list(range(20)), "resumed": 20},
        },
        "context": {
            "status": "success",
            "selected_files": [
                {"path": "src/app.py", "content": "x = 1\n" * 500, "chars": 3_000}
            ],
            "incremental": {"context_id": "abc123", "reused": 1},
            "adaptive_context": {"enabled": True},
        },
        "observations": {
            "schema_version": "1",
            "current": {
                "evidence_id": "observation:abc",
                "status": status,
                "validation": {"results": list(range(200))},
            },
            "current_retained_reasons": ["final_verification"],
            "referenced": [],
            "duplicate_observations_suppressed": 1,
        },
    }


def test_feedback_fingerprint_ignores_execution_reuse_but_tracks_semantic_state() -> None:
    summary = _summary()
    validation = summary["validation"]
    context = summary["context"]
    assert isinstance(validation, dict)
    assert isinstance(context, dict)
    first = feedback_state_fingerprint("fix auth", ["src/app.py"], validation, context)

    results = validation["results"]
    assert isinstance(results, list)
    assert isinstance(results[0], dict)
    results[0]["reuse"] = "executed"
    same = feedback_state_fingerprint("fix auth", ["src/app.py"], validation, context)
    results[0]["exit_code"] = 1
    changed = feedback_state_fingerprint("fix auth", ["src/app.py"], validation, context)

    assert first == same
    assert changed != first


def test_unchanged_success_becomes_small_expandable_receipt() -> None:
    summary = _summary()

    projected = apply_feedback_delta(
        summary,
        acknowledged_fingerprint="same",
        current_fingerprint="same",
        enabled=True,
        eligible=True,
    )

    assert projected["delta"]["reused"] is True  # type: ignore[index]
    assert projected["delta"]["chars_avoided"] > 5_000  # type: ignore[index]
    assert projected["validation"]["unchanged"] is True  # type: ignore[index]
    assert projected["context"]["selected_file_count"] == 1  # type: ignore[index]
    assert "selected_files" not in projected["context"]  # type: ignore[operator]
    assert len(json.dumps(projected)) < len(json.dumps(summary)) * 0.35


def test_failure_and_disabled_delta_keep_live_evidence() -> None:
    failed = _summary("failed")
    live = apply_feedback_delta(
        failed,
        acknowledged_fingerprint="same",
        current_fingerprint="same",
        enabled=True,
        eligible=False,
    )
    disabled = apply_feedback_delta(
        _summary(),
        acknowledged_fingerprint="same",
        current_fingerprint="same",
        enabled=False,
        eligible=True,
    )
    changed = apply_feedback_delta(
        _summary(),
        acknowledged_fingerprint="old-state",
        current_fingerprint="new-state",
        enabled=True,
        eligible=True,
    )

    assert live["delta"]["reason_code"] == "LIVE_EVIDENCE_REQUIRED"  # type: ignore[index]
    assert live["validation"] == failed["validation"]
    assert disabled["delta"]["reason_code"] == "SESSION_DELTA_DISABLED"  # type: ignore[index]
    assert disabled["delta"]["reused"] is False  # type: ignore[index]
    assert changed["delta"]["reason_code"] == "ACKNOWLEDGED_STATE_CHANGED"  # type: ignore[index]
    assert changed["delta"]["reused"] is False  # type: ignore[index]
