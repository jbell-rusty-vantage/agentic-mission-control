"""FX-TR (TRACING-PROPOSAL §P9, Stage 1 WP-TR-1): the tracing fixture on the production
offline stack, the FX-TR-RECONCILE proof and the lifecycle/"who" half of FX-TR-STEP.

The signed scoped stack (`tests/fixtures/scoped_api_stack.py`): a fresh common database on
the disposable cluster (the newest built release, 1.4.4), a local Temporal dev server, the
production workers with deterministic Deep Agents cognition (no provider call) and the
configured API over ASGI. `prepare_run(stack, "StageGraphTracing")` publishes the four-stage
`S1 -> S2 -> {S3, S4}` blueprint (`rrm009_production_stack.tracing_stage_blueprint`) whose `S2`
carries `StageCyclePolicy(max_cycles=3)`; the scripted model cycles `S2` at stage cycle
ordinals 0 and 1 and accepts at 2, from the operation id alone.

Unit shape of one tracing run, as the Stage Graph workflow schedules it today: a stage cycle
is applied only once nothing is active and nothing is ready (`workflows/stagegraph.py:963`),
so the consumers `S2`'s accepted result released (`S3@c0`, `S4@c0`) settle before the cycle
invalidates them and re-creates `S2`, `S3` and `S4` at the next ordinal. Ten units settle:
`S1@c0`, then `S2`, `S3`, `S4` at cycles 0, 1 and 2.

Helpers exported for the WP-TR proofs: `db_rows(stack, sql, *args)` (an owner-role read of
the common database with the tenant context set as `_insert_tenants` sets it),
`events_for_run(stack, run_id)` (the run's `mission_event` rows in `seq` order),
`units_by_location(points)`, and for WP-TR-2 `frames_for_run(stack, run_id)` (the run's
`provider_frame` rows joined to their unit), `frames_in_range(frames, point)`,
`transcript_entries(stack, run_id, full=)` and `harness_executions(stack, run_id)`.

WP-TR-2 (FX-TR-STEP, FX-TR-SUB, FX-TR-HOOK) fixture pieces: the exact MCP server is the
fixture-owned `tests/fixtures/rrm009_mcp_server.py` (a >12 KiB `lookup_binding_marker`
result), the tracing family's stage operations carry the catalog hook `rrm009.annotate`
once `DeploymentCapabilityComponents` can register its bundle, and
`scoped_api_stack.close_saver` closes the API's pinned saver for the "saver closed" reads.

WP-TR-3 (FX-TR-RETAIN, FX-TR-REPLAY, FX-TR-STEP on the projection) fixture pieces: the
scoped stack now serves the maintenance queue (`scoped_api_stack.maintenance_worker`:
`mc.frames_expire.v1` over the runtime pool, unless the production worker set already serves
it) and exposes it as `stack.maintenance_queue`; `run_frames_expiry(stack, now=)` drives the
retention workflow the way the FT-C1 integration proof does; `projection_state`,
`projected_entries` and `transcript_page(stack, run_id, by=, point=, ...)` read the persisted
projection and the grouped read model; `cli(url, token, *args)` runs one `missionctl` command.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import pytest
from tests.acceptance.mission_control.test_cognition_points import (
    BASE,
    all_points,
    assert_points_index_the_saver,
    completed,
    is_root,
    launch,
    saver_root_checkpoints,
    snapshot,
)
from tests.fixtures import rrm009_production_stack as technical
from tests.fixtures.scoped_api_stack import (
    ScopedStack,
    close_saver,
    inspect,
    scoped_stack,
    serve_loopback,
    until,
)

from mission_control.adapters.postgres.frames.retention import (
    FrameRetentionPolicy,
    PostgresFrameRetention,
)
from mission_control.adapters.postgres.scope import apply_scope
from mission_control.adapters.temporal.activities.frames_expire import (
    FRAMES_EXPIRE_WORKFLOW,
    FramesExpireInput,
)
from mission_control.application.execution.run_launch import fork_semantic_input_binding_ref
from mission_control.contracts.identities import mission_root_id
from mission_control.domain.capabilities.hooks import KERNEL_HOOK_IDS
from mission_control.domain.frames.contracts import DELTA_RETENTION_KINDS
from mission_control.domain.policies.contracts import ActorContext

pytestmark = pytest.mark.common_db

TRACING = technical.TRACING_FAMILY
CYCLE_STAGE = technical.TRACING_CYCLE_STAGE
LAST_CYCLE = technical.TRACING_CYCLES
# The derived frame events of `application/frames/reducer.py` (module docstring): every
# `session.*` fact, the tool effect settlement and the attempt outcome.
DERIVED_EVENT_PREFIXES = ("session.",)
DERIVED_EVENT_TYPES = frozenset({"tool_call.completed", "attempt.completed"})
# Derived events that precede their unit's first point (no `point_ref` to carry).
POINTLESS_EVENT_TYPES = frozenset({"session.started", "session.turn_started"})
# The family admission's lifecycle events (`application/programs/service.py:365-492`).
ADMISSION_EVENT_TYPES = frozenset(
    {"workflow_run.apply_authority_batch", "workflow_run.reserve_budget"}
)
# `ProgramService.decide_result`: `result-{sha256 hex of the semantic key}` (the full digest).
RESULT_DECISION_KEY = re.compile(r"^result-[0-9a-f]{64}$")
# WP-TR-2 contracts (TRACING-PROPOSAL §P3.1, §P3.3): the result point's workspace candidates
# reference and the promoted frame body scheme.
# OVE-204 slice 5: the result point's ref names the attempt's Workspace Closure.
WORKSPACE_CHECKPOINT_REF = re.compile(r"^workspace-closure://[0-9a-f-]{36}#sha256:[0-9a-f]{64}$")
FRAME_BODY_REF = re.compile(r"^frame-body://sha256:[0-9a-f]{64}\?bytes=\d+&type=[^&]+")
# The frame writer's excerpt cap (`standard` capture profile): one tool result exceeds it.
EXCERPT_CAP_BYTES = 8 * 1024
# The seeded Context Packet files of a stage attempt on the state backend
# (`test_cognition_points.py:293-297`).
PACKET_FILES = frozenset({"/.mission/inputs.json", "/.mission/context.md"})
# Tokens one unit consumes: the parent's four calls and the child's one, `TOKENS_PER_CALL` each.
UNIT_TOKENS = 5 * technical.TOKENS_PER_CALL
EVIDENCE_ROOT = Path(".scratch/tracing-stage-1")
# Under the 900 s pytest-timeout safety net; a run takes 60-200 s on the host.
RUN_SECONDS = 600
# A unit's four model calls are seconds apart; two minutes without one is a stall.
STALL_SECONDS = 120


# --- Helpers ---------------------------------------------------------------------------------


def as_json(value: Any) -> Any:
    """A jsonb column as asyncpg returns it without a codec (text) -> Python."""

    return json.loads(value) if isinstance(value, str | bytes) else value


async def db_rows(stack: ScopedStack, sql: str, *args: Any) -> list[dict[str, Any]]:
    """Rows of one owner-role read of the common database under the stack's tenant context.

    The owner pool is subject to the forced row-level security of the common component, so
    the `mc.installation_id` / `mc.application_id` / `mc.tenant_id` settings are bound for
    the transaction the way `mission_control_common_db._insert_tenants` binds them; the
    canonical scope `mc/{installation}/{application}/{tenant}` carries all three.
    """

    async with stack.owner_pool.acquire() as connection, connection.transaction():
        await apply_scope(connection, stack.scope)
        rows = await connection.fetch(sql, *args)
    return [dict(row) for row in rows]


async def events_for_run(stack: ScopedStack, run_id: str) -> list[dict[str, Any]]:
    """The run's `mission_event` rows, oldest first, with the 1.4.4 joinability columns."""

    rows = await db_rows(
        stack,
        """
        SELECT seq, event_type, event_version, actor_ref, run_id::text AS run_id,
               activation_id::text AS activation_id, unit_key, point_ref, payload,
               causation_ref, happened_at
        FROM mission_control.mission_event
        WHERE run_id = (SELECT run_id FROM mission_control.mission_run WHERE run_key = $1)
        ORDER BY seq
        """,
        run_id,
    )
    for row in rows:
        row["payload"] = as_json(row["payload"])
        row["point_ref"] = as_json(row["point_ref"])
    return rows


async def journal_for_run(stack: ScopedStack, run_id: str) -> list[dict[str, Any]]:
    """The run's family admission journal (one row per accepted family mutation)."""

    rows = await db_rows(
        stack,
        """
        SELECT family_version, mutation_kind, mutation_key, mutation, decided_at
        FROM mission_control.family_admission_journal
        WHERE run_key = $1
        ORDER BY family_version
        """,
        run_id,
    )
    for row in rows:
        row["mutation"] = as_json(row["mutation"])
    return rows


def units_by_location(points: list[dict[str, Any]]) -> dict[tuple[str, int], str]:
    """`(node_key, cycle) -> unit_key` over the listed points."""

    return {
        (item["location"]["node_key"], item["location"]["cycle"]): item["coordinate"]["unit_key"]
        for item in points
    }


def point_with_role(
    points: list[dict[str, Any]], *, node: str, cycle: int, role: str
) -> dict[str, Any]:
    return next(
        item
        for item in points
        if item["location"]["node_key"] == node
        and item["location"]["cycle"] == cycle
        and role in item["roles"]
    )


def admitted_proposals(journal: list[dict[str, Any]]) -> dict[tuple[str, int], dict[str, Any]]:
    """`(stage_id, stage_cycle_ordinal) -> proposal` of every `operation_admitted` mutation."""

    proposals: dict[tuple[str, int], dict[str, Any]] = {}
    for row in journal:
        mutation = row["mutation"]
        if mutation.get("decision_kind", mutation.get("mutation_kind")) != "operation_admitted":
            continue
        proposal = mutation["decision_payload"]["proposal"]
        candidate = proposal["identity"]["candidate"]
        proposals[(candidate["stage_id"], candidate["stage_cycle_ordinal"])] = proposal
    return proposals


async def settled_generations(stack: ScopedStack, run_id: str) -> list[dict[str, Any]]:
    """Every `checkpoint_transition` of the run's units (the activation key is the unit key)."""

    return await db_rows(
        stack,
        """
        SELECT t.unit_key, t.execution_generation, t.result_checkpoint_key,
               a.expansion_key, a.activation_id::text AS activation_id
        FROM mission_control.checkpoint_transition AS t
        JOIN mission_control.activation AS a
          ON a.installation_id = t.installation_id
         AND a.application_id = t.application_id
         AND a.tenant_id = t.tenant_id
         AND a.activation_key = t.unit_key
        WHERE a.run_id = (SELECT run_id FROM mission_control.mission_run WHERE run_key = $1)
        ORDER BY t.observed_at
        """,
        run_id,
    )


async def point_counts(stack: ScopedStack, run_id: str) -> dict[tuple[str, int], int]:
    rows = await db_rows(
        stack,
        """
        SELECT unit_key, execution_generation, count(*) AS points
        FROM mission_control.cognition_point
        WHERE run_id = (SELECT run_id FROM mission_control.mission_run WHERE run_key = $1)
        GROUP BY unit_key, execution_generation
        """,
        run_id,
    )
    return {(row["unit_key"], row["execution_generation"]): row["points"] for row in rows}


def _write_evidence(name: str, payload: dict[str, Any]) -> Path:
    path = EVIDENCE_ROOT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str))
    return path


async def temporal_diagnostics(stack: ScopedStack, run_id: str) -> list[dict[str, Any]]:
    """Every Temporal workflow of the run with its status and, when closed badly, the failure
    message of its last history event (the family workflow's `ApplicationError`)."""

    rows: list[dict[str, Any]] = []
    async for description in stack.client.list_workflows(
        f"WorkflowId STARTS_WITH '{mission_root_id(stack.scope, run_id)}'"
    ):
        row: dict[str, Any] = {
            "workflow_id": description.id,
            "type": description.workflow_type,
            "status": str(description.status),
        }
        if description.status is not None and description.status.name not in {
            "RUNNING",
            "COMPLETED",
        }:
            handle = stack.client.get_workflow_handle(description.id, run_id=description.run_id)
            history = await handle.fetch_history()
            last = history.events[-1]
            row["last_event"] = str(last)[-3000:]
        rows.append(row)
    return rows


async def run_tracing_to_completion(stack: ScopedStack) -> str:
    """Launch the tracing run and wait for completion; a stall (no model call for
    `STALL_SECONDS`) fails at once with diagnostics instead of waiting out the timeout."""

    started = time.monotonic()
    run_id = await launch(stack, TRACING)
    progress = (len(stack.model_log), time.monotonic())
    while True:
        if await completed(stack, run_id):
            break
        calls = len(stack.model_log)
        now = time.monotonic()
        if calls != progress[0]:
            progress = (calls, now)
        elif now - progress[1] > STALL_SECONDS or now - started > RUN_SECONDS:
            state = await inspect(stack, run_id)
            diagnostics = {
                "run_id": run_id,
                "lifecycle": state.get("lifecycle"),
                "phase": state.get("phase"),
                "runtime_state": state.get("projection", {}).get("runtime_state"),
                "units": state.get("units"),
                "temporal": await temporal_diagnostics(stack, run_id),
                "journal": [
                    (row["family_version"], row["mutation_kind"], row["mutation_key"])
                    for row in await journal_for_run(stack, run_id)
                ],
                "operations": sorted(
                    {item["operation"] for item in stack.model_log if item["model"] == "parent"}
                ),
                "model_calls": calls,
                "event_types": sorted(
                    {item["event_type"] for item in await events_for_run(stack, run_id)}
                ),
            }
            path = _write_evidence("fx-tr-stall.json", diagnostics)
            raise AssertionError(
                f"tracing run {run_id} stalled after {calls} model calls "
                f"({now - started:.0f}s); diagnostics at {path}: "
                f"temporal={diagnostics['temporal']}"
            )
        await asyncio.sleep(2.0)
    print(f"FX-TR: tracing run {run_id} completed in {time.monotonic() - started:.0f}s", flush=True)
    return run_id


def expected_units() -> set[tuple[str, int]]:
    return {("S1", 0)} | {
        (stage, cycle) for stage in ("S2", "S3", "S4") for cycle in range(LAST_CYCLE + 1)
    }


# --- WP-TR-2 helpers -------------------------------------------------------------------------


def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _excerpt(value: Any) -> tuple[str, Any]:
    """A `provider_frame.body_excerpt` (bytea) as text and, when it parses, as JSON."""

    if isinstance(value, bytes | bytearray):
        text = value.decode("utf-8", errors="replace")
    else:
        text = str(value)
    try:
        return text, json.loads(text)
    except ValueError:
        return text, None


async def frames_for_run(stack: ScopedStack, run_id: str) -> list[dict[str, Any]]:
    """The run's `provider_frame` rows joined to their unit (`activation.activation_key`), in
    arrival order per harness execution; `body` is the excerpt parsed as JSON when it is."""

    rows = await db_rows(
        stack,
        """
        SELECT f.frame_id::text AS frame_id, f.activation_id::text AS activation_id,
               a.activation_key AS unit_key, f.attempt_no,
               f.harness_execution_id::text AS harness_execution_id, f.generation,
               f.provider_key, f.arrival_ordinal, f.kind, f.raw_kind, f.closing,
               f.subordinate_ref, f.tool_call_ref, f.body_digest, f.body_bytes,
               f.body_media_type, f.body_excerpt, f.body_artifact_ref, f.native_session_ref,
               f.native_turn_ref, f.observed_at
        FROM mission_control.provider_frame AS f
        JOIN mission_control.activation AS a
          ON a.installation_id = f.installation_id
         AND a.application_id = f.application_id
         AND a.tenant_id = f.tenant_id
         AND a.activation_id = f.activation_id
        WHERE f.run_id = (SELECT run_id FROM mission_control.mission_run WHERE run_key = $1)
        ORDER BY f.harness_execution_id, f.arrival_ordinal
        """,
        run_id,
    )
    for row in rows:
        row["excerpt"], row["body"] = _excerpt(row.pop("body_excerpt"))
    return rows


def frames_in_range(frames: list[dict[str, Any]], point: dict[str, Any]) -> list[dict[str, Any]]:
    """The frames of the point's unit generation whose arrival ordinal is in its range."""

    window = point.get("frames")
    if not window:
        return []
    unit = point["coordinate"]["unit_key"]
    generation = point["coordinate"].get("execution_generation")
    return [
        item
        for item in frames
        if item["unit_key"] == unit
        and (generation is None or item["generation"] == generation)
        and window["from_ordinal"] <= item["arrival_ordinal"] <= window["to_ordinal"]
    ]


def frame_body(frame: dict[str, Any], full_entries: dict[str, dict[str, Any]]) -> Any:
    """The frame's body: the excerpt's JSON, or the `--full` transcript entry's body when the
    frame was promoted (the excerpt is then truncated)."""

    entry = full_entries.get(frame["frame_id"])
    if frame.get("body_artifact_ref") and entry is not None and entry.get("body_excerpt"):
        try:
            return json.loads(entry["body_excerpt"])
        except ValueError:
            pass
    return frame["body"]


async def transcript_entries(
    stack: ScopedStack, run_id: str, *, full: bool = False, **params: Any
) -> list[dict[str, Any]]:
    """Every transcript entry of the run (`GET runs/{id}/transcript?format=json`, paged by
    cursor; the route streams NDJSON unless `format=json` or an `application/json` accept)."""

    entries: list[dict[str, Any]] = []
    since: str | None = None
    while True:
        query: dict[str, Any] = {"limit": 5000, "format": "json", **params}
        if full:
            query["full"] = "true"
        if since:
            query["since"] = since
        response = await stack.http.get(f"{BASE}/{run_id}/transcript", params=query)
        assert response.status_code == 200, (response.status_code, response.text[:800])
        page = response.json()
        entries.extend(page["entries"])
        if not page.get("has_more") or not page.get("next_cursor"):
            return entries
        since = page["next_cursor"]


def entries_by_frame(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        item["refs"]["frame_id"]: item
        for item in entries
        if item.get("refs") and item["refs"].get("frame_id")
    }


async def harness_executions(stack: ScopedStack, run_id: str) -> list[dict[str, Any]]:
    rows = await db_rows(
        stack,
        """
        SELECT harness_execution_id::text AS harness_execution_id, generation, native_identity
        FROM mission_control.harness_execution
        WHERE run_id = (SELECT run_id FROM mission_control.mission_run WHERE run_key = $1)
        ORDER BY created_at
        """,
        run_id,
    )
    for row in rows:
        row["native_identity"] = as_json(row["native_identity"]) or {}
    return rows


async def settlements_for_run(stack: ScopedStack, run_id: str) -> list[dict[str, Any]]:
    """The latest settlement of every claimed operation: `(operation id, status, usage)`."""

    rows = await db_rows(
        stack,
        """
        SELECT DISTINCT ON (c.semantic_attempt_key)
               c.semantic_attempt_key, s.status, s.usage_payload
        FROM mission_control.operation_claim AS c
        JOIN mission_control.operation_settlement AS s
          ON (s.installation_id, s.application_id, s.tenant_id, s.claim_key)
           = (c.installation_id, c.application_id, c.tenant_id, c.claim_key)
        WHERE c.run_key = $1
        ORDER BY c.semantic_attempt_key, s.settlement_revision DESC
        """,
        run_id,
    )
    return [
        {
            "operation": row["semantic_attempt_key"].split(":operation:", 1)[-1],
            "status": row["status"],
            "usage": as_json(row["usage_payload"]),
        }
        for row in rows
    ]


async def state_as_of(stack: ScopedStack, run_id: str, point: dict[str, Any]) -> dict[str, Any]:
    response = await stack.http.get(f"{BASE}/{run_id}/points/{point['point_id']}/state-as-of")
    assert response.status_code == 200, response.text
    return response.json()


async def resolve_ref(
    stack: ScopedStack,
    run_id: str,
    ref: str | None,
    digest: str | None,
    full_by_ref: dict[str, dict[str, Any]],
) -> str | None:
    """How a promoted object reference resolved to bytes of the expected digest, or None.

    First through `GET transcript?full=true` (an entry whose `refs.artifact_ref` is the ref
    carries the whole body), then through `GET runs/{id}/artifacts/{ref}` (§P4.2, WP-TR-3),
    then read back in-process through the tenant's registered `GrantedArtifactBodyReader`
    (the reader `full=true` uses, under the `workflow.result.read` grant): a per-message
    object of a `model_request` is not a transcript entry of its own.
    """

    if not ref:
        return None
    entry = full_by_ref.get(ref)
    if entry is not None and entry.get("body_excerpt") is not None:
        if digest is None or sha256_text(entry["body_excerpt"]) == digest:
            return "transcript"
    response = await stack.http.get(f"{BASE}/{run_id}/artifacts/{ref}")
    if response.status_code == 200:
        actual = "sha256:" + hashlib.sha256(response.content).hexdigest()
        if digest is None or actual == digest:
            return "artifacts_route"
    readers = getattr(stack.application.state, "mission_control_artifact_body_readers", {})
    reader = next(
        (item for item in readers.values() if getattr(item, "request_scope", None) == stack.scope),
        None,
    )
    if reader is not None:
        actor = ActorContext(
            actor_id=technical.OPERATOR, permissions=frozenset({"workflow.result.read"})
        )
        try:
            text = await reader.read(stack.scope, actor, ref)
        except (LookupError, PermissionError):
            return None
        if digest is None or sha256_text(text) == digest:
            return "body_reader"
    return None


def is_child_point(point: dict[str, Any]) -> bool:
    coordinate = point["coordinate"]["point"]
    key = coordinate.get("key") or {}
    return bool(coordinate.get("subordinate_ref")) or bool(key.get("checkpoint_ns"))


def unit_points(points: list[dict[str, Any]], unit_key: str) -> list[dict[str, Any]]:
    return sorted(
        (item for item in points if item["coordinate"]["unit_key"] == unit_key),
        key=lambda item: (
            item["ordinal"] if item["ordinal"] is not None else -1,
            item["recorded_at"],
        ),
    )


def point_holding(points: list[dict[str, Any]], ordinal: int) -> dict[str, Any] | None:
    """The root point whose frame range holds the arrival ordinal."""

    for item in points:
        window = item.get("frames")
        if (
            window
            and not is_child_point(item)
            and window["from_ordinal"] <= ordinal <= window["to_ordinal"]
        ):
            return item
    return None


def find_keys(value: Any, name: str, found: list[Any] | None = None) -> list[Any]:
    """Every value under a key called `name`, anywhere in a JSON document."""

    found = [] if found is None else found
    if isinstance(value, dict):
        for key, item in value.items():
            if key == name:
                found.append(item)
            find_keys(item, name, found)
    elif isinstance(value, list):
        for item in value:
            find_keys(item, name, found)
    return found


async def terminal(stack: ScopedStack, run_id: str) -> bool:
    state = await inspect(stack, run_id)
    return state["lifecycle"] in {"completed", "cancelled", "failed"}


async def cancel_immediately(stack: ScopedStack, run_id: str) -> dict[str, Any]:
    """`cancel` with `urgency: immediate` over the commands route, re-reading a stale version."""

    body: dict[str, Any] = {}
    response = None
    for _attempt in range(12):
        state = await inspect(stack, run_id)
        body = {
            "request_id": str(uuid4()),
            "expected_version": state["version"],
            "expected_generation": state["execution_generation"],
            "target": {"kind": "run", "id": run_id},
            "kind": "cancel",
            "payload": {"urgency": "immediate"},
            "reason": "FX-TR-HOOK: stop fence",
        }
        response = await stack.http.post(f"{BASE}/{run_id}/commands", json=body)
        if response.status_code == 202:
            return body
        assert response.status_code == 409, response.text
    raise AssertionError(f"cancel never accepted: {response.text if response else 'no response'}")


# --- Smoke proof -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tracing_blueprint_cycles_s2_twice_and_completes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The FX-TR fixture itself: `S2` is cycled twice (units at cycles 0, 1 and 2), `S3` and
    `S4` run after the last cycle, every unit's points index the saver, and the run completes.
    Writes `.scratch/tracing-stage-1/fx-tr-smoke.json` with the event types, the journal
    mutation kinds and the unit map for the WP-TR proofs."""

    async with scoped_stack(tmp_path, monkeypatch) as stack:
        run_id = await run_tracing_to_completion(stack)
        state = await inspect(stack, run_id)
        assert state["lifecycle"] == "completed", state
        points = await all_points(stack, run_id)
        units = units_by_location(points)
        assert all(item["location"]["family"] == "stage_graph" for item in points)
        assert set(units) == expected_units(), sorted(units)
        # The `node`/`cycle` filters narrow to exactly one unit each.
        for cycle in range(LAST_CYCLE + 1):
            filtered = await all_points(stack, run_id, node=CYCLE_STAGE, cycle=cycle)
            assert filtered, (CYCLE_STAGE, cycle)
            assert {item["coordinate"]["unit_key"] for item in filtered} == {
                units[(CYCLE_STAGE, cycle)]
            }
        assert max(cycle for node, cycle in units if node == CYCLE_STAGE) == LAST_CYCLE
        # The scripted model answered `cycle` at ordinals 0 and 1 and `accept` at 2: two
        # `cycle_decided` family mutations, and no third cycle.
        journal = await journal_for_run(stack, run_id)
        kinds = [row["mutation"].get("decision_kind") for row in journal]
        assert kinds.count("cycle_decided") == LAST_CYCLE, kinds
        # S3 and S4 ran after the last cycle: their cycle-2 units settled after S2@c2's result.
        last_result = point_with_role(points, node=CYCLE_STAGE, cycle=LAST_CYCLE, role="result")
        for stage in ("S3", "S4"):
            first = min(
                (
                    item
                    for item in points
                    if item["location"]["node_key"] == stage
                    and item["location"]["cycle"] == LAST_CYCLE
                ),
                key=lambda item: item["recorded_at"],
            )
            assert first["recorded_at"] >= last_result["recorded_at"], (stage, first, last_result)
        # Every unit's root points index the saver (one row per stamped root checkpoint); the
        # sync child's nested points (WP-TR-2, `subordinate_ref`) are FX-TR-SUB's concern.
        saver = await saver_root_checkpoints(stack)
        root_points = [item for item in points if not is_child_point(item)]
        for unit_key in set(units.values()):
            assert_points_index_the_saver(root_points, saver, unit_key=unit_key)
        # The scripted cognition saw every stage once per cycle ordinal.
        parent_calls = [item for item in stack.model_log if item["model"] == "parent"]
        operations = {item["operation"] for item in parent_calls}
        assert {stage for stage, _cycle in units} == {
            op.split(":stage:", 1)[1].split(":", 1)[0] for op in operations
        }
        events = await events_for_run(stack, run_id)
        assert events, "the run recorded no mission events"
        evidence = {
            "run_id": run_id,
            "units": {f"{node}@c{cycle}": key for (node, cycle), key in sorted(units.items())},
            "event_types": sorted({item["event_type"] for item in events}),
            "event_count": len(events),
            "journal": [
                (row["family_version"], row["mutation_kind"], row["mutation_key"])
                for row in journal
            ],
            "temporal_executions": state.get("temporal_executions"),
            "units_inspection": state.get("units"),
            "operations": sorted(operations),
        }
        print(f"FX-TR: evidence at {_write_evidence('fx-tr-smoke.json', evidence)}", flush=True)
        assert state["lifecycle"] == "completed"


# --- WP-TR-1 proofs --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fx_tr_reconcile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """FX-TR-RECONCILE (WP-TR-1, TRACING-PROPOSAL §P3.1): with the test-only fault
    `MISSION_CONTROL_TEST_POINTS_FAULT=skip` (the production workers run in this process, so
    the environment reaches them), settled unit generations have a `checkpoint_transition`
    but no `cognition_point` rows; `POST runs/{id}/points:reconcile` answers
    `mc.points_reconciliation.v1` with `points_added > 0`, after which every stamped root
    checkpoint of the saver has exactly one point row written by the reconciler, with frame
    ranges where frames exist.

    Passes only once the WP-TR-1 reconciler and the fault hook land (source streams)."""

    monkeypatch.setenv("MISSION_CONTROL_TEST_POINTS_FAULT", "skip")
    assert os.environ["MISSION_CONTROL_TEST_POINTS_FAULT"] == "skip"
    async with scoped_stack(tmp_path, monkeypatch) as stack:
        run_id = await run_tracing_to_completion(stack)
        generations = await settled_generations(stack, run_id)
        assert generations, "no settled unit generation (checkpoint_transition) for the run"
        before = await point_counts(stack, run_id)
        without_points = [
            item
            for item in generations
            if (item["unit_key"], item["execution_generation"]) not in before
        ]
        assert without_points, (
            "MISSION_CONTROL_TEST_POINTS_FAULT=skip left no settled generation without "
            f"points; generations={len(generations)} point_counts={before}"
        )
        response = await stack.http.post(f"{BASE}/{run_id}/points:reconcile", json={})
        assert response.status_code in {200, 202}, response.text
        outcome = response.json()
        assert outcome.get("schema_version") == "mc.points_reconciliation.v1", outcome
        assert outcome["points_added"] > 0, outcome
        assert outcome["generations_checked"] >= len(without_points), outcome
        assert not outcome.get("saver_unreachable"), outcome
        # Every stamped root checkpoint has exactly one point row, written by the reconciler.
        points = await all_points(stack, run_id)
        saver = await saver_root_checkpoints(stack)
        restored_units = {item["unit_key"] for item in without_points}
        assert restored_units <= {item["coordinate"]["unit_key"] for item in points}
        # The reconciler restores the root points (the saver's stamped root checkpoints); the
        # sync child's nested points need the live recorder and are FX-TR-SUB's concern.
        root_points = [item for item in points if not is_child_point(item)]
        for unit_key in restored_units:
            assert_points_index_the_saver(root_points, saver, unit_key=unit_key)
            mine = [item for item in root_points if item["coordinate"]["unit_key"] == unit_key]
            assert {item["written_by"] for item in mine} == {"reconciler"}, unit_key
        # A second reconciliation finds nothing to add (idempotent on the point identity).
        again = await stack.http.post(f"{BASE}/{run_id}/points:reconcile", json={})
        assert again.status_code in {200, 202}, again.text
        assert again.json()["points_added"] == 0, again.json()
        _write_evidence(
            "fx-tr-reconcile.json",
            {
                "run_id": run_id,
                "outcome": outcome,
                "again": again.json(),
                "restored": sorted(restored_units),
            },
        )


def missionctl(url: str, token: str, *args: str) -> subprocess.Popen[bytes]:
    """A separate `missionctl` process (the Windows selector loop cannot spawn asyncio ones)."""

    return subprocess.Popen(
        [sys.executable, "-m", "mission_control.interfaces.cli", *args],
        env={
            **os.environ,
            "MISSION_CONTROL_URL": url,
            "MISSION_CONTROL_APPLICATION_ID": "biotech",
            "MISSION_CONTROL_TOKEN": token,
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


@pytest.mark.asyncio
async def test_fx_tr_reconcile_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """FX-TR-RECONCILE, CLI form: `missionctl run points RUN --reconcile` over real loopback
    HTTP restores the points the fault skipped and prints the `mc.points_reconciliation.v1`
    outcome. Skipped with a note while the CLI has no `--reconcile` (argparse rejects it)."""

    monkeypatch.setenv("MISSION_CONTROL_TEST_POINTS_FAULT", "skip")
    async with (
        scoped_stack(tmp_path, monkeypatch) as stack,
        serve_loopback(stack.application) as url,
    ):
        run_id = await run_tracing_to_completion(stack)
        before = await point_counts(stack, run_id)
        generations = await settled_generations(stack, run_id)
        assert any(
            (item["unit_key"], item["execution_generation"]) not in before for item in generations
        ), "the fault hook left every settled generation with points"
        process = missionctl(url, stack.token, "run", "points", run_id, "--reconcile")
        stdout, stderr = await asyncio.to_thread(process.communicate, timeout=120)
        out, err = stdout.decode(), stderr.decode()
        if process.returncode == 2 and "--reconcile" in err:
            pytest.skip(
                "missionctl run points has no --reconcile yet (WP-TR-1 source stream); "
                f"argparse said: {err.strip().splitlines()[-1]}"
            )
        assert process.returncode == 0, (out, err)
        assert "mc.points_reconciliation.v1" in out, (out, err)
        after = await point_counts(stack, run_id)
        assert sum(after.values()) > sum(before.values()), (before, after)


@pytest.mark.asyncio
async def test_fx_tr_step_lifecycle_half(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """FX-TR-STEP, the lifecycle and "who" questions of WP-TR-1 (TRACING-PROPOSAL §P1.1 rows
    "Unit released", "Attempt settles", "Decision over a result", "Cycle advance"; §P3.2,
    §P3.8): after a completed tracing run,

    - every derived frame event (`session.*`, `tool_call.completed`, `attempt.completed`)
      carries `activation_id` and `unit_key`;
    - the family admission events issued for a unit carry `unit_key`;
    - a `completion_decision` row keyed by the result mutation id (`result-<sha7>`) exists for
      every settled stage unit, with a `completion_candidate` keyed by the settlement;
    - `S2`'s cycle-1 and cycle-2 input points carry `parent_coordinate` = the previous
      cycle's result point and the role `cycle_start`;
    - the proposal of `S2@c1` carries `continues_from.prior_unit_key` = `S2@c0`'s unit key,
      and `S3`'s proposal carries `released_by` naming `S2` with the dependency and join ids;
    - `mission_run.temporal_workflow_id` / `temporal_run_id` are set and equal the family
      workflow the inspection route reports.

    Passes only once the WP-TR-1 writers land (source streams)."""

    async with scoped_stack(tmp_path, monkeypatch) as stack:
        run_id = await run_tracing_to_completion(stack)
        points = await all_points(stack, run_id)
        units = units_by_location(points)
        assert set(units) == expected_units(), sorted(units)
        events = await events_for_run(stack, run_id)
        failures: list[str] = []

        # 1. Derived frame events carry the activation and the unit.
        derived = [
            item
            for item in events
            if item["event_type"].startswith(DERIVED_EVENT_PREFIXES)
            or item["event_type"] in DERIVED_EVENT_TYPES
        ]
        assert derived, sorted({item["event_type"] for item in events})
        # The attempt outcome of a provider `finished` is deferred to the operation settlement
        # on this lane (`adapter._project_frame_facts`, `completion_policy="deferred"`), so
        # `attempt.completed` is not among the frame-derived events; the session and tool facts are.
        assert {"session.started", "session.ended", "tool_call.completed"} <= {
            item["event_type"] for item in derived
        }, sorted({item["event_type"] for item in derived})
        unjoined = [
            (item["seq"], item["event_type"], item["activation_id"], item["unit_key"])
            for item in derived
            if not item["activation_id"] or not item["unit_key"]
        ]
        if unjoined:
            failures.append(
                f"derived events without activation_id/unit_key: {len(unjoined)} of "
                f"{len(derived)}, first {unjoined[:5]}"
            )
        else:
            assert {item["unit_key"] for item in derived} <= set(units.values())

        # 2. The family admission events of a unit carry its unit key.
        admissions = [item for item in events if item["event_type"] in ADMISSION_EVENT_TYPES]
        assert admissions, sorted({item["event_type"] for item in events})
        # Run-level admissions (the baseline hold, the cycle usage) keep NULLs; the unit
        # admissions name their unit, one per admitted unit at least.
        keyed = [item for item in admissions if item["unit_key"]]
        if len(keyed) < len(units):
            failures.append(
                f"admission events carrying unit_key: {len(keyed)} of {len(admissions)} "
                f"({sorted({item['event_type'] for item in admissions})}); "
                f"expected at least one per unit ({len(units)})"
            )
        else:
            assert {item["unit_key"] for item in keyed} == set(units.values())

        # 3. Completion decisions keyed by the result mutation, candidates by the settlement.
        decisions = await db_rows(
            stack,
            """
            SELECT decision_key, result_disposition, activation_id::text AS activation_id,
                   candidate_id::text AS candidate_id, result_refs, reason_codes
            FROM mission_control.completion_decision
            WHERE run_id = (SELECT run_id FROM mission_control.mission_run WHERE run_key = $1)
            ORDER BY decided_at
            """,
            run_id,
        )
        generations = await settled_generations(stack, run_id)
        settled_units = {item["unit_key"] for item in generations}
        if not decisions:
            failures.append("no completion_decision rows for the run")
        else:
            bad_keys = [
                d["decision_key"]
                for d in decisions
                if not RESULT_DECISION_KEY.match(d["decision_key"])
            ]
            assert not bad_keys, bad_keys
            decided_activations = {d["activation_id"] for d in decisions if d["activation_id"]}
            settled_activations = {item["activation_id"] for item in generations}
            if not settled_activations <= decided_activations:
                failures.append(
                    "settled units without a completion_decision: "
                    f"{len(settled_activations - decided_activations)} of {len(settled_units)}"
                )
            candidates = await db_rows(
                stack,
                """
                SELECT c.candidate_id::text AS candidate_id, c.candidate_key,
                       c.activation_id::text AS activation_id
                FROM mission_control.completion_candidate AS c
                JOIN mission_control.activation AS a
                  ON a.installation_id = c.installation_id
                 AND a.application_id = c.application_id
                 AND a.tenant_id = c.tenant_id
                 AND a.activation_id = c.activation_id
                WHERE a.run_id = (SELECT run_id FROM mission_control.mission_run WHERE run_key = $1)
                """,
                run_id,
            )
            settlements = await db_rows(
                stack,
                "SELECT settlement_key, operation_settlement_id::text AS settlement_id "
                "FROM mission_control.operation_settlement",
            )
            settlement_keys = {row["settlement_key"] for row in settlements} | {
                row["settlement_id"] for row in settlements
            }
            by_id = {row["candidate_id"]: row for row in candidates}
            missing_candidates = [
                d["decision_key"] for d in decisions if d["candidate_id"] not in by_id
            ]
            if missing_candidates:
                failures.append(f"decisions without a candidate row: {missing_candidates[:5]}")
            else:
                unkeyed = [
                    by_id[d["candidate_id"]]["candidate_key"]
                    for d in decisions
                    if by_id[d["candidate_id"]]["candidate_key"] not in settlement_keys
                ]
                if unkeyed:
                    failures.append(f"candidates not keyed by a settlement: {unkeyed[:5]}")

        # 4. The cycle-start points continue from the previous cycle's result point.
        for cycle in range(1, LAST_CYCLE + 1):
            first = point_with_role(points, node=CYCLE_STAGE, cycle=cycle, role="input")
            prior = point_with_role(points, node=CYCLE_STAGE, cycle=cycle - 1, role="result")
            if "cycle_start" not in first["roles"]:
                failures.append(f"S2@c{cycle} input point roles {first['roles']} lack cycle_start")
            if first["parent_coordinate"] != prior["coordinate"]:
                failures.append(
                    f"S2@c{cycle} input point parent_coordinate {first['parent_coordinate']} "
                    f"!= S2@c{cycle - 1} result coordinate"
                )

        # 5. `continues_from` on S2@c1 and `released_by` on S3@c2.
        journal = await journal_for_run(stack, run_id)
        proposals = admitted_proposals(journal)
        assert set(proposals) == expected_units(), sorted(proposals)
        continues = proposals[(CYCLE_STAGE, 1)].get("continues_from")
        if not continues:
            failures.append("S2@c1 proposal has no continues_from")
        elif continues.get("prior_unit_key") != units[(CYCLE_STAGE, 0)]:
            failures.append(
                f"S2@c1 continues_from.prior_unit_key {continues.get('prior_unit_key')} != "
                f"S2@c0 {units[(CYCLE_STAGE, 0)]}"
            )
        released = proposals[("S3", LAST_CYCLE)].get("released_by")
        if not released:
            failures.append("S3@c2 proposal has no released_by")
        else:
            matching = [
                item
                for item in released
                if item.get("dependency_id") == "S2-to-S3"
                and item.get("join_id") == "S3-ready"
                and item.get("producer_unit_key") == units[(CYCLE_STAGE, LAST_CYCLE)]
            ]
            if not matching:
                failures.append(f"S3@c2 released_by does not name S2@c2 with its ids: {released}")

        # 6. The run row names its Temporal workflow, as the inspection reports it.
        run_rows = await db_rows(
            stack,
            "SELECT temporal_workflow_id, temporal_run_id FROM mission_control.mission_run "
            "WHERE run_id = (SELECT run_id FROM mission_control.mission_run WHERE run_key = $1)",
            run_id,
        )
        assert len(run_rows) == 1, run_rows
        row = run_rows[0]
        state = await inspect(stack, run_id)
        family = [
            item
            for item in state.get("temporal_executions", ())
            if item.get("workflow_id") == mission_root_id(stack.scope, run_id)
        ]
        if not row["temporal_workflow_id"] or not row["temporal_run_id"]:
            failures.append(f"mission_run temporal ids are NULL: {row}")
        else:
            assert row["temporal_workflow_id"] == mission_root_id(stack.scope, run_id), row
            if family:
                assert row["temporal_run_id"] in {item["temporal_run_id"] for item in family}, (
                    row,
                    family,
                )

        _write_evidence(
            "fx-tr-step-lifecycle.json",
            {
                "run_id": run_id,
                "failures": failures,
                "derived_event_types": sorted({item["event_type"] for item in derived}),
                "admission_event_types": sorted({item["event_type"] for item in admissions}),
                "decisions": decisions,
                "temporal": row,
                "temporal_executions": state.get("temporal_executions"),
            },
        )
        assert not failures, "\n".join(failures)


# --- WP-TR-2 proofs --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fx_tr_step(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """FX-TR-STEP in full (TRACING-PROPOSAL §P9; §P3.3-P3.7, §P4.2): after a completed tracing
    run, for every point of `S2@c1` (root and child),

    - the `model_request` frames in the point's frame range list message ids whose bodies
      resolve: AI and tool entries by digest against the run's `message` /
      `tool_call_completed` frames, human and system entries by a `ref` that
      `GET transcript?full=true` (or the artifacts route) resolves to bytes of that digest;
    - the promoted `message` and `tool_call_completed` frames resolve `--full`, and the
      >8 KiB `lookup_binding_marker` result's entry carries the whole body under `full=true`;
    - `environment_materialized` names the seeded packet files with the digests the saver's
      state reports, and the input point's `channel_facts.materialization_digest` is its digest;
    - the released-by, decision and cycle facts appear (the lifecycle helpers);
    - the derived frame events carry `activation_id`, `unit_key` and `point_ref`;
    - `harness_execution.native_identity.frame_capture_profile == "standard"`;
    - the result point's `workspace_checkpoint_ref` is a `workspace-closure://` reference;
    - with the API's saver closed, the transcript and points routes still answer.

    Passes only once the WP-TR-2 source streams land (observer, promoter, environment frame)."""

    async with scoped_stack(tmp_path, monkeypatch) as stack:
        run_id = await run_tracing_to_completion(stack)
        points = await all_points(stack, run_id)
        units = units_by_location(points)
        assert set(units) == expected_units(), sorted(units)
        unit = units[(CYCLE_STAGE, 1)]
        mine = unit_points(points, unit)
        roots = [item for item in mine if not is_child_point(item)]
        children = [item for item in mine if is_child_point(item)]
        frames = await frames_for_run(stack, run_id)
        unit_frames = [item for item in frames if item["unit_key"] == unit]
        assert unit_frames, f"no provider frames for {unit}"
        plain = await transcript_entries(stack, run_id)
        full = await transcript_entries(stack, run_id, full=True)
        plain_by_frame, full_by_frame = entries_by_frame(plain), entries_by_frame(full)
        full_by_ref = {
            item["refs"]["artifact_ref"]: item
            for item in full
            if item.get("refs") and item["refs"].get("artifact_ref")
        }
        failures: list[str] = []
        evidence: dict[str, Any] = {
            "run_id": run_id,
            "unit": unit,
            "root_points": len(roots),
            "child_points": len(children),
            "frame_kinds": sorted({item["kind"] for item in unit_frames}),
        }

        # 1. model_request frames in every point's range: message ids whose bodies resolve.
        digests = {
            item["body_digest"]
            for item in frames
            if item["kind"] in {"message", "tool_call_completed"}
        }
        model_requests = [item for item in unit_frames if item["kind"] == "model_request"]
        if not model_requests:
            failures.append(
                f"no model_request frames for {CYCLE_STAGE}@c1 (kinds: "
                f"{evidence['frame_kinds']}); WP-TR-2 model-request observer"
            )
        # A child's model_request sits in its own nested point's range and in the parent
        # step's, so coverage counts distinct frames.
        covered: set[str] = set()
        resolutions: dict[str, int] = {}
        for point in mine:
            for frame in frames_in_range(unit_frames, point):
                if frame["kind"] != "model_request":
                    continue
                covered.add(frame["provider_key"])
                body = frame_body(frame, full_by_frame)
                messages = body.get("messages") if isinstance(body, dict) else None
                if not messages:
                    failures.append(f"model_request {frame['provider_key']} lists no messages")
                    continue
                for entry in messages:
                    kind, digest, ref = entry.get("type"), entry.get("digest"), entry.get("ref")
                    if kind in {"ai", "tool"}:
                        if digest not in digests:
                            failures.append(
                                f"model_request {frame['provider_key']}: {kind} message "
                                f"{entry.get('id')} digest {digest} matches no message/"
                                "tool_call_completed frame of the run"
                            )
                    else:
                        how = await resolve_ref(stack, run_id, ref, digest, full_by_ref)
                        if how is None:
                            failures.append(
                                f"model_request {frame['provider_key']}: {kind} message "
                                f"{entry.get('id')} ref {ref!r} does not resolve to {digest}"
                            )
                        else:
                            resolutions[how] = resolutions.get(how, 0) + 1
        if model_requests and len(covered) != len(model_requests):
            failures.append(
                f"model_request frames outside every point range: {len(model_requests)} "
                f"frames, {len(covered)} in ranges"
            )
        evidence["model_requests"] = len(model_requests)
        evidence["ref_resolutions"] = resolutions

        # 2. The message and tool_call_completed frames resolve --full; the >8 KiB tool result.
        big = [
            item
            for item in unit_frames
            if item["kind"] == "tool_call_completed" and item["body_bytes"] > EXCERPT_CAP_BYTES
        ]
        evidence["over_cap_tool_results"] = [
            (item["tool_call_ref"], item["body_bytes"], item["body_artifact_ref"]) for item in big
        ]
        if not big:
            failures.append(
                f"no tool_call_completed frame over {EXCERPT_CAP_BYTES} bytes in {unit} "
                f"(fixture MCP result is at least {technical.MCP_RESULT_MIN_BYTES} bytes)"
            )
        marker = f"MCP-BOUND::{technical.MCP_CODE}::EXACT"
        for frame in big:
            if not frame["body_artifact_ref"]:
                failures.append(
                    f"over-cap tool result {frame['tool_call_ref']} ({frame['body_bytes']} B) "
                    "was not promoted (no body_artifact_ref); WP-TR-2 promoter"
                )
            elif not FRAME_BODY_REF.match(frame["body_artifact_ref"]):
                failures.append(f"unexpected body_artifact_ref {frame['body_artifact_ref']}")
            entry = plain_by_frame.get(frame["frame_id"])
            whole = full_by_frame.get(frame["frame_id"])
            if whole is None:
                failures.append(f"no transcript entry for frame {frame['frame_id']}")
                continue
            excerpt = (entry or {}).get("body_excerpt") or ""
            text = whole.get("body_excerpt") or ""
            if len(text) <= len(excerpt):
                failures.append(
                    f"full=true body ({len(text)} chars) is not longer than the excerpt "
                    f"({len(excerpt)} chars) for tool result {frame['tool_call_ref']}"
                )
            if marker not in text or technical.rrm009_mcp_server.LAST_LINE_PREFIX not in text:
                failures.append(
                    f"full=true body of tool result {frame['tool_call_ref']} lacks the whole "
                    f"MCP result (marker and closing line); {len(text)} chars"
                )
        promoted = [
            item
            for item in unit_frames
            if item["kind"] in {"message", "tool_call_completed"} and item["body_artifact_ref"]
        ]
        for frame in promoted:
            whole = full_by_frame.get(frame["frame_id"])
            text = (whole or {}).get("body_excerpt") or ""
            if whole is None or sha256_text(text) != frame["body_digest"]:
                failures.append(
                    f"promoted {frame['kind']} {frame['frame_id']} did not resolve --full to "
                    f"its digest ({len(text.encode('utf-8'))} of {frame['body_bytes']} bytes)"
                )
        evidence["promoted_frames"] = len(promoted)

        # 3. The environment: the seeded files with the digests the saver's state reports.
        environment = [item for item in unit_frames if item["kind"] == "environment_materialized"]
        first = next(item for item in roots if "input" in item["roles"])
        result = next(item for item in roots if "result" in item["roles"])
        result_state = await state_as_of(stack, run_id, result)
        state_digests = {
            item["path"]: item.get("digest") for item in result_state["state"]["files"]
        }
        if not environment:
            failures.append(
                f"no environment_materialized frame for {unit}; WP-TR-2 environment frame"
            )
        else:
            body = frame_body(environment[0], full_by_frame)
            manifest = body if isinstance(body, dict) else {}
            named = {item.get("path"): item.get("digest") for item in manifest.get("files") or []}
            if not set(named) >= PACKET_FILES:
                failures.append(
                    f"environment_materialized names {sorted(named)}; expected the seeded "
                    f"{sorted(PACKET_FILES)}"
                )
            for path in PACKET_FILES & set(named):
                if state_digests.get(path) != named[path]:
                    failures.append(
                        f"environment_materialized digest of {path} {named[path]} != the "
                        f"state's {state_digests.get(path)}"
                    )
            facts = first.get("channel_facts") or {}
            if not manifest.get("digest") or facts.get("materialization_digest") != manifest.get(
                "digest"
            ):
                failures.append(
                    f"input point channel_facts.materialization_digest "
                    f"{facts.get('materialization_digest')} != manifest digest "
                    f"{manifest.get('digest')}"
                )
            evidence["environment"] = {"files": named, "digest": manifest.get("digest")}
        packets = await db_rows(
            stack,
            "SELECT node_key, activation_key, packet_digest, packet FROM "
            "mission_control.context_selection WHERE run_key = $1",
            run_id,
        )
        evidence["packets"] = [
            {
                "node_key": row["node_key"],
                "activation_key": row["activation_key"],
                "packet_digest": row["packet_digest"],
                "items": [
                    (item.get("content_digest"), (item.get("materialize") or {}).get("path"))
                    for item in (as_json(row["packet"]) or {}).get("items", [])
                ],
            }
            for row in packets
        ]

        # 4. Released-by, decision and cycle facts (the lifecycle helpers).
        journal = await journal_for_run(stack, run_id)
        proposals = admitted_proposals(journal)
        continues = proposals[(CYCLE_STAGE, 1)].get("continues_from") or {}
        if continues.get("prior_unit_key") != units[(CYCLE_STAGE, 0)]:
            failures.append(f"S2@c1 continues_from {continues} does not name S2@c0")
        released = proposals[("S3", LAST_CYCLE)].get("released_by") or []
        if not any(
            item.get("producer_unit_key") == units[(CYCLE_STAGE, LAST_CYCLE)] for item in released
        ):
            failures.append(
                f"S3@c{LAST_CYCLE} released_by {released} does not name S2@c{LAST_CYCLE}"
            )
        kinds = [row["mutation"].get("decision_kind") for row in journal]
        if kinds.count("cycle_decided") != LAST_CYCLE:
            failures.append(
                f"cycle_decided mutations: {kinds.count('cycle_decided')} != {LAST_CYCLE}"
            )
        decisions = await db_rows(
            stack,
            """
            SELECT d.decision_key, d.result_disposition, a.activation_key AS unit_key
            FROM mission_control.completion_decision AS d
            JOIN mission_control.activation AS a
              ON a.installation_id = d.installation_id
             AND a.application_id = d.application_id
             AND a.tenant_id = d.tenant_id
             AND a.activation_id = d.activation_id
            WHERE d.run_id = (SELECT run_id FROM mission_control.mission_run WHERE run_key = $1)
            """,
            run_id,
        )
        if not any(row["unit_key"] == unit for row in decisions):
            failures.append(f"no completion_decision for {unit}")
        by_stage = await stack.http.get(
            f"{BASE}/{run_id}/transcript",
            params={"by": "stage", "unit": unit, "limit": 50, "format": "json"},
        )
        evidence["transcript_by_stage_status"] = by_stage.status_code

        # 5. The derived events carry the activation, the unit and the point.
        events = await events_for_run(stack, run_id)
        derived = [
            item
            for item in events
            if item["unit_key"] == unit
            and (
                item["event_type"].startswith(DERIVED_EVENT_PREFIXES)
                or item["event_type"] in DERIVED_EVENT_TYPES
            )
        ]
        if not derived:
            failures.append(f"no derived frame events joined to {unit}")
        # A session or turn start precedes its first point; every other derived fact closes
        # at a point (the reducer's `checkpoint_point_refs` over the closing frames).
        unjoined = [
            (item["seq"], item["event_type"])
            for item in derived
            if not item["activation_id"]
            or not item["unit_key"]
            or (not item["point_ref"] and item["event_type"] not in POINTLESS_EVENT_TYPES)
        ]
        if unjoined:
            failures.append(
                f"derived events of {unit} without activation_id/unit_key/point_ref: "
                f"{len(unjoined)} of {len(derived)}, first {unjoined[:5]}"
            )
        evidence["derived_events"] = len(derived)

        # 6. The capture profile on the harness execution.
        executions = await harness_executions(stack, run_id)
        profiles = {item["native_identity"].get("frame_capture_profile") for item in executions}
        if profiles != {"standard"}:
            failures.append(
                f"harness_execution.native_identity.frame_capture_profile: {profiles} != "
                "{'standard'}"
            )
        evidence["capture_profiles"] = sorted(str(item) for item in profiles)

        # 7. The result point's workspace checkpoint reference.
        reference = result.get("workspace_checkpoint_ref")
        if not reference or not WORKSPACE_CHECKPOINT_REF.match(reference):
            failures.append(f"result point workspace_checkpoint_ref {reference!r} is not set")
        evidence["workspace_checkpoint_ref"] = reference

        # 8. With the saver closed, the transcript and points routes still answer.
        closed = await close_saver(stack)
        evidence["saver_closed"] = closed
        if not closed:
            failures.append("could not close the API saver (no pinned saver reachable)")
        after_full = await stack.http.get(
            f"{BASE}/{run_id}/transcript",
            params={"full": "true", "limit": 50, "format": "json"},
        )
        after_points = await stack.http.get(f"{BASE}/{run_id}/points", params={"limit": 50})
        # `state-as-of` needs the saver: today the route lets the driver error escape (the
        # ASGI transport re-raises it); FX-TR-REMOTE (WP-TR-3) expects `503 state_unavailable`.
        try:
            after_state = await stack.http.get(
                f"{BASE}/{run_id}/points/{result['point_id']}/state-as-of"
            )
            state_outcome: str | int = after_state.status_code
        except Exception as error:  # recorded as evidence, not asserted
            state_outcome = f"raised {type(error).__name__}: {error}"
        evidence["saver_closed_reads"] = {
            "transcript_full": after_full.status_code,
            "points": after_points.status_code,
            "state_as_of": state_outcome,
        }
        if after_full.status_code != 200 or after_points.status_code != 200:
            failures.append(
                f"with the saver closed: transcript?full=true {after_full.status_code}, "
                f"points {after_points.status_code}"
            )

        evidence["failures"] = failures
        print(f"FX-TR-STEP: evidence at {_write_evidence('fx-tr-step.json', evidence)}", flush=True)
        assert not failures, "\n".join(failures)


@pytest.mark.asyncio
async def test_fx_tr_sub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """FX-TR-SUB (TRACING-PROPOSAL §P9, §P3.6): the sync child's `subagent_started` and
    `subagent_ended` frames (with usage), its points (`subordinate_ref`, `parent_point_id` =
    the parent's step point whose range holds the `task` `tool_call_started`, role
    `subagent_root` on the first) and its own `model_request` frame, all under the parent
    step; the lineage `visibility` is `full` where the inspection exposes it (the lineage graph
    is served by the stream service only, `application/streams/service.py`).

    Passes only once the WP-TR-2 subagent frames and nested points land (source streams)."""

    async with scoped_stack(tmp_path, monkeypatch) as stack:
        run_id = await run_tracing_to_completion(stack)
        points = await all_points(stack, run_id)
        units = units_by_location(points)
        unit = units[(CYCLE_STAGE, 1)]
        mine = unit_points(points, unit)
        roots = [item for item in mine if not is_child_point(item)]
        children = [item for item in mine if is_child_point(item)]
        frames = await frames_for_run(stack, run_id)
        unit_frames = [item for item in frames if item["unit_key"] == unit]
        failures: list[str] = []
        evidence: dict[str, Any] = {
            "run_id": run_id,
            "unit": unit,
            "frame_kinds": sorted({item["kind"] for item in unit_frames}),
        }

        task_calls = [
            item
            for item in unit_frames
            if item["kind"] == "tool_call_started"
            and isinstance(item["body"], dict)
            and item["body"].get("name") == "task"
        ]
        assert len(task_calls) == 1, [(item["provider_key"], item["body"]) for item in task_calls]
        task_call = task_calls[0]
        task_id = task_call["tool_call_ref"]
        step = point_holding(roots, task_call["arrival_ordinal"])
        if step is None:
            failures.append(
                f"no root point range holds the task call at {task_call['arrival_ordinal']}"
            )
        evidence["task_call"] = {
            "tool_call_id": task_id,
            "arrival_ordinal": task_call["arrival_ordinal"],
            "step_point": step["point_id"] if step else None,
        }
        later_roots = [
            item
            for item in roots
            if item.get("frames")
            and step
            and item["frames"]["from_ordinal"] > step["frames"]["to_ordinal"]
        ]
        window_end = (
            min(item["frames"]["to_ordinal"] for item in later_roots) if later_roots else None
        )

        # The child's frames: started, ended (closing, usage), its own model_request.
        started = [item for item in unit_frames if item["kind"] == "subagent_started"]
        ended = [item for item in unit_frames if item["kind"] == "subagent_ended"]
        if not started:
            failures.append("no subagent_started frame; WP-TR-2 subagent frames")
        if not ended:
            failures.append("no subagent_ended frame; WP-TR-2 subagent frames")
        for frame in started:
            body = frame["body"] if isinstance(frame["body"], dict) else {}
            if body.get("name") != technical.CHILD_NAME or body.get("tool_call_id") != task_id:
                failures.append(
                    f"subagent_started body {body} does not name the child and task call"
                )
        for frame in ended:
            body = frame["body"] if isinstance(frame["body"], dict) else {}
            if not frame["closing"]:
                failures.append("subagent_ended is not a closing frame")
            if body.get("tool_call_id") != task_id or not body.get("status"):
                failures.append(f"subagent_ended body {body} lacks the task call id or status")
            usage = body.get("usage") or {}
            if usage.get("total_tokens") != technical.TOKENS_PER_CALL:
                failures.append(
                    f"subagent_ended usage {usage} != the child's one call "
                    f"({technical.TOKENS_PER_CALL} tokens)"
                )
        child_requests = [
            item
            for item in unit_frames
            if item["kind"] == "model_request" and item["subordinate_ref"]
        ]
        if not child_requests:
            failures.append("no model_request frame with a subordinate_ref (the child's own)")
        evidence["child_frames"] = {
            "started": [item["arrival_ordinal"] for item in started],
            "ended": [item["arrival_ordinal"] for item in ended],
            "model_request": [item["arrival_ordinal"] for item in child_requests],
            "window": (step["frames"]["from_ordinal"] if step else None, window_end),
        }
        ordinals = [item["arrival_ordinal"] for item in (*started, *child_requests, *ended)]
        if step and ordinals:
            low = step["frames"]["from_ordinal"]
            outside = [
                item
                for item in ordinals
                if item < low or (window_end is not None and item > window_end)
            ]
            if outside:
                failures.append(
                    f"child frames outside the parent step window [{low}, {window_end}]: {outside}"
                )
            ordered = all(
                task_call["arrival_ordinal"] < s <= r < e
                for s, r, e in zip(
                    (f["arrival_ordinal"] for f in started),
                    (f["arrival_ordinal"] for f in child_requests),
                    (f["arrival_ordinal"] for f in ended),
                    strict=False,
                )
            )
            if not ordered:
                failures.append(
                    f"child frames are not ordered task < started <= request < ended: {ordinals}"
                )

        # The child's points: subordinate_ref, parent_point_id = the parent's step point.
        if not children:
            failures.append("no nested (child) points for the unit; WP-TR-2 nested points")
        else:
            first_child = children[0]
            if "subagent_root" not in first_child["roles"]:
                failures.append(
                    f"first child point roles {first_child['roles']} lack subagent_root"
                )
            refs = {item["coordinate"]["point"].get("subordinate_ref") for item in children}
            if any(ref is None or technical.CHILD_NAME not in ref for ref in refs):
                failures.append(
                    f"child points subordinate_ref {refs} do not name {technical.CHILD_NAME}"
                )
            parents = {
                item["parent_point_id"] for item in children if "subagent_root" in item["roles"]
            }
            if step and parents != {step["point_id"]}:
                failures.append(
                    f"child root parent_point_id {parents} != the parent's step point "
                    f"{step['point_id']}"
                )
            evidence["child_points"] = [
                (item["ordinal"], item["roles"], item["parent_point_id"]) for item in children
            ]

        # Lineage visibility, where exposed.
        state = await inspect(stack, run_id)
        visibilities = find_keys(state, "visibility")
        evidence["visibility"] = visibilities
        if visibilities:
            if any(item != "full" for item in visibilities):
                failures.append(f"lineage visibility {visibilities} != full")
        else:
            print(
                "FX-TR-SUB: lineage visibility not exposed by the inspection route (stream-only "
                "lineage graph); that line is skipped",
                flush=True,
            )

        evidence["failures"] = failures
        print(f"FX-TR-SUB: evidence at {_write_evidence('fx-tr-sub.json', evidence)}", flush=True)
        assert not failures, "\n".join(failures)


@pytest.mark.asyncio
async def test_fx_tr_hook(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """FX-TR-HOOK (TRACING-PROPOSAL §P9, §P3.5): the catalog hook `rrm009.annotate` has
    `hook_invoked` and `hook_result` frames with the kernel hooks' ids first (`KERNEL_HOOK_IDS`
    order) per tool call, and its annotation reaches the tool result; the `usage` frames'
    token sum equals the unit's settlement usage; then, in a second run with
    `MISSION_CONTROL_TECHNICAL_MODEL_DELAY_SECONDS=2.5`, `cancel --urgency immediate` while a
    turn runs yields a `hook_result` frame with `decision: deny` from `mc.stop_fence` (or the
    run ends `cancelled` with the fence recorded; the evidence says which).

    Passes only once the WP-TR-2 hook ports, the frame sink and the component registration
    (`DeploymentCapabilityComponents.hook_scripts`) land (source streams)."""

    async with scoped_stack(tmp_path, monkeypatch) as stack:
        run_id = await run_tracing_to_completion(stack)
        points = await all_points(stack, run_id)
        units = units_by_location(points)
        unit = units[(CYCLE_STAGE, 1)]
        frames = await frames_for_run(stack, run_id)
        unit_frames = [item for item in frames if item["unit_key"] == unit]
        failures: list[str] = []
        evidence: dict[str, Any] = {
            "run_id": run_id,
            "unit": unit,
            "hook_bound": stack.binding.hook_bound,
            "frame_kinds": sorted({item["kind"] for item in unit_frames}),
        }
        if not stack.binding.hook_bound:
            failures.append(
                "the catalog hook is not bound: DeploymentCapabilityComponents has no "
                "hook_scripts field (adapters/temporal/deployment_composition.py:350-369) and "
                "the ExactComponentRegistry composition forwards none (:437)"
            )

        # 1. Hook frames per tool call: kernel ids first, in order, then the catalog hook.
        hook_results = [item for item in unit_frames if item["kind"] == "hook_result"]
        hook_invoked = [item for item in unit_frames if item["kind"] == "hook_invoked"]
        if not hook_results or not hook_invoked:
            failures.append(
                f"hook frames: {len(hook_invoked)} hook_invoked, {len(hook_results)} "
                "hook_result; WP-TR-2 hook ports / frame sink"
            )

        def call_of(frame: dict[str, Any]) -> str | None:
            body = frame["body"] if isinstance(frame["body"], dict) else {}
            return frame["tool_call_ref"] or body.get("tool_call_id")

        # One dispatch per (tool call, hook event): `before_tool` and `before_mcp` (or
        # `subagent_start`) each run the kernel hooks in order before the catalog scripts.
        per_dispatch: dict[str, list[str]] = {}
        for frame in hook_results:
            body = frame["body"] if isinstance(frame["body"], dict) else {}
            call = call_of(frame)
            if call:
                key = f"{call}@{body.get('event')}"
                per_dispatch.setdefault(key, []).append(str(body.get("hook_id")))
        evidence["hook_results_per_dispatch"] = per_dispatch
        for dispatch, ids in per_dispatch.items():
            kernel = [item for item in ids if item in KERNEL_HOOK_IDS]
            expected = [item for item in KERNEL_HOOK_IDS if item in kernel]
            if kernel != expected:
                failures.append(f"{dispatch}: kernel hook ids {kernel} not in order {expected}")
            first_catalog = next(
                (i for i, item in enumerate(ids) if item not in KERNEL_HOOK_IDS), None
            )
            if first_catalog is not None and any(
                item in KERNEL_HOOK_IDS for item in ids[first_catalog:]
            ):
                failures.append(f"{dispatch}: a kernel hook ran after a catalog hook: {ids}")
        mcp_calls = [
            item
            for item in unit_frames
            if item["kind"] == "tool_call_started"
            and isinstance(item["body"], dict)
            and item["body"].get("name") == technical.MCP_TOOL_NAME
        ]
        assert len(mcp_calls) == 1, [item["body"] for item in mcp_calls]
        mcp_call = mcp_calls[0]["tool_call_ref"]
        catalog = [
            frame
            for frame in hook_results
            if call_of(frame) == mcp_call
            and isinstance(frame["body"], dict)
            and frame["body"].get("hook_id") == technical.TRACING_HOOK_ID
        ]
        if not catalog:
            failures.append(
                f"no hook_result of {technical.TRACING_HOOK_ID} for the "
                f"{technical.MCP_TOOL_NAME} call"
            )
        elif any(frame["body"].get("decision") != "allow" for frame in catalog):
            failures.append(
                f"catalog hook decisions: {[f['body'].get('decision') for f in catalog]}"
            )
        completed_mcp = [
            item
            for item in unit_frames
            if item["kind"] == "tool_call_completed" and item["tool_call_ref"] == mcp_call
        ]
        full = await transcript_entries(stack, run_id, full=True)
        full_by_frame = entries_by_frame(full)
        annotated = any(
            technical.TRACING_HOOK_CONTEXT
            in json.dumps(frame_body(item, full_by_frame), default=str)
            for item in completed_mcp
        )
        if not annotated:
            failures.append(
                f"the {technical.MCP_TOOL_NAME} result carries no "
                f"{technical.TRACING_HOOK_CONTEXT} annotation (the hook's additional_context)"
            )

        # 2. The usage port's frames match the model observer's counts, which the settlement
        # consumed: the observer's `model.usage` per AI message (`frames.py`) and the port's
        # hook-observed usage (`StreamUsageRecorder`, keyed under the hook dispatch) are two
        # records of the same tokens, never summed together.
        usage_frames = [item for item in unit_frames if item["kind"] == "usage"]

        def tokens(frames: list[dict[str, Any]]) -> int:
            return sum(
                int((item["body"] or {}).get("total_tokens") or 0)
                for item in frames
                if isinstance(item["body"], dict)
            )

        port_usage = [
            item
            for item in usage_frames
            if ":hook:" in item["provider_key"] or item["raw_kind"].startswith("custom.")
        ]
        observer_usage = [item for item in usage_frames if item not in port_usage]
        total = tokens(observer_usage)
        # The port sees the parent's model calls (the hook middleware runs on the parent
        # graph); the sync child's one call reaches the observer under its `subordinate_ref`
        # and the parent's `subagent_ended` usage, never the port.
        root_total = tokens([item for item in observer_usage if not item["subordinate_ref"]])
        if port_usage and tokens(port_usage) != root_total:
            failures.append(
                f"usage port frames sum {tokens(port_usage)} tokens != the model observer's "
                f"root-namespace {root_total} ({len(port_usage)} port, {len(observer_usage)} "
                "observer frames)"
            )
        if not port_usage:
            failures.append("no usage frames from the mc.usage port (WP-TR-2 usage recorder)")
        settlements = await settlements_for_run(stack, run_id)
        mine = [
            item
            for item in settlements
            if f":stage:{CYCLE_STAGE}:" in item["operation"]
            and ":stage-cycle:1" in item["operation"]
        ]
        settled = mine[0]["usage"] if mine and isinstance(mine[0]["usage"], dict) else {}
        settled_total = settled.get("tokens.total", settled.get("total_tokens"))
        evidence["usage"] = {
            "usage_frames": [
                (item["provider_key"], item["raw_kind"], item["body"]) for item in usage_frames
            ],
            "observer_total_tokens": total,
            "observer_root_tokens": root_total,
            "port_total_tokens": tokens(port_usage),
            "settlement": settled,
            "expected_unit_tokens": UNIT_TOKENS,
        }
        if not mine:
            failures.append(
                f"no settlement for {CYCLE_STAGE}@c1 among "
                f"{[item['operation'] for item in settlements]}"
            )
        elif settled_total is None:
            failures.append(f"settlement usage {settled} has no total tokens key")
        elif total != settled_total:
            failures.append(
                f"model observer usage frames sum {total} tokens != settlement {settled_total} "
                f"({len(observer_usage)} observer frames; a unit consumes {UNIT_TOKENS})"
            )

        # 3. The stop fence: cancel immediately inside a running turn of a second run.
        monkeypatch.setenv("MISSION_CONTROL_TECHNICAL_MODEL_DELAY_SECONDS", "2.5")
        second = await launch(stack, TRACING)

        async def active() -> bool:
            state = await inspect(stack, second)
            return state["lifecycle"] == "running" and state.get("phase") == "active"

        await until(active, seconds=300)
        await asyncio.sleep(6.0)
        command = await cancel_immediately(stack, second)
        await until(lambda: terminal(stack, second), seconds=400)
        monkeypatch.delenv("MISSION_CONTROL_TECHNICAL_MODEL_DELAY_SECONDS", raising=False)
        state = await inspect(stack, second)
        second_frames = await frames_for_run(stack, second)
        fence = [
            item
            for item in second_frames
            if item["kind"] == "hook_result"
            and isinstance(item["body"], dict)
            and item["body"].get("hook_id") == "mc.stop_fence"
            and item["body"].get("decision") == "deny"
        ]
        report = await stack.http.get(f"{BASE}/{second}/stop-fence")
        commands = (await stack.http.get(f"{BASE}/{second}/commands")).json().get("commands", [])
        receipt = next(
            (item for item in commands if item["command"]["command_id"] == command["request_id"]),
            None,
        )
        evidence["stop_fence"] = {
            "run_id": second,
            "lifecycle": state["lifecycle"],
            "deny_frames": [
                (item["provider_key"], item["tool_call_ref"], item["body"].get("reason"))
                for item in fence
            ],
            "hook_result_hook_ids": sorted(
                {
                    str((item["body"] or {}).get("hook_id"))
                    for item in second_frames
                    if item["kind"] == "hook_result" and isinstance(item["body"], dict)
                }
            ),
            "report_status": report.status_code,
            "report": report.json() if report.status_code == 200 else report.text[:500],
            "receipt_states": [item["state"] for item in (receipt or {}).get("receipts", [])],
        }
        fenced = report.status_code == 200 and bool(find_keys(report.json(), "fence"))
        if not fence:
            failures.append(
                f"no hook_result frame with decision deny from mc.stop_fence in run {second}; "
                f"observed: lifecycle {state['lifecycle']}, stop-fence report "
                f"{report.status_code}{' with a fence' if fenced else ''}, hook ids "
                f"{evidence['stop_fence']['hook_result_hook_ids']}"
            )
        if state["lifecycle"] != "cancelled":
            # Observed, not asserted here: the fence denies the turn's remaining tool calls
            # (the frames above) while the run's lifecycle outcome after an immediate cancel
            # belongs to the lifecycle proofs (ADR-0008, `turn_boundary_guaranteed`).
            print(
                f"FX-TR-HOOK: after cancel --urgency immediate run {second} ended "
                f"{state['lifecycle']} with the fence {evidence['stop_fence']['report']}",
                flush=True,
            )

        evidence["failures"] = failures
        print(f"FX-TR-HOOK: evidence at {_write_evidence('fx-tr-hook.json', evidence)}", flush=True)
        assert not failures, "\n".join(failures)


# --- WP-TR-3 helpers -------------------------------------------------------------------------

TRANSCRIPT_ENTRY_V2 = "mc.transcript_entry.v2"
REPLAY_REPORT_V1 = "mc.replay_report.v1"
# The delta retention class (`domain/frames/contracts.py::DELTA_RETENTION_KINDS`, generated
# into `provider_frame.retention_class` by 0047): deleted by `retain_days`.
DELTA_KINDS = frozenset(kind.value for kind in DELTA_RETENTION_KINDS)
# TR-D1: `retain_days` governs the delta class and the policy table admits 1 at least
# (`0027_provider_frames.sql:121`, `CHECK (retain_days >= 1)`), so the proof sets the minimum
# and pushes the expiry clock far ahead instead of the proposal's `retain_days = 0`.
MIN_RETAIN_DAYS = 1
EXPIRY_CLOCK_AHEAD = timedelta(days=400)
# §P3.9 / TR-D10: the projection is "seconds behind" every settlement (outbox-released).
PROJECTION_SECONDS = 45
# The keys a `--by stage` group's `facts` carry for a released unit and its decision.
RELEASED_FACT_KEYS = ("released_by",)
DECISION_FACT_KEYS = ("decision", "completion_decision", "result_disposition", "decision_key")


async def frame_class_counts(stack: ScopedStack, run_id: str) -> dict[str, int]:
    """`provider_frame.retention_class -> count` of the run (the generated 0047 column)."""

    rows = await db_rows(
        stack,
        """
        SELECT retention_class, count(*) AS frames
        FROM mission_control.provider_frame
        WHERE run_id = (SELECT run_id FROM mission_control.mission_run WHERE run_key = $1)
        GROUP BY retention_class
        """,
        run_id,
    )
    return {row["retention_class"]: int(row["frames"]) for row in rows}


async def projection_state(stack: ScopedStack, run_id: str) -> dict[str, Any] | None:
    """The run's `transcript_projection_state` row (0048), or None before any projection."""

    rows = await db_rows(
        stack,
        """
        SELECT projected_through_seq, projected_through_frame, entry_count,
               projection_version, projected_at
        FROM mission_control.transcript_projection_state
        WHERE run_id = (SELECT run_id FROM mission_control.mission_run WHERE run_key = $1)
        """,
        run_id,
    )
    if not rows:
        return None
    row = rows[0]
    row["projected_through_frame"] = as_json(row["projected_through_frame"])
    return row


async def projected_entries(stack: ScopedStack, run_id: str) -> list[dict[str, Any]]:
    """The run's `transcript_entry` rows (0048) in `entry_seq` order, `entry` parsed."""

    rows = await db_rows(
        stack,
        """
        SELECT cursor, entry_seq, unit_key, activation_id::text AS activation_id,
               point_id::text AS point_id, parent_point_id::text AS parent_point_id, node_key,
               iteration, cycle, session_generation, subordinate_ref, source, kind, role,
               canonical, at, body_state, entry, projection_version
        FROM mission_control.transcript_entry
        WHERE run_id = (SELECT run_id FROM mission_control.mission_run WHERE run_key = $1)
        ORDER BY entry_seq
        """,
        run_id,
    )
    for row in rows:
        row["entry"] = as_json(row["entry"])
    return rows


async def projection_snapshot(
    stack: ScopedStack, run_id: str
) -> tuple[dict[str, Any] | None, int, list[dict[str, Any]]]:
    """`projection_state`, `max_event_seq` and `projected_entries` of one run read under one
    REPEATABLE READ snapshot: the three agree with each other even while a relay-driven
    projection lands between them (the proof then judges one committed projection, not a
    state row of one and the rows of the next)."""

    async with stack.owner_pool.acquire() as connection:
        async with connection.transaction(isolation="repeatable_read", readonly=True):
            await apply_scope(connection, stack.scope)
            run_uuid = await connection.fetchval(
                "SELECT run_id FROM mission_control.mission_run WHERE run_key = $1", run_id
            )
            state_row = await connection.fetchrow(
                """
                SELECT projected_through_seq, projected_through_frame, entry_count,
                       projection_version, projected_at
                FROM mission_control.transcript_projection_state
                WHERE run_id = $1
                """,
                run_uuid,
            )
            max_seq = await connection.fetchval(
                "SELECT coalesce(max(seq), 0) FROM mission_control.mission_event WHERE run_id = $1",
                run_uuid,
            )
            rows = await connection.fetch(
                """
                SELECT cursor, entry_seq, unit_key, activation_id::text AS activation_id,
                       point_id::text AS point_id, parent_point_id::text AS parent_point_id,
                       node_key, iteration, cycle, session_generation, subordinate_ref, source,
                       kind, role, canonical, at, body_state, entry, projection_version,
                       projected_at
                FROM mission_control.transcript_entry
                WHERE run_id = $1
                ORDER BY entry_seq
                """,
                run_uuid,
            )
    state = dict(state_row) if state_row is not None else None
    if state is not None:
        state["projected_through_frame"] = as_json(state["projected_through_frame"])
    entries = [dict(row) for row in rows]
    for row in entries:
        row["entry"] = as_json(row["entry"])
    return state, int(max_seq), entries


async def max_event_seq(stack: ScopedStack, run_id: str) -> int:
    rows = await db_rows(
        stack,
        """
        SELECT coalesce(max(seq), 0) AS seq FROM mission_control.mission_event
        WHERE run_id = (SELECT run_id FROM mission_control.mission_run WHERE run_key = $1)
        """,
        run_id,
    )
    return int(rows[0]["seq"])


async def transcript_page(stack: ScopedStack, run_id: str, **params: Any) -> dict[str, Any]:
    """One `GET runs/{id}/transcript?format=json` page of up to 5000 entries, with the
    `groups` the `by=` read model adds (§P4.2); the whole JSON body."""

    response = await stack.http.get(
        f"{BASE}/{run_id}/transcript", params={"limit": 5000, "format": "json", **params}
    )
    assert response.status_code == 200, (params, response.status_code, response.text[:800])
    return response.json()


async def run_frames_expiry(stack: ScopedStack, *, now: datetime) -> dict[str, Any]:
    """`mc.frames_expire.v1` on the maintenance queue with the given clock, driven the way
    the FT-C1 integration proof drives it (`tests/integration/temporal/
    test_frames_expire_workflow.py`): `FramesExpireInput.now` is the activity's clock."""

    assert stack.maintenance_queue, "the scoped stack names no maintenance queue"
    result = await stack.client.execute_workflow(
        FRAMES_EXPIRE_WORKFLOW,
        FramesExpireInput(request_scopes=[stack.scope], now=now.isoformat()),
        id=f"fx-tr-retain:{uuid4()}",
        task_queue=stack.maintenance_queue,
        result_type=None,
        execution_timeout=timedelta(seconds=120),
    )
    return dict(result)


def step_holding_tool_call(
    roots: list[dict[str, Any]], unit_frames: list[dict[str, Any]], *, tool: str | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The root point whose range holds a root-namespace `tool_call_started` (of `tool` when
    named) and that frame: a tool-calling step (FX-TR-REPLAY)."""

    for frame in unit_frames:
        if frame["kind"] != "tool_call_started" or frame["subordinate_ref"]:
            continue
        body = frame["body"] if isinstance(frame["body"], dict) else {}
        if tool and body.get("name") != tool:
            continue
        step = point_holding(roots, frame["arrival_ordinal"])
        if step is not None:
            return step, frame
    raise AssertionError(
        f"no root point range holds a tool_call_started{' of ' + tool if tool else ''}"
    )


def model_requests_in(
    unit_frames: list[dict[str, Any]], point: dict[str, Any]
) -> list[dict[str, Any]]:
    """The root-namespace `model_request` frames of the point's range, in arrival order."""

    return [
        item
        for item in frames_in_range(unit_frames, point)
        if item["kind"] == "model_request" and not item["subordinate_ref"]
    ]


async def cli(url: str, token: str, *args: str) -> tuple[int, str, str]:
    """One `missionctl` command over loopback HTTP: (exit code, stdout, stderr)."""

    process = missionctl(url, token, *args)
    stdout, stderr = await asyncio.to_thread(process.communicate, timeout=180)
    return process.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace")


def last_line(text: str) -> str:
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return lines[-1] if lines else ""


def entry_body_state(entry: dict[str, Any]) -> str | None:
    """`body.state` of a v2 entry (§P4.1); a v1 `frame_expired` placeholder reads `expired`."""

    body = entry.get("body")
    if isinstance(body, dict) and body.get("state"):
        return str(body["state"])
    if entry.get("kind") == "frame_expired":
        return "expired"
    return None


def entry_frame_id(entry: dict[str, Any]) -> str | None:
    refs = entry.get("refs") or {}
    return refs.get("frame_id")


def replay_key_fields(report: dict[str, Any]) -> dict[str, Any]:
    return {
        key: report.get(key)
        for key in (
            "schema_version",
            "point_id",
            "call_index",
            "batch_digest_recorded",
            "batch_digest_reconstructed",
            "exact",
            "first_difference",
        )
    }


def parse_cli_json(out: str) -> dict[str, Any] | None:
    """The CLI's JSON document (whole stdout, or its last JSON line) when it prints one."""

    for candidate in (out, last_line(out)):
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None


async def artifact_bytes(stack: ScopedStack, run_id: str, ref: str) -> Any:
    """`GET runs/{id}/artifacts/{url-encoded ref}` (§P4.2): the raw httpx response."""

    return await stack.http.get(f"{BASE}/{run_id}/artifacts/{quote(ref, safe='')}")


# --- WP-TR-3 proofs --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fx_tr_retain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """FX-TR-RETAIN (TRACING-PROPOSAL §P9, §P8a, TR-D1): after a completed tracing run, with
    the application's retention policy at the minimum `retain_days` the contract allows (1;
    `0027:121`) and the expiry clock 400 days ahead, `mc.frames_expire.v1` on the maintenance
    queue (`FramesExpireInput.now`, the FT-C1 way; `PostgresFrameRetention.set_policy` on the
    runtime pool sets the policy, there being no policy route) deletes only
    `retention_class = 'delta'` frames: the step count is unchanged, every step frame id of
    the run (every `model_request`, `message`, `tool_call_*`, `environment_materialized`,
    `subagent_*`, `hook_*` frame present before) survives although the run is terminal
    (`step_retain_days` NULL: the step clock never runs), the delta count is 0 afterwards and
    the report's `deleted_non_closing` equals the run's delta count before; the transcript
    (re-projected after the expiry) shows `body.state == "expired"` (or the v1 `frame_expired`
    placeholder) for the deleted deltas only, never for a surviving step frame.

    The scripted model answers whole messages (no `_stream`), so the delta class holds only
    the lane's `heartbeat` / `status` frames when it writes any; with none, the "expired
    deltas" line is reported unexercised and the survival of step frames is still asserted.

    Passes only once the WP-TR-3 retention classes (0047 generated column, the narrowed
    `expire_provider_frames`) and the v2 `body.state` land (source streams)."""

    async with scoped_stack(tmp_path, monkeypatch) as stack:
        run_id = await run_tracing_to_completion(stack)
        frames = await frames_for_run(stack, run_id)
        assert frames, "no provider frames for the run"
        before = await frame_class_counts(stack, run_id)
        step_before = {
            item["frame_id"]: item["kind"] for item in frames if item["kind"] not in DELTA_KINDS
        }
        delta_before = [item for item in frames if item["kind"] in DELTA_KINDS]
        failures: list[str] = []
        evidence: dict[str, Any] = {
            "run_id": run_id,
            "maintenance": {
                "queue": stack.maintenance_queue,
                "served_by": stack.maintenance_served_by,
            },
            "classes_before": before,
            "step_kinds_before": sorted(set(step_before.values())),
            "delta_kinds_before": sorted({item["kind"] for item in delta_before}),
        }

        # 0. The generated class agrees with the domain rule (0047 <-> contracts.py).
        if before.get("delta", 0) != len(delta_before) or before.get("step", 0) != len(step_before):
            failures.append(
                f"provider_frame.retention_class counts {before} disagree with the domain's "
                f"DELTA_RETENTION_KINDS ({len(delta_before)} delta, {len(step_before)} step)"
            )

        # 1. The policy at the contract's minimum, then the expiry with the clock far ahead.
        retention = PostgresFrameRetention(stack.pool, actor_ref="fx-tr-retain")
        await retention.set_policy(stack.scope, FrameRetentionPolicy(retain_days=MIN_RETAIN_DAYS))
        policy = await retention.policy(stack.scope)
        assert policy.retain_days == MIN_RETAIN_DAYS, policy
        clock = datetime.now(UTC) + EXPIRY_CLOCK_AHEAD
        result = await run_frames_expiry(stack, now=clock)
        scopes = [dict(item) for item in result.get("scopes", [])]
        evidence["expiry"] = {"now": clock.isoformat(), "result": scopes}
        mine = next((item for item in scopes if item.get("request_scope") == stack.scope), None)
        if mine is None:
            failures.append(f"the expiry reported no result for {stack.scope}: {scopes}")
        elif mine.get("retain_days") != MIN_RETAIN_DAYS:
            failures.append(f"the expiry ran under retain_days {mine.get('retain_days')}")

        # 2. Only delta frames were deleted; every step frame survives.
        after_frames = await frames_for_run(stack, run_id)
        after = await frame_class_counts(stack, run_id)
        evidence["classes_after"] = after
        step_after = {
            item["frame_id"]: item["kind"]
            for item in after_frames
            if item["kind"] not in DELTA_KINDS
        }
        lost = {
            frame_id: kind for frame_id, kind in step_before.items() if frame_id not in step_after
        }
        if lost:
            failures.append(
                f"step frames deleted by the expiry: {len(lost)} of {len(step_before)}, kinds "
                f"{sorted(set(lost.values()))}"
            )
        if after.get("step", 0) != before.get("step", 0):
            failures.append(
                f"step count changed: {before.get('step', 0)} -> {after.get('step', 0)}"
            )
        if after.get("delta", 0) != 0:
            failures.append(f"delta frames survive the expiry: {after.get('delta', 0)}")
        if mine is not None and delta_before:
            deleted = int(mine.get("deleted_non_closing", 0)) + int(mine.get("deleted_closing", 0))
            if deleted != len(delta_before):
                failures.append(
                    f"the report deleted {deleted} frames; the run had {len(delta_before)} deltas"
                )
        deltas_after_delete = [item for item in after_frames if item["kind"] in DELTA_KINDS]
        if deltas_after_delete:
            kinds_left = sorted({item["kind"] for item in deltas_after_delete})
            failures.append(f"delta-kind frames still stored: {kinds_left}")

        # 3. The transcript: `expired` on the deleted deltas only.
        refresh = await stack.http.post(f"{BASE}/{run_id}/transcript/refresh")
        evidence["refresh_status"] = refresh.status_code
        entries = await transcript_entries(stack, run_id)
        deleted_ids = {item["frame_id"] for item in delta_before}
        expired = [item for item in entries if entry_body_state(item) == "expired"]
        step_expired = [item for item in expired if entry_frame_id(item) in step_after]
        foreign_expired = [
            item
            for item in expired
            if entry_frame_id(item) and entry_frame_id(item) not in deleted_ids
        ]
        evidence["transcript"] = {
            "entries": len(entries),
            "expired": len(expired),
            "expired_kinds": sorted({str(item.get("kind")) for item in expired}),
            "body_states": sorted({str(entry_body_state(item)) for item in entries}),
        }
        if step_expired:
            failures.append(
                f"{len(step_expired)} transcript entries of surviving step frames read expired"
            )
        if foreign_expired:
            failures.append(
                f"{len(foreign_expired)} expired entries reference frames that were not "
                "deleted deltas"
            )
        if delta_before:
            if not expired:
                failures.append(
                    f"{len(delta_before)} delta frames expired but the transcript shows no "
                    "expired entry (body.state == expired or kind frame_expired)"
                )
        else:
            print(
                "FX-TR-RETAIN: the run wrote no delta-class frame (the scripted model streams "
                "no deltas; no heartbeat/status frame): the 'expired deltas' line is "
                "unexercised; step-frame survival asserted",
                flush=True,
            )
            if expired:
                failures.append(f"no delta expired yet {len(expired)} entries read expired")

        evidence["failures"] = failures
        print(
            f"FX-TR-RETAIN: evidence at {_write_evidence('fx-tr-retain.json', evidence)}",
            flush=True,
        )
        assert not failures, "\n".join(failures)


@pytest.mark.asyncio
async def test_fx_tr_replay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """FX-TR-REPLAY (TRACING-PROPOSAL §P9, §P4.3, TR-D11): at the tool-calling step of `S2@c1`
    (the root point whose range holds the `lookup_binding_marker` `tool_call_started`),
    `GET runs/{id}/points/{pid}/replay?include_batch=true` answers `mc.replay_report.v1` with
    `exact: true`, `batch_digest_reconstructed == batch_digest_recorded`, every message
    `source` in {`frame`, `object`} (none `missing`), `first_difference` null and the batch
    included; the recorded digest is the `batch_digest` of the point's `model_request` frame
    at the report's `call_index`; `missionctl run replay RUN --point ID --dry-run` over
    loopback HTTP prints the same report; with the API's saver closed the route still answers
    the same report (the replay reads the Transcript alone).

    Passes only once the WP-TR-3 replay route and CLI land (source streams); the
    `model_request` frames and promoted objects are WP-TR-2's."""

    async with (
        scoped_stack(tmp_path, monkeypatch) as stack,
        serve_loopback(stack.application) as url,
    ):
        run_id = await run_tracing_to_completion(stack)
        points = await all_points(stack, run_id)
        units = units_by_location(points)
        unit = units[(CYCLE_STAGE, 1)]
        roots = [item for item in unit_points(points, unit) if not is_child_point(item)]
        frames = await frames_for_run(stack, run_id)
        unit_frames = [item for item in frames if item["unit_key"] == unit]
        full = await transcript_entries(stack, run_id, full=True)
        full_by_frame = entries_by_frame(full)
        step, tool_call = step_holding_tool_call(roots, unit_frames, tool=technical.MCP_TOOL_NAME)
        requests = model_requests_in(unit_frames, step)
        recorded: list[dict[str, Any]] = []
        for frame in requests:
            body = frame_body(frame, full_by_frame)
            body = body if isinstance(body, dict) else {}
            recorded.append(
                {
                    "frame_id": frame["frame_id"],
                    "call_index": body.get("call_index"),
                    "batch_digest": body.get("batch_digest"),
                    "messages": len(body.get("messages") or []),
                }
            )
        failures: list[str] = []
        evidence: dict[str, Any] = {
            "run_id": run_id,
            "unit": unit,
            "point_id": step["point_id"],
            "tool_call": (tool_call["tool_call_ref"], tool_call["arrival_ordinal"]),
            "model_requests": recorded,
        }
        if not requests:
            failures.append(
                f"no model_request frame in the range of the tool-calling step "
                f"{step['point_id']} (WP-TR-2 observer)"
            )

        def check(report: dict[str, Any], label: str) -> None:
            if report.get("schema_version") != REPLAY_REPORT_V1:
                failures.append(f"{label}: schema_version {report.get('schema_version')!r}")
            if report.get("point_id") != step["point_id"]:
                failures.append(f"{label}: point_id {report.get('point_id')} != {step['point_id']}")
            if report.get("exact") is not True:
                failures.append(
                    f"{label}: exact {report.get('exact')!r}, first_difference "
                    f"{report.get('first_difference')!r}"
                )
            if report.get("first_difference") is not None:
                failures.append(f"{label}: first_difference {report.get('first_difference')!r}")
            recorded_digest = report.get("batch_digest_recorded")
            reconstructed = report.get("batch_digest_reconstructed")
            if not recorded_digest or recorded_digest != reconstructed:
                failures.append(
                    f"{label}: batch_digest_reconstructed {reconstructed} != "
                    f"batch_digest_recorded {recorded_digest}"
                )
            messages = report.get("messages") or []
            if not messages:
                failures.append(f"{label}: the report lists no messages")
            sources = {str(item.get("source")) for item in messages}
            if not sources <= {"frame", "object"}:
                failures.append(f"{label}: message sources {sorted(sources)} (missing/other)")
            if report.get("batch") is None:
                failures.append(f"{label}: include_batch=true returned no batch")
            digests = {item["batch_digest"] for item in recorded if item["batch_digest"]}
            if recorded_digest and recorded_digest not in digests:
                failures.append(
                    f"{label}: recorded digest {recorded_digest} is not the batch_digest of a "
                    f"model_request frame of the point ({sorted(digests)})"
                )
            index = report.get("call_index")
            at_index = [item["batch_digest"] for item in recorded if item["call_index"] == index]
            if at_index and recorded_digest not in at_index:
                failures.append(
                    f"{label}: call_index {index} names model_request digest {at_index}, the "
                    f"report recorded {recorded_digest}"
                )

        # 1. The route, saver open.
        response = await stack.http.get(
            f"{BASE}/{run_id}/points/{step['point_id']}/replay", params={"include_batch": "true"}
        )
        evidence["replay_status"] = response.status_code
        report: dict[str, Any] = {}
        if response.status_code != 200:
            failures.append(
                f"GET points/{{pid}}/replay {response.status_code}: {response.text[:300]}; "
                "WP-TR-3 replay route"
            )
        else:
            report = response.json()
            evidence["replay"] = {
                **replay_key_fields(report),
                "sources": sorted({str(i.get("source")) for i in report.get("messages") or []}),
                "messages": len(report.get("messages") or []),
            }
            check(report, "GET replay")

        # 2. The CLI prints the same report.
        code, out, err = await cli(
            url, stack.token, "run", "replay", run_id, "--point", step["point_id"], "--dry-run"
        )
        evidence["cli"] = {"exit": code, "stderr_last": last_line(err), "stdout_bytes": len(out)}
        if code != 0:
            failures.append(
                f"missionctl run replay --dry-run exited {code}: {last_line(err) or last_line(out)}"
                "; WP-TR-3 CLI"
            )
        else:
            printed = parse_cli_json(out)
            if printed is None:
                if REPLAY_REPORT_V1 not in out or (
                    report and report.get("batch_digest_recorded", "\0") not in out
                ):
                    failures.append("missionctl run replay printed no mc.replay_report.v1 report")
            elif report and replay_key_fields(printed) != replay_key_fields(report):
                failures.append(
                    f"the CLI report {replay_key_fields(printed)} differs from the route's "
                    f"{replay_key_fields(report)}"
                )
            elif not report:
                check(printed, "missionctl run replay")

        # 3. With the saver closed the replay still answers, identically.
        closed = await close_saver(stack)
        evidence["saver_closed"] = closed
        if not closed:
            failures.append("could not close the API saver (no pinned saver reachable)")
        again = await stack.http.get(
            f"{BASE}/{run_id}/points/{step['point_id']}/replay", params={"include_batch": "true"}
        )
        evidence["replay_status_saver_closed"] = again.status_code
        if again.status_code != 200:
            failures.append(
                f"with the saver closed GET replay answered {again.status_code}: {again.text[:300]}"
            )
        elif report and replay_key_fields(again.json()) != replay_key_fields(report):
            failures.append(
                f"with the saver closed the report changed: {replay_key_fields(again.json())}"
            )

        evidence["failures"] = failures
        print(
            f"FX-TR-REPLAY: evidence at {_write_evidence('fx-tr-replay.json', evidence)}",
            flush=True,
        )
        assert not failures, "\n".join(failures)


@pytest.mark.asyncio
async def test_fx_tr_step_projection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """FX-TR-STEP on the projection (TRACING-PROPOSAL §P3.9, §P4.1, §P4.2, TR-D10): after a
    completed tracing run,

    - within `PROJECTION_SECONDS` of completion and without a refresh, the outbox-released
      projection wrote the run's `transcript_projection_state` row (reported as the failing
      assertion when the trigger is not there, never skipped);
    - after `POST transcript/refresh`, the row's `projected_through_seq` equals `max(seq)` of
      the run's events and `transcript_entry` rows exist, all `mc.transcript_entry.v2`, with
      `entry_seq` contiguous from 1 and `entry_count` equal to the row count;
    - every frame-sourced entry of `S2@c1`'s root points carries `point_id` (the root point
      holding its ordinal), `unit_key`, `node_key == "S2"` and `cycle == 1`;
    - `GET transcript?by=step&point=<result point>` returns one group whose `entry_cursors`
      all belong to that point; `GET transcript?by=stage` returns one group per unit, the
      `S3@c2` group's `facts` carrying `released_by` and a decision;
    - `GET transcript` (no params) equals the projected rows (same cursors, same count);
    - `GET points/{pid}/frames` returns exactly the frames of the point's range;
    - `GET artifacts/{ref}` for the >8 KiB tool result's `frame-body://` reference streams the
      whole body as `application/json` with the frame's digest and byte count;
      `missionctl run artifact RUN REF --out FILE` writes the same bytes;
    - `missionctl run transcript RUN --by step --point ID --full` prints the step group with
      the model request and the whole tool result (the owner's command of §C.4).

    Passes only once the WP-TR-3 projection, outbox trigger, grouped read model, frames-by-point,
    artifact download and CLI land (source streams)."""

    async with (
        scoped_stack(tmp_path, monkeypatch) as stack,
        serve_loopback(stack.application) as url,
    ):
        run_id = await run_tracing_to_completion(stack)
        completed_at = time.monotonic()
        points = await all_points(stack, run_id)
        units = units_by_location(points)
        assert set(units) == expected_units(), sorted(units)
        unit = units[(CYCLE_STAGE, 1)]
        mine = unit_points(points, unit)
        roots = [item for item in mine if not is_child_point(item)]
        result = next(item for item in roots if "result" in item["roles"])
        frames = await frames_for_run(stack, run_id)
        unit_frames = [item for item in frames if item["unit_key"] == unit]
        failures: list[str] = []
        evidence: dict[str, Any] = {
            "run_id": run_id,
            "unit": unit,
            "result_point": result["point_id"],
            "maintenance": {
                "queue": stack.maintenance_queue,
                "served_by": stack.maintenance_served_by,
            },
        }

        # 1. The projection ran after the last settlement without a refresh (outbox trigger).
        state_before: dict[str, Any] | None = None
        while time.monotonic() - completed_at < PROJECTION_SECONDS:
            state_before = await projection_state(stack, run_id)
            if state_before is not None:
                break
            await asyncio.sleep(1.0)
        seq_before = await max_event_seq(stack, run_id)
        evidence["projection_before_refresh"] = {
            "state": state_before,
            "max_seq": seq_before,
            "waited_s": round(time.monotonic() - completed_at, 1),
        }
        if state_before is None:
            failures.append(
                f"no transcript_projection_state row within {PROJECTION_SECONDS}s of completion "
                "without a refresh: the settlement path's outbox-released projection trigger "
                f"(§P3.9) did not run (maintenance queue {stack.maintenance_queue} served by "
                f"{stack.maintenance_served_by})"
            )

        # 2. The refresh: the state row at max(seq), the rows contiguous and v2.
        refresh = await stack.http.post(f"{BASE}/{run_id}/transcript/refresh")
        evidence["refresh"] = {
            "status": refresh.status_code,
            "body": refresh.json() if refresh.status_code == 200 else refresh.text[:300],
        }
        if refresh.status_code != 200:
            failures.append(f"POST transcript/refresh {refresh.status_code}: {refresh.text[:300]}")
        state, max_seq, rows = await projection_snapshot(stack, run_id)
        evidence["projection"] = {
            "state": state,
            "max_seq": max_seq,
            "rows": len(rows),
            "row_projections": sorted({str(row["projected_at"]) for row in rows}),
        }
        if state is None:
            failures.append("no transcript_projection_state row after the refresh")
        else:
            if state["projected_through_seq"] != max_seq:
                failures.append(
                    f"projected_through_seq {state['projected_through_seq']} != max(seq) {max_seq}"
                )
            if state["entry_count"] != len(rows):
                failures.append(f"entry_count {state['entry_count']} != {len(rows)} rows")
        if not rows:
            failures.append("no transcript_entry rows after the refresh")
        else:
            seqs = [row["entry_seq"] for row in rows]
            if seqs != list(range(1, len(rows) + 1)):
                failures.append(
                    f"entry_seq not contiguous from 1: first {seqs[:5]}, last {seqs[-3:]}"
                )
            versions = {row["entry"].get("schema_version") for row in rows}
            if versions != {TRANSCRIPT_ENTRY_V2}:
                failures.append(f"projected entry schema versions {sorted(map(str, versions))}")
            mismatched = [
                row["cursor"]
                for row in rows
                if row["entry"].get("cursor") != row["cursor"]
                or row["entry"].get("entry_seq") != row["entry_seq"]
            ]
            if mismatched:
                failures.append(f"rows whose entry disagrees with its columns: {mismatched[:3]}")

        # 3. Frame-sourced entries of S2@c1's root points carry the point and the location.
        by_frame_row = {
            row["entry"].get("refs", {}).get("frame_id"): row
            for row in rows
            if row["source"] == "provider_frame"
            and (row["entry"].get("refs") or {}).get("frame_id")
        }
        checked = 0
        for frame in unit_frames:
            root = point_holding(roots, frame["arrival_ordinal"])
            if root is None:
                continue
            row = by_frame_row.get(frame["frame_id"])
            if row is None:
                failures.append(
                    f"frame {frame['frame_id']} ({frame['kind']}, ordinal "
                    f"{frame['arrival_ordinal']}) of {unit} has no projected entry"
                )
                continue
            checked += 1
            problems = []
            if row["unit_key"] != unit:
                problems.append(f"unit_key {row['unit_key']}")
            if row["node_key"] != CYCLE_STAGE:
                problems.append(f"node_key {row['node_key']}")
            if row["cycle"] != 1:
                problems.append(f"cycle {row['cycle']}")
            if not row["point_id"]:
                problems.append("point_id NULL")
            elif not frame["subordinate_ref"] and row["point_id"] != root["point_id"]:
                problems.append(f"point_id {row['point_id']} != root {root['point_id']}")
            if problems:
                failures.append(
                    f"entry of frame {frame['frame_id']} ({frame['kind']}): {', '.join(problems)}"
                )
        evidence["frame_entries_checked"] = checked
        if not checked:
            failures.append(f"no frame of {unit} sits in a root point range")

        # 4. by=step for the result point; by=stage for every unit.
        step_page = await transcript_page(stack, run_id, by="step", point=result["point_id"])
        groups = step_page.get("groups")
        point_cursors = {row["cursor"] for row in rows if row["point_id"] == result["point_id"]}
        evidence["by_step"] = {
            "groups": len(groups or []),
            "entries": len(step_page.get("entries") or []),
            "point_rows": len(point_cursors),
        }
        if not groups:
            failures.append("GET transcript?by=step&point= returned no groups (WP-TR-3 read model)")
        elif len(groups) != 1:
            failures.append(f"by=step&point= returned {len(groups)} groups, not one")
        else:
            group = groups[0]
            cursors = set(group.get("entry_cursors") or [])
            if group.get("level") != "step" or group.get("point_id") != result["point_id"]:
                failures.append(
                    f"the step group is {group.get('level')} of {group.get('point_id')}"
                )
            if not cursors:
                failures.append("the step group lists no entry_cursors")
            elif not cursors <= point_cursors:
                failures.append(
                    f"{len(cursors - point_cursors)} of the step group's cursors belong to "
                    "another point"
                )
        stage_page = await transcript_page(stack, run_id, by="stage")
        stage_groups = stage_page.get("groups") or []
        evidence["by_stage"] = [
            (g.get("key"), g.get("node_key"), g.get("cycle"), sorted((g.get("facts") or {}).keys()))
            for g in stage_groups
        ]
        if not stage_groups:
            failures.append("GET transcript?by=stage returned no groups (WP-TR-3 read model)")
        else:
            group_units = [g.get("unit_key") for g in stage_groups]
            if sorted(filter(None, group_units)) != sorted(units.values()):
                failures.append(
                    f"by=stage groups name {len(group_units)} units, expected one per unit "
                    f"({len(units)})"
                )
            s3 = next(
                (g for g in stage_groups if g.get("unit_key") == units[("S3", LAST_CYCLE)]), None
            )
            if s3 is None:
                failures.append(f"no by=stage group for S3@c{LAST_CYCLE}")
            else:
                facts = s3.get("facts") or {}
                if not any(find_keys(facts, key) for key in RELEASED_FACT_KEYS):
                    failures.append(f"S3@c{LAST_CYCLE} facts carry no released_by: {facts}")
                if not any(find_keys(facts, key) for key in DECISION_FACT_KEYS):
                    failures.append(f"S3@c{LAST_CYCLE} facts carry no decision: {facts}")

        # 5. The plain HTTP transcript equals the projected rows.
        plain = await transcript_entries(stack, run_id)
        evidence["plain_entries"] = len(plain)
        if [item["cursor"] for item in plain] != [row["cursor"] for row in rows]:
            failures.append(
                f"GET transcript ({len(plain)} entries) != the projected rows ({len(rows)})"
            )

        # 6. frames-by-point.
        in_range = {item["frame_id"] for item in frames_in_range(unit_frames, result)}
        response = await stack.http.get(f"{BASE}/{run_id}/points/{result['point_id']}/frames")
        evidence["frames_by_point_status"] = response.status_code
        if response.status_code != 200:
            failures.append(
                f"GET points/{{pid}}/frames {response.status_code}: {response.text[:300]}"
            )
        else:
            served = response.json().get("entries") or []
            served_ids = {entry_frame_id(item) for item in served}
            window = result["frames"]
            outside = [
                (item.get("execution") or {}).get("arrival_ordinal")
                for item in served
                if not (
                    window["from_ordinal"]
                    <= ((item.get("execution") or {}).get("arrival_ordinal") or -1)
                    <= window["to_ordinal"]
                )
            ]
            if served_ids != in_range or outside:
                failures.append(
                    f"frames-by-point served {len(served)} entries, range holds {len(in_range)} "
                    f"frames; outside the range: {outside[:5]}"
                )

        # 7. The artifact download of the >8 KiB tool result, route and CLI.
        big = [
            item
            for item in unit_frames
            if item["kind"] == "tool_call_completed" and item["body_bytes"] > EXCERPT_CAP_BYTES
        ]
        ref = big[0]["body_artifact_ref"] if big else None
        evidence["artifact_ref"] = ref
        if not ref:
            failures.append("no promoted >8 KiB tool result in S2@c1 (WP-TR-2 promoter)")
        else:
            download = await artifact_bytes(stack, run_id, ref)
            evidence["artifact_status"] = download.status_code
            if download.status_code != 200:
                failures.append(
                    f"GET artifacts/{{ref}} {download.status_code}: {download.text[:300]}"
                )
            else:
                media = download.headers.get("content-type", "")
                digest = "sha256:" + hashlib.sha256(download.content).hexdigest()
                if not media.startswith("application/json"):
                    failures.append(f"artifact Content-Type {media!r}")
                if digest != big[0]["body_digest"] or len(download.content) != big[0]["body_bytes"]:
                    failures.append(
                        f"artifact bytes {len(download.content)} / {digest} != the frame's "
                        f"{big[0]['body_bytes']} / {big[0]['body_digest']}"
                    )
            out_file = tmp_path / "artifact.json"
            code, out, err = await cli(
                url, stack.token, "run", "artifact", run_id, ref, "--out", str(out_file)
            )
            evidence["cli_artifact"] = {"exit": code, "stderr_last": last_line(err)}
            if code != 0:
                failures.append(
                    f"missionctl run artifact exited {code}: {last_line(err) or last_line(out)}"
                )
            elif not out_file.exists():
                failures.append("missionctl run artifact wrote no file")
            else:
                written = "sha256:" + hashlib.sha256(out_file.read_bytes()).hexdigest()
                if written != big[0]["body_digest"]:
                    failures.append(f"missionctl run artifact wrote {written}")

        # 8. The owner's command: the step group with the model request and the whole result.
        step = point_holding(roots, big[0]["arrival_ordinal"]) if big else None
        if step is None:
            step = result
        code, out, err = await cli(
            url,
            stack.token,
            "run",
            "transcript",
            run_id,
            "--by",
            "step",
            "--point",
            step["point_id"],
            "--full",
        )
        evidence["cli_transcript"] = {
            "point": step["point_id"],
            "exit": code,
            "stderr_last": last_line(err),
            "stdout_bytes": len(out),
        }
        if code != 0:
            failures.append(
                f"missionctl run transcript --by step --point --full exited {code}: "
                f"{last_line(err) or last_line(out)}"
            )
        else:
            marker = f"MCP-BOUND::{technical.MCP_CODE}::EXACT"
            if "model_request" not in out:
                failures.append("the printed step group has no model_request entry")
            if big and (
                marker not in out or technical.rrm009_mcp_server.LAST_LINE_PREFIX not in out
            ):
                failures.append(
                    "the printed step group lacks the whole tool result (marker and closing line)"
                )

        evidence["failures"] = failures
        print(
            f"FX-TR-STEP (projection): evidence at "
            f"{_write_evidence('fx-tr-step-projection.json', evidence)}",
            flush=True,
        )
        assert not failures, "\n".join(failures)


# --- WP-TR-4: the precise fork (TRACING-PROPOSAL §P5) --------------------------------------------

FORK_MARKER = "FX-TR-FORK-CYCLE marker: prefer companies with CLIA labs."


def seedable_step(points: list[dict[str, Any]], unit_key: str) -> dict[str, Any]:
    """A root, seedable step of the unit after its input point (the point P of §P5.6)."""

    steps = sorted(
        (
            item
            for item in points
            if item["coordinate"]["unit_key"] == unit_key
            and is_root(item)
            and item["seedable"]
            and "input" not in item["roles"]
            and "result" not in item["roles"]
        ),
        key=lambda item: item["ordinal"],
    )
    return steps[len(steps) // 2] if steps else point_with_role_key(points, unit_key, "result")


def point_with_role_key(points: list[dict[str, Any]], unit_key: str, role: str) -> dict[str, Any]:
    return next(
        item
        for item in points
        if item["coordinate"]["unit_key"] == unit_key and role in item["roles"]
    )


@pytest.mark.asyncio
async def test_fx_tr_fork_cycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """FX-TR-FORK-CYCLE (TRACING-PROPOSAL §P5.2, §P5.3, §P5.6, TR-D12, TR-D13): after the
    tracing run completes (`S1@c0`, `S2@c0..c2`, `S3@c2`, `S4@c2`), a fork at
    `{stage: S2, cycle: 2}` seeded at a step P of `S2@c2` with an injected message and no
    frontier of its own:

    - the receipt records `frontier_requested == [S2]`, `frontier_closed == [S2, S3, S4]`
      (the closure over the frozen blueprint under the default `close` policy), the reuse
      of `S1@c0` alone (`reused_units` naming the source result point), `start_position`
      `{workflow_cycle_ordinal: 0, stage_cycle_ordinals: {S2: 2}, stage_objectives: {S2: the
      cycle-2 objective}}`, `seed_point == P` and `message_delivery == seed_head`;
    - the derived `fork_seed` point is the head after the copied P on a new thread, with one
      more message than P;
    - a `strict` fork with the same narrow frontier is refused `frontier_not_closed` naming
      `S3` and `S4`;
    - the derived run admits `S1@c0` (settled by reference with a `reused` point whose parent
      is the source result point), never `S2@c0` or `S2@c1`, runs `S2@c2` first (its root
      input point descends from the seed, its state at that point ends with the marker as
      the last human message, its objective override is the source's), then `S3@c0` and
      `S4@c0` fresh;
    - `missionctl run fork RUN --at stage:S2,cycle:2 --point P --inject FILE` over loopback
      HTTP answers a receipt with the same position and delivery (a second derived run,
      never launched), and `missionctl run transcript DERIVED --by stage` lists the derived
      run's stage groups.
    """

    failures: list[str] = []
    evidence: dict[str, Any] = {"proof": "FX-TR-FORK-CYCLE", "marker": FORK_MARKER}
    async with (
        scoped_stack(tmp_path, monkeypatch) as stack,
        serve_loopback(stack.application) as url,
    ):
        run_id = await run_tracing_to_completion(stack)
        points = await all_points(stack, run_id)
        units = units_by_location(points)
        evidence["source_run"] = run_id
        evidence["source_units"] = {f"{node}@{cycle}": key for (node, cycle), key in units.items()}
        seed_unit = units[(CYCLE_STAGE, LAST_CYCLE)]
        seed = seedable_step(points, seed_unit)
        seed_key = seed["coordinate"]["point"]["key"]
        s1_result = point_with_role_key(points, units[("S1", 0)], "result")
        journal = await journal_for_run(stack, run_id)
        proposals = admitted_proposals(journal)
        cycle_objective = (proposals.get((CYCLE_STAGE, LAST_CYCLE)) or {}).get("objective_override")
        evidence["seed"] = {
            "point_id": seed["point_id"],
            "ordinal": seed["ordinal"],
            "roles": seed["roles"],
            "message_count": seed["message_count"],
        }
        evidence["cycle_objective"] = cycle_objective

        # 1. The fork at S2 cycle 2, seeded at P, with the message; the default closure.
        manifest = await snapshot(stack, run_id)
        request_id = str(uuid4())
        fork = await stack.http.post(
            f"{BASE}/{run_id}/forks",
            json={
                "request_id": request_id,
                "snapshot_id": manifest["snapshot_id"],
                "snapshot_digest": manifest["snapshot_digest"],
                "at": {"stage": CYCLE_STAGE, "cycle": LAST_CYCLE},
                "cognitive_seed": {"unit_key": seed_unit, "checkpoint": seed_key},
                "message": {"text": FORK_MARKER},
                "baseline_reservations": technical.baseline_reservation(TRACING),
                "sponsorship_ref": "sponsorship:test",
                "approval_refs": ["approval:test"],
                "reason": "FX-TR-FORK-CYCLE: fork at S2 cycle 2 from a step",
            },
        )
        assert fork.status_code == 202, fork.text
        receipt = fork.json()["receipt"]
        derived_run = receipt["target_run_id"]
        evidence["receipt"] = receipt
        if receipt.get("frontier_requested") != [CYCLE_STAGE]:
            failures.append(f"frontier_requested {receipt.get('frontier_requested')}")
        if receipt.get("frontier_closed") != [CYCLE_STAGE, "S3", "S4"]:
            failures.append(f"frontier_closed {receipt.get('frontier_closed')}")
        reused = receipt.get("reused_units") or []
        if [item["source_unit_key"] for item in reused] != [units[("S1", 0)]]:
            failures.append(f"reused_units {reused}")
        elif (
            reused[0].get("source_result_point")
            != (s1_result["coordinate"]["point"]["key"]["checkpoint_id"])
        ):
            failures.append(
                f"reused S1 names source_result_point {reused[0].get('source_result_point')}, "
                f"the source result point is {s1_result['coordinate']['point']['key']}"
            )
        start = receipt.get("start_position") or {}
        if start.get("workflow_cycle_ordinal") != 0 or start.get("stage_cycle_ordinals") != {
            CYCLE_STAGE: LAST_CYCLE
        }:
            failures.append(f"start_position {start}")
        if cycle_objective and start.get("stage_objectives") != {CYCLE_STAGE: cycle_objective}:
            failures.append(
                f"start_position.stage_objectives {start.get('stage_objectives')} is not the "
                f"cycle-{LAST_CYCLE} objective"
            )
        if receipt.get("seed_point") != seed_key["checkpoint_id"]:
            failures.append(f"seed_point {receipt.get('seed_point')}")
        if receipt.get("message_delivery") != "seed_head":
            failures.append(f"message_delivery {receipt.get('message_delivery')}")
        invalidated = set(receipt["lineage"]["invalidated_unit_keys"])
        # Every settled unit but S1@c0: S2, S3 and S4 at each cycle the source ran them.
        if len(invalidated) != len(expected_units()) - 1:
            failures.append(
                f"{len(invalidated)} invalidated units, expected {len(expected_units()) - 1}"
            )
        seeded = await all_points(stack, derived_run, role="fork_seed")
        if len(seeded) != 1:
            failures.append(f"{len(seeded)} fork_seed points on the derived run")
        else:
            head = seeded[0]
            if head["parent_coordinate"]["point"]["key"] != seed_key:
                failures.append("the fork_seed point's parent is not P")
            if (
                head["coordinate"]["point"]["key"]["parent_checkpoint_id"]
                != seed_key["checkpoint_id"]
            ):
                failures.append("the seeded head is not the checkpoint after the copied P")
            if head["coordinate"]["point"]["key"]["thread_id"] == seed_key["thread_id"]:
                failures.append("the seeded head lies on the source thread")
            if head["message_count"] != seed["message_count"] + 1:
                failures.append(
                    f"seeded head message_count {head['message_count']} != P's + 1 "
                    f"({seed['message_count']} + 1)"
                )
            evidence["fork_seed"] = {
                "point_id": head["point_id"],
                "key": head["coordinate"]["point"]["key"],
                "message_count": head["message_count"],
                "channel_facts": head.get("channel_facts"),
            }

        # 2. `strict` refuses the narrow frontier, naming the missing consumers.
        strict = await stack.http.post(
            f"{BASE}/{run_id}/forks",
            json={
                "request_id": str(uuid4()),
                "snapshot_id": manifest["snapshot_id"],
                "snapshot_digest": manifest["snapshot_digest"],
                "at": {"stage": CYCLE_STAGE, "cycle": LAST_CYCLE},
                "invalidation_frontier": [CYCLE_STAGE],
                "frontier_policy": "strict",
                "cognitive_seed": {"unit_key": seed_unit, "checkpoint": seed_key},
                "message": {"text": FORK_MARKER},
                "baseline_reservations": technical.baseline_reservation(TRACING),
                "sponsorship_ref": "sponsorship:test",
                "approval_refs": ["approval:test"],
                "reason": "FX-TR-FORK-CYCLE: strict frontier",
            },
        )
        evidence["strict"] = {"status": strict.status_code, "body": strict.text[:400]}
        detail = strict.json().get("detail", {}) if strict.status_code != 202 else {}
        if strict.status_code != 422 or detail.get("code") != "frontier_not_closed":
            failures.append(f"strict fork answered {strict.status_code}: {strict.text[:300]}")
        elif "S3" not in strict.text or "S4" not in strict.text:
            failures.append(f"strict refusal does not name S3 and S4: {strict.text[:300]}")

        # 3. The derived run: S1 by reference, S2 at cycle 2 from the seed, S3 and S4 fresh.
        from dataclasses import asdict

        catalog = stack.catalogs[TRACING]
        launched = await stack.http.post(
            f"{BASE}/{derived_run}/launch",
            json={
                "family": "StageGraph",
                "stagegraph": asdict(
                    technical.stage_input(
                        catalog,
                        derived_run,
                        fork_semantic_input_binding_ref(receipt["request_id"]),
                        1,
                    )
                ),
                "source_semantic_input_binding_ref": f"semantic-input:scoped-proof:{run_id}",
            },
        )
        assert launched.status_code == 202, launched.text
        await until(lambda: completed(stack, derived_run), seconds=RUN_SECONDS)
        derived_points = await all_points(stack, derived_run)
        derived_units = units_by_location(derived_points)
        evidence["derived_run"] = derived_run
        evidence["derived_units"] = {
            f"{node}@{cycle}": key for (node, cycle), key in derived_units.items()
        }
        expected = {("S1", 0), (CYCLE_STAGE, LAST_CYCLE), ("S3", 0), ("S4", 0)}
        if set(derived_units) != expected:
            failures.append(f"derived units {sorted(derived_units)}, expected {sorted(expected)}")
        s1_points = unit_points(derived_points, derived_units.get(("S1", 0), ""))
        s1_reused = [item for item in s1_points if "reused" in item["roles"]]
        if len(s1_reused) != 1 or len(s1_points) != 1:
            failures.append(
                f"derived S1 has {len(s1_points)} points, {len(s1_reused)} reused: "
                f"{[item['roles'] for item in s1_points]}"
            )
        elif s1_reused[0]["parent_coordinate"] != s1_result["coordinate"]:
            failures.append("the derived S1 reused point's parent is not the source result point")
        elif s1_reused[0].get("source") != "fork" or s1_reused[0].get("written_by") != "fork_seed":
            failures.append(
                f"the reused point is {s1_reused[0].get('source')}/{s1_reused[0].get('written_by')}"
            )
        s2_points = [
            item
            for item in unit_points(
                derived_points, derived_units.get((CYCLE_STAGE, LAST_CYCLE), "")
            )
            if "reused" not in item["roles"]
        ]
        first = next(
            (item for item in s2_points if "input" in item["roles"] and is_root(item)), None
        )
        if first is None or not seeded:
            failures.append("the derived S2@c2 has no root input point")
        else:
            if first["parent_point_id"] != seeded[0]["point_id"]:
                failures.append(
                    f"derived S2 input point parent {first['parent_point_id']} is not the "
                    f"fork_seed point {seeded[0]['point_id']}"
                )
            if (
                first["coordinate"]["point"]["key"]["thread_id"]
                != seeded[0]["coordinate"]["point"]["key"]["thread_id"]
            ):
                failures.append("the derived S2 does not run on the seeded thread")
            state = await state_as_of(stack, derived_run, first)
            messages = state["state"]["messages"]
            humans = [item for item in messages if item["role"] == "human"]
            evidence["derived_input_state"] = [
                (item["role"], (item["text"] or "")[:80]) for item in messages
            ]
            if not humans or FORK_MARKER not in (humans[-1]["text"] or ""):
                failures.append(
                    "the last human message at the derived S2 input point is not the marker: "
                    f"{(humans[-1]['text'] if humans else None)!r}"
                )
            if len(messages) < seed["message_count"] + 1:
                failures.append(
                    f"{len(messages)} messages at the derived input point, fewer than P's + 1"
                )
        derived_journal = await journal_for_run(stack, derived_run)
        derived_proposals = admitted_proposals(derived_journal)
        admitted_cycles = sorted(
            cycle for (node, cycle) in derived_proposals if node == CYCLE_STAGE
        )
        if admitted_cycles != [LAST_CYCLE]:
            failures.append(f"the derived run admitted {CYCLE_STAGE} cycles {admitted_cycles}")
        derived_objective = (derived_proposals.get((CYCLE_STAGE, LAST_CYCLE)) or {}).get(
            "objective_override"
        )
        if cycle_objective and derived_objective != cycle_objective:
            failures.append(
                f"the derived S2@c{LAST_CYCLE} objective override {derived_objective!r} is not the "
                f"source's {cycle_objective!r}"
            )
        if await all_points(stack, run_id) != points:
            failures.append("the source run's points changed after the fork")

        # 4. The owner's commands over loopback HTTP: a second fork from the same point.
        inject = tmp_path / "msg.json"
        inject.write_text(json.dumps({"text": FORK_MARKER}), encoding="utf-8")
        code, out, err = await cli(
            url,
            stack.token,
            "run",
            "fork",
            run_id,
            "--at",
            f"stage:{CYCLE_STAGE},cycle:{LAST_CYCLE}",
            "--point",
            seed["point_id"],
            "--inject",
            str(inject),
            "--from-snapshot",
            manifest["snapshot_id"],
            "--sponsorship-ref",
            "sponsorship:test",
            "--approval-ref",
            "approval:test",
            "--reason",
            "FX-TR-FORK-CYCLE: the owner's command",
        )
        cli_fork = parse_cli_json(out)
        evidence["cli_fork"] = {"exit": code, "stderr_last": last_line(err), "body": cli_fork}
        cli_receipt = (cli_fork or {}).get("receipt") or {}
        if code != 0 or cli_receipt.get("message_delivery") != "seed_head":
            failures.append(f"missionctl run fork: exit {code}, {last_line(err)!r}, {out[:300]!r}")
        elif cli_receipt.get("start_position") != receipt.get("start_position"):
            failures.append(
                f"missionctl run fork start_position {cli_receipt.get('start_position')} differs"
            )
        code, out, err = await cli(
            url, stack.token, "run", "transcript", derived_run, "--by", "stage"
        )
        groups = [json.loads(line) for line in out.splitlines() if line.strip().startswith("{")]
        evidence["cli_transcript"] = {
            "exit": code,
            "stderr_last": last_line(err),
            "lines": len(groups),
            "stage_groups": [item.get("key") for item in groups if item.get("level") == "stage"][
                :8
            ],
        }
        if code != 0:
            failures.append(
                f"missionctl run transcript --by stage: exit {code}, {last_line(err)!r}"
            )

        evidence["failures"] = failures
        print(
            f"FX-TR-FORK-CYCLE: evidence at {_write_evidence('fx-tr-fork-cycle.json', evidence)}",
            flush=True,
        )
        assert not failures, "\n".join(failures)
