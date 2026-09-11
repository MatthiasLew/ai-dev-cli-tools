from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

VALID_LEVELS = {"off", "basic", "research"}
DEFAULT_LEVEL = "off"
DEFAULT_ENDPOINT = ""
CONFIG_FILENAME = "community_telemetry.json"


@dataclass(slots=True, frozen=True)
class CommunityTelemetryConfig:
    telemetry_level: str = DEFAULT_LEVEL
    endpoint: str = DEFAULT_ENDPOINT

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


def load_community_config() -> CommunityTelemetryConfig:
    config_path = get_user_config_dir() / CONFIG_FILENAME
    level = DEFAULT_LEVEL
    endpoint = DEFAULT_ENDPOINT

    if config_path.is_file():
        try:
            raw = config_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, dict):
                raw_level = str(data.get("telemetry_level", "")).strip().lower()
                if raw_level in VALID_LEVELS:
                    level = raw_level
                raw_endpoint = data.get("endpoint")
                if isinstance(raw_endpoint, str):
                    endpoint = raw_endpoint.strip()
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            # Safe fallback if file is corrupted or unreadable
            level = DEFAULT_LEVEL

    # Environment variable override takes precedence for endpoint
    env_endpoint = os.environ.get("AI_DEV_COMMUNITY_TELEMETRY_ENDPOINT")
    if env_endpoint is not None:
        endpoint = env_endpoint.strip()

    return CommunityTelemetryConfig(telemetry_level=level, endpoint=endpoint)


def save_community_config(level: str, endpoint: str | None = None) -> CommunityTelemetryConfig:
    normalized_level = level.strip().lower()
    if normalized_level not in VALID_LEVELS:
        valid_str = sorted(VALID_LEVELS)
        raise ValueError(f"Invalid telemetry level '{level}'. Must be one of: {valid_str}")

    config_dir = get_user_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / CONFIG_FILENAME

    current = load_community_config()
    final_endpoint = current.endpoint if endpoint is None else endpoint.strip()

    payload = {
        "telemetry_level": normalized_level,
        "endpoint": final_endpoint,
    }

    # Write atomically
    temp_path = config_path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(config_path)

    return CommunityTelemetryConfig(telemetry_level=normalized_level, endpoint=final_endpoint)
