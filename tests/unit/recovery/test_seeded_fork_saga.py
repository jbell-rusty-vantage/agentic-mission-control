"""Tracing Stage 3 (R2-2, R2-3): a seeded fork's receipt proves its seed is in place.

The fork saga runs the cognitive seed after materialization and before the receipt
(`before_receipt`): a refused seed leaves no receipt and the fork replayable, a replay of a
fork with its receipt never re-runs the copy, the launch refuses a seeded fork without a
receipt retryably (`fork_seed_pending`), and re-seeding a namespace with the same head is the
recorded namespace rather than a conflict.
"""

from __future__ import annotations

from typing import Any

import pytest
from tests.fixtures.checkpoint_lineage import namespace_claim, stage_unit
from tests.unit.runtime.test_runtime_recovery_stage3 import (
    DIGEST,
    ForkAuthority,
    ForkMaterializer,
    fork_request,
)

from mission_control.application.execution.operations.checkpoint_lineage import (
    InMemoryCheckpointLineageRepository,
)
from mission_control.application.execution.run_launch import (
    RunLaunchRejected,
    RunLaunchRequest,
    RunLaunchService,
)
from mission_control.application.recovery.run_forks import ForkOfRun
from mission_control.application.recovery.runtime_recovery import (
    ForkMaterializationObservation,
    InMemoryForkRepository,
    RuntimeForkService,
)
from mission_control.domain.execution.checkpoint_lineage import CheckpointLineageConflict
from mission_control.domain.graph_runtime.identities import QualifiedCheckpointKey
from mission_control.domain.policies.forks import (
    CognitiveSeed,
    ForkRejected,
    RunForkPatch,
    RunForkReceipt,
    RunForkRequest,
)

SEED_KEY = QualifiedCheckpointKey(
    checkpointer_ref_digest=DIGEST,
    thread_id="belllabs/stage/source/gen/1",
    checkpoint_ns="",
    checkpoint_id="point-7",
)


def seeded_request() -> RunForkRequest:
    request = fork_request()
    patch = RunForkPatch.create(
        source_snapshot_id=request.patch.source_snapshot_id,
        source_snapshot_digest=request.patch.source_snapshot_digest,
        target_admission_request_ref=request.patch.target_admission_request_ref,
        cognitive_seed=CognitiveSeed(unit_key="bl-unit-v1:" + "ab" * 32, checkpoint=SEED_KEY),
    )
    return request.model_copy(update={"patch": patch})


class ReconcilingMaterializer(ForkMaterializer):
    """A materializer whose recorded lineage a replay reconciles."""

    def __init__(self) -> None:
        super().__init__()
        self.recorded: Any = None

    async def materialize(self, request, admission):  # type: ignore[no-untyped-def]
        self.recorded = await super().materialize(request, admission)
        return self.recorded

    async def reconcile_materialization(self, _request, _admission):  # type: ignore[no-untyped-def]
        return ForkMaterializationObservation(status="materialized", materialization=self.recorded)


class Seeds:
    def __init__(self, *, refuse: int = 0) -> None:
        self.calls: list[str] = []
        self.refuse = refuse

    async def seed(self, request: RunForkRequest, receipt: RunForkReceipt) -> None:
        self.calls.append(receipt.request_id)
        if self.refuse:
            self.refuse -= 1
            raise ForkRejected("cognitive_seed_unavailable", "the saver did not answer")


def saga() -> tuple[RuntimeForkService, InMemoryForkRepository]:
    repository = InMemoryForkRepository()
    return (
        RuntimeForkService(
            repository=repository,
            authority=ForkAuthority(),  # type: ignore[arg-type]
            materializer=ReconcilingMaterializer(),  # type: ignore[arg-type]
        ),
        repository,
    )


@pytest.mark.asyncio
async def test_the_seed_runs_before_the_receipt_and_never_again_on_a_replay() -> None:
    service, repository = saga()
    seeds = Seeds()
    request = seeded_request()

    receipt = await service.fork(request, before_receipt=seeds.seed)
    replay = await service.fork(request, before_receipt=seeds.seed)

    assert replay == receipt
    assert seeds.calls == ["fork-1"]
    assert await repository.get("tenant-1", "fork-1") == receipt


@pytest.mark.asyncio
async def test_a_refused_seed_leaves_no_receipt_and_the_fork_replayable() -> None:
    service, repository = saga()
    seeds = Seeds(refuse=1)
    request = seeded_request()

    with pytest.raises(ForkRejected) as refused:
        await service.fork(request, before_receipt=seeds.seed)
    assert refused.value.code == "cognitive_seed_unavailable"
    assert await repository.get("tenant-1", "fork-1") is None

    receipt = await service.fork(request, before_receipt=seeds.seed)
    assert seeds.calls == ["fork-1", "fork-1"]
    assert await repository.get("tenant-1", "fork-1") == receipt


class Materializations:
    async def fork_of_run(self, request_scope: str, derived_run_id: str) -> ForkOfRun:
        return ForkOfRun(fork_request_id="fork-1", materialized=True)


class Receipts:
    def __init__(self, request: RunForkRequest) -> None:
        self.request = request

    async def get_request(self, request_scope: str, request_id: str) -> RunForkRequest:
        return self.request

    async def get(self, request_scope: str, request_id: str) -> None:
        return None


@pytest.mark.asyncio
async def test_the_launch_refuses_a_seeded_fork_without_its_receipt_retryably() -> None:
    def launcher(request: RunForkRequest) -> RunLaunchService:
        return RunLaunchService(
            run_control=object(),  # type: ignore[arg-type]
            submitter=object(),  # type: ignore[arg-type]
            forks=Receipts(request),  # type: ignore[arg-type]
            materializations=Materializations(),  # type: ignore[arg-type]
        )

    launch = RunLaunchRequest(
        request_scope="tenant-1", run_id="run-derived", family="StageGraph", stagegraph={}
    )
    with pytest.raises(RunLaunchRejected) as refused:
        await launcher(seeded_request())._fork_of(launch)
    assert refused.value.code == "fork_seed_pending" and refused.value.retryable
    # An unseeded fork without a receipt is the lineage gap it always was.
    with pytest.raises(RunLaunchRejected) as missing:
        await launcher(fork_request())._fork_of(launch)
    assert missing.value.code == "fork_lineage_missing" and not missing.value.retryable


@pytest.mark.asyncio
async def test_seeding_a_namespace_again_with_the_same_head_is_not_a_conflict() -> None:
    lineage = InMemoryCheckpointLineageRepository()
    claim = namespace_claim(
        stage_unit(request_scope="tenant-1", run_id="run-derived", operation_id="S2")
    )
    head = SEED_KEY.model_copy(update={"thread_id": claim.namespace})
    first = await lineage.seed_namespace_head("tenant-1", claim, head, observed_at=None)  # type: ignore[arg-type]
    again = await lineage.seed_namespace_head("tenant-1", claim, head, observed_at=None)  # type: ignore[arg-type]
    assert again == first and again.head == head
    other = head.model_copy(update={"checkpoint_id": "point-8"})
    with pytest.raises(CheckpointLineageConflict):
        await lineage.seed_namespace_head("tenant-1", claim, other, observed_at=None)  # type: ignore[arg-type]


def test_the_fork_seed_point_records_the_head_count_the_lane_read() -> None:
    """Tracing Stage 3 (R2-1): the `fork_seed` point's message count is the one the lane read
    at the seed head, never the source's count plus one."""

    from tests.unit.temporal.test_fork_seed_runner import request as seed_request

    from mission_control.application.execution.harness.time_travel import ForkSeedReceipt
    from mission_control.application.recovery.cognitive_seed import _head_message_count

    source = seed_request().source.model_copy(update={"message_count": 5})

    def receipt(**artifacts: str) -> ForkSeedReceipt:
        return ForkSeedReceipt(
            restore_level="R3",
            derived=source.coordinate,
            copied_checkpoints=1,
            native_artifacts=artifacts,
        )

    assert _head_message_count(receipt(seed_head_message_count="3"), source, "msg") == 3
    assert _head_message_count(receipt(), source, "msg") is None
    assert _head_message_count(receipt(), source, None) == 5
