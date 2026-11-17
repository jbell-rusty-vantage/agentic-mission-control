"""scripts/dev/dev_cli.py: the ./dev front door answers in JSON with typed exit codes."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CLI = ROOT / "scripts" / "dev" / "dev_cli.py"


def dev(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(CLI), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def test_status_orients_in_one_json_document() -> None:
    done = dev("status")
    assert done.returncode == 0, done.stderr
    data = json.loads(done.stdout)
    assert data["repo"] == "mission-control"
    assert {"branch", "ahead", "modified", "hooks", "trace", "entrypoints", "hints"} <= set(data)


def test_usage_errors_exit_2_and_name_the_choices() -> None:
    assert dev().returncode == 2
    wrong = dev("test", "everything")
    assert wrong.returncode == 2 and "unit" in wrong.stderr


def test_trace_passes_through_to_the_trace_tool() -> None:
    done = dev("trace", "show", "NOPE-S404")
    assert done.returncode == 3 and "no record named" in done.stderr
