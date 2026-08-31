from __future__ import annotations

TOP_LEVEL_COMMANDS = (
    "doctor scan bootstrap environment run stop map check test logs context cache index "
    "baseline benchmark explain feedback watch session agents diagnostics git mcp semantic policy "
    "capabilities plan sarif finish completion"
)
GLOBAL_FLAGS = "--project --json --quiet --help --version"
COMMAND_FLAGS = (
    "--mode --jobs --no-cache --resume --retry-flaky --retry-infra --policy --compare --dry-run "
    "--explain --create-env --if-needed --foreground --timeout --ready-http --ready-tcp "
    "--startup-timeout --startup-log-lines --max-files --max-depth --tool --task --profile "
    "--max-chars --max-file-chars --max-diff-chars --include --exclude --changed-only "
    "--staged-only --no-git --format --output --incremental --since --retrieval --tokenizer "
    "--token-budget --provider-usage --refine --refinement-rounds --refinement-max-files "
    "--compression --debounce --poll --initial --max-runs --max-updates --idle-timeout --backend "
    "--title --path --depends-on --agent --input "
    "--lease-seconds --suite --variant --trials --cache-state --symbol --tail"
)


def _candidates() -> list[str]:
    return TOP_LEVEL_COMMANDS.split() + GLOBAL_FLAGS.split() + COMMAND_FLAGS.split()


def render_completion(shell: str) -> str:
    if shell == "bash":
        return _bash()
    if shell == "zsh":
        return _zsh()
    if shell == "fish":
        return _fish()
    if shell == "powershell":
        return _powershell()
    raise ValueError(f"Unsupported shell: {shell}")


def _bash() -> str:
    return f'''_ai_dev_complete() {{
  local current="${{COMP_WORDS[COMP_CWORD]}}"
  COMPREPLY=($(compgen -W "{TOP_LEVEL_COMMANDS} {GLOBAL_FLAGS} {COMMAND_FLAGS}" -- "$current"))
}}
complete -F _ai_dev_complete ai-dev
'''


def _zsh() -> str:
    words = " ".join(_candidates())
    return f"""#compdef ai-dev
_ai_dev() {{
  local -a candidates
  candidates=({words})
  compadd -- $candidates
}}
compdef _ai_dev ai-dev
"""


def _fish() -> str:
    lines = ["complete -c ai-dev -f"]
    lines.extend(
        f"complete -c ai-dev -n '__fish_use_subcommand' -a '{item}'"
        for item in TOP_LEVEL_COMMANDS.split()
    )
    lines.extend(
        f"complete -c ai-dev -l '{item[2:]}'"
        for item in GLOBAL_FLAGS.split() + COMMAND_FLAGS.split()
        if item.startswith("--")
    )
    return "\n".join(lines) + "\n"


def _powershell() -> str:
    candidates = ", ".join(
        f"'{item}'" for item in _candidates()
    )
    return f"""Register-ArgumentCompleter -Native -CommandName ai-dev -ScriptBlock {{
  param($wordToComplete, $commandAst, $cursorPosition)
  @({candidates}) |
    Where-Object {{ $_ -like "$wordToComplete*" }} |
    ForEach-Object {{
      [System.Management.Automation.CompletionResult]::new(
        $_, $_, 'ParameterValue', $_
      )
    }}
}}
"""
