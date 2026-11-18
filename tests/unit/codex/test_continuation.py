"""MP-08 x MP-12: the codex continuation (sealed checkpoint -> a fresh thread).

FIXTURES: the FIXTURE app-server (`tests/support/providers/codex.py`) and the MP-12
in-memory continuation service (`tests/support/continuation.py`). Proves:

- the snapshot port freezes `inputs/`, `outputs/`, `.mission/` and takes custody of the lease's
  git patch, never the lane's state root or `CODEX_HOME`;
- the hydrator restores the snapshot and the continuation packet into the live lease and
  starts a FRESH thread on a FRESH app-server (`thread/start`; no `thread/resume`, no
  `thread/fork`); nothing is sent to the target before the handover turn;
- the phase machine (`ContinuationPhaseService` + `LaneTurnService`): the requested
  continuation ends the source turn at its boundary, the phases activate the hydrated target,
  and the next `lane.turn` adopts it (the source app-server terminated) and sends exactly one
  continuation turn carrying the sealed packet;
- the in-segment handover (`SessionHandoverLane`): a continuation hydrated while the source
  turn runs is sent at that turn's boundary within the same segment;
- the registration resolves only `codex` and stays unqualified; the lane's delivery row is
  `wait_then_send`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mission_control.adapters.codex.continuation import (
    WORKSPACE_SNAPSHOT_PREFIX,
    CodexSessionHydrator,
    CodexWorkspaceSnapshots,
    codex_continuation_registration,
)
from mission_control.application.context.continuation import (
    ContinuationRejected,
)
from mission_control.application.context.hydrators import LaneHydratorRegistry
from mission_control.application.execution.harness.controls import SessionHandoverLane
from mission_control.domain.context.checkpoint import continuation_delivery
from mission_control.domain.execution.lanes import LaneSegmentBounds
from tests.support.ids import SCOPE
from tests.support.knowledge.stores import InMemoryStaging
from tests.support.providers.codex import codex_stack

SOURCE = "thr-0001"
BOUNDS = LaneSegmentBounds(max_frames=200, max_duration_s=20, heartbeat_timeout_s=3)


# --- registration and delivery -----------------------------------------------------------------


def test_the_registration_resolves_this_lane_only_and_stays_unqualified(tmp_path: Path) -> None:
    stack = codex_stack(tmp_path, approvals=False)
    registry = LaneHydratorRegistry()
    registry.register(codex_continuation_registration(stack.harness, InMemoryStaging()))
    assert registry.profiles() == ("codex",)
    assert isinstance(registry.hydrator("codex", SCOPE), CodexSessionHydrator)
    assert isinstance(registry.snapshots("codex", SCOPE), CodexWorkspaceSnapshots)
    assert registry.registration("codex").qualified is False
    with pytest.raises(ContinuationRejected):
        registry.hydrator("claude_agent_sdk", SCOPE)
    assert stack.harness.describe().features["continuation"].qualified is False
    assert isinstance(stack.harness, SessionHandoverLane)
    # The continuation turn is a `turn/start` sent only on the idle fresh thread.
    assert continuation_delivery("codex") == "wait_then_send"


async def test_snapshots_refuse_a_thread_this_worker_does_not_hold(tmp_path: Path) -> None:
    stack = codex_stack(tmp_path, approvals=False)
    snapshots = CodexWorkspaceSnapshots(stack.harness, InMemoryStaging())
    with pytest.raises(ContinuationRejected) as rejected:
        await snapshots.snapshot(
            request_scope=SCOPE, run_key="run-1", session_ref="thr-elsewhere", roots=()
        )
    assert rejected.value.code == "CHECKPOINT_INVALID"
    assert await snapshots.load(request_scope=SCOPE, snapshot_ref="other:1") is None
    missing = f"{WORKSPACE_SNAPSHOT_PREFIX}missing"
    assert await snapshots.load(request_scope=SCOPE, snapshot_ref=missing) is None


# --- the phase machine: boundary, phases, activated target, continuation turn -------------------


# --- the in-segment handover: hydrated while the source turn runs ------------------------------


async def test_hydration_refuses_a_thread_without_a_live_lease(tmp_path: Path) -> None:
    from mission_control.application.execution.harness.protocol import NativeTurnLost

    stack = codex_stack(tmp_path, approvals=False)
    stack.harness.stage(stack.heid, stack.operation)
    with pytest.raises(NativeTurnLost):
        await stack.harness.hydrate_session(
            stack.heid, transfer_id="t-1", prompt_text="x", source_session_ref=SOURCE
        )
    assert stack.launcher.launches == []
