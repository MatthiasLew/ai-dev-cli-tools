from __future__ import annotations

import json
from pathlib import Path

from ai_dev_tools.cli import build_parser, main


def test_integrations_and_dashboard_status_cli(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    code = main(
        ["--project", str(tmp_path), "--json", "integrations", "install", "generic"]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["summary"]["clients"] == ["generic"]

    code = main(["--project", str(tmp_path), "--json", "dashboard", "status"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["summary"]["project_root"] == str(tmp_path.resolve())


def test_daemon_and_benchmark_gate_cli_paths(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    code = main(["--project", str(tmp_path), "--json", "index", "daemon", "status"])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["status"] == "partial"

    missing = tmp_path / "missing.json"
    code = main(
        [
            "--project",
            str(tmp_path),
            "--json",
            "benchmark",
            "gate",
            str(missing),
            str(missing),
            "--min-token-reduction",
            "15",
        ]
    )
    assert code == 1
    assert json.loads(capsys.readouterr().out)["status"] == "failed"


def test_adaptive_context_cli_reports_resolved_budget(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "README.md").write_text("docs\n", encoding="utf-8")

    code = main(
        [
            "--project",
            str(tmp_path),
            "--json",
            "context",
            "build",
            "--task",
            "document API",
            "--include",
            "README.md",
            "--no-git",
            "--adaptive",
            "--explain",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["summary"]["adaptive_context"]["enabled"] is True
    assert payload["summary"]["adaptive_context"]["intent"] == "docs"


def test_feedback_delta_cli_flags_parse_explicit_handshake() -> None:
    args = build_parser().parse_args(
        ["feedback", "--no-delta", "--ack-state", "abc123"]
    )

    assert args.delta is False
    assert args.ack_state == "abc123"


def test_task_cli_returns_reference_first_receipt(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='cli-task'\nversion='0.0.0'\n", encoding="utf-8"
    )
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")

    code = main(
        [
            "--project",
            str(tmp_path),
            "--json",
            "task",
            "--task",
            "inspect value",
            "--client",
            "codex",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["summary"]["client"] == "codex"
    assert payload["summary"]["constraints"]["content_default"] == "references"
    assert payload["summary"]["token_savings"]["delivery"]["delivery"] == "references"


def test_telemetry_import_and_status_cli(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    source = tmp_path / "usage.json"
    source.write_text(json.dumps({"usage": {
        "input_tokens": 30, "cached_input_tokens": 10, "output_tokens": 4,
    }}), encoding="utf-8")

    code = main(["--project", str(tmp_path), "--json", "telemetry", "import",
                 str(source), "--client", "cursor", "--format", "generic"])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["summary"]["input_tokens"] == 30

    code = main(["--project", str(tmp_path), "--json", "telemetry", "status"])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["summary"]["sessions"] == 1


def test_telemetry_pricing_and_gate_cli(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    pricing = tmp_path / "pricing.json"
    pricing.write_text(json.dumps({
        "models": {"default": {"input_per_million": 1, "output_per_million": 2}}
    }), encoding="utf-8")
    code = main([
        "--project", str(tmp_path), "--json", "telemetry", "pricing", "import",
        str(pricing), "--provider", "generic", "--version", "v1", "--no-activate",
    ])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["summary"]["active"] is False

    code = main([
        "--project", str(tmp_path), "--json", "telemetry", "pricing", "activate",
        "generic", "v1",
    ])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["summary"]["active"] is True

    policy = tmp_path / ".ai-dev/telemetry-budgets.json"
    policy.write_text(json.dumps({"limits": {"max_sessions": 0}}), encoding="utf-8")
    code = main(["--project", str(tmp_path), "--json", "telemetry", "gate"])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["summary"]["passed"] is True

    source = tmp_path / "usage.json"
    source.write_text(
        json.dumps({"usage": {"input_tokens": 1, "output_tokens": 0}}),
        encoding="utf-8",
    )
    code = main([
        "--project", str(tmp_path), "--json", "telemetry", "import", str(source),
        "--client", "generic", "--format", "generic",
    ])
    assert code == 0
    capsys.readouterr()
    code = main(["--project", str(tmp_path), "--json", "telemetry", "gate"])
    assert code == 1
    assert json.loads(capsys.readouterr().out)["summary"]["passed"] is False
