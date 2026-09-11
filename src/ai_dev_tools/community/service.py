from __future__ import annotations

import contextlib
import os
import threading
from pathlib import Path

from ai_dev_tools.community.builder import build_community_payload
from ai_dev_tools.community.config import (
    CONFIG_FILENAME,
    get_user_config_dir,
    load_community_config,
    save_community_config,
)
from ai_dev_tools.community.queue import (
    clear_queue,
    enqueue_event,
    list_queued_events,
    queue_size,
    remove_event,
)
from ai_dev_tools.community.schema import COMMUNITY_SCHEMA_VERSION
from ai_dev_tools.community.transport import send_event
from ai_dev_tools.models.report import Report


def get_telemetry_status(project_root: Path | None = None) -> Report:
    config = load_community_config()
    count = queue_size()
    level_str = config.telemetry_level.upper()
    endpoint_status = "configured" if config.endpoint else "not configured"

    report = Report(command="telemetry sharing status", project_root=project_root or Path.cwd())
    report.status = "success"
    report.summary = {
        "community_telemetry": level_str,
        "endpoint": endpoint_status,
        "endpoint_url": config.endpoint or None,
        "queued_events": count,
        "schema_version": COMMUNITY_SCHEMA_VERSION,
        "config_file": str(get_user_config_dir() / CONFIG_FILENAME),
    }
    return report


def enable_telemetry(level: str, project_root: Path | None = None) -> Report:
    normalized = level.strip().lower()
    root = project_root or Path.cwd()
    if normalized not in {"basic", "research"}:
        report = Report(command=f"telemetry sharing enable {level}", project_root=root)
        report.status = "failed"
        report.summary = {
            "message": f"Invalid level '{level}'. Must be 'basic' or 'research'.",
            "reason_code": "INVALID_CONFIGURATION",
        }
        return report

    saved = save_community_config(normalized)
    report = Report(command=f"telemetry sharing enable {normalized}", project_root=root)
    report.status = "success"
    level_upper = saved.telemetry_level.upper()
    report.summary = {
        "community_telemetry": level_upper,
        "endpoint": "configured" if saved.endpoint else "not configured",
        "queued_events": queue_size(),
        "message": (
            f"Community telemetry enabled at level '{level_upper}'. "
            "Thank you for helping improve ai-dev!"
        ),
    }
    return report


def disable_telemetry(project_root: Path | None = None) -> Report:
    save_community_config("off")
    deleted_events = clear_queue()

    root = project_root or Path.cwd()
    report = Report(command="telemetry sharing disable", project_root=root)
    report.status = "success"
    report.summary = {
        "community_telemetry": "OFF",
        "queued_events": 0,
        "deleted_events": deleted_events,
        "message": f"Community telemetry disabled. Cleared {deleted_events} queued event(s).",
    }
    return report


def preview_telemetry(
    level: str | None = None,
    project_root: Path | None = None,
    report_to_preview: Report | None = None,
    sample: bool = False,
) -> Report:
    config = load_community_config()
    target_level = level.strip().lower() if level else config.telemetry_level
    if target_level not in {"basic", "research"}:
        # If currently off and no explicit level was specified, default to basic for preview
        target_level = "basic"

    root = project_root or Path.cwd()
    payload = build_community_payload(
        target_level,
        report=report_to_preview,
        project_root=root,
        sample=sample,
    )

    cmd = f"telemetry sharing preview --level {target_level}"
    if sample:
        cmd += " --sample"

    report = Report(command=cmd, project_root=root)
    report.status = "success"
    mode_str = (
        "SAMPLE / EXAMPLE — NOT QUEUED, NOT SENT" if sample else "ACTUAL REPOSITORY PREVIEW"
    )
    report.summary = {
        "telemetry_level": target_level.upper(),
        "mode": mode_str,
        "payload": payload,
    }
    return report


def flush_telemetry(project_root: Path | None = None) -> Report:
    config = load_community_config()
    report = Report(command="telemetry sharing flush", project_root=project_root or Path.cwd())

    if not config.endpoint:
        report.status = "warning"
        report.summary = {
            "message": "No community telemetry endpoint configured. Events remain queued locally.",
            "queued_events": queue_size(),
            "endpoint": "not configured",
        }
        return report

    events = list_queued_events()
    if not events:
        report.status = "success"
        report.summary = {
            "message": "Queue is empty. No events to flush.",
            "delivered": 0,
            "failed": 0,
            "queued_events": 0,
        }
        return report

    delivered = 0
    failed = 0
    last_error = ""

    for path, payload in events:
        result = send_event(config.endpoint, payload)
        if result.success:
            remove_event(path)
            delivered += 1
        else:
            failed += 1
            last_error = result.message
            if not result.retryable:
                # Malformed or permanent client error: drop from queue
                remove_event(path)

    remaining = queue_size()
    if failed == 0:
        report.status = "success"
        report.summary = {
            "message": f"Successfully flushed {delivered} event(s).",
            "delivered": delivered,
            "failed": 0,
            "queued_events": remaining,
        }
    elif delivered > 0:
        report.status = "partial"
        report.summary = {
            "message": f"Delivered {delivered} event(s), {failed} failed.",
            "delivered": delivered,
            "failed": failed,
            "queued_events": remaining,
            "last_error": last_error,
        }
    else:
        report.status = "partial"
        report.summary = {
            "message": f"Failed to flush {failed} event(s) to endpoint.",
            "delivered": 0,
            "failed": failed,
            "queued_events": remaining,
            "last_error": last_error,
        }

    return report


_autoflush_thread: threading.Thread | None = None


def _opportunistic_flush(endpoint: str) -> None:
    try:
        events = list_queued_events()
        for path, payload in events[:5]:  # Send at most 5 events opportunistically per command
            result = send_event(endpoint, payload, timeout=2.0, retries=1)
            if result.success or not result.retryable:
                remove_event(path)
    except Exception:
        pass


def start_background_autoflush() -> threading.Thread | None:
    global _autoflush_thread
    try:
        if os.environ.get("AI_DEV_COMMUNITY_TELEMETRY_NO_AUTO_FLUSH"):
            return None
        config = load_community_config()
        if not config.is_enabled or not config.endpoint:
            return None
        if queue_size() == 0:
            return None

        thread = threading.Thread(
            target=_opportunistic_flush,
            args=(config.endpoint,),
            daemon=True,
            name="ai-dev-community-autoflush",
        )
        thread.start()
        _autoflush_thread = thread
        return thread
    except Exception:
        return None


def wait_for_autoflush(timeout: float = 0.05) -> None:
    global _autoflush_thread
    if _autoflush_thread is not None and _autoflush_thread.is_alive():
        with contextlib.suppress(Exception):
            _autoflush_thread.join(timeout=timeout)


def record_command_event(
    report: Report,
    duration_seconds: float,
    project_root: Path | None = None,
) -> None:
    try:
        # Avoid recording recursive community sharing commands
        if report.command.startswith("telemetry sharing"):
            return

        config = load_community_config()
        if not config.is_enabled:
            return

        payload = build_community_payload(
            config.telemetry_level,
            report=report,
            duration_seconds=duration_seconds,
            project_root=project_root or report.project_root,
        )

        enqueue_event(payload)
    except Exception:
        # Guarantee: community telemetry failure NEVER breaks user commands
        pass


def record_provider_usage_event(
    *,
    client: str,
    model: str = "",
    task_kind: str = "",
    input_tokens: int = 0,
    cached_input_tokens: int = 0,
    output_tokens: int = 0,
    reasoning_tokens: int = 0,
    quality_passed: bool | None = None,
    duration_seconds: float | None = None,
    command_name: str = "mcp",
) -> None:
    try:
        config = load_community_config()
        if config.telemetry_level != "research":
            return

        from ai_dev_tools.community.builder import build_provider_usage_payload

        payload = build_provider_usage_payload(
            client=client,
            model=model,
            task_kind=task_kind,
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_tokens,
            output_tokens=output_tokens,
            reasoning_tokens=reasoning_tokens,
            quality_passed=quality_passed,
            duration_seconds=duration_seconds,
            command_name=command_name,
        )
        enqueue_event(payload)
    except Exception:
        pass
