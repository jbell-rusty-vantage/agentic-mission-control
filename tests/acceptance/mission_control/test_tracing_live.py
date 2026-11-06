"""Tracing Stage 2 (SESSION-STAGE-2): the FX-TR fixtures against the owner's real models (T2).

GPT-6 Sol is the parent and GPT-6 Luna the in-process sync subagent, both through the
production OpenAI factory (`tests/fixtures/live_models.py`); everything else is the
production offline stack of the T0 proofs (`tests/fixtures/scoped_api_stack.py`: a fresh
common database on release 1.4.4, a local Temporal, the production workers, the configured
API). Every run writes the owner's files (§4a) under `.scratch/tracing-stage-2/<fixture>/<run
id>/` and appends its spend to `.scratch/tracing-stage-2/spend.jsonl` before the next run.

Gated by `BELLABS_RUN_TRACING_LIVE=1` (paid). Run one test per pytest call, in the
foreground; each refuses to start once the recorded stage spend reaches the ceiling, and a
watchdog cancels its run (`cancel`, `urgency: immediate`) once the run's own spend passes
the item's reserve.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import time
from collections import Counter
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from tests.acceptance.mission_control.test_cognition_points import BASE, all_points, snapshot
from tests.acceptance.mission_control.test_goal_output_unparseable import reconcile_attempts
from tests.acceptance.mission_control.test_tracing import (
    EXPIRY_CLOCK_AHEAD,
    MIN_RETAIN_DAYS,
    cancel_immediately,
    db_rows,
    entry_body_state,
    find_keys,
    frame_class_counts,
    frames_for_run,
    is_child_point,
    parse_cli_json,
    run_frames_expiry,
    settlements_for_run,
    step_holding_tool_call,
    temporal_diagnostics,
    terminal,
    transcript_entries,
    unit_points,
    units_by_location,
)
from tests.acceptance.mission_control.test_tracing_forks import (
    OBJECTIVE as GOAL_OBJECTIVE,
)
from tests.acceptance.mission_control.test_tracing_forks import (
    persist_derived_goal_templates,
)
from tests.acceptance.mission_control.test_tracing_stream import stream_proof
from tests.fixtures import rrm009_production_stack as technical
from tests.fixtures.live_models import (
    CALLS_ROOT,
    CEILING_USD,
    LiveTechnicalBinding,
    SpendMeter,
    live_technical_binding,
    record_spend,
    require_live,
    stage_spend_so_far,
    worker_commit,
    write_json,
)
from tests.fixtures.scoped_api_stack import (
    ScopedStack,
    inspect,
    prepare_run,
    scoped_stack,
    serve_loopback,
    until,
)
from tests.fixtures.stage2_outputs import missionctl, run_directory, write_outputs
from tests.fixtures.stream_capture import StreamCapture, mission_socket
from tests.fixtures.tcp_proxy import ConnectProxy

from mission_control.adapters.postgres.frames.retention import (
    FrameRetentionPolicy,
    PostgresFrameRetention,
)
from mission_control.adapters.temporal.deployment_composition import goal_output_schemas
from mission_control.application.execution.run_launch import fork_semantic_input_binding_ref
from mission_control.application.programs.goal_directed import OUTPUT_UNPARSEABLE
from mission_control.domain.programs.contracts import GoalDirectedStartPosition
from mission_control.domain.programs.goal_directed_runtime import (
    GoalNamedExecutorObservation,
    GoalVerifierObservation,
)

pytestmark = pytest.mark.common_db

GOAL_CONTRACT = technical.GOAL_OUTPUT_CONTRACT
GOAL_OBLIGATION = technical.GOAL_OBLIGATION


@dataclass
class LiveStack:
    stack: ScopedStack
    url: str
    binding: LiveTechnicalBinding
    fixture: str


@asynccontextmanager
async def live_stack(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    fixture: str,
    reserve_usd: float,
    unit_reservation: dict[str, int],
    ceilings: dict[str, int],
    stage_objectives: dict[str, str] | None = None,
    goal_objectives: dict[str, str] | None = None,
    goal_schema_roles: tuple[str, ...] = ("executor", "verifier"),
) -> AsyncIterator[LiveStack]:
    """The scoped stack with the live models and the fixture's reservations and objectives.

    Refuses to start when the recorded stage spend plus this item's reserve would pass the
    owner's ceiling.
    """

    key = require_live()
    spent = stage_spend_so_far()
    if spent + reserve_usd > CEILING_USD:
        pytest.fail(
            f"stage spend {spent:.4f} USD + reserve {reserve_usd} USD passes the "
            f"{CEILING_USD} USD ceiling; not starting {fixture}"
        )
    stamp = time.strftime("%Y%m%dT%H%M%S")
    binding = live_technical_binding(SpendMeter(path=CALLS_ROOT / f"{fixture}-{stamp}.jsonl"))
    monkeypatch.setattr(technical, "technical_binding", lambda: binding)
    monkeypatch.setattr(technical, "UNIT_RESERVATION", dict(unit_reservation))
    monkeypatch.setattr(technical, "TRACING_CEILINGS", dict(ceilings))
    monkeypatch.setattr(technical, "TECHNICAL_CEILINGS", dict(ceilings))
    monkeypatch.setattr(technical, "STAGE_OBJECTIVES", dict(stage_objectives or {}))
    monkeypatch.setattr(technical, "GOAL_OBJECTIVES", dict(goal_objectives or {}))
    schemas = {
        "executor": next(
            digest
            for digest, model in goal_output_schemas().items()
            if model is GoalNamedExecutorObservation
        ),
        "verifier": next(
            digest
            for digest, model in goal_output_schemas().items()
            if model is GoalVerifierObservation
        ),
    }
    monkeypatch.setattr(
        technical,
        "GOAL_SCHEMA_DIGESTS",
        {role: schemas[role] for role in goal_schema_roles},
    )
    monkeypatch.setenv("SCOPED_PROOF_TOKEN_SECONDS", "10800")
    async with (
        scoped_stack(tmp_path, monkeypatch) as stack,
        serve_loopback(stack.application) as url,
    ):
        # The stack pins a placeholder key for the deterministic models; the live factory
        # resolves `environment:OPENAI_API_KEY` when it constructs a model, after this.
        monkeypatch.setenv("OPENAI_API_KEY", key)
        yield LiveStack(stack, url, binding, fixture)


@asynccontextmanager
async def spend_watchdog(
    live: LiveStack, run_ids: list[str], reserve_usd: float
) -> AsyncIterator[dict[str, Any]]:
    """Cancel (`urgency: immediate`) every listed run once the meter passes the reserve."""

    state: dict[str, Any] = {"tripped": False}

    async def watch() -> None:
        while True:
            await asyncio.sleep(5)
            if live.binding.meter.total()["usd"] > reserve_usd and not state["tripped"]:
                state["tripped"] = True
                for run_id in run_ids:
                    with contextlib.suppress(Exception):
                        await cancel_immediately(live.stack, run_id)

    task = asyncio.create_task(watch())
    try:
        yield state
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def run_record(live: LiveStack, run_id: str, **extra: Any) -> dict[str, Any]:
    """What the ledger records with every run (§1): ids, digests, worker commit, spend."""

    return {
        "fixture": live.fixture,
        "run_id": run_id,
        "worker_commit": worker_commit(),
        "model_profiles": live.binding.profile_digests(),
        "binding_digest": live.binding.binding.binding_digest,
        "spend": live.binding.meter.total(),
        **extra,
    }


# --- F-T3-1 on a live Goal Loop (§2, §5: 1.0 USD) --------------------------------------------

F_T3_1_EXECUTOR = (
    "You are the executor of a small knowledge task. Write a note of about 120 words that "
    "explains to a new engineer what a database write-ahead log is and why a committed "
    "transaction survives a crash. Save it with write_file at /goal/1/executor/work/note.md. "
    "Then reply to the user in plain prose, two sentences, saying what you wrote and where."
)
F_T3_1_VERIFIER = (
    "You are the verifier. Judge whether the executor produced a correct, clear note about the "
    "write-ahead log. Answer only through the structured observation: `decision` is "
    "'accepted' when the note is correct and clear, otherwise 'rejected'; `progress_made` "
    f"true if any work was produced; `output_contract_ref` is exactly '{GOAL_CONTRACT}'; when "
    f"accepted, `accepted_obligation_refs` is ['{GOAL_OBLIGATION}'] and `unmet_obligations` is "
    f"[], otherwise `unmet_obligations` is ['{GOAL_OBLIGATION}']; `obligation_applicability` "
    f"is [['{GOAL_OBLIGATION}', true]]; put one short finding per problem in `findings`."
)


@pytest.mark.asyncio
async def test_live_f_t3_1_prose_executor_settles_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F-T3-1, live: the Sol executor has no structured-output binding (the template's schema
    digest is not registered) and answers in prose; the verifier has the registered schema.
    The executor iteration settles `failed` with `output_unparseable:...`, every
    `reconcile_operation` runs once, the run reaches a terminal state and `run inspect`
    names the reason."""

    reserve = 1.0
    async with live_stack(
        tmp_path,
        monkeypatch,
        fixture="f-t3-1-live",
        reserve_usd=reserve,
        unit_reservation={"tokens.total": 200_000, "model.turns": 24},
        ceilings={
            "tokens.total": 2_000_000,
            "model.turns": 400,
            "operation.attempts": 12,
            "goal.iterations": 6,
        },
        goal_objectives={"executor": F_T3_1_EXECUTOR, "verifier": F_T3_1_VERIFIER},
        goal_schema_roles=("verifier",),
    ) as live:
        stack = live.stack
        run_id, body = await prepare_run(stack, "GoalDirected")
        started = time.monotonic()
        async with spend_watchdog(live, [run_id], reserve) as watchdog:
            launched = await stack.http.post(f"{BASE}/{run_id}/launch", json=body)
            assert launched.status_code == 202, launched.text
            try:
                await until(lambda: terminal(stack, run_id), seconds=400)
            finally:
                spend = record_spend(
                    live.fixture, [run_id], live.binding.meter, tripped=watchdog["tripped"]
                )
        elapsed = time.monotonic() - started
        state = await inspect(stack, run_id)
        attempts = await reconcile_attempts(stack, run_id)
        iterations = await db_rows(
            stack,
            "SELECT payload FROM mission_control.runtime_document "
            "WHERE contract = 'goal.iteration/1' AND identity LIKE $1",
            f'["{run_id}"%',
        )
        outputs = await write_outputs(
            stack,
            live.url,
            fixture=live.fixture,
            run_id=run_id,
            group="iteration",
            mission={
                "family": "GoalDirected",
                "launch": body,
                "objectives": {"executor": F_T3_1_EXECUTOR, "verifier": F_T3_1_VERIFIER},
                "structured_output": {"executor": "unregistered digest", "verifier": "registered"},
            },
            extra_files={
                "evidence.json": {
                    **run_record(live, run_id, elapsed_seconds=round(elapsed, 1)),
                    "spend_entry": spend,
                    "lifecycle": state["lifecycle"],
                    "execution_outcome": state.get("execution_outcome"),
                    "unit_failures": state.get("unit_failures"),
                    "reconcile_activities": attempts,
                    "iteration_documents": iterations,
                    "temporal": await temporal_diagnostics(stack, run_id),
                    "model_calls": live.binding.meter.calls,
                }
            },
        )
        print("F-T3-1 LIVE", json.dumps(outputs, default=str)[:2000])
        print("F-T3-1 LIVE SPEND", json.dumps(spend))
        assert state["lifecycle"] == "completed" and state["phase"] == "terminal", state
        assert attempts and all(item.get("attempt", 1) == 1 for item in attempts), attempts
        assert not any("failed" in item for item in attempts), attempts
        failures = state.get("unit_failures") or []
        assert any(item["reason"] == OUTPUT_UNPARSEABLE for item in failures), state


# --- §4 item 1: the Stage Graph mission, live (2.5 USD; STREAM, RECONCILE-LIVE, RETAIN ride) ---

BRIEF_TOPIC = (
    "an engineering brief on how PostgreSQL's write-ahead log (WAL) makes a committed "
    "transaction durable, and what can still go wrong"
)
# No `output_refs` key: the Stage Graph merges the model's structured output over the result,
# so a model-written `output_refs` replaces the refs the attempt registered (AUDIT §A4/§D4,
# OC-D4); the first live mission instructed `"output_refs": []` and S1 settled with no output.
FINAL_JSON = '{"answer": "RRM009-OK", "facts": {"child": true, "mcp": true}'


def stage_procedure(stage: str, task: str, file_name: str, extra_json: str = "") -> str:
    return (
        f"You are stage {stage} of a four-stage pipeline that produces {BRIEF_TOPIC}. "
        f"Your task: {task} Read what earlier stages handed you in your context packet and "
        "your read-only inputs before you write.\n"
        "Follow this procedure, one tool call per step:\n"
        '1. Call the `task` tool once with subagent_type "technical-child" and a one-sentence '
        "question whose answer helps your task; use the answer.\n"
        '2. Call `lookup_binding_marker` once with code "RRM009". It returns a long '
        "reference text; you only need its first line.\n"
        f"3. Write your stage record (Markdown, under 250 words) with `write_file` to "
        f"/workspace/output/{file_name}.\n"
        "4. Finish with ONLY one JSON object, no prose and no code fence: "
        f"{FINAL_JSON}{extra_json}}}"
    )


S2_CYCLES = (
    "\nThis stage is reviewed in cycles. Look in your context packet for the newest line that "
    "starts with 'Brief cycle'; its number N is your cycle (no such line: N is 0). If N is 0 "
    'or 1, add to the final JSON the keys "evaluation": "cycle", "cycle_scope": "stage", '
    '"invalidation_frontier": ["S2"], "next_objective": "Brief cycle <N+1>: <one sentence '
    'naming what to improve in the brief>", "evaluation_ref": '
    '"evaluation:stage2-live:S2:cycle-<N>", "evaluation_contract_ref": '
    f'"{technical.TRACING_EVALUATION_CONTRACT}", "objective_contract_ref": '
    f'"{technical.TRACING_OBJECTIVE_CONTRACT}" (write the numbers, not the brackets). If N '
    'is 2, add "evaluation": "accept" instead.'
)
STAGE_OBJECTIVES = {
    "S1": stage_procedure(
        "S1",
        "gather the five facts the brief must rest on (commit record, fsync, checkpoints, "
        "full-page writes, crash replay), one short paragraph each.",
        "s1-facts.md",
    ),
    "S2": stage_procedure(
        "S2",
        "draft the brief itself from S1's facts: what happens at commit, what recovery "
        "replays, and why the result is durable.",
        "s2-brief.md",
    )
    + S2_CYCLES,
    "S3": stage_procedure(
        "S3",
        "write a five-bullet executive summary of S2's brief for engineering managers.",
        "s3-summary.md",
    ),
    "S4": stage_procedure(
        "S4",
        "list the failure modes the brief implies (for example fsync disabled, storage that "
        "lies about flushes, lost WAL segments) with one mitigation each.",
        "s4-risks.md",
    ),
}
INJECT_TEXT = (
    "Operator note, mid-turn: keep the stage record under 200 words and end it with one "
    "sentence naming the single most common cause of lost committed data."
)
STAGE_GRAPH_CEILINGS = {
    "tokens.total": 3_000_000,
    "model.turns": 600,
    "operation.attempts": 48,
    "goal.iterations": 6,
    "stage.cycles": 8,
}
UNIT_RESERVATION = {"tokens.total": 150_000, "model.turns": 24}


async def inject_mid_turn(
    stack: ScopedStack, run_id: str, node_key: str, text: str
) -> dict[str, Any]:
    """`interrupt_and_inject` naming the stage, re-reading a stale version (FX-DA-INJECT)."""

    for _attempt in range(12):
        state = await inspect(stack, run_id)
        body = {
            "request_id": str(uuid4()),
            "expected_version": state["version"],
            "expected_generation": state["execution_generation"],
            "target": {"kind": "run", "id": run_id},
            "kind": "interrupt_and_inject",
            "payload": {"content": {"text": text}, "node_key": node_key},
            "reason": "Stage 2: one inject mid-turn",
        }
        response = await stack.http.post(f"{BASE}/{run_id}/commands", json=body)
        if response.status_code == 202:
            return body
        assert response.status_code == 409, response.text
    raise AssertionError("the inject was never accepted")


async def transcript_digest(live: LiveStack, run_id: str) -> str:
    code, out, err = await missionctl(
        live.url,
        live.stack.token,
        "run",
        "transcript",
        run_id,
        "--format",
        "jsonl",
        "--limit",
        "5000",
    )
    assert code == 0, err
    return hashlib.sha256(out).hexdigest()


async def calls_at_least(live: LiveStack, count: int) -> bool:
    return len(live.binding.meter.calls) >= count


def mcp_step_of(
    units: dict[tuple[str, int], str],
    points: list[dict[str, Any]],
    frames: list[dict[str, Any]],
) -> tuple[str, dict[str, Any]] | None:
    for (node, cycle), unit in sorted(units.items()):
        roots = [item for item in unit_points(points, unit) if not is_child_point(item)]
        unit_frames = [item for item in frames if item["unit_key"] == unit]
        try:
            step, _call = step_holding_tool_call(roots, unit_frames, tool=technical.MCP_TOOL_NAME)
        except AssertionError:
            continue
        return f"{node}@c{cycle}", step
    return None


async def step_and_replay(
    live: LiveStack, run_id: str, point_id: str, evidence: dict[str, Any], failures: list[str]
) -> dict[str, str]:
    """`run transcript --by step --point P --full` (a whole tool result above 8 KiB) and
    `run replay --point P --dry-run` (`exact: true`) at a real tool-calling step."""

    directory = run_directory(live.fixture, run_id)
    directory.mkdir(parents=True, exist_ok=True)
    step_file = directory / f"step-{point_id}.jsonl"
    code, out, err = await missionctl(
        live.url,
        live.stack.token,
        *("run", "transcript", run_id, "--by", "step", "--point", point_id, "--full"),
        *("--format", "jsonl"),
    )
    step_file.write_bytes(out)
    results = [
        item
        for line in out.decode("utf-8").splitlines()
        if line.strip()
        for item in json.loads(line).get("entries", [])
        if item.get("kind") == "tool_call_completed"
        and technical.MCP_TOOL_NAME in json.dumps(item, default=str)
    ]
    sizes = [len((item.get("body_excerpt") or "").encode()) for item in results]
    evidence["step_tool_result_bytes"] = sizes
    if code != 0 or not any(size > 8 * 1024 for size in sizes):
        failures.append(f"--by step --full: no whole tool result above 8 KiB {sizes} {err[-300:]}")
    replay_file = directory / f"replay-{point_id}.json"
    code, _out, err = await missionctl(
        live.url,
        live.stack.token,
        *("run", "replay", run_id, "--point", point_id, "--dry-run", "--include-batch"),
        *("--out", str(replay_file)),
    )
    report = json.loads(replay_file.read_text(encoding="utf-8")) if replay_file.exists() else {}
    evidence["replay"] = {
        key: report.get(key)
        for key in (
            "exact",
            "batch_digest_recorded",
            "batch_digest_reconstructed",
            "first_difference",
            "call_index",
        )
    }
    if code != 0 or report.get("exact") is not True:
        failures.append(f"replay --dry-run not exact: {evidence['replay']} {err[-300:]}")
    return {"step": str(step_file), "replay": str(replay_file)}


async def reconcile_live(
    live: LiveStack,
    run_id: str,
    points: list[dict[str, Any]],
    evidence: dict[str, Any],
    failures: list[str],
) -> None:
    """FX-TR-RECONCILE-LIVE: nothing to write on a complete run; nothing changes."""

    written_before = sorted((item["point_id"], item.get("written_by")) for item in points)
    digest_before = await transcript_digest(live, run_id)
    code, out, err = await missionctl(
        live.url, live.stack.token, "run", "points", run_id, "--reconcile", "--json"
    )
    report = parse_cli_json(out.decode("utf-8")) if code == 0 else None
    after = await all_points(live.stack, run_id)
    written_after = sorted((item["point_id"], item.get("written_by")) for item in after)
    digest_after = await transcript_digest(live, run_id)
    ranges_before = {item["point_id"]: item.get("frames") for item in points}
    evidence["reconcile_filled"] = [
        {
            "point_id": item["point_id"],
            "unit": item["coordinate"]["unit_key"],
            "roles": item["roles"],
            "ordinal": item["ordinal"],
            "frames": item.get("frames"),
        }
        for item in after
        if item.get("frames") != ranges_before.get(item["point_id"])
    ]
    evidence["reconcile"] = {
        "exit": code,
        "report": report or err[-600:],
        "transcript_digest_equal": digest_before == digest_after,
        "written_by_unchanged": written_before == written_after,
    }
    added = find_keys(report or {}, "points_added")
    filled = find_keys(report or {}, "frame_ranges_filled")
    if (
        code != 0
        or any(int(value or 0) for value in [*added, *filled])
        or written_before != written_after
        or digest_before != digest_after
    ):
        failures.append(f"FX-TR-RECONCILE-LIVE: {evidence['reconcile']}")


async def retain_live(
    stack: ScopedStack, run_id: str, evidence: dict[str, Any], failures: list[str]
) -> None:
    """FX-TR-RETAIN with a streaming model: the deltas go, the steps stay, `expired` reads."""

    before = await frame_class_counts(stack, run_id)
    retention = PostgresFrameRetention(stack.pool, actor_ref="stage2-retain")
    await retention.set_policy(stack.scope, FrameRetentionPolicy(retain_days=MIN_RETAIN_DAYS))
    expiry = await run_frames_expiry(stack, now=datetime.now(UTC) + EXPIRY_CLOCK_AHEAD)
    after = await frame_class_counts(stack, run_id)
    await stack.http.post(f"{BASE}/{run_id}/transcript/refresh")
    entries = await transcript_entries(stack, run_id)
    expired = [item for item in entries if entry_body_state(item) == "expired"]
    evidence["retain"] = {
        "before": before,
        "after": after,
        "expired_entries": len(expired),
        "expired_kinds": sorted({str(item.get("kind")) for item in expired}),
        "expiry": expiry,
    }
    if not before.get("delta"):
        failures.append(f"FX-TR-RETAIN: the streaming run wrote no delta frames: {before}")
    if after.get("delta", 0) != 0 or after.get("step") != before.get("step"):
        failures.append(f"FX-TR-RETAIN: classes {before} -> {after}")
    if before.get("delta") and not expired:
        failures.append("FX-TR-RETAIN: deltas expired but no transcript entry reads expired")


@pytest.mark.asyncio
async def test_live_stage_graph_mission(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """§4 item 1 with FX-TR-STREAM, FX-TR-RECONCILE-LIVE and FX-TR-RETAIN (§4c): `S1 -> S2 ->
    {S3, S4}` on Sol with the Luna child, S2 cycled twice by the model's own evaluation, one
    `interrupt_and_inject` into S1's running turn. Every failure is collected into the
    evidence file before the assertion."""

    reserve = 2.5
    failures: list[str] = []
    evidence: dict[str, Any] = {}
    async with (
        live_stack(
            tmp_path,
            monkeypatch,
            fixture="stage-graph-live",
            reserve_usd=reserve,
            unit_reservation=UNIT_RESERVATION,
            ceilings=STAGE_GRAPH_CEILINGS,
            stage_objectives=STAGE_OBJECTIVES,
        ) as live,
        mission_socket(live.stack.application) as socket_url,
    ):
        stack = live.stack
        run_id, body = await prepare_run(stack, technical.TRACING_FAMILY)
        started = time.monotonic()
        capture = StreamCapture(socket_url, stack.token, run_id)
        async with spend_watchdog(live, [run_id], reserve) as watchdog:
            launched = await stack.http.post(f"{BASE}/{run_id}/launch", json=body)
            assert launched.status_code == 202, launched.text
            await capture.start()
            try:
                await until(lambda: calls_at_least(live, 2), seconds=300)
                evidence["inject"] = await inject_mid_turn(stack, run_id, "S1", INJECT_TEXT)
                await until(lambda: terminal(stack, run_id), seconds=2400)
            finally:
                evidence["spend_entry"] = record_spend(
                    live.fixture, [run_id], live.binding.meter, tripped=watchdog["tripped"]
                )
        evidence["elapsed_seconds"] = round(time.monotonic() - started, 1)
        state = await inspect(stack, run_id)
        evidence["lifecycle"] = [state["lifecycle"], state.get("execution_outcome")]
        if state["lifecycle"] != "completed" or state.get("execution_outcome") == "failed":
            failures.append(f"run not completed: {evidence['lifecycle']}")
        try:
            stream = await stream_proof(stack, socket_url, run_id, capture)
        finally:
            await capture.close()
        evidence["stream"] = {key: value for key, value in stream.items() if key != "resume"}
        resume = stream.get("resume") or {}
        evidence["stream_resume"] = {k: v for k, v in resume.items() if k != "remainder"}
        if stream["problems"] or not resume.get("exact_remainder"):
            failures.append(f"FX-TR-STREAM: {stream['problems']} {evidence['stream_resume']}")

        points = await all_points(stack, run_id)
        units = units_by_location(points)
        evidence["units"] = sorted(f"{node}@c{cycle}" for node, cycle in units)
        for expected in (("S1", 0), ("S2", 0), ("S2", 1), ("S2", 2), ("S3", 2), ("S4", 2)):
            if expected not in units:
                failures.append(f"unit {expected} missing: {evidence['units']}")
        frames = await frames_for_run(stack, run_id)
        evidence["frame_kinds"] = dict(Counter(item["kind"] for item in frames))

        commands = (await stack.http.get(f"{BASE}/{run_id}/commands")).json()["commands"]
        inject_id = (evidence.get("inject") or {}).get("request_id")
        entry: dict[str, Any] = next(
            (c for c in commands if c["command"]["command_id"] == inject_id), {}
        )
        receipts = [receipt["state"] for receipt in entry.get("receipts", [])]
        evidence["inject_receipts"] = receipts
        if not receipts or receipts[-1] != "applied":
            failures.append(f"inject not applied: {receipts}")
        s1 = units.get(("S1", 0), "")
        s1_roles = {role for item in unit_points(points, s1) for role in item["roles"]}
        evidence["s1_roles"] = sorted(s1_roles)
        if not {"interrupted", "replacement_start"} <= s1_roles:
            failures.append(f"S1 points lack interrupted/replacement_start: {sorted(s1_roles)}")

        children = [item for item in points if is_child_point(item)]
        evidence["child_points"] = len(children)
        if not children or not evidence["frame_kinds"].get("subagent_ended"):
            failures.append("FX-TR-SUB: no nested child points or no subagent_ended frame")
        hooked = [
            item
            for item in frames
            if item["kind"] == "hook_invoked"
            and technical.TRACING_HOOK_ID in json.dumps(item["body"], default=str)
        ]
        evidence["catalog_hook_invocations"] = len(hooked)
        if not hooked:
            failures.append("FX-TR-HOOK: no hook_invoked frame names the catalog hook")

        step = mcp_step_of(units, points, frames)
        files: dict[str, str] = {}
        if step is None:
            failures.append("no step holds the lookup_binding_marker tool call")
        else:
            evidence["step_unit"] = step[0]
            files = await step_and_replay(live, run_id, step[1]["point_id"], evidence, failures)

        evidence["outputs"] = await write_outputs(
            stack,
            live.url,
            fixture=live.fixture,
            run_id=run_id,
            group="stage",
            mission={
                "family": "StageGraph (the FX-TR tracing blueprint)",
                "blueprint": technical.tracing_stage_blueprint().model_dump(mode="json"),
                "objectives": STAGE_OBJECTIVES,
                "inject": INJECT_TEXT,
                "launch": body,
                "unit_reservation": UNIT_RESERVATION,
                "ceilings": STAGE_GRAPH_CEILINGS,
            },
            extra_files={"stream-report.json": stream},
        )
        await reconcile_live(live, run_id, points, evidence, failures)
        await retain_live(stack, run_id, evidence, failures)
        record = {**run_record(live, run_id), **evidence, "files": files, "failures": failures}
        write_json(run_directory(live.fixture, run_id) / "evidence.json", record)
        summary = {"spend": evidence["spend_entry"], "failures": failures}
        print("STAGE GRAPH LIVE", json.dumps(summary))
        assert not failures, "\n".join(failures)


# --- §4c FX-TR-BUDGET (0.4 USD) and FX-TR-CANCEL-LIVE (0.4 USD) -------------------------------

TWO_STAGE_OBJECTIVES = {
    "draft": stage_procedure(
        "draft",
        "draft a 200-word explanation of how the write-ahead log makes a commit durable.",
        "draft.md",
    ),
    "review": stage_procedure("review", "review the draft for errors and list them.", "review.md"),
}
# The cancel run's draft is long on purpose: eight tool calls before its answer, so an
# immediate cancel lands inside the turn.
LONG_DRAFT = (
    "You are the draft stage. Write eight separate short files, one `write_file` call each, "
    "named /workspace/output/part-1.md to /workspace/output/part-8.md, each a 60-word "
    "paragraph on one WAL topic (commit record, fsync, group commit, checkpoints, full-page "
    "writes, replay, archiving, replication). Then call `lookup_binding_marker` with code "
    '"RRM009", then answer with ONLY the JSON object '
    f"{FINAL_JSON}}}"
)
BUDGET_TOKENS = 5_000
BUDGET_CEILINGS = {
    "tokens.total": 20_000,
    "model.turns": 200,
    "operation.attempts": 12,
    "goal.iterations": 6,
    "stage.cycles": 8,
}


async def unit_settlements(stack: ScopedStack, run_id: str) -> list[dict[str, Any]]:
    return await settlements_for_run(stack, run_id)


@pytest.mark.asyncio
async def test_live_budget_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """FX-TR-BUDGET: `tokens.total` reserved per unit (5 000) below what Sol spends on the
    draft (each call carries a ~3 000-token prompt). The draft settles with the typed budget
    outcome (not a provider error, not a retry loop); the result point's `budget_snapshot`
    shows the exhausted dimension; `run inspect` shows the budget state; `review` is not
    admitted; the recorded spend stops at the cap (at most the one call that crossed it)."""

    reserve = 0.4
    failures: list[str] = []
    evidence: dict[str, Any] = {"unit_tokens": BUDGET_TOKENS}
    async with live_stack(
        tmp_path,
        monkeypatch,
        fixture="fx-tr-budget",
        reserve_usd=reserve,
        unit_reservation={"tokens.total": BUDGET_TOKENS, "model.turns": 24},
        ceilings=BUDGET_CEILINGS,
        stage_objectives=TWO_STAGE_OBJECTIVES,
    ) as live:
        stack = live.stack
        run_id, body = await prepare_run(stack, "StageGraph")
        async with spend_watchdog(live, [run_id], reserve) as watchdog:
            launched = await stack.http.post(f"{BASE}/{run_id}/launch", json=body)
            assert launched.status_code == 202, launched.text
            try:
                await until(lambda: draft_settled(stack, run_id), seconds=420)
                await asyncio.sleep(10)
            finally:
                evidence["spend_entry"] = record_spend(
                    live.fixture, [run_id], live.binding.meter, tripped=watchdog["tripped"]
                )
        state = await inspect(stack, run_id)
        settlements = await unit_settlements(stack, run_id)
        points = await all_points(stack, run_id)
        results = [item for item in points if "result" in item["roles"]]
        attempts = await db_rows(
            stack,
            "SELECT count(*) AS n FROM mission_control.operation_claim WHERE run_key = $1",
            run_id,
        )
        calls = live.binding.meter.calls
        tokens = [item["input_tokens"] + item["output_tokens"] for item in calls]
        crossed = next(
            (index for index in range(len(tokens)) if sum(tokens[: index + 1]) >= BUDGET_TOKENS),
            None,
        )
        evidence.update(
            {
                "lifecycle": [state["lifecycle"], state.get("execution_outcome")],
                "settlements": settlements,
                "claims": attempts,
                "result_points": [
                    {"unit": item["coordinate"]["unit_key"], "budget": item.get("budget_snapshot")}
                    for item in results
                ],
                "model_calls": calls,
                "call_crossing_cap": crossed,
            }
        )
        draft = [item for item in settlements if ":stage:draft:" in item["operation"]]
        review = [item for item in settlements if ":stage:review:" in item["operation"]]
        if not draft or draft[-1]["status"] != "failed":
            failures.append(f"draft did not settle failed: {draft}")
        if review:
            failures.append(f"review was admitted: {review}")
        snapshots = [item["budget"] for item in evidence["result_points"] if item["budget"]]
        if not any(
            snap.get("failure_code") == "budget_exceeded"
            and "tokens.total" in (snap.get("exhausted") or [])
            for snap in snapshots
        ):
            failures.append(f"no result point names the exceeded budget: {snapshots}")
        budget = state.get("budget") or {}
        evidence["inspect_budget"] = budget
        if not budget.get("dimensions"):
            failures.append("run inspect shows no budget state")
        # The bound: no parent (Sol) call after the call that crossed the cap; a child task in
        # flight at that moment may finish its own calls.
        parent_after = [
            index
            for index, call in enumerate(calls)
            if crossed is not None and index > crossed and call["model"] == "gpt-6-sol"
        ]
        evidence["parent_calls_after_cap"] = parent_after
        if parent_after:
            failures.append(
                f"spend did not stop at the cap: parent calls {parent_after} after the cap was "
                f"crossed at call {crossed}"
            )
        evidence["outputs"] = await write_outputs(
            stack,
            live.url,
            fixture=live.fixture,
            run_id=run_id,
            group="stage",
            mission={
                "family": "StageGraph (draft, review)",
                "objectives": TWO_STAGE_OBJECTIVES,
                "unit_tokens": BUDGET_TOKENS,
                "launch": body,
            },
        )
        record = {**run_record(live, run_id), **evidence, "failures": failures}
        write_json(run_directory(live.fixture, run_id) / "evidence.json", record)
        print("FX-TR-BUDGET", json.dumps({"spend": evidence["spend_entry"], "failures": failures}))
        assert not failures, "\n".join(failures)


async def draft_settled(stack: ScopedStack, run_id: str) -> bool:
    if await terminal(stack, run_id):
        return True
    settled = await unit_settlements(stack, run_id)
    return any(":stage:draft:" in item["operation"] for item in settled)


@pytest.mark.asyncio
async def test_live_cancel_immediate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """FX-TR-CANCEL-LIVE: `cancel --urgency immediate` after the draft's second model call.
    The stop fence refuses the next tool call (`hook_result decision: deny` from
    `mc.stop_fence`), the unit settles `cancelled` (not `completed`, WP-TR-2's observation),
    the fence frame follows the last admitted tool call, and no `model_request` is observed
    after the cancel was accepted."""

    reserve = 0.4
    failures: list[str] = []
    evidence: dict[str, Any] = {}
    async with live_stack(
        tmp_path,
        monkeypatch,
        fixture="fx-tr-cancel-live",
        reserve_usd=reserve,
        unit_reservation={"tokens.total": 150_000, "model.turns": 24},
        ceilings=STAGE_GRAPH_CEILINGS,
        stage_objectives={**TWO_STAGE_OBJECTIVES, "draft": LONG_DRAFT},
    ) as live:
        stack = live.stack
        run_id, body = await prepare_run(stack, "StageGraph")
        async with spend_watchdog(live, [run_id], reserve) as watchdog:
            launched = await stack.http.post(f"{BASE}/{run_id}/launch", json=body)
            assert launched.status_code == 202, launched.text
            try:
                await until(lambda: calls_at_least(live, 2), seconds=300)
                command = await cancel_immediately(stack, run_id)
                accepted_at = datetime.now(UTC)
                evidence["cancel"] = {"command": command, "accepted_at": accepted_at.isoformat()}
                await until(lambda: terminal(stack, run_id), seconds=400)
            finally:
                evidence["spend_entry"] = record_spend(
                    live.fixture, [run_id], live.binding.meter, tripped=watchdog["tripped"]
                )
        state = await inspect(stack, run_id)
        frames = await frames_for_run(stack, run_id)
        settlements = await unit_settlements(stack, run_id)
        deny = [
            item
            for item in frames
            if item["kind"] == "hook_result"
            and isinstance(item["body"], dict)
            and item["body"].get("hook_id") == "mc.stop_fence"
            and item["body"].get("decision") == "deny"
        ]
        requests_after = [
            item
            for item in frames
            if item["kind"] == "model_request" and item["observed_at"] > accepted_at
        ]
        tool_calls = [item for item in frames if item["kind"] == "tool_call_completed"]
        report = await stack.http.get(f"{BASE}/{run_id}/stop-fence")
        evidence.update(
            {
                "lifecycle": [state["lifecycle"], state.get("execution_outcome")],
                "settlements": settlements,
                "deny_frames": [
                    (str(item["observed_at"]), item["tool_call_ref"], item["body"].get("reason"))
                    for item in deny
                ],
                "last_tool_call_at": str(tool_calls[-1]["observed_at"]) if tool_calls else None,
                "model_requests_after_cancel": [
                    str(item["observed_at"]) for item in requests_after
                ],
                "stop_fence_report": report.json() if report.status_code == 200 else report.text,
                "frame_kinds": dict(Counter(item["kind"] for item in frames)),
            }
        )
        draft = [item for item in settlements if ":stage:draft:" in item["operation"]]
        if not draft or draft[-1]["status"] != "cancelled":
            failures.append(f"the draft unit did not settle cancelled: {draft}")
        # Where the cancel lands decides whether a tool call is denied: during a model call
        # the fence denies the tool call it returns; during a tool the next model call is
        # stopped (F-S2-9). Either way no tool call completes after the cancel.
        completed_after = [item for item in tool_calls if item["observed_at"] > accepted_at]
        evidence["tool_calls_completed_after_cancel"] = [
            (str(item["observed_at"]), item["tool_call_ref"]) for item in completed_after
        ]
        if completed_after:
            failures.append(f"{len(completed_after)} tool calls completed after the cancel")
        if requests_after:
            failures.append(f"{len(requests_after)} model requests after the cancel")
        evidence["outputs"] = await write_outputs(
            stack,
            live.url,
            fixture=live.fixture,
            run_id=run_id,
            group="stage",
            mission={
                "family": "StageGraph (draft, review)",
                "draft_objective": LONG_DRAFT,
                "launch": body,
            },
        )
        record = {**run_record(live, run_id), **evidence, "failures": failures}
        write_json(run_directory(live.fixture, run_id) / "evidence.json", record)
        print(
            "FX-TR-CANCEL-LIVE",
            json.dumps({"spend": evidence["spend_entry"], "failures": failures}, default=str),
        )
        assert not failures, "\n".join(failures)


# --- §4 item 2: the fork from S2 cycle 2 with an injected message (1.5 USD) ------------------

FORK_MESSAGE = (
    "Operator instruction for this fork: the brief must add one paragraph on "
    "synchronous_commit=off, what it trades away and when a team should accept that trade."
)


def seedable_step_of(points: list[dict[str, Any]], unit_key: str) -> dict[str, Any]:
    """A root, seedable step of the unit after its input point (the point P of §P5.6)."""

    steps = sorted(
        (
            item
            for item in points
            if item["coordinate"]["unit_key"] == unit_key
            and item["coordinate"]["point"]["key"].get("checkpoint_ns", "") == ""
            and item["seedable"]
            and "input" not in item["roles"]
            and "result" not in item["roles"]
        ),
        key=lambda item: item["ordinal"],
    )
    return steps[len(steps) // 2]


def human_texts(request_body: dict[str, Any]) -> list[str]:
    texts: list[str] = []
    for message in request_body.get("messages") or []:
        body = message.get("body") if isinstance(message, dict) else None
        if message.get("type") == "human" and body is not None:
            texts.append(json.dumps(body, ensure_ascii=False))
    return texts


@pytest.mark.asyncio
async def test_live_fork_from_s2_cycle_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """§4 item 2 (FX-TR-FORK-CYCLE live): the source mission (no inject), then the owner's
    `missionctl run fork RUN --at stage:S2,cycle:2 --point P --inject msg.json`, then the
    derived run to completion: S1 by reference, S2@c2 from the seeded head with the message,
    S3 and S4 fresh; the derived S2@c2's first `model_request` lists the copied messages and
    the injected one, then the packet turn."""

    reserve = 3.0
    failures: list[str] = []
    evidence: dict[str, Any] = {}
    async with live_stack(
        tmp_path,
        monkeypatch,
        fixture="fork-s2-c2-live",
        reserve_usd=reserve,
        unit_reservation=UNIT_RESERVATION,
        ceilings=STAGE_GRAPH_CEILINGS,
        stage_objectives=STAGE_OBJECTIVES,
    ) as live:
        stack = live.stack
        run_id, body = await prepare_run(stack, technical.TRACING_FAMILY)
        derived_run = ""
        async with spend_watchdog(live, [run_id], reserve) as watchdog:
            launched = await stack.http.post(f"{BASE}/{run_id}/launch", json=body)
            assert launched.status_code == 202, launched.text
            try:
                # The source repeats item 1's inject into S1, so F-S2-6 (the interrupted
                # turn's frame ranges at settlement) is proven live by its reconcile below.
                await until(lambda: calls_at_least(live, 2), seconds=300)
                evidence["inject"] = await inject_mid_turn(stack, run_id, "S1", INJECT_TEXT)
                await until(lambda: terminal(stack, run_id), seconds=2400)
                source_spend = live.binding.meter.total()["usd"]
                points = await all_points(stack, run_id)
                units = units_by_location(points)
                evidence["source_units"] = sorted(f"{n}@c{c}" for n, c in units)
                seed_unit = units[(technical.TRACING_CYCLE_STAGE, 2)]
                seed = seedable_step_of(points, seed_unit)
                directory = run_directory(live.fixture, run_id)
                directory.mkdir(parents=True, exist_ok=True)
                seed_state = await stack.http.get(
                    f"{BASE}/{run_id}/points/{seed['point_id']}/state-as-of"
                )
                write_json(
                    directory / f"state-as-of-{seed['point_id']}.json",
                    seed_state.json() if seed_state.status_code == 200 else seed_state.text,
                )
                manifest = await snapshot(stack, run_id)
                message_file = tmp_path / "msg.json"
                message_file.write_text(json.dumps({"text": FORK_MESSAGE}), encoding="utf-8")
                code, out, err = await missionctl(
                    live.url,
                    stack.token,
                    *("run", "fork", run_id, "--at", "stage:S2,cycle:2", "--point"),
                    *(seed["point_id"], "--inject", str(message_file), "--from-snapshot"),
                    *(manifest["snapshot_id"], "--sponsorship-ref", "sponsorship:test"),
                    *("--approval-ref", "approval:test", "--reason", "Stage 2 live fork"),
                    *(
                        f"--baseline-reservation={dimension}={amount}"
                        for dimension, amount in technical.baseline_reservation(
                            technical.TRACING_FAMILY
                        ).items()
                    ),
                    "--json",
                )
                fork = parse_cli_json(out.decode("utf-8")) or {}
                receipt = fork.get("receipt") or {}
                evidence["fork_cli"] = {"exit": code, "stderr": err[-600:]}
                evidence["receipt"] = receipt
                assert code == 0 and receipt, (code, err[-600:], out[:600])
                derived_run = receipt["target_run_id"]
                catalog = stack.catalogs[technical.TRACING_FAMILY]
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
                        "source_semantic_input_binding_ref": (
                            f"semantic-input:scoped-proof:{run_id}"
                        ),
                    },
                )
                assert launched.status_code == 202, launched.text
                await until(lambda: terminal(stack, derived_run), seconds=2400)
            finally:
                evidence["spend_entry"] = record_spend(
                    live.fixture,
                    [run_id, derived_run],
                    live.binding.meter,
                    tripped=watchdog["tripped"],
                )
        evidence["source_spend_usd"] = source_spend
        if receipt.get("frontier_closed") != ["S2", "S3", "S4"]:
            failures.append(f"frontier_closed {receipt.get('frontier_closed')}")
        reused = [item.get("source_unit_key") for item in receipt.get("reused_units") or []]
        if reused != [units[("S1", 0)]]:
            failures.append(f"reused_units {reused}")
        start = receipt.get("start_position") or {}
        if start.get("stage_cycle_ordinals") != {"S2": 2}:
            failures.append(f"start_position {start}")
        if receipt.get("message_delivery") != "seed_head":
            failures.append(f"message_delivery {receipt.get('message_delivery')}")
        if receipt.get("seed_point") != seed["coordinate"]["point"]["key"]["checkpoint_id"]:
            failures.append(f"seed_point {receipt.get('seed_point')}")

        state = await inspect(stack, derived_run)
        evidence["derived_lifecycle"] = [state["lifecycle"], state.get("execution_outcome")]
        if state["lifecycle"] != "completed" or state.get("execution_outcome") == "failed":
            failures.append(f"derived run not completed: {evidence['derived_lifecycle']}")
        derived_points = await all_points(stack, derived_run)
        derived_units = units_by_location(derived_points)
        evidence["derived_units"] = sorted(f"{n}@c{c}" for n, c in derived_units)
        if set(derived_units) != {("S1", 0), ("S2", 2), ("S3", 0), ("S4", 0)}:
            failures.append(f"derived units {evidence['derived_units']}")
        s1_points = unit_points(derived_points, derived_units.get(("S1", 0), ""))
        if [item["roles"] for item in s1_points] != [["reused"]]:
            failures.append(f"derived S1 points {[item['roles'] for item in s1_points]}")
        seeded = [item for item in derived_points if "fork_seed" in item["roles"]]
        s2 = derived_units.get(("S2", 2), "")
        first = next(
            (
                item
                for item in sorted(unit_points(derived_points, s2), key=lambda p: p["ordinal"])
                if "input" in item["roles"] and not is_child_point(item)
            ),
            None,
        )
        if not seeded or first is None or first["parent_point_id"] != seeded[0]["point_id"]:
            failures.append("the derived S2@c2 input point does not follow the fork_seed point")
        if first is not None:
            response = await stack.http.get(
                f"{BASE}/{derived_run}/points/{first['point_id']}/state-as-of"
            )
            found = response.json() if response.status_code == 200 else {"state": {}}
            messages = found["state"].get("messages") or []
            humans = [item for item in messages if item["role"] == "human"]
            evidence["derived_input_last_human"] = (
                (humans[-1]["text"] or "")[:300] if humans else None
            )
            if not humans or FORK_MESSAGE not in (humans[-1]["text"] or ""):
                failures.append("the last human message at the derived S2 input is not the inject")
        entries = await transcript_entries(stack, derived_run, full=True)
        requests = [
            item
            for item in entries
            if item.get("kind") == "model_request"
            and item.get("unit_key") == s2
            and not item.get("subordinate_ref")
        ]
        if not requests:
            failures.append("the derived S2@c2 has no model_request")
        else:
            request_body = json.loads(requests[0].get("body_excerpt") or "{}")
            texts = human_texts(request_body)
            evidence["derived_first_request"] = {
                "messages": len(request_body.get("messages") or []),
                "seed_message_count": seed["message_count"],
                "humans": [text[:160] for text in texts],
            }
            if len(request_body.get("messages") or []) < seed["message_count"] + 1:
                failures.append("the derived first request does not carry the copied messages")
            if not any(FORK_MESSAGE in text for text in texts):
                failures.append("the derived first request does not carry the injected message")

        source_outputs = await write_outputs(
            stack,
            live.url,
            fixture=live.fixture,
            run_id=run_id,
            group="stage",
            mission={
                "family": "StageGraph (fork source)",
                "objectives": STAGE_OBJECTIVES,
                "launch": body,
            },
        )
        derived_outputs = await write_outputs(
            stack,
            live.url,
            fixture=live.fixture,
            run_id=derived_run,
            group="stage",
            mission={
                "family": "StageGraph (derived by fork)",
                "source_run": run_id,
                "fork_message": FORK_MESSAGE,
                "seed_point": seed["point_id"],
            },
            fork_receipt=fork,
        )
        evidence["outputs"] = {"source": source_outputs, "derived": derived_outputs}
        source_reconcile: dict[str, Any] = {}
        await reconcile_live(live, run_id, points, source_reconcile, failures)
        evidence["source_reconcile"] = source_reconcile
        # The inject reached the replacement turn's model request (F-S2-8 keeps the whole
        # request body, so the full transcript shows the injected message).
        transcript_text = await asyncio.to_thread(
            Path(source_outputs["files"]["transcript.jsonl"]).read_text, encoding="utf-8"
        )
        evidence["inject_in_source_transcript"] = INJECT_TEXT in transcript_text
        if INJECT_TEXT not in transcript_text:
            failures.append("the injected operator note is not in the source transcript")
        record = {
            **run_record(live, derived_run),
            "source_run_id": run_id,
            **evidence,
            "failures": failures,
        }
        write_json(run_directory(live.fixture, derived_run) / "evidence.json", record)
        summary = {"spend": evidence["spend_entry"], "failures": failures}
        print("FORK LIVE", json.dumps(summary, default=str))
        assert not failures, "\n".join(failures)


# --- §4 item 3: a three-iteration Goal Loop and its fork at iteration 2 (2.5 USD) -------------

GOAL_EXECUTOR = (
    "You are the executor of a three-iteration knowledge task: a note for new engineers on how "
    "a database write-ahead log makes a committed transaction survive a crash. Your context "
    "packet names your goal iteration and your writable work slot (the path ending in /work). "
    "Read the verifier's findings and the handoff from the previous iteration when there is "
    "one, then write or improve the note with write_file at <your work slot>/note.md (about "
    "150 words). Answer through the structured observation: `disposition` 'completed', "
    f"`output_contract_ref` exactly '{GOAL_CONTRACT}', `evidence_refs` and "
    "`accepted_fact_refs` one short reference each (for example 'note:iteration-<n>'), and "
    "`completion_claim` true only at iteration 3."
)
GOAL_VERIFIER = (
    "You are the verifier of a three-iteration Goal Loop about a note on the write-ahead log. "
    "Your context packet names the goal iteration. Read the executor's note from your inputs. "
    "At iterations 1 and 2 the loop is designed to continue: `decision` 'rejected', "
    "`progress_made` true, one concrete improvement per entry in `findings`, "
    f"`unmet_obligations` ['{GOAL_OBLIGATION}']. At iteration 3 judge on the merits: "
    f"'accepted' with `accepted_obligation_refs` ['{GOAL_OBLIGATION}'] and `unmet_obligations` "
    "[] when the note is correct and clear. Always: `output_contract_ref` exactly "
    f"'{GOAL_CONTRACT}', `obligation_applicability` [['{GOAL_OBLIGATION}', true]], "
    "`evidence_refs` one short reference."
)
GOAL_FORK_MESSAGE = (
    "Operator instruction for this fork: rewrite the note for an on-call engineer, starting "
    "from the symptom 'the database restarted after a power loss'."
)
GOAL_CEILINGS = {
    "tokens.total": 3_000_000,
    "model.turns": 600,
    "operation.attempts": 24,
    "goal.iterations": 8,
}


@pytest.mark.asyncio
async def test_live_goal_loop_and_fork(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """§4 item 3 (FX-TR-FORK-GD live): three iterations on Sol (executor and verifier with
    their registered structured-output schemas), then a fork at iteration 2 from a seedable
    executor point with an injected message: the derived iteration 1 settles by reference,
    iteration 2's executor runs on the seeded thread with the message, the verifier fresh."""

    reserve = 3.0
    failures: list[str] = []
    evidence: dict[str, Any] = {}
    original_blueprint = technical.goal_blueprint
    monkeypatch.setattr(
        technical,
        "goal_blueprint",
        lambda **kwargs: original_blueprint(**{**kwargs, "max_iterations": 3}),
    )
    async with live_stack(
        tmp_path,
        monkeypatch,
        fixture="goal-loop-live",
        reserve_usd=reserve,
        unit_reservation=UNIT_RESERVATION,
        ceilings=GOAL_CEILINGS,
        goal_objectives={"executor": GOAL_EXECUTOR, "verifier": GOAL_VERIFIER},
    ) as live:
        stack = live.stack
        run_id, body = await prepare_run(stack, "GoalDirected")
        derived_run = ""
        fork: dict[str, Any] = {}
        async with spend_watchdog(live, [run_id], reserve) as watchdog:
            launched = await stack.http.post(f"{BASE}/{run_id}/launch", json=body)
            assert launched.status_code == 202, launched.text
            try:
                await until(lambda: terminal(stack, run_id), seconds=2400)
                evidence["source_spend_usd"] = live.binding.meter.total()["usd"]
                state = await inspect(stack, run_id)
                evidence["source_lifecycle"] = [state["lifecycle"], state.get("execution_outcome")]
                points = await all_points(stack, run_id)
                units = goal_units(points)
                evidence["source_units"] = sorted(f"{it}/{role}" for it, role in units)
                executor_2 = sorted(
                    (
                        item
                        for item in points
                        if item["location"]["iteration"] == 2
                        and item["location"]["node_key"] == "executor"
                        and not is_child_point(item)
                        and item["seedable"]
                    ),
                    key=lambda item: item["ordinal"],
                )
                assert executor_2, f"no seedable iteration-2 executor point: {evidence}"
                seed = next(
                    (item for item in executor_2 if "input" in item["roles"]), executor_2[0]
                )
                directory = run_directory(live.fixture, run_id)
                directory.mkdir(parents=True, exist_ok=True)
                seed_state = await stack.http.get(
                    f"{BASE}/{run_id}/points/{seed['point_id']}/state-as-of"
                )
                write_json(
                    directory / f"state-as-of-{seed['point_id']}.json",
                    seed_state.json() if seed_state.status_code == 200 else seed_state.text,
                )
                manifest = await snapshot(stack, run_id)
                response = await stack.http.post(
                    f"{BASE}/{run_id}/forks",
                    json={
                        "request_id": str(uuid4()),
                        "snapshot_id": manifest["snapshot_id"],
                        "snapshot_digest": manifest["snapshot_digest"],
                        "at": {
                            "iteration": 2,
                            "session_generation": seed["location"]["session_generation"],
                        },
                        "cognitive_seed": {
                            "unit_key": seed["coordinate"]["unit_key"],
                            "checkpoint": seed["coordinate"]["point"]["key"],
                        },
                        "message": {"text": GOAL_FORK_MESSAGE},
                        "baseline_reservations": technical.baseline_reservation("GoalDirected"),
                        "sponsorship_ref": "sponsorship:test",
                        "approval_refs": ["approval:test"],
                        "reason": "Stage 2 live Goal Directed fork at iteration 2",
                    },
                )
                assert response.status_code == 202, response.text
                fork = response.json()
                receipt = fork["receipt"]
                derived_run = receipt["target_run_id"]
                catalog = stack.catalogs["GoalDirected"]
                derived_binding = fork_semantic_input_binding_ref(receipt["request_id"])
                await persist_derived_goal_templates(stack, catalog, derived_binding)
                start = receipt.get("start_position") or {}
                position = GoalDirectedStartPosition(
                    goal_iteration=int(start.get("goal_iteration") or 2),
                    session_generation=int(start.get("session_generation") or 1),
                    agent_run=int(start.get("agent_run") or 1),
                )
                launched = await stack.http.post(
                    f"{BASE}/{derived_run}/launch",
                    json={
                        "family": "GoalDirected",
                        "goal_directed": asdict(
                            technical.goal_input(
                                catalog,
                                derived_run,
                                derived_binding,
                                1,
                                GOAL_OBJECTIVE,
                                revision_id=receipt.get("derived_goal_revision_id") or None,
                                envelope_digest=technical.goal_revision(
                                    run_id, GOAL_OBJECTIVE
                                ).envelope_digest,
                                start_position=position,
                            )
                        ),
                    },
                )
                assert launched.status_code == 202, launched.text
                await until(lambda: terminal(stack, derived_run), seconds=2400)
            finally:
                evidence["spend_entry"] = record_spend(
                    live.fixture,
                    [run_id, derived_run],
                    live.binding.meter,
                    tripped=watchdog["tripped"],
                )
        if set(units) != {(it, role) for it in (1, 2, 3) for role in ("executor", "verifier")}:
            failures.append(f"source iterations {evidence['source_units']} (three expected)")
        if receipt.get("message_delivery") != "seed_head":
            failures.append(f"message_delivery {receipt.get('message_delivery')}")
        reused = {item["source_unit_key"] for item in receipt.get("reused_units") or []}
        if reused != {units.get((1, "executor")), units.get((1, "verifier"))}:
            failures.append(f"reused_units {sorted(reused)}")
        derived_state = await inspect(stack, derived_run)
        evidence["derived_lifecycle"] = [
            derived_state["lifecycle"],
            derived_state.get("execution_outcome"),
        ]
        if derived_state["phase"] != "terminal":
            failures.append(f"derived run not terminal: {evidence['derived_lifecycle']}")
        derived_points = await all_points(stack, derived_run)
        derived_units = goal_units(derived_points)
        evidence["derived_units"] = sorted(f"{it}/{role}" for it, role in derived_units)
        for role in ("executor", "verifier"):
            mine = [
                item
                for item in derived_points
                if item["location"]["iteration"] == 1 and item["location"]["node_key"] == role
            ]
            if [item["roles"] for item in mine] != [["reused"]]:
                failures.append(f"derived iteration-1 {role}: {[i['roles'] for i in mine]}")
        seeded = [item for item in derived_points if "fork_seed" in item["roles"]]
        executor_2 = sorted(
            (
                item
                for item in derived_points
                if item["location"]["iteration"] == 2
                and item["location"]["node_key"] == "executor"
                and "input" in item["roles"]
                and not is_child_point(item)
            ),
            key=lambda item: item["ordinal"],
        )
        if (
            not seeded
            or not executor_2
            or executor_2[0]["parent_point_id"] != seeded[0]["point_id"]
        ):
            failures.append("the derived iteration-2 executor does not follow the fork_seed point")
        else:
            response = await stack.http.get(
                f"{BASE}/{derived_run}/points/{executor_2[0]['point_id']}/state-as-of"
            )
            found = response.json() if response.status_code == 200 else {"state": {}}
            humans = [m for m in found["state"].get("messages") or [] if m["role"] == "human"]
            evidence["derived_executor_last_human"] = (
                (humans[-1]["text"] or "")[:300] if humans else None
            )
            if not humans or GOAL_FORK_MESSAGE not in (humans[-1]["text"] or ""):
                failures.append("the derived iteration-2 executor's last human is not the inject")
        verifier_2 = [
            item
            for item in derived_points
            if item["location"]["iteration"] == 2 and item["location"]["node_key"] == "verifier"
        ]
        if not verifier_2 or any("reused" in item["roles"] for item in verifier_2):
            failures.append("the derived iteration-2 verifier did not run fresh")

        source_outputs = await write_outputs(
            stack,
            live.url,
            fixture=live.fixture,
            run_id=run_id,
            group="iteration",
            mission={
                "family": "GoalDirected (three iterations)",
                "objectives": {"executor": GOAL_EXECUTOR, "verifier": GOAL_VERIFIER},
                "launch": body,
            },
        )
        derived_outputs = await write_outputs(
            stack,
            live.url,
            fixture=live.fixture,
            run_id=derived_run,
            group="iteration",
            mission={
                "family": "GoalDirected (derived by fork at iteration 2)",
                "source_run": run_id,
                "fork_message": GOAL_FORK_MESSAGE,
                "seed_point": seed["point_id"],
            },
            fork_receipt=fork,
        )
        evidence["outputs"] = {"source": source_outputs, "derived": derived_outputs}
        record = {
            **run_record(live, derived_run),
            "source_run_id": run_id,
            **evidence,
            "failures": failures,
        }
        write_json(run_directory(live.fixture, derived_run) / "evidence.json", record)
        print("GOAL LIVE", json.dumps({"spend": evidence["spend_entry"], "failures": failures}))
        assert not failures, "\n".join(failures)


def goal_units(points: list[dict[str, Any]]) -> dict[tuple[int, str], str]:
    return {
        (int(item["location"]["iteration"]), str(item["location"]["node_key"])): str(
            item["coordinate"]["unit_key"]
        )
        for item in points
    }


# --- §4c FX-TR-DISCONNECT (0.5 USD; runs last) ----------------------------------------------


async def call_in_flight(live: LiveStack, count: int) -> bool:
    meter = live.binding.meter
    return meter.started >= count and len(meter.calls) + len(meter.errors) < meter.started


@pytest.mark.asyncio
async def test_live_provider_disconnect(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """FX-TR-DISCONNECT: every provider connection goes through a loopback `CONNECT` tunnel
    (`HTTPS_PROXY`); one second into the draft's second model call every open tunnel is cut.
    Recorded, then asserted: the typed outcome the activity settles with (there is no retry
    classifier for provider errors; the evidence names what happens), the partial frames of
    the cut turn survive with their point, the retries are bounded, the run reaches a
    terminal state, and the spend of the partial turn is recorded."""

    reserve = 0.5
    failures: list[str] = []
    evidence: dict[str, Any] = {}
    proxy = ConnectProxy()
    await proxy.start()
    monkeypatch.setenv("HTTPS_PROXY", f"http://127.0.0.1:{proxy.port}")
    monkeypatch.setenv("https_proxy", f"http://127.0.0.1:{proxy.port}")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    try:
        async with live_stack(
            tmp_path,
            monkeypatch,
            fixture="fx-tr-disconnect",
            reserve_usd=reserve,
            unit_reservation={"tokens.total": 150_000, "model.turns": 24},
            ceilings=STAGE_GRAPH_CEILINGS,
            stage_objectives=STAGE_OBJECTIVES,
        ) as live:
            stack = live.stack
            # The four-stage blueprint declares no wait: the two-stage one parks a run whose
            # draft failed at the human wait before `review` (attempt 1 of this fixture).
            run_id, body = await prepare_run(stack, technical.TRACING_FAMILY)
            started = time.monotonic()
            async with spend_watchdog(live, [run_id], reserve) as watchdog:
                launched = await stack.http.post(f"{BASE}/{run_id}/launch", json=body)
                assert launched.status_code == 202, launched.text
                try:
                    await until(lambda: call_in_flight(live, 2), seconds=300)
                    await asyncio.sleep(1.0)
                    evidence["cut"] = {
                        "at": datetime.now(UTC).isoformat(),
                        "tunnels_cut": proxy.sever_open(),
                        "calls_started": live.binding.meter.started,
                        "calls_finished": len(live.binding.meter.calls),
                    }
                    try:
                        await until(lambda: terminal(stack, run_id), seconds=900)
                        evidence["terminal"] = True
                    except (AssertionError, TimeoutError) as error:
                        evidence["terminal"] = False
                        evidence["terminal_wait"] = str(error)[:300]
                finally:
                    evidence["spend_entry"] = record_spend(
                        live.fixture, [run_id], live.binding.meter, tripped=watchdog["tripped"]
                    )
            evidence["elapsed_seconds"] = round(time.monotonic() - started, 1)
            evidence["model_errors"] = live.binding.meter.errors
            evidence["tunnels"] = proxy.tunnels
            state = await inspect(stack, run_id)
            evidence["lifecycle"] = [
                state["lifecycle"],
                state.get("phase"),
                state.get("execution_outcome"),
            ]
            settlements = await settlements_for_run(stack, run_id)
            evidence["settlements"] = settlements
            attempts = await db_rows(
                stack,
                "SELECT a.attempt_no, a.execution_generation, a.execution_outcome, a.failure_class "
                "FROM mission_control.attempt a "
                "JOIN mission_control.mission_run r ON r.run_id = a.run_id AND "
                "r.installation_id = a.installation_id AND r.tenant_id = a.tenant_id "
                "WHERE r.run_key = $1 ORDER BY a.created_at",
                run_id,
            )
            evidence["attempts"] = attempts
            frames = await frames_for_run(stack, run_id)
            points = await all_points(stack, run_id)
            evidence["frame_kinds"] = dict(Counter(item["kind"] for item in frames))
            evidence["points"] = [
                {
                    "unit": item["coordinate"]["unit_key"],
                    "roles": item["roles"],
                    "generation": item["coordinate"].get("execution_generation"),
                    "frames": item.get("frames"),
                }
                for item in points
            ]
            evidence["temporal"] = await temporal_diagnostics(stack, run_id)
            if not evidence.get("terminal"):
                failures.append("the run did not reach a terminal state after the cut")
            if len(attempts) > 6:
                failures.append(f"{len(attempts)} attempts: retries are not bounded")
            cut_at = datetime.fromisoformat(evidence["cut"]["at"])
            before_cut = [item for item in frames if item["observed_at"] < cut_at]
            if not before_cut:
                failures.append("no frame of the cut turn survived")
            if not any(item.get("frames") for item in points):
                failures.append("no point holds a frame range after the cut")
            if not any((item.get("usage") or {}).get("tokens.total") for item in settlements):
                failures.append("the settlement recorded no usage for the calls before the cut")
            evidence["outputs"] = await write_outputs(
                stack,
                live.url,
                fixture=live.fixture,
                run_id=run_id,
                group="stage",
                mission={
                    "family": "StageGraph (the FX-TR tracing blueprint)",
                    "objectives": STAGE_OBJECTIVES,
                    "proxy": f"CONNECT tunnel 127.0.0.1:{proxy.port}",
                    "launch": body,
                },
            )
            record = {**run_record(live, run_id), **evidence, "failures": failures}
            write_json(run_directory(live.fixture, run_id) / "evidence.json", record)
            print(
                "FX-TR-DISCONNECT",
                json.dumps({"spend": evidence["spend_entry"], "failures": failures}, default=str),
            )
    finally:
        await proxy.stop()
    assert not failures, "\n".join(failures)
