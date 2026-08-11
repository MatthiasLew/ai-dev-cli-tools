from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ai_dev_tools.context.selection import _dependency_files, _rel


def refine_candidates(
    root: Path,
    candidates: dict[Path, str],
    candidate_pool: dict[Path, str],
    signals: list[object],
    max_rounds: int,
    max_added_files: int,
) -> tuple[dict[Path, str], dict[str, Any]]:
    signal_text = json.dumps(signals, sort_keys=True, default=str).lower()
    terms = {
        token for token in re.findall(r"[a-zA-Z_][a-zA-Z0-9_.\-/]+", signal_text) if len(token) >= 3
    }
    report_rounds: list[dict[str, object]] = []
    added: list[str] = []
    frontier = set(candidates)
    stop_reason = "NO_REFINEMENT_SIGNAL"
    if not terms or max_rounds <= 0 or max_added_files <= 0:
        return candidates, _report(
            max_rounds, max_added_files, signals, report_rounds, added, stop_reason
        )

    for round_number in range(1, min(max_rounds, 3) + 1):
        discovered = _dependency_files(
            root, {path: candidates.get(path, "seed") for path in frontier}
        )
        matches = {
            path: "hierarchical retrieval refinement"
            for path in candidate_pool
            if path not in candidates and _matches(root, path, terms)
        }
        for path in discovered:
            if path not in candidates:
                matches[path] = "hierarchical retrieval refinement"
        remaining = max_added_files - len(added)
        chosen = sorted(matches, key=lambda path: _match_priority(root, path, terms))[:remaining]
        round_paths = [_rel(root, path) for path in chosen]
        report_rounds.append(
            {
                "round": round_number,
                "added_files": round_paths,
                "reason_code": "FAILURE_SYMBOL_OR_EVIDENCE_REFINEMENT",
            }
        )
        if not chosen:
            stop_reason = "NO_NEW_HIGH_CONFIDENCE_EVIDENCE"
            break
        for path in chosen:
            candidates[path] = matches[path]
        added.extend(round_paths)
        frontier = set(chosen)
        if len(added) >= max_added_files:
            stop_reason = "REFINEMENT_FILE_BUDGET_REACHED"
            break
    else:
        stop_reason = "REFINEMENT_ROUND_BUDGET_REACHED"
    return candidates, _report(
        max_rounds, max_added_files, signals, report_rounds, added, stop_reason
    )


def _match_priority(root: Path, path: Path, terms: set[str]) -> tuple[int, str]:
    relative = _rel(root, path).lower()
    exact = any(term == relative or term.endswith("/" + relative) for term in terms)
    return (0 if exact else 1, relative)


def _matches(root: Path, path: Path, terms: set[str]) -> bool:
    relative = _rel(root, path).lower()
    stem = path.stem.lower()
    return any(
        term == relative or term.endswith("/" + relative) or (len(stem) >= 3 and stem in term)
        for term in terms
    )


def _report(
    max_rounds: int,
    max_added_files: int,
    signals: list[object],
    rounds: list[dict[str, object]],
    added: list[str],
    stop_reason: str,
) -> dict[str, Any]:
    return {
        "enabled": max_rounds > 0,
        "max_rounds": min(max_rounds, 3),
        "max_added_files": max_added_files,
        "signal_count": len(signals),
        "rounds": rounds,
        "added_files": added,
        "added_count": len(added),
        "stop_reason": stop_reason,
        "reason_code": "BOUNDED_HIERARCHICAL_RETRIEVAL",
    }
