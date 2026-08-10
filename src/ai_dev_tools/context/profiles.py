from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ContextProfile:
    name: str
    max_chars: int
    max_files: int
    max_file_chars: int
    max_diff_chars: int
    changed_only: bool = False
    description: str = ""


PROFILES: dict[str, ContextProfile] = {
    "minimal": ContextProfile(
        "minimal", 12_000, 8, 2_500, 4_000, description="Smallest useful agent handoff"
    ),
    "debug": ContextProfile(
        "debug", 60_000, 35, 10_000, 20_000, description="Failures, diffs, and nearby code"
    ),
    "review": ContextProfile(
        "review",
        40_000,
        25,
        6_000,
        20_000,
        changed_only=True,
        description="Changed files and review evidence",
    ),
    "full": ContextProfile(
        "full", 150_000, 100, 20_000, 50_000, description="Broad repository context"
    ),
}


def get_context_profile(name: str) -> ContextProfile | None:
    if name == "default":
        return None
    try:
        return PROFILES[name]
    except KeyError as exc:
        raise ValueError(f"Unknown context profile: {name}") from exc


def profile_names() -> tuple[str, ...]:
    return tuple(PROFILES)
