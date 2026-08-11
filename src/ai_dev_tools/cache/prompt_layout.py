from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from ai_dev_tools import __version__
from ai_dev_tools.cache.repository import update_repository_index

CACHE_LAYOUT_SCHEMA_VERSION = "1"
CACHE_LAYOUT_PATH = Path(".ai/cache/cache-layout.json")
_STABLE_SECTIONS = ("protocol", "project_identity", "repository_facts")
_VOLATILE_SECTIONS = ("git_state", "task", "current_observation", "model_response")
_PROJECT_FILES = {
    ".ai-dev-tools.toml",
    "cargo.toml",
    "composer.json",
    "package.json",
    "pom.xml",
    "pyproject.toml",
    "settings.gradle",
    "settings.gradle.kts",
}


def write_cache_layout_manifest(root: Path) -> tuple[dict[str, Any], Path]:
    resolved = root.resolve()
    index = update_repository_index(resolved)
    entries = _entries(index.get("entries"))
    stable_payload = {
        "protocol": {
            "agent_protocol_version": "1",
            "report_schema_version": "1.1",
            "tool_version": __version__,
            "transport": ["cli-json", "mcp-stdio"],
        },
        "project_identity": {
            "configuration_files": [
                {"path": item["path"], "sha256": item["sha256"]}
                for item in entries
                if Path(item["path"]).name.lower() in _PROJECT_FILES
            ],
        },
        "repository_facts": {
            "content_fingerprint": _fingerprint(entries),
            "file_count": len(entries),
            "path_order": "project-relative-lexicographic",
        },
    }
    section_fingerprints = {name: _fingerprint(stable_payload[name]) for name in _STABLE_SECTIONS}
    encoded_prefix = _canonical(stable_payload)
    prefix_fingerprint = _fingerprint(stable_payload)
    manifest: dict[str, Any] = {
        "schema_version": CACHE_LAYOUT_SCHEMA_VERSION,
        "section_order": [*_STABLE_SECTIONS, *_VOLATILE_SECTIONS],
        "stable_prefix": {
            "sections": list(_STABLE_SECTIONS),
            "fingerprint": prefix_fingerprint,
            "chars": len(encoded_prefix),
            "section_fingerprints": section_fingerprints,
            "payload": stable_payload,
        },
        "volatile_suffix": {
            "sections": list(_VOLATILE_SECTIONS),
            "excluded_from_prefix_fingerprint": True,
        },
        "provider_breakpoints": [
            {
                "provider": "openai",
                "after_section": "repository_facts",
                "prefix_fingerprint": prefix_fingerprint,
                "reason_code": "EXACT_STABLE_PREFIX_BOUNDARY",
            },
            {
                "provider": "anthropic",
                "after_section": "repository_facts",
                "prefix_fingerprint": prefix_fingerprint,
                "reason_code": "EXPLICIT_CACHE_CONTROL_BOUNDARY",
            },
            {
                "provider": "provider-neutral",
                "after_section": "repository_facts",
                "prefix_fingerprint": prefix_fingerprint,
                "reason_code": "STABLE_BEFORE_VOLATILE",
            },
        ],
        "invariants": {
            "absolute_paths": False,
            "timestamps": False,
            "random_ids": False,
            "ordering": "deterministic",
            "volatile_content_after_breakpoint": True,
        },
    }
    path = resolved / CACHE_LAYOUT_PATH
    _atomic_write(path, manifest)
    return manifest, path


def read_cache_layout_manifest(root: Path) -> dict[str, Any]:
    try:
        value = json.loads((root.resolve() / CACHE_LAYOUT_PATH).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(value, dict) or value.get("schema_version") != CACHE_LAYOUT_SCHEMA_VERSION:
        return {}
    return value


def _entries(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return sorted(
        [
            {"path": str(item["path"]), "sha256": str(item["sha256"])}
            for item in value
            if isinstance(item, dict)
            and isinstance(item.get("path"), str)
            and isinstance(item.get("sha256"), str)
        ],
        key=lambda item: item["path"],
    )


def _fingerprint(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
