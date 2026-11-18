"""Builders, constants and fakes that other test files import.

Moved from tests/unit/temporal/test_fork_seed_runner.py.
"""

from __future__ import annotations

from datetime import UTC, datetime

from mission_control.application.execution.harness.time_travel import ForkSeedRequest
from mission_control.domain.execution.cognition_points import (
    CheckpointPoint,
    CognitionCoordinate,
    CognitionPointRecord,
    UnitLocationFacts,
    point_id_for,
)
from mission_control.domain.graph_runtime.identities import QualifiedCheckpointKey

DIGEST = "sha256:" + "5" * 64
UNIT_KEY = "bl-unit-v1:" + "ab" * 32


def request() -> ForkSeedRequest:
    key = QualifiedCheckpointKey(
        checkpointer_ref_digest=DIGEST, thread_id="thread", checkpoint_ns="", checkpoint_id="p"
    )
    return ForkSeedRequest(
        source=CognitionPointRecord(
            point_id=point_id_for("run-source", UNIT_KEY, 1, "checkpoint", "p"),
            coordinate=CognitionCoordinate(
                run_id="run-source",
                unit_key=UNIT_KEY,
                execution_generation=1,
                point=CheckpointPoint(key=key),
            ),
            lane_profile="deep_agents",
            location=UnitLocationFacts(family="stage_graph", node_key="S2", iteration=0, cycle=0),
            seedable=True,
            written_by="adapter",
            recorded_at=datetime.now(UTC),
        ),
        derived_run_id="run-derived",
        derived_unit_key=UNIT_KEY,
        derived_namespace="derived-thread",
        derived_invocation_id="sha256:" + "6" * 64,
        fork_request_id="fork-1",
    )
