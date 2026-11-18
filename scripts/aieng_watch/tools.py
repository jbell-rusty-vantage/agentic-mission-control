"""Build 08 loop 8 (candidate G): the AI Engineer knowledge-loop watch tools.

A Deep Agents node calls them.

Each tool runs one command of the AI Engineer lab watch
(`aiengineer/ai-engineer-db-contract/scripts/knowledge-lab/loop8_watch.py`) in a subprocess and
returns its JSON. Every call names the Mission Control invocation that made it (mission, run,
operation, attempt, generation, lane); the AI Engineer side writes it into
`orchestration.operation_intent` (origin_kind `mission_invocation`) and marks its sweeps and probe
runs `origin_kind = 'mission'`. Budget enforcement across runs lives on the AI Engineer side (the
mission row's `budget_cost_usd` against the spend of its sweeps).

The deterministic technical model calls them in a fixed order under the `aieng-watch` script,
which scripts/aieng_watch_mission.py registers (`MISSION_CONTROL_SCRIPTED_MODEL=aieng-watch`,
`watch_step`): the GoalDirected executor of
iteration 1 runs one watch tick (releases, due, rerun, admit) and the verifier of iteration 1
reads the tick back (status). No model provider is called.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from langchain_core.messages import BaseMessage, ToolMessage
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import DefinitionKind, ExactDefinitionRef
from mission_control.domain.execution.contracts import DeepAgentToolComponent

BELLLABS = Path(__file__).resolve().parents[4]
WATCH_SCRIPT = (
    BELLLABS
    / "aiengineer"
    / "ai-engineer-db-contract"
    / "scripts"
    / "knowledge-lab"
    / "loop8_watch.py"
)
LANE = "deep_agents"
# The driver registers each admitted run's Mission Control mission id before launch (serial runs,
# one process).
RUN_MISSIONS: dict[str, str] = {}
# The AI Engineer mission (orchestration.mission slug) each command writes under; the driver may
# point a run at another one.
RUN_AIENG_MISSIONS: dict[str, dict[str, str]] = {}
DEFAULT_MISSIONS = {
    "watch": "watch-langchain-ecosystem",
    "revalidate": "revalidate-langchain-probes",
}
TIMEOUT_SECONDS = float(os.environ.get("AIENG_WATCH_TOOL_TIMEOUT", "1500"))
CALLS: list[dict[str, Any]] = []


class Invocation(BaseModel):
    mc_run_id: str = Field(min_length=1)
    mc_operation_id: str = Field(min_length=1)
    mc_operation_attempt: int = Field(ge=1)
    mc_execution_generation: int = Field(ge=1)


def _invocation(args: Invocation) -> dict[str, Any]:
    mission = RUN_MISSIONS.get(args.mc_run_id)
    if not mission:
        raise RuntimeError(f"no Mission Control mission registered for run {args.mc_run_id}")
    return {**args.model_dump(), "mc_mission_id": mission, "mc_lane": LANE}


async def _run(
    command: str, mission: str, invocation: dict[str, Any] | None, run: str | None = None
) -> str:
    argv = [sys.executable, "-I", "-X", "utf8", str(WATCH_SCRIPT), command, "--mission", mission]
    if invocation is not None:
        argv += ["--invocation", json.dumps(invocation, sort_keys=True)]
    if run:
        argv += ["--run", run]

    def call() -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: PLW1510 (the exit code is reported)
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=TIMEOUT_SECONDS,
            cwd=str(WATCH_SCRIPT.parents[2]),
        )

    done = await asyncio.to_thread(call)
    out = done.stdout.strip().splitlines()[-1] if done.stdout.strip() else ""
    CALLS.append(
        {
            "command": command,
            "mission": mission,
            "exit": done.returncode,
            "invocation": invocation,
            "stdout": out[:4000],
            "stderr": done.stderr[-1500:],
        }
    )
    if done.returncode != 0:
        return json.dumps({"error": f"exit {done.returncode}", "stderr": done.stderr[-1500:]})
    return out[:12000]


def _mission(run_id: str, role: str) -> str:
    return RUN_AIENG_MISSIONS.get(run_id, {}).get(role, DEFAULT_MISSIONS[role])


async def aieng_watch_releases(**kwargs: Any) -> str:
    args = Invocation(**kwargs)
    return await _run("releases", _mission(args.mc_run_id, "watch"), _invocation(args))


async def aieng_watch_due(**kwargs: Any) -> str:
    args = Invocation(**kwargs)
    return await _run("due", _mission(args.mc_run_id, "watch"), _invocation(args))


async def aieng_watch_rerun(**kwargs: Any) -> str:
    args = Invocation(**kwargs)
    return await _run("rerun", _mission(args.mc_run_id, "revalidate"), _invocation(args))


async def aieng_watch_admit(**kwargs: Any) -> str:
    args = Invocation(**kwargs)
    return await _run("admit", _mission(args.mc_run_id, "revalidate"), _invocation(args))


async def aieng_watch_status(**kwargs: Any) -> str:
    args = Invocation(**kwargs)
    watch = json.loads(
        await _run("status", _mission(args.mc_run_id, "watch"), None, args.mc_run_id) or "{}"
    )
    reval = json.loads(
        await _run("status", _mission(args.mc_run_id, "revalidate"), None, args.mc_run_id) or "{}"
    )
    return json.dumps({"watch": watch, "revalidate": reval})


ENTRIES: tuple[tuple[str, Any, str], ...] = (
    (
        "aieng_watch_releases",
        aieng_watch_releases,
        "Capture the PyPI registry pages of the watched LangChain libraries and record stable "
        "releases newer than the catalog, under a mission sweep.",
    ),
    (
        "aieng_watch_due",
        aieng_watch_due,
        "Read the AI Engineer due-lists: api.attention_due and api.probe_revalidation_due "
        "(read only).",
    ),
    (
        "aieng_watch_rerun",
        aieng_watch_rerun,
        "Rerun the due deterministic probes in a rebuilt latest environment cell, register the "
        "runs and recompute the verdict rules, under a mission sweep.",
    ),
    (
        "aieng_watch_admit",
        aieng_watch_admit,
        "Dispatch the Knowledge Services admission run for confirmed, unverified "
        "probe-supported claims; does nothing when none are ready.",
    ),
    (
        "aieng_watch_status",
        aieng_watch_status,
        "Read back this run's sweeps of the watch and revalidation missions, with spend and "
        "budget (read only).",
    ),
)


def build_watch_tools(
    *, attachment_target: str = "agent"
) -> tuple[tuple[DeepAgentToolComponent, ...], dict[str, BaseTool]]:
    """The exact tool components (template binding) and the tools by component digest.

    The digest map is what the worker registry serves.
    """

    from mission_control.adapters.deep_agents.materializer import tool_schema_digest

    components: list[DeepAgentToolComponent] = []
    tools: dict[str, BaseTool] = {}
    for name, coroutine, description in ENTRIES:
        tool = StructuredTool.from_function(
            coroutine=coroutine, name=name, description=description, args_schema=Invocation
        )
        schema = tool_schema_digest(tool)
        digest = sha256_digest(
            {"tool": name, "schema_digest": schema, "kind": "aieng-watch-tool.v1"}
        )
        components.append(
            DeepAgentToolComponent(
                ref=ExactDefinitionRef(
                    kind=DefinitionKind.TOOL,
                    logical_id=f"tool.aieng-watch.{name.replace('_', '-')}",
                    revision=1,
                    digest=digest,
                ),
                tool_name=name,
                schema_digest=schema,
                attachment_target=attachment_target,
            )
        )
        tools[digest] = tool
    return tuple(components), tools


def _goal_position(operation_id: str) -> tuple[int, str] | None:
    if "goal-iteration/" not in operation_id:
        return None
    iteration, role = operation_id.split("goal-iteration/", 1)[1].split("/")[:2]
    return int(iteration), role.split(":", 1)[0]


def watch_step(model: Any, since_input: list[BaseMessage], tools: int) -> dict[str, Any] | None:
    """The scripted watch call after the three standard technical steps, or None (answer).

    Executor of iteration 1: releases (tool 3), due (4), rerun (5), admit (6), then answer.
    Verifier of iteration 1: status (3), then answer. Every other operation answers as before.
    The arguments are the node's own invocation identity.
    """

    position = _goal_position(model.operation_id)
    if position is None or position[0] != 1:
        return None
    args = {
        "mc_run_id": model.run_id,
        "mc_operation_id": model.operation_id,
        "mc_operation_attempt": int(getattr(model, "operation_attempt", 1)),
        "mc_execution_generation": int(getattr(model, "execution_generation", 1)),
    }
    plan = {
        "executor": [
            "aieng_watch_releases",
            "aieng_watch_due",
            "aieng_watch_rerun",
            "aieng_watch_admit",
        ],
        "verifier": ["aieng_watch_status"],
    }.get(position[1], [])
    step = tools - 3
    if 0 <= step < len(plan):
        return {"name": plan[step], "args": args}
    return None


def last_tool_json(since_input: list[BaseMessage]) -> dict[str, Any]:
    for item in reversed(since_input):
        if isinstance(item, ToolMessage):
            try:
                return json.loads(str(item.content))
            except json.JSONDecodeError:
                return {}
    return {}
