from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

from ai_dev_tools import dashboard
from ai_dev_tools.dashboard import collect_status, create_dashboard_server, dashboard_status
from ai_dev_tools.integrations import install_integrations


def test_ready_client_configs_are_generated_without_overwriting(tmp_path: Path) -> None:
    report = install_integrations(tmp_path, "all")

    assert report.status == "success"
    assert (tmp_path / ".codex/config.toml").is_file()
    codex = (tmp_path / ".codex/config.toml").read_text()
    assert "[mcp_servers.ai-dev-tools]" in codex
    assert '"-m", "ai_dev_tools"' in codex
    cursor = json.loads((tmp_path / ".cursor/mcp.json").read_text())
    assert "ai-dev-tools" in cursor["mcpServers"]
    profile = json.loads((tmp_path / ".ai-dev/clients/codex.json").read_text())
    assert profile["content_default"] == "references"
    assert profile["delta"] is True
    assert profile["telemetry_tool"] == "record_usage"
    assert profile["telemetry_status_tool"] == "usage_status"
    assert profile["telemetry_optimizer_tool"] == "optimize_usage"

    (tmp_path / ".mcp.json").write_text('{"keep": true}\n', encoding="utf-8")
    second = install_integrations(tmp_path, "claude")
    assert second.status == "partial"
    assert json.loads((tmp_path / ".mcp.json").read_text()) == {"keep": True}


def test_dashboard_collects_local_index_cache_and_errors(tmp_path: Path) -> None:
    cache = tmp_path / ".ai/cache"
    cache.mkdir(parents=True)
    (cache / "repository-index.json").write_text(
        json.dumps({"entries": [{"path": "app.py"}], "generated_at": "now"}), encoding="utf-8"
    )
    (cache / "semantic-index.json").write_text(
        json.dumps({"backend": "treesitter", "symbols": [{"name": "run"}]}), encoding="utf-8"
    )
    (tmp_path / ".ai/report.json").write_text(
        json.dumps({"issues": [{"severity": "error", "message": "boom"}]}), encoding="utf-8"
    )
    receipts = tmp_path / ".ai/token-efficiency/receipts"
    receipts.mkdir(parents=True)
    (receipts / "one.json").write_text(
        json.dumps({"saved_tokens": 120}), encoding="utf-8"
    )
    (tmp_path / ".ai/token-efficiency/latest.json").write_text(
        json.dumps(
            {
                "saved_tokens": 120,
                "saved_percent": 40.0,
                "cache": {"hit": True},
                "delivery": {"delivery": "references"},
            }
        ),
        encoding="utf-8",
    )

    status = collect_status(tmp_path)

    assert status["index"]["files"] == 1
    assert status["semantic"] == {"symbols": 1, "backend": "treesitter"}
    assert status["errors"] == ["boom"]
    assert status["token_efficiency"]["total_saved_tokens"] == 120
    assert status["token_efficiency"]["latest_delivery"] == "references"
    assert status["provider_usage"]["sessions"] == 0
    assert status["provider_usage"]["policy"]["configured"] is False
    assert status["provider_usage"]["optimizer"]["budget_recommendations"] == 0
    assert status["provider_usage"]["optimizer"]["gaps"] == 2
    assert dashboard_status(tmp_path).summary["semantic"]["symbols"] == 1


def test_dashboard_http_is_loopback_read_only(tmp_path: Path) -> None:
    server = create_dashboard_server(tmp_path, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        with urllib.request.urlopen(base + "/api/status", timeout=2) as response:  # noqa: S310
            assert json.load(response)["project_root"] == str(tmp_path.resolve())
        with urllib.request.urlopen(base + "/", timeout=2) as response:  # noqa: S310
            assert b"ai-dev dashboard" in response.read()
        try:
            urllib.request.urlopen(base + "/missing", timeout=2)  # noqa: S310
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    try:
        create_dashboard_server(tmp_path, "0.0.0.0", 8765)
    except ValueError as exc:
        assert "loopback" in str(exc)
    else:
        raise AssertionError("non-loopback dashboard host was accepted")


def test_force_merge_preserves_existing_client_configuration(tmp_path: Path) -> None:
    path = tmp_path / ".mcp.json"
    path.write_text(json.dumps({"keep": True, "mcpServers": {"other": {}}}), encoding="utf-8")

    report = install_integrations(tmp_path, "claude", force=True)

    payload = json.loads(path.read_text())
    assert report.status == "success"
    assert payload["keep"] is True
    assert set(payload["mcpServers"]) == {"other", "ai-dev-tools"}


def test_unknown_integration_client_fails_closed(tmp_path: Path) -> None:
    report = install_integrations(tmp_path, "unknown")
    assert report.status == "invalid_configuration"


def test_dashboard_serve_handles_keyboard_interrupt(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    class Server:
        server_port = 1234

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def serve_forever(self) -> None:
            raise KeyboardInterrupt

    monkeypatch.setattr(dashboard, "create_dashboard_server", lambda *args: Server())
    assert dashboard.serve_dashboard(tmp_path, port=0) == 0


def test_dashboard_surfaces_invalid_usage_policy(tmp_path: Path) -> None:
    policy = tmp_path / ".ai-dev/telemetry-budgets.json"
    policy.parent.mkdir()
    policy.write_text(json.dumps({"unknown": True}), encoding="utf-8")

    status = collect_status(tmp_path)

    assert status["provider_usage"]["policy"]["passed"] is False
    assert status["provider_usage"]["policy"]["violations"][0]["code"] == (
        "INVALID_TELEMETRY_POLICY"
    )


def test_force_replaces_invalid_json_and_appends_codex(tmp_path: Path) -> None:
    generic = tmp_path / "mcp.ai-dev.json"
    generic.write_text("invalid", encoding="utf-8")
    assert install_integrations(tmp_path, "generic", force=True).status == "success"
    assert "ai-dev-tools" in json.loads(generic.read_text())["mcpServers"]

    codex = tmp_path / ".codex/config.toml"
    codex.parent.mkdir()
    codex.write_text("model = 'gpt'\n", encoding="utf-8")
    assert install_integrations(tmp_path, "codex", force=True).status == "success"
    assert "model = 'gpt'" in codex.read_text()
    assert "[mcp_servers.ai-dev-tools]" in codex.read_text()
