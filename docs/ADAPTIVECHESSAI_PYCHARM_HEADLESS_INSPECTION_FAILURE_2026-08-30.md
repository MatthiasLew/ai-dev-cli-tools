# PyCharm headless inspection failure for AdaptiveChessAI

## Summary

PyCharm Community Edition 2023.2 could not start its offline inspection runner
for the `AdaptiveChessAI` repository. The failure happened during IDE startup,
before project inspections were executed.

## Environment

- Date: 2026-08-30
- OS: Windows
- IDE: PyCharm Community Edition 2023.2
- JRE: JetBrains Runtime 17.0.7+7-b1000.6
- Project: `C:\Users\Praca\fork\MatthiasLew\AdaptiveChessAI`

## Command

```powershell
& "C:\Program Files\JetBrains\PyCharm Community Edition 2023.2\bin\inspect.bat" `
  "C:\Users\Praca\fork\MatthiasLew\AdaptiveChessAI" `
  "Default" `
  "<writable-output-directory>"
```

## Failure

```text
Start Failed
Internal error.

java.net.SocketException: Invalid argument: bind
    at java.base/sun.nio.UnixDomainSockets.bind0(Native Method)
    at com.intellij.idea.DirectoryLock.tryListen(DirectoryLock.java:224)
    at com.intellij.idea.DirectoryLock.lockOrActivate(DirectoryLock.java:120)
```

## Impact

No PyCharm-specific inspection results were produced. The failure did not
modify the application and did not indicate a problem in its Python code.

## Fallback validation

The repository was checked with the following independent tools:

- Ruff lint checks,
- Ruff formatting checks,
- mypy static type checks,
- pytest test suite.

These checks provide coverage for common PyCharm warnings such as malformed or
unused imports, PEP 8 formatting problems, unresolved local type mismatches and
incorrect modern PySide6 enum usage.

## Suggested follow-up

Retry the inspection using a newer PyCharm version or with isolated IDE system
and configuration directories. The failure appears related to the IDE startup
directory-lock socket rather than the inspected repository.
