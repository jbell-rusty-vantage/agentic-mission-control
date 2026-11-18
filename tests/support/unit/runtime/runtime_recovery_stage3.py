"""Builders, constants and fakes that other test files import.

Moved from tests/unit/runtime/test_runtime_recovery_stage3.py.
"""

from __future__ import annotations

from datetime import UTC, datetime

from mission_control.application.recovery.runtime_recovery import (
    ForkAdmission,
    ForkAdmissionObservation,
    ForkMaterialization,
    ForkMaterializationObservation,
)
from mission_control.domain.graph_runtime.identities import ExecutionEpochKey
from mission_control.domain.policies.forks import (
    RunForkPatch,
    RunForkRequest,
    admission_request_ref,
    lineage_for,
)
from tests.support.run_control import request as run_request

DIGEST = "sha256:" + "a" * 64
NOW = datetime(2026, 8, 6, 20, 0, tzinfo=UTC)


SOURCE_RUN = "run-1"
DERIVED_RUN = "run-2"
SNAPSHOT_ID = "run-snapshot:" + "1" * 64
SNAPSHOT_DIGEST = "sha256:" + "2" * 64


def fork_request(
    *,
    effective_configuration_digest: str = DIGEST,
    requested_at: datetime = NOW,
    reason: str = "branch from a settled boundary",
) -> RunForkRequest:
    target = run_request(request_id="fork-1").model_copy(
        update={
            "effective_configuration_digest": effective_configuration_digest,
            "requested_at": requested_at,
        }
    )
    patch = RunForkPatch.create(
        source_snapshot_id=SNAPSHOT_ID,
        source_snapshot_digest=SNAPSHOT_DIGEST,
        target_admission_request_ref=admission_request_ref(target),
    )
    return RunForkRequest(
        request_id="fork-1",
        idempotency_key="fork-1",
        request_scope="tenant-1",
        source_run_id=SOURCE_RUN,
        source_execution_epoch=1,
        snapshot_id=SNAPSHOT_ID,
        snapshot_digest=SNAPSHOT_DIGEST,
        patch=patch,
        target=target,
        derived_run_id=DERIVED_RUN,
        actor_id="operator",
        reason=reason,
        requested_at=requested_at,
    )


class ForkAuthority:
    def __init__(self, *, epoch: int = 1) -> None:
        self.calls = 0
        self._epoch = epoch

    async def admit_fork(self, request):  # type: ignore[no-untyped-def]
        self.calls += 1
        return ForkAdmission(
            request_id=request.request_id,
            target_epoch=ExecutionEpochKey(
                request_scope=request.request_scope,
                belllabs_run_id=request.derived_run_id,
                execution_epoch=self._epoch,
            ),
            admission_ref=f"admission:{request.request_id}",
            budget_reservation_ref="budget:fork-1",
            admitted_effective_configuration_digest=request.target.effective_configuration_digest,
        )

    async def reconcile_fork_admission(self, _request):  # type: ignore[no-untyped-def]
        return ForkAdmissionObservation(status="ambiguous")


class ForkMaterializer:
    def __init__(self) -> None:
        self.calls = 0

    async def materialize(self, request, admission):  # type: ignore[no-untyped-def]
        self.calls += 1
        return ForkMaterialization(
            request_id=request.request_id,
            target_run_id=admission.target_epoch.belllabs_run_id,
            lineage=lineage_for(request, admission_ref=admission.admission_ref),
        )

    async def reconcile_materialization(self, _request, _admission):  # type: ignore[no-untyped-def]
        return ForkMaterializationObservation(status="ambiguous")
