from pathlib import Path

from ai_dev_tools.security.secrets import scan_paths_for_secrets


def test_secret_scanner_masks_values(tmp_path: Path) -> None:
    path = tmp_path / "config.txt"
    path.write_text("OPENAI_API_KEY=sk-1234567890abcdef1234567890\n", encoding="utf-8")
    findings = scan_paths_for_secrets(tmp_path, [path])
    assert findings
    masked = findings[0].masked_dict()["masked_value"]
    assert "1234567890abcdef" not in str(masked)
    assert "..." in str(masked)
