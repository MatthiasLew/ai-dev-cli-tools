from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field


@dataclass(slots=True)
class SymbolSnippet:
    name: str
    kind: str
    start_line: int
    end_line: int
    reason: str
    reason_code: str
    referenced_local_symbols: list[str] = field(default_factory=list)
    truncated: bool = False


@dataclass(slots=True)
class SymbolSelection:
    content: str
    snippets: list[SymbolSnippet]
    omitted_content: bool
    truncated: bool


def select_python_symbols(
    source: str,
    display_source: str,
    task: str,
    max_chars: int,
) -> SymbolSelection | None:
    if len(display_source) <= max_chars:
        return None
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    definitions = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    if not definitions:
        return None

    task_tokens = _task_tokens(task)
    matched = [node for node in definitions if _name_tokens(node.name) & task_tokens]
    candidates = matched or [node for node in definitions if not node.name.startswith("_")]
    if not candidates:
        candidates = definitions
    candidates = sorted(
        candidates,
        key=lambda node: (_symbol_score(node.name, task_tokens), -node.lineno),
        reverse=True,
    )

    local_names = {node.name for node in definitions}
    source_lines = display_source.splitlines(keepends=True)
    selected: list[SymbolSnippet] = []
    sections: list[str] = []
    remaining = max(max_chars, 0)

    imports = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    if imports and remaining > 0:
        start = min(node.lineno for node in imports)
        end = max(_end_line(node) for node in imports)
        import_budget = min(remaining, max(200, min(1_500, max_chars // 4)))
        unused_import_budget = _append_section(
            sections,
            selected,
            source_lines,
            SymbolSnippet(
                "<imports>",
                "imports",
                start,
                end,
                "imports required by selected symbols",
                "REQUIRED_IMPORTS",
            ),
            import_budget,
        )
        remaining -= import_budget - unused_import_budget

    for node in candidates:
        if remaining <= 0:
            break
        reason = (
            "symbol name matches task terms"
            if _name_tokens(node.name) & task_tokens
            else "top-level public symbol"
        )
        referenced = sorted(
            {
                child.id
                for child in ast.walk(node)
                if isinstance(child, ast.Name) and child.id in local_names and child.id != node.name
            }
        )
        snippet = SymbolSnippet(
            name=node.name,
            kind=_symbol_kind(node),
            start_line=node.lineno,
            end_line=_end_line(node),
            reason=reason,
            reason_code=(
                "TASK_SYMBOL_MATCH"
                if reason == "symbol name matches task terms"
                else "PUBLIC_SYMBOL"
            ),
            referenced_local_symbols=referenced,
        )
        remaining = _append_section(sections, selected, source_lines, snippet, remaining)

    if not selected:
        return None
    return SymbolSelection(
        content="\n\n".join(sections).rstrip() + "\n",
        snippets=selected,
        omitted_content=True,
        truncated=any(item.truncated for item in selected),
    )


def _append_section(
    sections: list[str],
    selected: list[SymbolSnippet],
    lines: list[str],
    snippet: SymbolSnippet,
    remaining: int,
) -> int:
    header = (
        f"# [{snippet.kind}] {snippet.name} "
        f"(lines {snippet.start_line}-{snippet.end_line}; {snippet.reason})\n"
    )
    body = "".join(lines[snippet.start_line - 1 : snippet.end_line])
    separator_cost = 2 if sections else 0
    available = max(remaining - len(header) - separator_cost, 0)
    if available <= 0:
        return remaining
    if len(body) > available:
        marker = "\n# [SYMBOL TRUNCATED]\n"
        body = body[: max(available - len(marker), 0)] + marker
        snippet.truncated = True
    sections.append(header + body.rstrip())
    selected.append(snippet)
    return max(remaining - len(sections[-1]) - separator_cost, 0)


def _task_tokens(task: str) -> set[str]:
    return {
        token.lower() for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]+", task) if len(token) >= 3
    }


def _name_tokens(name: str) -> set[str]:
    split = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name).lower()
    return {token for token in split.split("_") if token}


def _symbol_score(name: str, task_tokens: set[str]) -> int:
    matches = len(_name_tokens(name) & task_tokens)
    return matches * 100 + (10 if not name.startswith("_") else 0)


def _end_line(node: ast.AST) -> int:
    value = getattr(node, "end_lineno", None)
    return value if isinstance(value, int) else getattr(node, "lineno", 1)


def _symbol_kind(node: ast.AST) -> str:
    if isinstance(node, ast.ClassDef):
        return "class"
    if isinstance(node, ast.AsyncFunctionDef):
        return "async-function"
    return "function"
