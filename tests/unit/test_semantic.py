import json
from pathlib import Path

from ai_dev_tools.semantic import run_semantic, semantic_capabilities


def test_structural_semantic_index_is_bounded_and_local(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from ai_dev_tools import semantic

    monkeypatch.setattr(semantic, "tree_sitter_available", lambda: False)
    source = tmp_path / "src" / "service.py"
    source.parent.mkdir()
    source.write_text("class Service:\n    pass\n\ndef run():\n    return 1\n", encoding="utf-8")

    report = run_semantic(tmp_path, "index")

    assert report.status == "success"
    assert report.summary["backend"] == "structural"
    assert report.summary["symbol_count"] == 2
    payload = json.loads((tmp_path / ".ai" / "cache" / "semantic-index.json").read_text())
    assert payload["symbols"][0]["path"] == "src/service.py"


def test_semantic_capabilities_expose_plugins_lsp_and_fallback() -> None:
    capabilities = semantic_capabilities()
    assert capabilities["plugin_group"] == "ai_dev_tools.semantic_backends"
    assert capabilities["fallback"] == "structural"
    assert capabilities["local_only"] is True


def test_unknown_semantic_backend_fails_closed(tmp_path: Path) -> None:
    report = run_semantic(tmp_path, "index", "does-not-exist")
    assert report.status == "invalid_configuration"
    assert report.summary["reason_code"] == "SEMANTIC_BACKEND_UNAVAILABLE"


def test_semantic_status_and_explicit_plugin_backend(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from ai_dev_tools import semantic

    class Provider:
        def index(self, project_root: Path, paths: list[Path]) -> list[dict[str, object]]:
            return [{"path": "app.py", "name": "provided"}, "ignored"]  # type: ignore[list-item]

    class EntryPoint:
        def load(self):  # type: ignore[no-untyped-def]
            return Provider

    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    monkeypatch.setattr(semantic, "_backend_entry_points", lambda: {"provider": EntryPoint()})

    report = run_semantic(tmp_path, "index", "provider")
    status = run_semantic(tmp_path, "status")

    assert report.summary["backend"] == "provider"
    assert report.summary["symbol_count"] == 1
    assert status.summary["indexed"] is True


def test_semantic_provider_must_return_a_list(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from ai_dev_tools import semantic

    class Provider:
        def index(self, project_root: Path, paths: list[Path]) -> object:
            return {"not": "a list"}

    class EntryPoint:
        def load(self):  # type: ignore[no-untyped-def]
            return Provider()

    monkeypatch.setattr(semantic, "_backend_entry_points", lambda: {"invalid": EntryPoint()})
    report = run_semantic(tmp_path, "index", "invalid")
    assert report.status == "invalid_configuration"


def test_auto_tree_sitter_failure_uses_structural_fallback(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from ai_dev_tools import semantic

    (tmp_path / "app.py").write_text("def run(): pass\n", encoding="utf-8")
    monkeypatch.setattr(semantic, "tree_sitter_available", lambda: True)
    monkeypatch.setattr(
        semantic,
        "tree_sitter_index",
        lambda root, paths: (_ for _ in ()).throw(RuntimeError("grammar unavailable")),
    )
    report = run_semantic(tmp_path, "index", "auto")
    assert report.status == "partial"
    assert report.summary["backend"] == "structural"
    assert report.issues[0].code == "TREE_SITTER_FALLBACK"
