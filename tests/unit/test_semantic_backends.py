from __future__ import annotations

import shutil
import subprocess
import sys
import threading
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from ai_dev_tools import semantic
from ai_dev_tools.semantic_backends import (
    LspSession,
    _flatten_lsp_symbols,
    lsp_index,
    tree_sitter_index,
)


class Node:
    def __init__(self, node_type: str, start: int, end: int, children: list[Node] | None = None):
        self.type = node_type
        self.start_byte = start
        self.end_byte = end
        self.start_point = (0, start)
        self.end_point = (0, end)
        self.children = children or []

    def child_by_field_name(self, name: str) -> Node | None:
        return self.children[0] if name == "name" and self.children else None


def test_tree_sitter_backend_uses_real_parser_contract(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    source = tmp_path / "app.py"
    source.write_text("def run():\n    pass\n", encoding="utf-8")
    name = Node("identifier", 4, 7)
    root = Node("module", 0, 19, [Node("function_definition", 0, 19, [name])])
    parser = SimpleNamespace(parse=lambda value: SimpleNamespace(root_node=root))
    package = SimpleNamespace(
        PackConfig=lambda **kwargs: kwargs,
        init=lambda config: None,
        get_parser=lambda language: parser,
    )
    monkeypatch.setitem(sys.modules, "tree_sitter_language_pack", package)

    rows = tree_sitter_index(tmp_path, [source])

    assert rows[0]["name"] == "run"
    assert rows[0]["backend"] == "treesitter"


def test_lsp_symbols_are_flattened_with_one_based_lines() -> None:
    rows = _flatten_lsp_symbols(
        [
            {
                "name": "Service",
                "kind": 5,
                "range": {"start": {"line": 2}, "end": {"line": 8}},
                "children": [
                    {
                        "name": "run",
                        "kind": 6,
                        "selectionRange": {"start": {"line": 4}, "end": {"line": 5}},
                    }
                ],
            }
        ],
        "app.py",
    )

    assert [(row["name"], row["start_line"]) for row in rows] == [
        ("Service", 3),
        ("run", 5),
    ]


def test_unavailable_lsp_is_reported_without_crashing(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "app.py").write_text("def run(): pass\n", encoding="utf-8")
    monkeypatch.setattr(
        semantic,
        "lsp_index",
        lambda root, paths: (_ for _ in ()).throw(OSError("missing")),
    )

    report = semantic.run_semantic(tmp_path, "index", "lsp")

    assert report.status == "invalid_configuration"
    assert report.summary["reason_code"] == "SEMANTIC_BACKEND_UNAVAILABLE"


def test_lsp_index_routes_supported_files_to_available_server(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    source = tmp_path / "app.py"
    source.write_text("def run(): pass\n", encoding="utf-8")

    class Session:
        def __init__(self, command: list[str], root: Path) -> None:
            assert command[0] == "pyright-langserver"

        def __enter__(self) -> Session:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def document_symbols(
            self, path: Path, language_id: str, root: Path
        ) -> list[dict[str, object]]:
            return [{"path": path.name, "name": "run", "language": language_id}]

    from ai_dev_tools import semantic_backends

    monkeypatch.setattr(shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(semantic_backends, "LspSession", Session)
    rows = lsp_index(tmp_path, [source, tmp_path / "README.md"])
    assert rows == [{"path": "app.py", "name": "run", "language": "python"}]


class FakeProcess:
    def __init__(self) -> None:
        self.stdin = BytesIO()
        self.stdout = BytesIO()
        self.waited = False
        self.terminated = False

    def wait(self, timeout: float) -> int:
        self.waited = True
        return 0

    def terminate(self) -> None:
        self.terminated = True


def test_lsp_session_json_rpc_lifecycle(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    process = FakeProcess()
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(
        threading,
        "Thread",
        lambda **kwargs: SimpleNamespace(start=lambda: None),
    )
    session = LspSession(["server"], tmp_path)
    session.messages.put({"id": 1, "result": {}})
    entered = session.__enter__()
    assert entered is session
    source = tmp_path / "app.py"
    source.write_text("def run(): pass\n", encoding="utf-8")
    session.messages.put(
        {
            "id": 2,
            "result": [
                {"name": "run", "kind": 12, "range": {"start": {"line": 0}, "end": {"line": 0}}}
            ],
        }
    )
    assert session.document_symbols(source, "python", tmp_path)[0]["name"] == "run"
    session.messages.put({"id": 3, "result": None})
    session.__exit__()
    assert process.waited is True
    assert b"Content-Length:" in process.stdin.getvalue()


def test_lsp_session_timeout_and_failed_shutdown(tmp_path: Path) -> None:
    session = LspSession(["server"], tmp_path, timeout=0.001)
    process = FakeProcess()
    session.process = process  # type: ignore[assignment]
    try:
        session._request("slow", {})
    except TimeoutError:
        pass
    else:
        raise AssertionError("LSP timeout was not raised")
    session.__exit__()
    assert process.terminated is True


def test_lsp_reader_accepts_framed_json_and_skips_invalid(tmp_path: Path) -> None:
    session = LspSession(["server"], tmp_path)
    payload = b'{"id":7,"result":[]}'
    stream = BytesIO(
        b"Bad: header\r\n\r\n" + f"Content-Length: {len(payload)}\r\n\r\n".encode() + payload
    )
    session._read_messages(stream)
    assert session.messages.get_nowait()["id"] == 7


def test_lsp_send_requires_running_process(tmp_path: Path) -> None:
    session = LspSession(["server"], tmp_path)
    try:
        session._send({"jsonrpc": "2.0"})
    except OSError as exc:
        assert "not running" in str(exc)
    else:
        raise AssertionError("missing LSP process was accepted")


def test_lsp_request_surfaces_server_error(tmp_path: Path) -> None:
    session = LspSession(["server"], tmp_path)
    session.process = FakeProcess()  # type: ignore[assignment]
    session.messages.put({"id": 1, "error": {"code": -1, "message": "failed"}})
    try:
        session._request("symbols", {})
    except ValueError as exc:
        assert "LSP error" in str(exc)
    else:
        raise AssertionError("LSP server error was ignored")


def test_flatten_lsp_symbols_ignores_malformed_values() -> None:
    assert _flatten_lsp_symbols(None, "app.py") == []
    assert _flatten_lsp_symbols([{"name": "bad", "range": "invalid"}], "app.py") == []
