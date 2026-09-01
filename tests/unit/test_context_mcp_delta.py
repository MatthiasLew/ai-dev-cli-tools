from __future__ import annotations

from pathlib import Path

from ai_dev_tools.cache.repository import update_repository_index
from ai_dev_tools.context.mcp_delta import apply_context_delta, context_state_fingerprint


def _payload(*, status: str = "success", issues: list[object] | None = None) -> dict[str, object]:
    return {
        "command": "context build",
        "status": status,
        "summary": {
            "task": "inspect auth",
            "selected_files": [{"path": "auth.py", "content": "secret body"}],
            "incremental": {"context_id": "0123456789abcdef"},
        },
        "issues": issues or [],
        "artifacts": [],
    }


def test_context_fingerprint_tracks_repository_content_and_request(tmp_path: Path) -> None:
    source = tmp_path / "auth.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    update_repository_index(tmp_path)
    first = context_state_fingerprint(tmp_path, {"task": "inspect auth"})

    assert first == context_state_fingerprint(tmp_path, {"task": "inspect auth"})
    assert first != context_state_fingerprint(tmp_path, {"task": "inspect billing"})

    source.write_text("VALUE = 2\n", encoding="utf-8")
    update_repository_index(tmp_path)
    assert first != context_state_fingerprint(tmp_path, {"task": "inspect auth"})


def test_acknowledged_unchanged_context_becomes_receipt(tmp_path: Path) -> None:
    (tmp_path / "auth.py").write_text("VALUE = 1\n", encoding="utf-8")
    update_repository_index(tmp_path)
    state = context_state_fingerprint(tmp_path, {"task": "inspect auth"})

    result = apply_context_delta(
        _payload(),
        acknowledged_fingerprint=state,
        current_fingerprint=state,
        enabled=True,
        eligible=True,
    )

    summary = result["summary"]
    assert isinstance(summary, dict)
    assert summary["context_receipt"]["unchanged"] is True
    assert summary["delta"]["reused"] is True
    assert summary["delta"]["chars_avoided"] >= 0
    assert summary["delta"]["estimated_tokens_avoided"] >= 0
    assert summary["delta"]["live_context_chars_avoided"] > 0
    assert "selected_files" not in summary


def test_changed_or_ineligible_context_keeps_full_payload() -> None:
    changed = apply_context_delta(
        _payload(),
        acknowledged_fingerprint="old",
        current_fingerprint="new",
        enabled=True,
        eligible=True,
    )
    unsafe = apply_context_delta(
        _payload(status="partial", issues=[{"code": "WARNING"}]),
        acknowledged_fingerprint="same",
        current_fingerprint="same",
        enabled=True,
        eligible=False,
    )

    changed_summary = changed["summary"]
    unsafe_summary = unsafe["summary"]
    assert isinstance(changed_summary, dict)
    assert isinstance(unsafe_summary, dict)
    changed_delta = changed_summary["delta"]
    unsafe_delta = unsafe_summary["delta"]
    assert isinstance(changed_delta, dict)
    assert isinstance(unsafe_delta, dict)
    assert "selected_files" in changed_summary
    assert changed_delta["reason_code"] == "ACKNOWLEDGED_CONTEXT_CHANGED"
    assert "selected_files" in unsafe_summary
    assert unsafe_delta["reason_code"] == "LIVE_CONTEXT_REQUIRED"
