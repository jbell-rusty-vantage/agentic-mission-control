from __future__ import annotations

from dataclasses import asdict
from types import SimpleNamespace
from typing import Any, cast

import pytest

from mission_control.application.execution.operations.journaled_operation_execution import (
    JournaledOperationExecutionCoordinator,
)
from mission_control.application.execution.operations.operation_execution import (
    RunControlOperationAuthority,
    bind_operation_execution_request,
)
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.execution.contracts import OperationAttemptIdentity
from mission_control.domain.execution.journal import OperationClaimResult
from mission_control.domain.graph_runtime.identities import NO_MAPPED_INSTANCE
from mission_control.domain.policies.contracts import (
    CancelAction,
    CommandStatus,
    ExecutionTarget,
    PauseAction,
    PauseDecision,
    StartAction,
)
from mission_control.domain.programs.contracts import (
    StageCandidateIdentity,
    StageExecutionIdentity,
    StageGraphDecisionMutation,
)
from mission_control.domain.programs.runtime_units import stage_runtime_unit
from tests.unit.operations.test_operation_execution import operation_request
from tests.unit.run_control.test_operation_authority_cas import claim as authority_claim
from tests.unit.run_control.test_run_control import DIGEST, NOW, actor, command, request, service


def admitted_stage():  # type: ignore[no-untyped-def]
    identity = StageExecutionIdentity(
        "run-operation",
        1,
        StageCandidateIdentity("formulations", 0, NO_MAPPED_INSTANCE, 0, 0, "produce"),
        1,
    )
    unit = stage_runtime_unit("tenant-1", identity)
    operation = operation_request().model_copy(
        update={
            "identity": OperationAttemptIdentity(
                run_id=identity.run_id,
                operation_id=identity.operation_id,
                operation_attempt=1,
            ),
            "runtime_unit": unit,
            "idempotency_key": f"stagegraph:{identity.semantic_key}:generation:1",
        }
    )
    digest = sha256_digest(identity.semantic_key)[7:]
    exact_ref = f"operation-request:{digest}"
    mutation = StageGraphDecisionMutation(
        mutation_id=f"admit-{digest}",
        request_scope="tenant-1",
        run_id=identity.run_id,
        expected_family_version=0,
        exact_operation_request_ref=exact_ref,
        decided_at=NOW,
        decision_kind="operation_admitted",
        prior_projection_digest=DIGEST,
        next_projection_digest="sha256:" + "b" * 64,
        decision_payload={
            "proposal": {
                "identity": asdict(identity),
                "exact_operation_request_ref": exact_ref,
                "reservation_id": operation.budget_reservation_id,
                "reservation": operation.budget_limits,
            }
        },
    )
    target = ExecutionTarget(
        family="StageGraph", family_workflow_id="family", root_workflow_id="root"
    )
    run = SimpleNamespace(
        version=5,
        execution_target=target,
        effective_configuration_digest=DIGEST,
    )
    admission = SimpleNamespace(
        resulting_version=4,
        command_id=f"stagegraph:admit-{digest}",
        evidence_refs=(exact_ref,),
        resulting_projection=SimpleNamespace(
            effective_configuration_digest=DIGEST,
            execution_target=target,
        ),
    )

    class Authority:
        async def get_family_mutation(self, *args: Any) -> Any:
            return mutation

        async def list_transitions(self, *args: Any) -> Any:
            return (admission,)

    authority = RunControlOperationAuthority(cast(Any, Authority()), cast(Any, None))
    return authority, operation, run, mutation, admission


@pytest.mark.asyncio
async def test_later_version_first_bind_requires_recorded_exact_stage_admission() -> None:
    authority, operation, run, _, _ = admitted_stage()
    await authority._verify_stage_admission(operation, run)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        "foreign_attempt",
        "foreign_scope",
        "generation",
        "reservation",
        "request_ref",
        "nonadmission",
        "transition_version",
        "transition_command",
        "transition_evidence",
        "macro_generation",
        "epoch",
        "erc",
        "backwards",
        "no_unit",
    ],
)
async def test_later_version_cannot_borrow_another_stage_admission(change: str) -> None:
    authority, operation, run, mutation, admission = admitted_stage()
    proposal = mutation.decision_payload["proposal"]
    assert isinstance(proposal, dict)
    if change == "foreign_attempt":
        operation = operation.model_copy(
            update={
                "identity": operation.identity.model_copy(
                    update={"operation_attempt": 2},
                )
            }
        )
    elif change == "foreign_scope":
        operation = operation.model_copy(update={"request_scope": "other-scope"})
    elif change == "generation":
        identity = proposal["identity"]
        assert isinstance(identity, dict)
        identity["execution_generation"] = 2
    elif change == "reservation":
        proposal["reservation_id"] = "another-reservation"
    elif change == "request_ref":
        proposal["exact_operation_request_ref"] = "operation-request:other"
    elif change == "nonadmission":
        object.__setattr__(mutation, "decision_kind", "result_decided")
    elif change == "transition_version":
        admission.resulting_version = 3
    elif change == "transition_command":
        admission.command_id = "stagegraph:other"
    elif change == "transition_evidence":
        admission.evidence_refs = ("operation-request:other",)
    elif change in {"macro_generation", "epoch"}:
        field = "execution_generation" if change == "macro_generation" else "execution_epoch"
        run.execution_target = run.execution_target.model_copy(update={field: 2})
    elif change == "erc":
        admission.resulting_projection.effective_configuration_digest = "sha256:" + "f" * 64
    elif change == "backwards":
        run.version = 3
    elif change == "no_unit":
        operation = operation.model_copy(update={"runtime_unit": None})
    with pytest.raises(ValueError, match="Run Control revision"):
        await authority._verify_stage_admission(operation, run)


@pytest.mark.asyncio
@pytest.mark.parametrize("intervention", ["pause", "cancel"])
async def test_claim_cas_retry_rechecks_control_phase_before_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    intervention: str,
) -> None:
    control, repository = service()
    admitted = await control.admit(request())
    assert admitted.run_id is not None
    run_id = admitted.run_id
    await control.execute(command(run_id, 1, "start", StartAction()))
    operation = operation_request().model_copy(
        update={
            "identity": OperationAttemptIdentity(
                run_id=run_id, operation_id="stage", operation_attempt=1
            ),
            "run_control_revision": 2,
            "budget_reservation_id": "baseline",
            "budget_limits": {"tokens.total": 20},
        }
    )
    binding = bind_operation_execution_request(operation)
    committed: list[Any] = []

    class Journal:
        async def commit(self, mutation: Any) -> OperationClaimResult:
            committed.append(mutation)
            return OperationClaimResult(status="acquired", claim=mutation.claim, reason="claimed")

    coordinator = JournaledOperationExecutionCoordinator(
        journal=cast(Any, Journal()),
        run_control=control,
        results=cast(Any, None),
        actor=actor(),
    )
    original = repository.commit_command
    intervened = False

    async def commit(mutation: Any):  # type: ignore[no-untyped-def]
        nonlocal intervened
        if mutation.result.idempotency_issuer == "operation-journal" and not intervened:
            intervened = True
            action = (
                CancelAction()
                if intervention == "cancel"
                else PauseAction(
                    decision=PauseDecision(
                        decision_id="pause",
                        scope=frozenset({"run"}),
                        reason="operator",
                        authority_ref="authority:lifecycle",
                    ),
                    runnable_work_remains=False,
                )
            )
            accepted = await control.execute(command(run_id, 2, "intervention", action))
            assert accepted.status is CommandStatus.ACCEPTED
        return await original(mutation)

    monkeypatch.setattr(repository, "commit_command", commit)
    with pytest.raises(ValueError, match="current authority phase"):
        await coordinator.acquire(binding, claimed_by="fixture:worker")
    assert intervened and committed == []
    assert (await control.get_effects("tenant-1", run_id)).claims == {}
    if intervention == "cancel":
        cancelled = await coordinator.acquire(
            binding, claimed_by="fixture:cancel", at_current_version=True
        )
        assert cancelled.status == "acquired" and cancelled.claim is not None


@pytest.mark.asyncio
async def test_pinned_authority_replay_cannot_refresh_a_recovery_version() -> None:
    control, _ = service()
    admitted = await control.admit(request())
    assert admitted.run_id is not None
    await control.execute(command(admitted.run_id, 1, "start", StartAction()))
    coordinator = JournaledOperationExecutionCoordinator(
        journal=cast(Any, None),
        run_control=control,
        results=cast(Any, None),
        actor=actor(),
    )
    original = authority_claim(admitted.run_id, "pinned")
    issued, accepted = await coordinator._execute_replayable(original, pinned_version=True)
    assert accepted.status is CommandStatus.ACCEPTED
    assert await coordinator._execute_replayable(issued, pinned_version=True) == (issued, accepted)
    with pytest.raises(RuntimeError, match="pinned version"):
        await coordinator._execute_replayable(
            original.model_copy(update={"expected_run_version": 99}),
            pinned_version=True,
        )
    assert len((await control.get_effects("tenant-1", admitted.run_id)).claims) == 1


@pytest.mark.asyncio
async def test_standalone_synthetic_stage_unit_retains_exact_absent_macro_target() -> None:
    """GenericArtifactWorkflow may attach a unit after a standalone StartAction()."""
    control, _ = service()
    admitted = await control.admit(request())
    assert admitted.run_id is not None
    run_id = admitted.run_id
    await control.execute(command(run_id, 1, "standalone-start", StartAction()))
    _, template, _, _, _ = admitted_stage()
    assert template.runtime_unit is not None
    unit = template.runtime_unit.model_copy(update={"belllabs_run_id": run_id})
    operation = template.model_copy(
        update={
            "identity": template.identity.model_copy(update={"run_id": run_id}),
            "runtime_unit": unit,
            "run_control_revision": 2,
            "budget_reservation_id": "baseline",
            "budget_limits": {"tokens.total": 20},
        }
    )
    binding = bind_operation_execution_request(operation)

    class Journal:
        async def commit(self, mutation: Any) -> OperationClaimResult:
            return OperationClaimResult(status="acquired", claim=mutation.claim, reason="claimed")

    coordinator = JournaledOperationExecutionCoordinator(
        journal=cast(Any, Journal()),
        run_control=control,
        results=cast(Any, None),
        actor=actor(),
    )
    validate = await coordinator._authority_validator(
        binding,
        claiming=True,
        cancellation_claim=False,
    )
    run = await control.get_run("tenant-1", run_id)
    budget = await control.get_budget("tenant-1", run_id)
    effects = await control.get_effects("tenant-1", run_id)
    assert run.execution_target is None
    validate(run, budget, effects)
    replacement = run.model_copy(
        update={
            "execution_target": ExecutionTarget(
                family="StageGraph",
                family_workflow_id="different-family",
                root_workflow_id="new-root",
            )
        }
    )
    with pytest.raises(ValueError, match="no longer matches"):
        validate(replacement, budget, effects)
    claimed = await coordinator.acquire(binding, claimed_by="fixture:standalone")
    assert claimed.status == "acquired" and claimed.claim is not None
    # Standalone compatibility does not enable the StageGraph later-version firstbind gate.
    authority = RunControlOperationAuthority(control, cast(Any, None))
    with pytest.raises(ValueError, match="Run Control revision"):
        await authority._verify_stage_admission(
            operation, await control.get_run("tenant-1", run_id)
        )
