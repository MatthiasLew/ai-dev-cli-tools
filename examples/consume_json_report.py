from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def main(project: Path) -> int:
    completed = subprocess.run(
        ["ai-dev", "--project", str(project), "check", "--mode", "changed", "--json"],
        check=False,
        capture_output=True,
        text=True,
    )
    report = json.loads(completed.stdout)
    print(f"status={report['status']} failed={report['summary'].get('checks_failed', 0)}")
    for artifact in report.get("artifacts", []):
        print(f"artifact={artifact['kind']}:{artifact['path']}")
    return int(report.get("exit_code", completed.returncode))


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()))
