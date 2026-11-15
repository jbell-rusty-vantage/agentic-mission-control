"""Build 08 loop 8 (candidate G): Mission Control runs the AI Engineer knowledge-loop watch.

The watch runs on the Deep Agents lane.

The signed scoped stack (`tests/fixtures/scoped_api_stack.py`) for the `ai-engineer` application: a
fresh common database on the disposable cluster named by MISSION_CONTROL_TEST_ADMIN_DSN, a local
Temporal dev server, the production workers and the configured API. Every GoalDirected role is the
deterministic technical agent (no provider call); with MISSION_CONTROL_TECHNICAL_AIENG_WATCH=1 its
executor of iteration 1 calls the five AI Engineer watch tools
(`tests/fixtures/aieng_watch_tools.py`): releases, due, rerun, admit; its verifier reads the tick
back. Runs are serial ticks; each run's Mission Control mission id is read from its inspection and
registered for the tools before launch. The AI Engineer missions' budgets bound the work across
runs.

  tick-1      watch-langchain-ecosystem + revalidate-langchain-probes (the real tick)
  tick-2      the same missions again (expected: nothing new, nothing due)
  tick-3      control: watch-budget-control (budget 0): the tools must record budget_stopped
              and do nothing else

Usage (from platform/mission-control):
  MISSION_CONTROL_TEST_ADMIN_DSN=postgresql://...@127.0.0.1:55433/postgres \
  MISSION_CONTROL_WORKSPACE_ROOT=<BellLabs>/biotech \\
  uv run --no-sync python scripts/aieng_watch_mission.py --out <dir> [--ticks tick-1,tick-2,tick-3]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.fixtures import aieng_watch_tools as W  # noqa: E402, N812
from tests.fixtures.scoped_api_stack import inspect, prepare_run, scoped_stack, until  # noqa: E402

from mission_control.adapters.postgres.knowledge.invocation_locator import (  # noqa: E402
    PostgresInvocationLocator,
)

TICKS = {
    "tick-1": {"watch": "watch-langchain-ecosystem", "revalidate": "revalidate-langchain-probes"},
    "tick-2": {"watch": "watch-langchain-ecosystem", "revalidate": "revalidate-langchain-probes"},
    "tick-3": {"watch": "watch-budget-control", "revalidate": "watch-budget-control"},
    "tick-4": {"watch": "watch-langchain-ecosystem", "revalidate": "revalidate-langchain-probes"},
}


def find_key(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        if value.get(key):
            return value[key]
        for item in value.values():
            found = find_key(item, key)
            if found:
                return found
    if isinstance(value, list):
        for item in value:
            found = find_key(item, key)
            if found:
                return found
    return None


async def run_tick(stack: Any, name: str, missions: dict[str, str], out: Path) -> dict[str, Any]:
    started = time.time()
    run_id, body = await prepare_run(stack, "GoalDirected")
    # The ledger mission id (mission_control.mission_run.mission_id), read the way knowledge-tool
    # origins read it.
    mission_id, _activation = await PostgresInvocationLocator(stack.pool).locate(
        stack.scope, run_id, None
    )
    W.RUN_MISSIONS[run_id] = str(mission_id)
    W.RUN_AIENG_MISSIONS[run_id] = dict(missions)
    calls_before = len(W.CALLS)
    launched = await stack.http.post(
        f"/v1/applications/{stack.application_id}/runs/{run_id}/launch", json=body
    )
    assert launched.status_code == 202, launched.text
    print(f"WATCH: {name} launched run {run_id} (mission {mission_id})", flush=True)

    async def done() -> bool:
        state = await inspect(stack, run_id)
        if state["lifecycle"] in {"failed", "cancelled"}:
            raise RuntimeError(f"{name}: run {run_id} {state['lifecycle']}")
        return state["lifecycle"] == "completed"

    await until(done, seconds=float(os.environ.get("AIENG_WATCH_RUN_SECONDS", "2400")))
    final = await inspect(stack, run_id)
    calls = W.CALLS[calls_before:]
    record = {
        "tick": name,
        "run_id": run_id,
        "mission_id": mission_id,
        "aieng_missions": missions,
        "lifecycle": final["lifecycle"],
        "seconds": round(time.time() - started, 1),
        "tool_calls": calls,
        "model_calls": [m for m in stack.model_log if m.get("run_id") == run_id],
    }
    (out / f"{name}.json").write_text(
        json.dumps({**record, "inspection": final}, indent=2, default=str), encoding="utf-8"
    )
    print(
        f"WATCH: {name} {final['lifecycle']} in {record['seconds']}s; tools "
        + ", ".join(f"{c['command']}={c['exit']}" for c in calls),
        flush=True,
    )
    return record


async def serve(out: Path, ticks: list[str]) -> None:
    components, tools = W.build_watch_tools()
    os.environ["MISSION_CONTROL_TECHNICAL_AIENG_WATCH"] = "1"
    with tempfile.TemporaryDirectory() as root, pytest.MonkeyPatch.context() as environment:
        # The stack is local (loopback disposable cluster): the remote AI Engineer project fields
        # from .env must not apply.
        for name in ("MC_AIENG_DB_PROJECT_REF", "MC_AIENG_DB_URL", "MC_AIENG_DB_SECRET_KEY"):
            environment.setenv(name, "")
        async with scoped_stack(
            Path(root),
            environment,
            application_id="ai-engineer",
            knowledge_tools=components,
            extra_tools=tools,
        ) as stack:
            summary = [await run_tick(stack, name, TICKS[name], out) for name in ticks]
    (out / "summary.json").write_text(
        json.dumps(
            [
                {k: v for k, v in s.items() if k not in ("tool_calls", "model_calls")}
                | {"tools": [(c["command"], c["mission"], c["exit"]) for c in s["tool_calls"]]}
                for s in summary
            ],
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--ticks", default="tick-1,tick-2,tick-3")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    asyncio.run(
        serve(out, args.ticks.split(",")),
        loop_factory=asyncio.SelectorEventLoop if sys.platform == "win32" else None,
    )


if __name__ == "__main__":
    main()
