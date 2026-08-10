# Tool Output Parsers

`ai_dev_tools.parsers.logs` exposes a small parser layer built around `ToolOutputParser` and `ParsedToolResult`.

Supported parser families in 0.2.0:

- Python: pytest, Ruff, mypy, coverage.py.
- JavaScript and TypeScript: Jest, Vitest, ESLint, TypeScript compiler, npm fallback.
- Java: Maven Surefire, Maven build output, Gradle output.
- Rust: cargo test, cargo clippy, cargo fmt.
- PHP: PHPUnit, PHPStan, PHP-CS-Fixer.

Every parser strips ANSI, tolerates CRLF/LF, handles partial logs, and falls back to `generic` with `parser_confidence: low` when no dedicated parser matches.

Examples:

```bash
ai-dev logs summarize pytest.log --tool auto
ai-dev logs summarize pytest.log --tool pytest --json
```
## Extension API

Parser selection uses an ordered `ParserRegistry` instead of a hard-coded conditional chain. A parser implements `tool_name`, `can_parse(CommandResult)`, and `parse(CommandResult)`. Register a project or plugin parser before parsing output:

```python
from ai_dev_tools.parsers.logs import register_parser, unregister_parser

register_parser(MyToolParser())
# parse logs or command results
unregister_parser("my-tool")
```

Names are unique by default. Pass `replace=True` only when intentionally overriding an existing parser. Custom parsers are prepended so the generic fallback cannot shadow them. `parser_names()` exposes deterministic selection order for diagnostics and tests.