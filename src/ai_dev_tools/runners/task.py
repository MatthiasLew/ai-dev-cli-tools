from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ai_dev_tools.context import ContextOptions, build_context
from ai_dev_tools.context.mcp_delta import context_state_fingerprint
from ai_dev_tools.models.report import Artifact, Report
from ai_dev_tools.reporters.progressive import add_progressive_metadata
from ai_dev_tools.reporters.writer import write_json, write_markdown
from ai_dev_tools.runners.plan import run_agent_plan
from ai_dev_tools.token_efficiency import (
    client_profile,
    compact_context,
    load_acknowledged_state,
    persist_acknowledged_state,
    record_receipt,
)


@dataclass(frozen=True, slots=True)
class TaskOptions:
    task: str
    mode: str = "changed"
    profile: str = "minimal"
    client: str = "generic"
    acknowledged_state: str | None = None
    persist_ack: bool = True
    include_content: bool = False


def run_prepare_task(project_root: Path, options: TaskOptions) -> Report:
    root = project_root.resolve()
    report = Report(command="task", project_root=root)
    if not options.task.strip():
        report.status = "invalid_configuration"
        report.summary = {
            "reason_code": "TASK_REQUIRED",
            "message": "Provide a non-empty task description.",
        }
        return report.finish()

    profile = client_profile(options.client)
    plan = run_agent_plan(root, task=options.task, mode=options.mode)
    context = build_context(
        root,
        ContextOptions(
            task=options.task,
            profile=options.profile,
            max_chars=_integer(profile.get("max_chars"), 20_000),
            max_files=_integer(profile.get("max_files"), 20),
            max_file_chars=_integer(profile.get("max_file_chars"), 4_000),
            format="json",
            incremental=True,
            adaptive=True,
            tokenizer=str(profile["tokenizer"]),
        ),
    )
    annotated = add_progressive_metadata({"summary": context.summary})
    annotated_summary = annotated.get("summary")
    source_summary = annotated_summary if isinstance(annotated_summary, dict) else context.summary
    compact, delivery_receipt = compact_context(
        source_summary, include_content=options.include_content
    )

    fingerprint_arguments: dict[str, object] = {
        "task": options.task,
        "mode": options.mode,
        "profile": options.profile,
        "client": options.client,
        "include_content": options.include_content,
    }
    current_state = context_state_fingerprint(root, fingerprint_arguments)
    acknowledged = options.acknowledged_state or load_acknowledged_state(root, options.client)
    if options.acknowledged_state and options.persist_ack:
        state_path = persist_acknowledged_state(root, options.client, options.acknowledged_state)
        report.artifacts.append(
            Artifact(str(state_path), "client-state", "Explicitly acknowledged AI client state")
        )

    eligible = context.status == "success" and not context.issues
    reused = bool(eligible and acknowledged == current_state)
    if reused:
        compact = {
            "context_receipt": {
                "unchanged": True,
                "reason_code": "UNCHANGED_CONTEXT_REUSED",
                "selected_file_count": delivery_receipt["included_files"],
            }
        }
    delta_tokens = (
        _integer(delivery_receipt.get("estimated_tokens_avoided"))
        if not options.include_content
        else 0
    )
    accounting = context.summary.get("token_accounting", {})
    accounting_dict = accounting if isinstance(accounting, dict) else {}
    base_receipt = accounting_dict.get("savings_receipt", {})
    base_receipt_dict = base_receipt if isinstance(base_receipt, dict) else {}
    budget_saved = _integer(base_receipt_dict.get("saved_tokens"))
    character_budget = source_summary.get("character_budget", {})
    character_budget_dict = character_budget if isinstance(character_budget, dict) else {}
    character_saved = _tokens_for_chars(character_budget_dict.get("chars_avoided"))
    reference_saved = delta_tokens
    delivered_tokens = _tokens_for_chars(delivery_receipt.get("delivered_context_chars"))
    total_saved = budget_saved + character_saved + reference_saved
    original_tokens = delivered_tokens + total_saved
    token_receipt = {
        **base_receipt_dict,
        "client": options.client,
        "delivery": delivery_receipt,
        "saved_tokens": total_saved,
        "saved_percent": (
            round(total_saved / original_tokens * 100, 2) if original_tokens else 0.0
        ),
        "original_input_tokens": original_tokens,
        "input_tokens": delivered_tokens,
        "budget_saved_tokens": budget_saved,
        "character_budget_saved_tokens": character_saved,
        "reference_delivery_saved_tokens": reference_saved,
        "reused_state": reused,
    }
    receipt_path = record_receipt(root, token_receipt, command="task", client=options.client)
    report.artifacts.append(
        Artifact(str(receipt_path), "token-efficiency", "Latest token savings receipt")
    )

    report.status = (
        "partial" if context.status == "partial" or plan.status == "partial" else "success"
    )
    if context.status not in {"success", "partial"} or plan.status not in {"success", "partial"}:
        report.status = "failed"
    report.issues.extend(plan.issues)
    report.issues.extend(context.issues)
    report.summary = {
        "task": options.task,
        "client": options.client,
        "client_profile": profile,
        "decision": plan.summary.get("decision", {}),
        "plan": {
            "scope": plan.summary.get("scope", {}),
            "next_actions": plan.summary.get("next_actions", []),
            "validation": plan.summary.get("validation", {}),
            "evidence": plan.summary.get("evidence", []),
        },
        "context": compact,
        "state": {
            "fingerprint": current_state,
            "acknowledged_fingerprint": acknowledged,
            "acknowledgement_source": (
                "request"
                if options.acknowledged_state
                else "persisted"
                if acknowledged
                else "none"
            ),
            "reused": reused,
            "next_action": "Acknowledge this fingerprint only after consuming this response.",
        },
        "token_savings": token_receipt,
        "constraints": {
            "checks_preview_only": True,
            "commands_executed": False,
            "content_default": "full" if options.include_content else "references",
            "full_content_opt_in": True,
        },
    }
    report.finish()
    output = root / ".ai" / "reports" / "task-latest"
    write_json(report, output.with_suffix(".json"))
    write_markdown(report, output.with_suffix(".md"))
    return report


def _integer(value: object, default: int = 0) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _tokens_for_chars(value: object) -> int:
    chars = _integer(value)
    return (chars + 3) // 4
