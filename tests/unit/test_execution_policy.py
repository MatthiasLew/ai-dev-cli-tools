from pathlib import Path

from ai_dev_tools.runners.policy import run_policy_assess
from ai_dev_tools.security.execution import ExecutionPolicy, assess_command


def test_enforced_policy_blocks_destructive_and_non_allowlisted_commands(tmp_path: Path) -> None:
    policy = ExecutionPolicy(mode="enforce", allow_prefixes=("python -m pytest",))
    allowed = assess_command(["python", "-m", "pytest", "tests"], tmp_path, policy)
    blocked = assess_command(["git", "reset", "--hard"], tmp_path, policy)

    assert allowed.allowed is True
    assert blocked.allowed is False
    assert blocked.impact == "critical"


def test_policy_cli_contract_uses_project_configuration(tmp_path: Path) -> None:
    (tmp_path / ".ai-dev-tools.toml").write_text(
        '[execution]\nmode="enforce"\nmaximum_impact="medium"\n'
        'allow_prefixes=["python -m pytest"]\n',
        encoding="utf-8",
    )
    report = run_policy_assess(tmp_path, ["curl", "https://example.com"])
    assert report.status == "blocked"
    assert report.summary["commands_executed"] is False


def test_policy_classifies_empty_network_install_deny_and_impact(tmp_path: Path) -> None:
    assert assess_command([], tmp_path, ExecutionPolicy()).reason_code == "EMPTY_COMMAND"
    network = assess_command(["curl", "https://example.com"], tmp_path, ExecutionPolicy())
    assert network.impact == "high"
    assert assess_command(["pip", "install", "demo"], tmp_path, ExecutionPolicy()).impact == "high"
    denied = assess_command(
        ["python", "tool.py"],
        tmp_path,
        ExecutionPolicy(mode="enforce", deny_prefixes=("python",)),
    )
    assert denied.reason_code == "COMMAND_DENYLISTED"
    over_limit = assess_command(
        ["python", "-m", "pytest"],
        tmp_path,
        ExecutionPolicy(mode="enforce", maximum_impact="low"),
    )
    assert over_limit.reason_code == "COMMAND_IMPACT_EXCEEDS_POLICY"
    absolute_python = assess_command(
        [str(tmp_path / "Python313" / "python.exe"), "-m", "pytest"],
        tmp_path,
        ExecutionPolicy(mode="enforce", allow_prefixes=("python -m pytest",)),
    )
    assert absolute_python.allowed is True
