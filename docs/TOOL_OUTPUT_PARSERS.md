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