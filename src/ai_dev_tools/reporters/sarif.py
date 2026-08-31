from __future__ import annotations

import json
from pathlib import Path

from ai_dev_tools.models.report import Artifact, Report
from ai_dev_tools.security.secrets import mask_text


def run_sarif_export(project_root: Path, input_path: Path, output_path: Path | None) -> Report:
    root = project_root.resolve()
    report = Report(command="sarif", project_root=root)
    try:
        source = _inside(root, input_path)
        output = _inside(root, output_path or Path(".ai/reports/ai-dev.sarif"))
        if source.stat().st_size > 10_000_000:
            raise ValueError("Input report exceeds 10 MB")
        payload = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Input report must be a JSON object")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report.status = "invalid_configuration"
        report.summary = {"reason_code": "INVALID_SARIF_INPUT", "message": str(exc)}
        return report
    issues = payload.get("issues", [])
    rows = [item for item in issues if isinstance(item, dict)] if isinstance(issues, list) else []
    rules = _rules(rows)
    results = [_result(item) for item in rows[:5_000]]
    sarif = {
        "version": "2.1.0",
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "ai-dev-cli-tools",
                        "informationUri": "https://github.com/MatthiasLew/ai-dev-cli-tools",
                        "rules": rules,
                    }
                },
                "results": results,
            }
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(mask_text(json.dumps(sarif, indent=2) + "\n"), encoding="utf-8")
    report.summary = {
        "source": str(source),
        "output": str(output),
        "issues": len(rows),
        "results": len(results),
        "truncated": len(rows) > 5_000,
    }
    report.artifacts.append(Artifact(str(output), "sarif", "GitHub code scanning results"))
    return report


def _rules(issues: list[dict[str, object]]) -> list[dict[str, object]]:
    unique: dict[str, dict[str, object]] = {}
    for issue in issues:
        code = str(issue.get("code") or "AI_DEV_ISSUE")
        unique[code] = {
            "id": code,
            "name": code,
            "shortDescription": {"text": code.replace("_", " ").title()},
        }
    return [unique[key] for key in sorted(unique)]


def _result(issue: dict[str, object]) -> dict[str, object]:
    code = str(issue.get("code") or "AI_DEV_ISSUE")
    severity = str(issue.get("severity") or "warning")
    result: dict[str, object] = {
        "ruleId": code,
        "level": {"critical": "error", "error": "error", "warning": "warning"}.get(
            severity, "note"
        ),
        "message": {"text": str(issue.get("message") or code)},
    }
    file = issue.get("file") or issue.get("location")
    if isinstance(file, str) and file:
        region: dict[str, int] = {}
        line = issue.get("line")
        column = issue.get("column")
        if isinstance(line, int) and not isinstance(line, bool):
            region["startLine"] = max(1, line)
        if isinstance(column, int) and not isinstance(column, bool):
            region["startColumn"] = max(1, column)
        location: dict[str, object] = {"artifactLocation": {"uri": file.replace("\\", "/")}}
        if region:
            location["region"] = region
        result["locations"] = [{"physicalLocation": location}]
    return result


def _inside(root: Path, path: Path) -> Path:
    resolved = (path if path.is_absolute() else root / path).resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError("SARIF paths must stay inside the project")
    return resolved
