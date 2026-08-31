from __future__ import annotations

import json
import queue
import shutil
import subprocess
import threading
from pathlib import Path
from typing import BinaryIO

LANGUAGE_BY_SUFFIX = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".java": "java",
    ".rs": "rust",
    ".php": "php",
}

SYMBOL_NODE_TYPES = {
    "class_definition": "class",
    "class_declaration": "class",
    "function_definition": "function",
    "function_declaration": "function",
    "function_item": "function",
    "method_declaration": "method",
    "method_definition": "method",
    "interface_declaration": "interface",
    "trait_item": "trait",
    "struct_item": "struct",
    "enum_item": "enum",
}

LSP_COMMANDS: dict[str, list[tuple[list[str], str]]] = {
    "python": [(["pyright-langserver", "--stdio"], "python"), (["pylsp"], "python")],
    "javascript": [(["typescript-language-server", "--stdio"], "javascript")],
    "typescript": [(["typescript-language-server", "--stdio"], "typescript")],
    "tsx": [(["typescript-language-server", "--stdio"], "typescriptreact")],
    "rust": [(["rust-analyzer"], "rust")],
    "java": [(["jdtls"], "java")],
    "php": [(["intelephense", "--stdio"], "php")],
}


def tree_sitter_available() -> bool:
    try:
        import tree_sitter_language_pack  # noqa: F401
    except ImportError:
        return False
    return True


def tree_sitter_index(root: Path, paths: list[Path]) -> list[dict[str, object]]:
    try:
        from tree_sitter_language_pack import PackConfig, get_parser, init
    except ImportError as exc:
        raise ImportError("Install ai-dev-cli-tools[semantic] for Tree-sitter support") from exc

    rows: list[dict[str, object]] = []
    cache = root / ".ai" / "cache" / "tree-sitter"
    cache.mkdir(parents=True, exist_ok=True)
    init(PackConfig(cache_dir=str(cache)))
    parsers: dict[str, object] = {}
    for path in paths[:2_000]:
        language = LANGUAGE_BY_SUFFIX.get(path.suffix.lower())
        if language is None:
            continue
        try:
            source = path.read_bytes()
            parser = parsers.setdefault(language, get_parser(language))
            tree = parser.parse(source)  # type: ignore[attr-defined]
            nodes = [tree.root_node]
            while nodes:
                node = nodes.pop()
                nodes.extend(reversed(node.children))
                kind = SYMBOL_NODE_TYPES.get(node.type)
                if kind is None:
                    continue
                name_node = node.child_by_field_name("name")
                if name_node is None:
                    continue
                name = source[name_node.start_byte : name_node.end_byte].decode(
                    "utf-8", errors="replace"
                )
                rows.append(
                    {
                        "path": path.relative_to(root).as_posix(),
                        "name": name,
                        "kind": kind,
                        "start_line": node.start_point[0] + 1,
                        "end_line": node.end_point[0] + 1,
                        "backend": "treesitter",
                        "language": language,
                    }
                )
        except (OSError, LookupError, ValueError):
            continue
    return rows


def lsp_index(root: Path, paths: list[Path]) -> list[dict[str, object]]:
    grouped: dict[str, list[Path]] = {}
    for path in paths[:2_000]:
        language = LANGUAGE_BY_SUFFIX.get(path.suffix.lower())
        if language in LSP_COMMANDS:
            grouped.setdefault(language, []).append(path)
    rows: list[dict[str, object]] = []
    for language, selected in grouped.items():
        available = [entry for entry in LSP_COMMANDS[language] if shutil.which(entry[0][0])]
        if not available:
            raise OSError(f"No local LSP server found for {language}")
        command, language_id = available[0]
        with LspSession(command, root) as session:
            for path in selected:
                rows.extend(session.document_symbols(path, language_id, root))
    return rows


class LspSession:
    def __init__(self, command: list[str], root: Path, timeout: float = 5.0) -> None:
        self.command = command
        self.root = root
        self.timeout = timeout
        self.process: subprocess.Popen[bytes] | None = None
        self.messages: queue.Queue[dict[str, object]] = queue.Queue()
        self.next_id = 1

    def __enter__(self) -> LspSession:
        self.process = subprocess.Popen(
            self.command,
            cwd=self.root,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
        if self.process.stdin is None or self.process.stdout is None:
            raise OSError("LSP server did not expose stdio")
        threading.Thread(
            target=self._read_messages,
            args=(self.process.stdout,),
            daemon=True,
        ).start()
        self._request(
            "initialize",
            {
                "processId": None,
                "rootUri": self.root.as_uri(),
                "capabilities": {"textDocument": {"documentSymbol": {}}},
            },
        )
        self._notify("initialized", {})
        return self

    def __exit__(self, *args: object) -> None:
        if self.process is None:
            return
        try:
            self._request("shutdown", None)
            self._notify("exit", None)
            self.process.wait(timeout=2)
        except (OSError, TimeoutError, subprocess.TimeoutExpired):
            self.process.terminate()

    def document_symbols(self, path: Path, language_id: str, root: Path) -> list[dict[str, object]]:
        text = path.read_text(encoding="utf-8", errors="replace")
        uri = path.resolve().as_uri()
        self._notify(
            "textDocument/didOpen",
            {"textDocument": {"uri": uri, "languageId": language_id, "version": 1, "text": text}},
        )
        result = self._request("textDocument/documentSymbol", {"textDocument": {"uri": uri}})
        self._notify("textDocument/didClose", {"textDocument": {"uri": uri}})
        return _flatten_lsp_symbols(result, path.relative_to(root).as_posix())

    def _notify(self, method: str, params: object) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _request(self, method: str, params: object) -> object:
        request_id = self.next_id
        self.next_id += 1
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        while True:
            try:
                message = self.messages.get(timeout=self.timeout)
            except queue.Empty as exc:
                raise TimeoutError(f"LSP request timed out: {method}") from exc
            if message.get("id") == request_id:
                if "error" in message:
                    raise ValueError(f"LSP error: {message['error']}")
                return message.get("result")

    def _send(self, payload: dict[str, object]) -> None:
        if self.process is None or self.process.stdin is None:
            raise OSError("LSP process is not running")
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.process.stdin.write(f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
        self.process.stdin.flush()

    def _read_messages(self, stream: BinaryIO) -> None:
        while True:
            headers: dict[str, str] = {}
            while True:
                line = stream.readline()
                if not line:
                    return
                if line == b"\r\n":
                    break
                key, _, value = line.decode("ascii", errors="replace").partition(":")
                headers[key.lower()] = value.strip()
            try:
                length = int(headers["content-length"])
                payload = json.loads(stream.read(length))
            except (KeyError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                self.messages.put(payload)


def _flatten_lsp_symbols(value: object, path: str) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, object]] = []
    pending = [item for item in value if isinstance(item, dict)]
    while pending:
        item = pending.pop(0)
        children = item.get("children")
        if isinstance(children, list):
            pending.extend(child for child in children if isinstance(child, dict))
        location = item.get("selectionRange", item.get("range", {}))
        if not isinstance(location, dict):
            continue
        start = location.get("start", {})
        end = location.get("end", {})
        if not isinstance(start, dict) or not isinstance(end, dict):
            continue
        rows.append(
            {
                "path": path,
                "name": str(item.get("name", "")),
                "kind": f"lsp:{item.get('kind', 0)}",
                "start_line": _line_number(start.get("line")) + 1,
                "end_line": _line_number(end.get("line"), _line_number(start.get("line"))) + 1,
                "backend": "lsp",
            }
        )
    return rows


def _line_number(value: object, default: int = 0) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default
