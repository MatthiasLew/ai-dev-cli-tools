from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

VALID_LEVELS = {"off", "basic", "research"}
DEFAULT_LEVEL = "off"
DEFAULT_COMMUNITY_ENDPOINT = ""
DEFAULT_ENDPOINT = DEFAULT_COMMUNITY_ENDPOINT  # Backward-compatible alias
CONFIG_FILENAME = "community_telemetry.json"


@dataclass(slots=True, frozen=True)
class CommunityTelemetryConfig:
    telemetry_level: str = DEFAULT_LEVEL
    endpoint_override: str | None = None
    default_endpoint: str = DEFAULT_COMMUNITY_ENDPOINT

    @property
    def endpoint(self) -> str:
        # Precedence:
        # 1. Environment variable override
        # 2. User explicit override (non-empty)
        # 3. Package default endpoint
        env = os.environ.get("AI_DEV_COMMUNITY_TELEMETRY_ENDPOINT")
        if env is not None and env.strip():
            return env.strip()
        if self.endpoint_override and self.endpoint_override.strip():
            return self.endpoint_override.strip()
        return self.default_endpoint or ""

    @property
    def is_enabled(self) -> bool:
        return self.telemetry_level in {"basic", "research"}


def get_user_config_dir() -> Path:
    override = os.environ.get("AI_DEV_COMMUNITY_TELEMETRY_CONFIG_DIR")
    if override:
        return Path(override).resolve()

    platform = sys.platform
    if platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
        return (base / "ai-dev").resolve()
    elif platform == "darwin":
        return (Path.home() / "Library" / "Application Support" / "ai-dev").resolve()
    else:
        # Linux and other Unix-like systems (XDG)
        xdg_config = os.environ.get("XDG_CONFIG_HOME")
        base = Path(xdg_config) if xdg_config else Path.home() / ".config"
        return (base / "ai-dev").resolve()


def get_user_data_dir() -> Path:
    override = os.environ.get("AI_DEV_COMMUNITY_TELEMETRY_DATA_DIR")
    if override:
        return Path(override).resolve()

    platform = sys.platform
    if platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
        return (base / "ai-dev" / "community-telemetry").resolve()
    elif platform == "darwin":
        return (
            Path.home() / "Library" / "Application Support" / "ai-dev" / "community-telemetry"
        ).resolve()
    else:
        # Linux and other Unix-like systems (XDG)
        xdg_data = os.environ.get("XDG_DATA_HOME")
        base = Path(xdg_data) if xdg_data else Path.home() / ".local" / "share"
        return (base / "ai-dev" / "community-telemetry").resolve()


def load_community_config(
    default_endpoint: str = DEFAULT_COMMUNITY_ENDPOINT,
) -> CommunityTelemetryConfig:
    config_path = get_user_config_dir() / CONFIG_FILENAME
    level = DEFAULT_LEVEL
    endpoint_override: str | None = None

    if config_path.is_file():
        try:
            raw = config_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, dict):
                raw_level = str(data.get("telemetry_level", "")).strip().lower()
                if raw_level in VALID_LEVELS:
                    level = raw_level

                if "endpoint_override" in data:
                    raw_override = data.get("endpoint_override")
                    if isinstance(raw_override, str) and raw_override.strip():
                        endpoint_override = raw_override.strip()
                elif "endpoint" in data:
                    raw_legacy = data.get("endpoint")
                    # Migration rule: empty string in legacy config was just the old empty default,
                    # so treat it as None (do not let it override future package defaults)!
                    if isinstance(raw_legacy, str) and raw_legacy.strip():
                        endpoint_override = raw_legacy.strip()
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            level = DEFAULT_LEVEL

    return CommunityTelemetryConfig(
        telemetry_level=level,
        endpoint_override=endpoint_override,
        default_endpoint=default_endpoint,
    )


def save_community_config(
    level: str,
    endpoint: str | None = None,
    *,
    endpoint_override: str | None = None,
) -> CommunityTelemetryConfig:
    normalized_level = level.strip().lower()
    if normalized_level not in VALID_LEVELS:
        valid_str = sorted(VALID_LEVELS)
        raise ValueError(f"Invalid telemetry level '{level}'. Must be one of: {valid_str}")

    config_dir = get_user_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / CONFIG_FILENAME

    effective_override = endpoint_override if endpoint_override is not None else endpoint
    current = load_community_config()
    final_override = (
        current.endpoint_override
        if effective_override is None
        else (effective_override.strip() or None)
    )

    payload: dict[str, Any] = {
        "telemetry_level": normalized_level,
    }
    if final_override:
        payload["endpoint_override"] = final_override

    # Write atomically
    temp_path = config_path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(config_path)

    return CommunityTelemetryConfig(
        telemetry_level=normalized_level, endpoint_override=final_override
    )
