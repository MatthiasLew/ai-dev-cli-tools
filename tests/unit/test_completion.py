import pytest

from ai_dev_tools.completion import render_completion


@pytest.mark.parametrize(
    ("shell", "marker"),
    [
        ("bash", "complete -F _ai_dev_complete ai-dev"),
        ("zsh", "compdef _ai_dev ai-dev"),
        ("fish", "complete -c ai-dev"),
        ("powershell", "Register-ArgumentCompleter -Native -CommandName ai-dev"),
    ],
)
def test_completion_scripts_include_shell_registration_and_commands(
    shell: str, marker: str
) -> None:
    script = render_completion(shell)
    assert marker in script
    assert "context" in script
    assert "diagnostics" in script
    assert "--project" in script or "-l 'project'" in script


def test_completion_rejects_unknown_shell() -> None:
    with pytest.raises(ValueError, match="Unsupported shell"):
        render_completion("cmd")
