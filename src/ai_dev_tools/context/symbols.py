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


@dataclass(slots=True)
class _JavaScriptSymbol:
    name: str
    kind: str
    start_line: int
    end_line: int


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


def select_javascript_symbols(
    source: str,
    display_source: str,
    task: str,
    max_chars: int,
) -> SymbolSelection | None:
    """Select useful top-level JavaScript/TypeScript declarations.

    This is intentionally a conservative structural extractor, not a complete
    JavaScript parser. Ambiguous or unbalanced input falls back to file-prefix
    selection in the caller.
    """
    if len(display_source) <= max_chars:
        return None
    structure = _javascript_structure(source)
    if structure is None:
        return None
    cleaned, line_depths = structure
    definitions = _javascript_definitions(cleaned, line_depths)
    if not definitions:
        return None

    task_tokens = _task_tokens(task)
    matched = [item for item in definitions if _name_tokens(item.name) & task_tokens]
    candidates = matched or [item for item in definitions if not item.name.startswith("_")]
    if not candidates:
        candidates = definitions
    candidates = sorted(
        candidates,
        key=lambda item: (_symbol_score(item.name, task_tokens), -item.start_line),
        reverse=True,
    )

    local_names = {item.name for item in definitions}
    source_lines = display_source.splitlines(keepends=True)
    cleaned_lines = cleaned.splitlines(keepends=True)
    selected: list[SymbolSnippet] = []
    sections: list[str] = []
    remaining = max(max_chars, 0)

    import_lines = [
        index
        for index, line in enumerate(cleaned_lines, start=1)
        if line_depths[index - 1] == 0
        and re.match(r"\s*(?:import\b|(?:const|let|var)\b.*\brequire\s*\()", line)
    ]
    if import_lines and remaining > 0:
        import_budget = min(remaining, max(200, min(1_500, max_chars // 4)))
        unused_import_budget = _append_section(
            sections,
            selected,
            source_lines,
            SymbolSnippet(
                "<imports>",
                "imports",
                min(import_lines),
                max(import_lines),
                "imports required by selected symbols",
                "REQUIRED_IMPORTS",
            ),
            import_budget,
            comment_prefix="//",
        )
        remaining -= import_budget - unused_import_budget

    for item in candidates:
        if remaining <= 0:
            break
        reason = (
            "symbol name matches task terms"
            if _name_tokens(item.name) & task_tokens
            else "top-level public symbol"
        )
        body = "".join(cleaned_lines[item.start_line - 1 : item.end_line])
        referenced = sorted(
            name
            for name in local_names
            if name != item.name and re.search(rf"(?<![\w$]){re.escape(name)}(?![\w$])", body)
        )
        remaining = _append_section(
            sections,
            selected,
            source_lines,
            SymbolSnippet(
                name=item.name,
                kind=item.kind,
                start_line=item.start_line,
                end_line=item.end_line,
                reason=reason,
                reason_code=(
                    "TASK_SYMBOL_MATCH"
                    if reason == "symbol name matches task terms"
                    else "PUBLIC_SYMBOL"
                ),
                referenced_local_symbols=referenced,
            ),
            remaining,
            comment_prefix="//",
        )

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
    comment_prefix: str = "#",
) -> int:
    header = (
        f"{comment_prefix} [{snippet.kind}] {snippet.name} "
        f"(lines {snippet.start_line}-{snippet.end_line}; {snippet.reason})\n"
    )
    body = "".join(lines[snippet.start_line - 1 : snippet.end_line])
    separator_cost = 2 if sections else 0
    available = max(remaining - len(header) - separator_cost, 0)
    if available <= 0:
        return remaining
    if len(body) > available:
        marker = f"\n{comment_prefix} [SYMBOL TRUNCATED]\n"
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


def _javascript_structure(source: str) -> tuple[str, list[int]] | None:
    cleaned: list[str] = []
    line_depths = [0]
    depth = 0
    state = "code"
    quote = ""
    escaped = False
    index = 0
    while index < len(source):
        char = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""
        if char == "\n":
            cleaned.append(char)
            if state == "line-comment":
                state = "code"
            line_depths.append(depth)
            escaped = False
            index += 1
            continue
        if state == "line-comment":
            cleaned.append(" ")
        elif state == "block-comment":
            if char == "*" and following == "/":
                cleaned.extend((" ", " "))
                state = "code"
                index += 2
                continue
            cleaned.append(" ")
        elif state == "string":
            cleaned.append(" ")
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                state = "code"
        elif char == "/" and following == "/":
            cleaned.extend((" ", " "))
            state = "line-comment"
            index += 2
            continue
        elif char == "/" and following == "*":
            cleaned.extend((" ", " "))
            state = "block-comment"
            index += 2
            continue
        elif char in {"'", '"', chr(96)}:
            cleaned.append(" ")
            state = "string"
            quote = char
        else:
            cleaned.append(char)
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth < 0:
                    return None
        index += 1
    if state in {"block-comment", "string"} or depth != 0:
        return None
    return "".join(cleaned), line_depths


def _javascript_definitions(cleaned: str, line_depths: list[int]) -> list[_JavaScriptSymbol]:
    patterns = (
        (
            re.compile(
                r"\s*(?:export\s+(?:default\s+)?)?(?:async\s+)?function\s+"
                r"([A-Za-z_$][\w$]*)"
            ),
            "function",
        ),
        (
            re.compile(r"\s*(?:export\s+(?:default\s+)?)?class\s+([A-Za-z_$][\w$]*)"),
            "class",
        ),
        (re.compile(r"\s*(?:export\s+)?interface\s+([A-Za-z_$][\w$]*)"), "interface"),
        (re.compile(r"\s*(?:export\s+)?enum\s+([A-Za-z_$][\w$]*)"), "enum"),
        (re.compile(r"\s*(?:export\s+)?namespace\s+([A-Za-z_$][\w$]*)"), "namespace"),
        (re.compile(r"\s*(?:export\s+)?type\s+([A-Za-z_$][\w$]*)\b"), "type"),
        (
            re.compile(
                r"\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)"
                r"(?:\s*:[^=;]+)?\s*=\s*(?:async\s*)?"
                r"(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"
            ),
            "arrow-function",
        ),
    )
    offsets = _line_offsets(cleaned)
    lines = cleaned.splitlines()
    found: list[_JavaScriptSymbol] = []
    for line_index, line in enumerate(lines):
        if line_index >= len(line_depths) or line_depths[line_index] != 0:
            continue
        for pattern, kind in patterns:
            match = pattern.match(line)
            if match is None:
                continue
            start_offset = offsets[line_index] + match.start()
            end_line = _javascript_declaration_end(cleaned, start_offset, line_index + 1, kind)
            if end_line is not None:
                found.append(_JavaScriptSymbol(match.group(1), kind, line_index + 1, end_line))
            break
    return found


def _javascript_declaration_end(
    cleaned: str, start_offset: int, start_line: int, kind: str
) -> int | None:
    if kind in {"function", "class", "interface", "enum", "namespace"}:
        brace = cleaned.find("{", start_offset)
        semicolon = cleaned.find(";", start_offset)
        if brace < 0 or 0 <= semicolon < brace:
            return None
        return _matching_brace_line(cleaned, brace)
    line_end = cleaned.find("\n", start_offset)
    search_end = len(cleaned) if line_end < 0 else line_end
    if kind == "arrow-function":
        arrow = cleaned.find("=>", start_offset, search_end)
        if arrow < 0:
            return None
        brace = cleaned.find("{", arrow + 2, search_end)
        if brace >= 0:
            return _matching_brace_line(cleaned, brace)
    semicolon = cleaned.find(";", start_offset)
    if semicolon >= 0:
        return cleaned.count("\n", 0, semicolon) + 1
    return start_line


def _matching_brace_line(cleaned: str, opening: int) -> int | None:
    depth = 0
    for index in range(opening, len(cleaned)):
        if cleaned[index] == "{":
            depth += 1
        elif cleaned[index] == "}":
            depth -= 1
            if depth == 0:
                return cleaned.count("\n", 0, index) + 1
    return None


def _line_offsets(text: str) -> list[int]:
    offsets = [0]
    offsets.extend(match.end() for match in re.finditer("\n", text))
    return offsets
