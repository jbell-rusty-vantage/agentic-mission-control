"""HL-08 opt-in live session drill on local Temporal and PostgreSQL (skipped by default).

Runs only with `MC_CLAUDE_MANAGED_LIVE=1`, an `ANTHROPIC_API_KEY`, a finite
`MC_PAID_BUDGET_USD` the owner authorized, the real local Temporal server and the disposable
PostgreSQL (`MISSION_CONTROL_TEST_ADMIN_DSN`). The real `OperationWorkflow` schedules
`lane.turn` on the hosted lane queue `mc-ai-engineer-lane-hosted`, served by a worker composed
here with the real `ClaudeManagedHarness` over the real Managed Agents API (frames, lane state,
the dispatch journal and the MO-16 preparation record in PostgreSQL):

1. a turn that runs to its close: prepare from a minimal drill pack (no tools the agent needs,
   no skills, no vault), a budgeted session, the stream and the history observed, the turn
   settled from its closing idle with usage and cost from `list_cost`, then end (archive and the
   deletion order);
2. a turn interrupted while it runs: the workflow's `cancel_command` reaches the provider as
   `user.interrupt`, the turn closes `cancelled`, then end.

After custody every session is deleted (the retention timer's job, run here at once), the agent
archived and the environment deleted. Every resource carries `mc_run=$MC_RUN_LABEL` (default
`run1-HL-08`). With `MC_CLAUDE_MANAGED_EVIDENCE=<path>` the ids, statuses, frame kinds, usage
and cleanup outcomes (never model text) are written there as JSON.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections import Counter
from datetime import timedelta
from pathlib import Path
from typing import Any, Final
from uuid import uuid4

import asyncpg
import pytest
from pydantic import SecretStr
from temporalio.client import Client
from temporalio.worker import Worker

from mission_control.adapters.anthropic_managed.client import ManagedAgentsClient
from mission_control.adapters.anthropic_managed.frames import list_cost_minor_units, stop_reason
from mission_control.adapters.anthropic_managed.harness import (
    ClaudeManagedHarness,
    ManagedSessionDeleter,
)
from mission_control.adapters.anthropic_managed.pack import RenderedPack, load_pack, render_pack
from mission_control.adapters.anthropic_managed.prepare import ClaudeManagedPrepare
from mission_control.adapters.postgres.frames.repository import PostgresFrameRepository
from mission_control.adapters.secrets.sources import WorkerEnvironmentSource
from mission_control.adapters.temporal.operation_activities import (
    parse_operation_result,
)
from mission_control.adapters.temporal.workflow_sandbox import coordinator_workflow_runner
from mission_control.adapters.temporal.workflows.operation import OperationWorkflow
from mission_control.application.execution.harness.retention import SessionRetentionService
from mission_control.application.secrets.broker import SecretBroker
from mission_control.domain.execution.contracts import (
    OperationAttemptIdentity,
    OperationExecutionRequest,
)
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.fixtures.session_retention import RecordingDeletionScheduler
from tests.support.artifacts import MemoryArtifacts
from tests.support.db_builders import admit_unit_attempt
from tests.support.integration.anthropic_managed.session_lifecycle_live import (
    _frames,
    _lane_worker,
    _request,
)
from tests.support.providers.managed_agents import (
    LANE_QUEUE,
    PROFILE,
    managed_binding,
    managed_operation,
)

ADDRESS: Final = os.environ.get("MC_TEMPORAL_TEST_ADDRESS", "127.0.0.1:7233")
NAMESPACE: Final = os.environ.get("MC_TEMPORAL_TEST_NAMESPACE", "default")
# The attempt budget each drill session is created with (USD minor units).
SESSION_CAP_MINOR_UNITS: Final = 50
COMPLETE_PROMPT: Final = "Reply with exactly one line: LIFECYCLE-OK"
# Long enough (one model request of tens of seconds) for the interrupt to land mid-request.
LONG_PROMPT: Final = (
    "Write the integers from 1 to 1500 in English words, in ascending order, one per line, as "
    "plain text. Do not use any tool."
)
DRILL_PACK: Final = {
    "pack.yaml": (
        "schema: mc.hosted_pack.claude_managed.v1\n"
        "pack: hl08-lifecycle-drill\n"
        "application: ai-engineer\n"
        "lane_profile: claude_managed\n"
        "placement: cloud\n"
        "data_class: internal\n"
        f"task_queue: {LANE_QUEUE}\n"
    ),
    "agent.yaml": (
        "name: mc-hl08-lifecycle-drill\n"
        "model: claude-haiku-5-5\n"
        "system: system.md\n"
        "tools:\n"
        "  read: always_allow\n"
    ),
    "system.md": (
        "You are a Mission Control session lifecycle drill. Answer in plain text only and do "
        "exactly what the message asks. Do not call tools.\n"
    ),
    "environment.yaml": "kit: hl08-drill\nnetworking:\n  allowed_hosts: []\n",
    "vault.yaml": "credentials: []\n",
}

LIVE = (
    os.environ.get("MC_CLAUDE_MANAGED_LIVE") == "1"
    and bool(os.environ.get("ANTHROPIC_API_KEY"))
    and float(os.environ.get("MC_PAID_BUDGET_USD", "0") or 0) > 0
)

pytestmark = pytest.mark.skipif(
    not LIVE,
    reason="paid live drill: set MC_CLAUDE_MANAGED_LIVE=1, ANTHROPIC_API_KEY, MC_PAID_BUDGET_USD",
)


def _drill_pack(root: Path) -> RenderedPack:
    directory = root / "hl08-drill-pack"
    directory.mkdir()
    for name, text in DRILL_PACK.items():
        (directory / name).write_text(text, encoding="utf-8")
    return render_pack(load_pack(directory), installation_id="local")


async def _unit(
    pool: asyncpg.Pool, db: CommonDatabase, pack: RenderedPack, prompt: str
) -> OperationExecutionRequest:
    admitted = await admit_unit_attempt(pool, db)
    unit = admitted.unit
    binding = managed_binding(
        pack.materialization_digest,
        task_queue=LANE_QUEUE,
        provider_options={
            "provider": PROFILE,
            "max_list_cost_minor_units": SESSION_CAP_MINOR_UNITS,
        },
    )
    payload = managed_operation(binding, prompt=prompt).model_dump(mode="python")
    payload.update(
        request_scope=unit.request_scope,
        identity=OperationAttemptIdentity(
            run_id=admitted.run_key,
            operation_id=unit.semantic_operation_id,
            operation_attempt=unit.semantic_attempt,
        ),
        runtime_unit=unit,
        idempotency_key=f"hl08-live:{unit.unit_key}",
    )
    return OperationExecutionRequest.model_validate(payload)


@pytest.mark.common_db
async def test_a_live_session_runs_is_interrupted_and_ends_archived_then_deleted(
    common_db: CommonDatabase,
    tmp_path: Path,
) -> None:
    evidence_path = os.environ.get("MC_CLAUDE_MANAGED_EVIDENCE")
    if evidence_path and not Path(evidence_path).parent.is_dir():
        pytest.fail("MC_CLAUDE_MANAGED_EVIDENCE names a missing directory; nothing was created")
    label = os.environ.get("MC_RUN_LABEL", "run1-HL-08")
    client = ManagedAgentsClient(SecretStr(os.environ["ANTHROPIC_API_KEY"]))
    pack = _drill_pack(tmp_path)
    preparer = ClaudeManagedPrepare(
        client,
        SecretBroker(environment=WorkerEnvironmentSource({})),
        installation_id="local",
        labels={"mc_run": label},
    )
    deletions = RecordingDeletionScheduler()
    harness = ClaudeManagedHarness(
        client=client,
        preparer=preparer,
        pack=pack,
        artifacts=MemoryArtifacts(),
        retention=SessionRetentionService(deletions),
        labels={"mc_run": label},
    )
    temporal = await Client.connect(ADDRESS, namespace=NAMESPACE)
    pool = await common_db.pool("mission_control_runtime")
    frames = PostgresFrameRepository(pool)
    record: dict[str, Any] = {"label": label, "lane_queue": LANE_QUEUE, "runs": {}}
    try:
        completed = await _unit(pool, common_db, pack, COMPLETE_PROMPT)
        interrupted = await _unit(pool, common_db, pack, LONG_PROMPT)
        workflow_queue = f"hl08-live-wf-{uuid4().hex[:8]}"
        async with Worker(
            temporal,
            task_queue=workflow_queue,
            workflows=[OperationWorkflow],
            workflow_runner=coordinator_workflow_runner(),
        ):
            # 1. A turn that runs to its close.
            async with _lane_worker(temporal, harness, completed, pool, frames):
                handle = await temporal.start_workflow(
                    OperationWorkflow.run,
                    _request(completed),
                    id=f"hl08-live-complete-{uuid4().hex[:8]}",
                    task_queue=workflow_queue,
                    execution_timeout=timedelta(minutes=10),
                )
                result = await asyncio.wait_for(handle.result(), 600)
            record["runs"]["complete"] = _run_record(result, await _frames(frames, completed))

            # 2. A turn interrupted while it runs.
            async with _lane_worker(temporal, harness, interrupted, pool, frames):
                handle = await temporal.start_workflow(
                    OperationWorkflow.run,
                    _request(interrupted),
                    id=f"hl08-live-interrupt-{uuid4().hex[:8]}",
                    task_queue=workflow_queue,
                    execution_timeout=timedelta(minutes=10),
                )
                await _model_request_started(frames, interrupted)
                await handle.execute_update("cancel_command", args=["hl08-live-cancel"])
                result = await asyncio.wait_for(handle.result(), 600)
            record["runs"]["interrupt"] = _run_record(result, await _frames(frames, interrupted))

        complete, interrupt = record["runs"]["complete"], record["runs"]["interrupt"]
        assert complete["disposition"] == "completed" and complete["status"] == "completed"
        assert complete["closing"]["status"] == "finished"
        assert complete["closing"]["usage"] and complete["closing"]["list_cost_minor_units"] >= 0
        assert complete["duplicate_keys"] == 0 and complete["kinds"]["run_result"] == 1
        assert interrupt["disposition"] == "cancelled"
        assert interrupt["duplicate_keys"] == 0
        assert len(deletions.orders) == 2, "both sessions archived and ordered deleted"
    finally:
        record["cleanup"] = await _cleanup(client, preparer, pack, deletions)
        await pool.close()
        await client.aclose()
        if evidence_path:
            _write_evidence(Path(evidence_path), record)


async def _model_request_started(
    frames: PostgresFrameRepository, operation: OperationExecutionRequest
) -> None:
    """Return once the turn's first model request started (the interrupt then lands mid-turn)."""

    for _poll in range(480):
        stored = await _frames(frames, operation)
        if any(frame.raw_kind == "span.model_request_start" for frame in stored):
            return
        await asyncio.sleep(0.5)
    raise AssertionError("the interrupted turn never started a model request")


def _write_evidence(path: Path, record: dict[str, Any]) -> None:
    path.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")


def _run_record(result: Any, frames: Any) -> dict[str, Any]:
    keys = [frame.provider_key for frame in frames]
    closing = next(
        (
            _turn_summary(frame.body_excerpt)
            for frame in reversed(frames)
            if frame.kind == "run_result"
        ),
        None,
    )
    settled = parse_operation_result(result.result)
    return {
        "disposition": result.disposition,
        "status": settled.status,
        "failure_code": settled.failure_code,
        "usage": dict(settled.usage.amounts),
        "frames": len(frames),
        "duplicate_keys": len(keys) - len(set(keys)),
        "kinds": dict(Counter(frame.kind.value for frame in frames)),
        "raw_kinds": [frame.raw_kind for frame in frames],
        "session": next((frame.native_session_ref for frame in frames), None),
        "closing": (
            {key: value for key, value in closing.items() if key != "result"} if closing else None
        ),
    }


def _turn_summary(excerpt: str) -> dict[str, Any] | None:
    """The `mc_turn` summary the lane wrote on the closing frame (its stored excerpt)."""

    try:
        body = json.loads(excerpt)
    except ValueError:
        return None
    summary = body.get("mc_turn") if isinstance(body, dict) else None
    return summary if isinstance(summary, dict) else None


async def _cleanup(
    client: ManagedAgentsClient,
    preparer: ClaudeManagedPrepare,
    pack: RenderedPack,
    deletions: RecordingDeletionScheduler,
) -> dict[str, Any]:
    """Delete every session of the drill's agent (after recording its spend), archive the
    agent and delete the environment; each outcome is recorded, none is fatal."""

    outcomes: dict[str, Any] = {"ordered_deletions": sorted(deletions.orders)}
    deleter = ManagedSessionDeleter(client)
    try:
        prepared = await preparer.sync(pack)  # reads the drill's resources back, creates nothing
    except Exception as error:
        outcomes["readback"] = f"failed: {type(error).__name__}"
        return outcomes
    spend = 0
    for session in await client.list_sessions(agent_id=prepared.agent.agent_id):
        session_id = str(session["id"])
        cost = list_cost_minor_units(session.get("usage")) or 0
        spend += cost
        # The provider's own log of the session (event types and stop reasons, no content).
        log = [
            str(event.get("type"))
            + (f"{{{reason}}}" if (reason := stop_reason(event)) is not None else "")
            async for event in client.list_events(session_id)
        ]
        try:
            outcomes[session_id] = {
                "status": session.get("status"),
                "archived": bool(session.get("archived_at")),
                "list_cost_minor_units": cost,
                "events": log,
                "deleted": await deleter.delete_session(session_id),
            }
        except Exception as error:
            outcomes[session_id] = {"list_cost_minor_units": cost, "deleted": repr(error)[:200]}
    outcomes["spend_minor_units"] = spend
    for resource_id, step in (
        (prepared.environment.environment_id, client.delete_environment),
        (prepared.agent.agent_id, client.archive_agent),
    ):
        try:
            await step(resource_id)
            outcomes[resource_id] = "archived" if resource_id.startswith("agent_") else "deleted"
        except Exception as error:
            outcomes[resource_id] = f"failed: {type(error).__name__}"
    return outcomes
