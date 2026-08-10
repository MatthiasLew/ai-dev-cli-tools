from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from ai_dev_tools.runners.check_selection import infer_tests_for_changed_files
from ai_dev_tools.security.secrets import mask_text
from ai_dev_tools.source_symbols import SourceSymbol, extract_source_symbols
from ai_dev_tools.utils.subprocess import run_command

_SUPPORTED_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx"}
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_MAX_FILES = 50
_MAX_SOURCE_BYTES = 1_000_000


class ChangedSymbolDict(TypedDict):
    path: str
    name: str
    kind: str
    change_type: str
    start_line: int | None
    end_line: int | None
    added_lines: int
    deleted_lines: int
    signature: str | None
    signature_changed: bool
    risk: str
    related_tests: list[str]
    confidence: str
    reason_code: str


class SymbolDiffFallback(TypedDict):
    path: str
    reason_code: str


class SymbolDiffSummary(TypedDict):
    supported_files: int
    files_analyzed: int
    symbols_changed: int
    risk_counts: dict[str, int]
    fallback_count: int
    files_omitted_by_limit: int
    max_files: int


class SymbolDiffResult(TypedDict):
    symbols: list[ChangedSymbolDict]
    summary: SymbolDiffSummary
    fallbacks: list[SymbolDiffFallback]
    supported_languages: list[str]


@dataclass(slots=True, frozen=True)
class LineChange:
    old_start: int
    old_count: int
    new_start: int
    new_count: int


@dataclass(slots=True)
class ChangedSymbol:
    path: str
    name: str
    kind: str
    change_type: str
    start_line: int | None
    end_line: int | None
    added_lines: int
    deleted_lines: int
    signature: str | None
    signature_changed: bool
    risk: str
    related_tests: list[str]
    confidence: str

    def to_dict(self) -> ChangedSymbolDict:
        return {
            "path": self.path,
            "name": self.name,
            "kind": self.kind,
            "change_type": self.change_type,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "added_lines": self.added_lines,
            "deleted_lines": self.deleted_lines,
            "signature": self.signature,
            "signature_changed": self.signature_changed,
            "risk": self.risk,
            "related_tests": self.related_tests,
            "confidence": self.confidence,
            "reason_code": "CHANGED_SYMBOL",
        }


def analyze_symbol_diff(
    root: Path,
    changed_files: list[str],
    *,
    untracked_files: list[str] | None = None,
    deleted_files: list[str] | None = None,
    max_files: int = _MAX_FILES,
) -> SymbolDiffResult:
    """Summarize a working-tree diff at top-level symbol granularity.

    Python uses the standard-library AST. JavaScript and TypeScript use the
    project's conservative structural extractor. Unsupported, binary, large,
    or syntactically ambiguous files are reported as fallbacks rather than
    guessed.
    """
    untracked = set(untracked_files or [])
    deleted = set(deleted_files or [])
    candidates = [
        path for path in changed_files if Path(path).suffix.lower() in _SUPPORTED_SUFFIXES
    ]
    analyzed = candidates[: max(max_files, 0)]
    related = [_portable_path(item) for item in infer_tests_for_changed_files(root, analyzed)]
    symbols: list[ChangedSymbol] = []
    fallbacks: list[SymbolDiffFallback] = []

    for relative in analyzed:
        path = root / relative
        if path.exists() and path.stat().st_size > _MAX_SOURCE_BYTES:
            fallbacks.append({"path": relative, "reason_code": "SOURCE_TOO_LARGE"})
            continue
        current = None if relative in deleted else _read_source(path)
        old = None if relative in untracked else _git_source(root, relative)
        current_symbols = _extract(current, path.suffix)
        old_symbols = _extract(old, path.suffix)
        if current is not None and current_symbols is None:
            fallbacks.append({"path": relative, "reason_code": "SYMBOL_PARSE_FALLBACK"})
            continue
        if old is not None and old_symbols is None:
            fallbacks.append({"path": relative, "reason_code": "BASE_SYMBOL_PARSE_FALLBACK"})
            continue

        changes = _changes_for_file(root, relative, current, old, relative in untracked)
        file_tests = _tests_for_file(root, relative, related)
        found = _map_symbols(
            relative,
            current or "",
            old or "",
            current_symbols or [],
            old_symbols or [],
            changes,
            file_tests,
        )
        if found:
            symbols.extend(found)
        elif changes:
            additions = sum(item.new_count for item in changes)
            deletions = sum(item.old_count for item in changes)
            symbols.append(
                ChangedSymbol(
                    path=relative,
                    name="<module>",
                    kind="module",
                    change_type=_change_type(old is not None, current is not None),
                    start_line=None,
                    end_line=None,
                    added_lines=additions,
                    deleted_lines=deletions,
                    signature=None,
                    signature_changed=False,
                    risk="medium" if deletions else "low",
                    related_tests=file_tests,
                    confidence="file",
                )
            )

    risk_counts = {
        level: sum(item.risk == level for item in symbols) for level in ("high", "medium", "low")
    }
    return {
        "symbols": [item.to_dict() for item in symbols],
        "summary": {
            "supported_files": len(candidates),
            "files_analyzed": len(analyzed) - len(fallbacks),
            "symbols_changed": len(symbols),
            "risk_counts": risk_counts,
            "fallback_count": len(fallbacks),
            "files_omitted_by_limit": max(len(candidates) - len(analyzed), 0),
            "max_files": max_files,
        },
        "fallbacks": fallbacks,
        "supported_languages": ["python", "javascript", "typescript"],
    }


def parse_unified_hunks(diff: str) -> list[LineChange]:
    changes: list[LineChange] = []
    for line in diff.splitlines():
        match = _HUNK.match(line)
        if match is None:
            continue
        changes.append(
            LineChange(
                int(match.group(1)),
                int(match.group(2) or 1),
                int(match.group(3)),
                int(match.group(4) or 1),
            )
        )
    return changes


def _changes_for_file(
    root: Path, relative: str, current: str | None, old: str | None, is_untracked: bool
) -> list[LineChange]:
    if is_untracked:
        return [LineChange(0, 0, 1, len((current or "").splitlines()))]
    result = run_command(
        ["git", "diff", "HEAD", "--unified=0", "--no-color", "--no-ext-diff", "--", relative],
        root,
        30,
    )
    if result.exit_code == 0:
        return parse_unified_hunks(result.stdout)
    if old is None and current is not None:
        return [LineChange(0, 0, 1, len(current.splitlines()))]
    return []


def _map_symbols(
    relative: str,
    current: str,
    old: str,
    current_symbols: list[SourceSymbol],
    old_symbols: list[SourceSymbol],
    changes: list[LineChange],
    related_tests: list[str],
) -> list[ChangedSymbol]:
    output: list[ChangedSymbol] = []
    old_by_identity = {(item.name, item.kind): item for item in old_symbols}
    current_by_identity = {(item.name, item.kind): item for item in current_symbols}

    for symbol in current_symbols:
        added = sum(
            _overlap(symbol.start_line, symbol.end_line, change.new_start, change.new_count)
            for change in changes
        )
        old_symbol = old_by_identity.get((symbol.name, symbol.kind))
        deleted = 0
        if old_symbol is not None:
            deleted = sum(
                _overlap(
                    old_symbol.start_line, old_symbol.end_line, change.old_start, change.old_count
                )
                for change in changes
            )
        if added == 0 and deleted == 0:
            continue
        signature = _signature(current, symbol)
        old_signature = _signature(old, old_symbol) if old_symbol is not None else None
        signature_changed = old_symbol is None or signature != old_signature
        change_type = "added" if old_symbol is None else "modified"
        output.append(
            _changed_symbol(
                relative,
                symbol,
                change_type,
                added,
                deleted,
                signature,
                signature_changed,
                related_tests,
            )
        )

    for symbol in old_symbols:
        if (symbol.name, symbol.kind) in current_by_identity:
            continue
        deleted = sum(
            _overlap(symbol.start_line, symbol.end_line, change.old_start, change.old_count)
            for change in changes
        )
        if deleted == 0:
            continue
        output.append(
            _changed_symbol(
                relative,
                symbol,
                "deleted",
                0,
                deleted,
                _signature(old, symbol),
                True,
                related_tests,
                deleted_symbol=True,
            )
        )

    unmatched_added = max(
        sum(item.new_count for item in changes) - sum(item.added_lines for item in output), 0
    )
    unmatched_deleted = max(
        sum(item.old_count for item in changes) - sum(item.deleted_lines for item in output), 0
    )
    if unmatched_added or unmatched_deleted:
        output.append(
            ChangedSymbol(
                path=relative,
                name="<module>",
                kind="module",
                change_type=_change_type(bool(old), bool(current)),
                start_line=None,
                end_line=None,
                added_lines=unmatched_added,
                deleted_lines=unmatched_deleted,
                signature=None,
                signature_changed=False,
                risk="medium" if unmatched_deleted else "low",
                related_tests=related_tests,
                confidence="file",
            )
        )
    return output


def _changed_symbol(
    relative: str,
    symbol: SourceSymbol,
    change_type: str,
    added: int,
    deleted: int,
    signature: str | None,
    signature_changed: bool,
    related_tests: list[str],
    *,
    deleted_symbol: bool = False,
) -> ChangedSymbol:
    public = not symbol.name.startswith("_")
    risk = (
        "high"
        if deleted_symbol or (public and signature_changed)
        else "medium"
        if public or added + deleted > 20
        else "low"
    )
    return ChangedSymbol(
        path=relative,
        name=symbol.name,
        kind=symbol.kind,
        change_type=change_type,
        start_line=None if deleted_symbol else symbol.start_line,
        end_line=None if deleted_symbol else symbol.end_line,
        added_lines=added,
        deleted_lines=deleted,
        signature=signature,
        signature_changed=signature_changed,
        risk=risk,
        related_tests=related_tests,
        confidence="ast" if Path(relative).suffix.lower() == ".py" else "structural",
    )


def _extract(source: str | None, suffix: str) -> list[SourceSymbol] | None:
    return None if source is None else extract_source_symbols(source, suffix)


def _read_source(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return None


def _git_source(root: Path, relative: str) -> str | None:
    result = run_command(["git", "show", f"HEAD:{Path(relative).as_posix()}"], root, 30)
    return result.stdout if result.exit_code == 0 else None


def _signature(source: str, symbol: SourceSymbol | None) -> str | None:
    if symbol is None:
        return None
    lines = source.splitlines()
    if not 1 <= symbol.start_line <= len(lines):
        return None
    return mask_text(lines[symbol.start_line - 1].strip())[:300]


def _overlap(symbol_start: int, symbol_end: int, change_start: int, change_count: int) -> int:
    if change_count <= 0:
        return 0
    change_end = change_start + change_count - 1
    return max(min(symbol_end, change_end) - max(symbol_start, change_start) + 1, 0)


def _tests_for_file(root: Path, relative: str, all_tests: list[str]) -> list[str]:
    direct = {_portable_path(item) for item in infer_tests_for_changed_files(root, [relative])}
    return [item for item in all_tests if item in direct]


def _portable_path(value: str) -> str:
    return value.replace("\\", "/")


def _change_type(had_old: bool, has_current: bool) -> str:
    if not had_old:
        return "added"
    if not has_current:
        return "deleted"
    return "modified"
