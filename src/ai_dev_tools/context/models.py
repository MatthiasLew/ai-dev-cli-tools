from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from ai_dev_tools.context.symbols import SymbolSnippet

ContextFormat = Literal["markdown", "json", "both"]
RetrievalMode = Literal["auto", "always", "never"]

DEFAULT_MAX_CHARS = 50_000
DEFAULT_MAX_FILES = 30
DEFAULT_MAX_FILE_CHARS = 8_000
DEFAULT_MAX_DIFF_CHARS = 15_000


@dataclass(frozen=True, slots=True)
class ContextOptions:
    task: str = ""
    max_chars: int = DEFAULT_MAX_CHARS
    max_files: int = DEFAULT_MAX_FILES
    max_file_chars: int = DEFAULT_MAX_FILE_CHARS
    max_diff_chars: int = DEFAULT_MAX_DIFF_CHARS
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    changed_only: bool = False
    staged_only: bool = False
    no_git: bool = False
    output: Path | None = None
    format: ContextFormat = "both"
    explain: bool = False
    incremental: bool = False
    profile: str = "default"
    retrieval: RetrievalMode = "auto"
    tokenizer: str = "estimate"
    token_budgets: tuple[str, ...] = ()
    provider_usage: Path | None = None


@dataclass(slots=True)
class SelectedFile:
    path: str
    reason: str
    reason_code: str
    chars: int
    truncated: bool
    content: str
    selection_strategy: str = "file-prefix"
    omitted_content: bool = False
    snippets: list[SymbolSnippet] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class RejectedFile:
    path: str
    reason: str
    reason_code: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
