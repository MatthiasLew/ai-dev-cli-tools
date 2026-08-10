from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("github_token", re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}")),
    ("openai_key", re.compile(r"sk-[A-Za-z0-9_-]{20,}")),
    ("openrouter_key", re.compile(r"sk-or-[A-Za-z0-9_-]{20,}")),
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("connection_string", re.compile(r"(?i)(postgres|mysql|mongodb|redis)://[^\s]+")),
    ("password_assignment", re.compile(r"(?i)(password|passwd|pwd)\s*=\s*['\"]?[^'\"\s]{8,}")),
    ("api_key_assignment", re.compile(r"(?i)(api[_-]?key|token|secret)\s*=\s*['\"]?[^'\"\s]{12,}")),
)


@dataclass(slots=True)
class SecretFinding:
    path: str
    line: int
    kind: str
    value: str

    def masked_value(self) -> str:
        return "***" if len(self.value) <= 8 else f"{self.value[:4]}...{self.value[-4:]}"

    def masked_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "line": self.line,
            "kind": self.kind,
            "masked_value": self.masked_value(),
        }


def scan_paths_for_secrets(root: Path, paths: list[Path]) -> list[SecretFinding]:
    findings: list[SecretFinding] = []
    for path in paths:
        if not path.exists() or not path.is_file() or path.stat().st_size > 1_000_000:
            continue
        rel = str(path.relative_to(root))
        if path.name == ".env":
            findings.append(SecretFinding(rel, 1, "env_file", ".env"))
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_number, line in enumerate(text.splitlines(), start=1):
            for kind, pattern in SECRET_PATTERNS:
                for match in pattern.finditer(line):
                    findings.append(SecretFinding(rel, line_number, kind, match.group(0)))
    return findings


def mask_text(text: str) -> str:
    masked = text
    for kind, pattern in SECRET_PATTERNS:
        masked = pattern.sub(f"***MASKED_{kind.upper()}***", masked)
    return masked
