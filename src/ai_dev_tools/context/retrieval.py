from __future__ import annotations

import fnmatch
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from ai_dev_tools.context.models import ContextOptions

_BROAD_TASK_TERMS = re.compile(
    r"\b(?:architecture|across|all files|codebase|dependency|dependencies|integration|"
    r"monorepo|repository|refactor|workflow|whole project)\b",
    re.IGNORECASE,
)
_BROAD_CONFIG_NAMES = {
    ".ai-dev-tools.toml",
    "cargo.toml",
    "composer.json",
    "package.json",
    "pyproject.toml",
    "settings.gradle",
    "settings.gradle.kts",
}


@dataclass(frozen=True, slots=True)
class RetrievalDecision:
    mode_requested: str
    decision: str
    confidence: str
    reason_code: str
    signals: tuple[str, ...]
    focused_roots: tuple[str, ...]
    candidates_before: int
    candidates_after: int
    omitted_candidates: tuple[str, ...]
    omitted_candidate_count: int
    conservative_fallback_used: bool
    expected_related_tests: tuple[str, ...]
    selected_related_tests: tuple[str, ...]
    missed_related_tests: tuple[str, ...]
    false_negative_proxy: bool
    expansion_command: str = "ai-dev context build --retrieval always"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def apply_retrieval_gate(
    root: Path,
    options: ContextOptions,
    candidates: dict[Path, str],
    changed_files: list[str],
    related_tests: list[str],
) -> tuple[dict[Path, str], RetrievalDecision]:
    if options.retrieval not in {"auto", "always", "never"}:
        raise ValueError(f"unknown retrieval mode: {options.retrieval}")

    normalized = {_rel(root, path): path for path in candidates}
    explicit = _matching_paths(normalized, options.include)
    changed = {item for item in changed_files if item in normalized}
    expected_tests = {item for item in related_tests if item in normalized}
    expected_tests.update(_infer_related_tests(normalized, candidates, explicit | changed))
    focused = explicit | changed | expected_tests
    signals = _signals(options, explicit, changed, expected_tests)
    fallback = False

    if options.retrieval == "always":
        kept = dict(candidates)
        decision = "retrieve"
        reason_code = "RETRIEVAL_FORCED"
        confidence = "high"
    elif options.retrieval == "never":
        kept = _focused_candidates(normalized, candidates, focused)
        decision = "abstain"
        reason_code = "RETRIEVAL_DISABLED"
        confidence = "high"
    elif not focused:
        kept = dict(candidates)
        decision = "retrieve"
        reason_code = "NO_FOCUS_CONSERVATIVE_FALLBACK"
        confidence = "low"
        fallback = True
    elif any(_is_broad_config(item) for item in changed):
        kept = dict(candidates)
        decision = "retrieve"
        reason_code = "BROAD_CONFIGURATION_CHANGE"
        confidence = "high"
    elif _BROAD_TASK_TERMS.search(options.task):
        kept = dict(candidates)
        decision = "retrieve"
        reason_code = "BROAD_TASK_SCOPE"
        confidence = "medium"
    else:
        kept = _focused_candidates(normalized, candidates, focused)
        decision = "abstain"
        reason_code = "FOCUSED_ROOTS_SUFFICIENT"
        confidence = "high" if explicit else "medium"

    selected_tests = expected_tests & {_rel(root, path) for path in kept}
    missed_tests = expected_tests - selected_tests
    if options.retrieval == "auto" and missed_tests:
        kept = dict(candidates)
        selected_tests = set(expected_tests)
        missed_tests.clear()
        decision = "retrieve"
        reason_code = "RELATED_TEST_CONSERVATIVE_FALLBACK"
        confidence = "low"
        fallback = True

    kept_paths = {_rel(root, path) for path in kept}
    omitted = sorted(set(normalized) - kept_paths)
    report = RetrievalDecision(
        mode_requested=options.retrieval,
        decision=decision,
        confidence=confidence,
        reason_code=reason_code,
        signals=tuple(signals),
        focused_roots=tuple(sorted(focused)),
        candidates_before=len(candidates),
        candidates_after=len(kept),
        omitted_candidates=tuple(omitted[:100]),
        omitted_candidate_count=len(omitted),
        conservative_fallback_used=fallback,
        expected_related_tests=tuple(sorted(expected_tests)),
        selected_related_tests=tuple(sorted(selected_tests)),
        missed_related_tests=tuple(sorted(missed_tests)),
        false_negative_proxy=bool(missed_tests),
    )
    return kept, report


def _focused_candidates(
    normalized: dict[str, Path], candidates: dict[Path, str], focused: set[str]
) -> dict[Path, str]:
    return {normalized[rel]: candidates[normalized[rel]] for rel in sorted(focused)}


def _matching_paths(normalized: dict[str, Path], patterns: tuple[str, ...]) -> set[str]:
    return {
        rel
        for rel in normalized
        if any(fnmatch.fnmatch(rel, pattern.replace("\\", "/")) for pattern in patterns)
    }


def _infer_related_tests(
    normalized: dict[str, Path], candidates: dict[Path, str], roots: set[str]
) -> set[str]:
    stems = {Path(item).stem.removeprefix("test_").removesuffix("_test") for item in roots}
    stems.discard("")
    return {
        rel
        for rel, path in normalized.items()
        if "test" in candidates[path].lower() and any(stem in Path(rel).stem for stem in stems)
    }


def _signals(
    options: ContextOptions,
    explicit: set[str],
    changed: set[str],
    expected_tests: set[str],
) -> list[str]:
    signals: list[str] = []
    if explicit:
        signals.append(f"explicit_include:{len(explicit)}")
    if changed:
        signals.append(f"changed_files:{len(changed)}")
    if expected_tests:
        signals.append(f"related_tests:{len(expected_tests)}")
    if any(_is_broad_config(item) for item in changed):
        signals.append("broad_configuration_change")
    if _BROAD_TASK_TERMS.search(options.task):
        signals.append("broad_task_scope")
    if not signals:
        signals.append("no_focused_signal")
    return signals


def _is_broad_config(rel: str) -> bool:
    normalized = rel.replace("\\", "/").lower()
    return Path(normalized).name in _BROAD_CONFIG_NAMES or normalized.startswith(
        ".github/workflows/"
    )


def _rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()
