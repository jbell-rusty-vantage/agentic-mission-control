"""Serve the deterministic offline operator API on loopback for wake-channel drills (MO-43).

Starts the signed scoped stack of ``tests/fixtures/scoped_api_stack.py``: a fresh common
database on the disposable cluster named by ``MISSION_CONTROL_TEST_ADMIN_DSN``, a local Temporal
dev server, and the production workers with deterministic DeepAgents cognition (no provider
call, nothing paid). It serves the configured API on ``127.0.0.1``, admits one GoalDirected run
(not launched) and writes into ``--out``:

- ``stack.json``: the API URL, the application id and the admitted run id;
- ``launch.json``: that run's launch body, for ``missionctl run start RUN --request-file``;
- ``token``: the signed bearer token (file only; never printed).

An orchestrating agent then drives the run through the operator API like any coordinator:
``missionctl run start``, then ``missionctl wait --run RUN`` as a background task. The stack
runs until ``--out/stop`` exists (or Ctrl+C) and then drops its database.

The stack sets MISSION_CONTROL_APPLICATION to its application itself; the capability
resource owner must still exist (MISSION_CONTROL_WORKSPACE_ROOT, or the profile's
``../../biotech`` from a canonical BellLabs checkout).

Required (OC-R4): set MISSION_CONTROL_APPLICATION, or both MISSION_CONTROL_WORKSPACE_ROOT and
TEMPORAL_TASK_QUEUE, for the live scripts, the local worker and the technical API; without them
startup fails with InstallationDefaultUnavailable (there are no defaults).

Usage:
  MISSION_CONTROL_TEST_ADMIN_DSN=postgresql://...@127.0.0.1:55433/postgres \\
  MISSION_CONTROL_WORKSPACE_ROOT=<BellLabs>/biotech \\
  uv run --no-sync python scripts/offline_operator_stack.py --out .scratch/wake-drill
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.fixtures.scoped_api_stack import (  # noqa: E402
    prepare_run,
    scoped_stack,
    serve_loopback,
)

STOP_POLL_SECONDS = 1.0


def write_drill_files(out: Path, url: str, run_id: str, launch: dict[str, Any], token: str) -> None:
    (out / "token").write_text(token, encoding="utf-8")
    (out / "launch.json").write_text(json.dumps(launch, indent=2), encoding="utf-8")
    (out / "stack.json").write_text(
        json.dumps({"url": url, "application_id": "biotech", "run_id": run_id}, indent=2),
        encoding="utf-8",
    )


def wait_for_stop(stop: Path) -> None:
    while not stop.exists():
        time.sleep(STOP_POLL_SECONDS)


async def serve(out: Path, family: str) -> None:
    with tempfile.TemporaryDirectory() as root, pytest.MonkeyPatch.context() as environment:
        async with (
            scoped_stack(Path(root), environment) as stack,
            serve_loopback(stack.application) as url,
        ):
            run_id, launch = await prepare_run(stack, family)
            write_drill_files(out, url, run_id, launch, stack.token)
            print(f"OFFLINE STACK: serving {url}; admitted {family} run {run_id}", flush=True)
            await asyncio.to_thread(wait_for_stop, out / "stop")
            print("OFFLINE STACK: stop requested", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True, help="drill directory (git-ignored)")
    parser.add_argument("--family", choices=("GoalDirected", "StageGraph"), default="GoalDirected")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / "stop").unlink(missing_ok=True)
    # psycopg (the LangGraph checkpointer) needs a selector loop on Windows, as the worker does.
    asyncio.run(
        serve(out, args.family),
        loop_factory=asyncio.SelectorEventLoop if sys.platform == "win32" else None,
    )


if __name__ == "__main__":
    main()
