from __future__ import annotations

import pytest

from mission_control.application.programs.service import producer_effects_settled
from mission_control.domain.policies.contracts import EffectLedgerState
from tests.unit.operations.test_rrm_009_cancellation_composition import _claim

RESERVATION = "reservation:run-1:operation:formulations:attempt:1"
KEY = "stagegraph:run-1:operation:formulations:attempt:1:generation:1"


def runtime(*, settled: bool = True, key: str = KEY):  # type: ignore[no-untyped-def]
    return _claim("own-runtime", "operation.runtime", "binding-1", settled=settled).model_copy(
        update={"reservation_id": RESERVATION, "provider_idempotency_key": key}
    )


def ledger(*claims):  # type: ignore[no-untyped-def]
    return EffectLedgerState(run_id="run-1", claims={claim.effect_id: claim for claim in claims})


def scoped(effects, **kwargs):  # type: ignore[no-untyped-def]
    return producer_effects_settled(
        effects,
        producer_reservation_id=RESERVATION,
        producer_side_effect_key=KEY,
        **kwargs,
    )


def test_parallel_siblings_effects_do_not_hold_this_producer_open() -> None:
    own = runtime()
    sibling = _claim("sibling", "operation.runtime", "binding-other", settled=False)
    child = _claim("sibling-child", "async_subagent.child", "binding-other", settled=False)
    assert scoped(ledger(own, sibling, child))
    assert not producer_effects_settled(ledger(own, sibling, child)), (
        "global terminal rule unchanged"
    )


@pytest.mark.parametrize("kind", ["operation.runtime", "async_subagent.child", "tool-effect:write"])
def test_own_pending_runtime_children_and_tools_still_block(kind: str) -> None:
    if kind == "operation.runtime":
        assert not scoped(ledger(runtime(settled=False)))
    else:
        assert not scoped(ledger(runtime(), _claim("own-effect", kind, "binding-1", settled=False)))


@pytest.mark.parametrize("change", ["missing", "reservation", "attempt", "generation", "ambiguous"])
def test_owner_resolution_fails_closed_without_exact_admitted_authority(change: str) -> None:
    own = runtime()
    claims = [own]
    if change == "missing":
        claims = []
    elif change == "reservation":
        claims = [own.model_copy(update={"reservation_id": "another-reservation"})]
    elif change == "attempt":
        claims = [runtime(key=KEY.replace("attempt:1", "attempt:2"))]
    elif change == "generation":
        claims = [runtime(key=KEY.replace("generation:1", "generation:2"))]
    else:
        claims.append(
            own.model_copy(update={"effect_id": "duplicate", "operation_ref": "binding-2"})
        )
    assert not scoped(ledger(*claims))


def test_reconciled_unit_generation_does_not_rekey_immutable_operation_binding() -> None:
    # Unit/checkpoint generation may advance independently; the effect remains the admitted
    # OperationExecutionBinding's exact generation-1 idempotency key and reservation.
    assert scoped(ledger(runtime()))
    assert not producer_effects_settled(
        ledger(runtime()),
        producer_reservation_id=RESERVATION,
        producer_side_effect_key=KEY.replace("generation:1", "generation:2"),
    )


def test_cancellation_exempts_only_owned_child_usage_not_other_effects() -> None:
    child = _claim("own-child", "async_subagent.child", "binding-1", settled=False)
    sibling = _claim("sibling", "operation.runtime", "other-binding", settled=False)
    assert scoped(ledger(runtime(), child, sibling), cancelled_binding_id="binding-1")
    assert not scoped(ledger(runtime(), child), cancelled_binding_id="another-binding")
    assert not scoped(
        ledger(
            runtime(), child, _claim("own-tool", "tool-effect:write", "binding-1", settled=False)
        ),
        cancelled_binding_id="binding-1",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("changes_requested", [False, True])
@pytest.mark.parametrize(
    "corruption",
    [
        None,
        "scope",
        "epoch",
        "packet",
        "open",
        "missing",
        "next_objective",
        "evaluation_ref",
        "evaluation_contract_ref",
        "objective_contract_ref",
        "invalidation_frontier",
        "evaluation",
        "cycle_scope",
    ],
)
async def test_human_gate_requires_exact_stored_terminal_task(corruption, changes_requested):
    from dataclasses import replace

    from mission_control.application.programs.service import StageGraphDecisionService
    from mission_control.domain.authoring.contracts import StageGraphBlueprint, WorkflowCyclePolicy
    from mission_control.domain.programs.contracts import (
        LateResultFacts,
        StageGraphResultActivityRequest,
        StageResultObservation,
    )
    from mission_control.domain.programs.human_gate import (
        HumanResolution,
        open_activation,
        outcome_for,
        stagegraph_gate_result,
    )
    from tests.unit.human_tasks.fixtures import open_task, packet
    from tests.unit.orchestration.test_human_gate_budget_admission import (
        GATE,
        fixture,
    )

    control, repository, candidate = await fixture()
    gate = GATE.model_copy(update={"remediation_target": "work", "max_review_rounds": 2})
    policy = WorkflowCyclePolicy(
        max_cycles=2,
        evaluation_contract_ref="evaluation:workflow@1",
        objective_contract_ref="objective:workflow@1",
        reservation={"workflow.cycles": 1},
    )
    blueprint = StageGraphBlueprint.model_validate(candidate.blueprint).model_copy(
        update={
            "workflow_cycle_policy": policy,
            "workflow_evaluation_contract_ref": policy.evaluation_contract_ref,
        }
    )
    candidate = replace(candidate, human_gate=gate, blueprint=blueprint.model_dump(mode="json"))

    class Gates:
        async def verify(self, actual):
            assert actual.human_gate == gate
            return (gate,)

    admitted = await StageGraphDecisionService(
        control, repository, human_gates=Gates()
    ).admit_operation(candidate)
    identity = candidate.proposal.identity
    activation = open_activation(
        request_scope=candidate.request_scope,
        run_id=candidate.run_id,
        family="StageGraph",
        activation_key=f"stage:{identity.semantic_key}",
        execution_epoch=identity.execution_epoch,
        review_round=1,
        spec=gate,
        packet=packet(),
        opened_at=candidate.occurred_at,
    )
    task = open_task(activation)
    resolution = HumanResolution(
        human_task_id=task.human_task_id,
        request_id="actual-answer",
        actor_ref="actual-owner",
        decision="request_changes" if changes_requested else "approve",
        resolution_action="review_reject" if changes_requested else "review_accept",
        review_decision="request_changes" if changes_requested else "approve",
        reviewed_packet_digest=activation.packet_digest,
        expected_task_version=1,
        decided_at=candidate.occurred_at,
    )
    task = task.model_copy(update={"lifecycle": "resolved", "resolution": resolution})
    outcome = outcome_for(task)
    assert outcome is not None
    disposition, payload = stagegraph_gate_result(
        outcome,
        evaluation_contract_ref=policy.evaluation_contract_ref,
        objective_contract_ref=policy.objective_contract_ref,
    )
    observed = StageGraphResultActivityRequest(
        run_id=candidate.run_id,
        request_scope=candidate.request_scope,
        projection=admitted.projection,
        observation=StageResultObservation(
            identity, payload, True, True, True, True, 1, operation_disposition=disposition
        ),
        late_facts=LateResultFacts(),
        blueprint=candidate.blueprint,
        effective_max_concurrency=1,
        occurred_at=candidate.occurred_at,
        idempotency_issuer="operator",
        correlation_id="stored-host-proof",
    )
    if corruption in {"scope", "epoch"}:
        task = task.model_copy(
            update={
                "activation": activation.model_copy(
                    update={
                        "request_scope"
                        if corruption == "scope"
                        else "execution_epoch": "other-scope"
                        if corruption == "scope"
                        else identity.execution_epoch + 1,
                    }
                )
            }
        )
    elif corruption == "packet":
        observed = replace(
            observed,
            observation=replace(
                observed.observation,
                operation_result={
                    **payload,
                    "human_gate": {
                        **outcome.model_dump(mode="json"),
                        "packet_digest": "sha256:" + "a" * 64,
                    },
                },
            ),
        )
    elif corruption == "open":
        task = open_task(activation)
    elif corruption is not None:
        observed = replace(
            observed,
            observation=replace(
                observed.observation,
                operation_result={
                    **payload,
                    corruption: ["other-stage"]
                    if corruption == "invalidation_frontier"
                    else "altered",
                },
            ),
        )

    class Tasks:
        async def get(self, scope, task_id):
            assert scope == candidate.request_scope and task_id == task.human_task_id
            return None if corruption == "missing" else task

    service = StageGraphDecisionService(control, repository, human_tasks=Tasks())
    budget = await control.get_budget(candidate.request_scope, candidate.run_id)
    effects = ledger(_claim("sibling", "operation.runtime", "another-binding", settled=False))
    assert await service._nonoperation_effects_settled(
        observed,
        candidate.proposal.reservation_id,
        budget,
        effects,
    ) is (corruption is None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "corruption",
    [
        None,
        "missing",
        "attempt",
        "digest",
        "usage",
        "open_child",
        "body",
        "unstarted",
        "unstarted_spend",
        "unstarted_effect",
        "never_activated",
    ],
)
async def test_nested_body_requires_stored_activation_receipt_and_parent_usage(corruption):
    from dataclasses import replace
    from types import SimpleNamespace

    from mission_control.application.programs.nested_bodies import (
        InMemoryNestedActivationStore,
        NestedActivationRecord,
    )
    from mission_control.application.programs.service import StageGraphDecisionService
    from mission_control.domain.authoring.canonical import sha256_digest
    from mission_control.domain.authoring.contracts import StageGraphBlueprint
    from mission_control.domain.policies.contracts import RecordUsageAction, RunOutcome, RunPhase
    from mission_control.domain.programs.nested import NestedProjection
    from tests.unit.orchestration.test_completion_validation_service import prepared
    from tests.unit.orchestration.test_wi13_nested_runtime import body
    from tests.unit.run_control.test_run_control import command

    fixture = await prepared(release_usage=False)
    candidate = fixture.result
    identity = candidate.observation.identity
    liability = candidate.projection.producer_liabilities[identity.semantic_key]
    host = body().model_copy(
        update={
            "host_id": identity.stage_id,
            "node_key": identity.stage_id,
            "position": identity.stage_id,
            "exports": body().exports[:1],
        }
    )
    blueprint = StageGraphBlueprint.model_validate(candidate.blueprint).model_copy(
        update={"nested_bodies": () if corruption == "body" else (host,)}
    )
    candidate = replace(candidate, blueprint=blueprint.model_dump(mode="json"))
    unstarted = corruption in {
        "unstarted",
        "unstarted_spend",
        "unstarted_effect",
        "never_activated",
    }
    receipt = NestedProjection(
        child_run_id="" if corruption == "never_activated" else "actual-child",
        position=identity.stage_id,
        outcome="cancelled" if unstarted else "completed",
        composite_accepted=not unstarted,
        actual_usage={} if unstarted else {"tokens.total": 1},
    ).receipt()
    result = await fixture.run_control.execute(
        command(
            candidate.run_id,
            candidate.projection.run_version,
            "nested-settlement",
            RecordUsageAction(
                usage_id=f"nested-usage:{liability.reservation_id}",
                reservation_id=liability.reservation_id,
                actual_amounts={} if unstarted else {"tokens.total": 1},
                release_amounts={"tokens.total": 1} if unstarted else {},
            ),
        )
    )
    assert result.status.value == "accepted"
    store = InMemoryNestedActivationStore()
    record = NestedActivationRecord(
        request_scope=candidate.request_scope,
        parent_run_id=candidate.run_id,
        host_id=identity.stage_id,
        semantic_attempt_id=identity.semantic_key,
        position=identity.stage_id,
        family="StageGraph",
        depth=1,
        child_run_id="actual-child",
        budget_ceiling={"tokens.total": 1},
        body_digest=sha256_digest(host),
        activated_at=candidate.occurred_at,
        receipt=receipt,
        settled_at=candidate.occurred_at,
    )
    if corruption == "attempt":
        record = replace(record, semantic_attempt_id="other-attempt")
    if corruption not in {"missing", "never_activated"}:
        await store.record(record)
    if corruption == "digest":
        receipt = {**receipt, "receipt_digest": "sha256:" + "b" * 64}
    candidate = replace(
        candidate,
        observation=replace(
            candidate.observation,
            operation_result={"nested": receipt, "output_refs": []},
            operation_disposition="cancelled" if unstarted else "completed",
        ),
    )
    budget = await fixture.run_control.get_budget(candidate.request_scope, candidate.run_id)
    if corruption == "usage":
        budget = budget.model_copy(update={"usage_records": {}})

    class Control:
        async def get_run(self, scope, child):
            assert scope == candidate.request_scope and child == "actual-child"
            return SimpleNamespace(
                phase=RunPhase.CANCELLING
                if unstarted
                else (RunPhase.ACTIVE if corruption == "open_child" else RunPhase.TERMINAL),
                terminal_outcome=RunOutcome.COMPLETED,
                execution_target=None,
            )

        async def get_effects(self, scope, child):
            return ledger(
                *(
                    [_claim("own-child", "operation.runtime", "child-binding", settled=False)]
                    if corruption == "unstarted_effect"
                    else []
                )
            )

        async def get_budget(self, scope, child):
            return budget.model_copy(
                update={
                    "consumed": {"tokens.total": 1} if corruption == "unstarted_spend" else {},
                    "pending_settlement": {},
                }
            )

    service = StageGraphDecisionService(Control(), fixture.repository, nested_activations=store)
    assert await service._nonoperation_effects_settled(
        candidate,
        liability.reservation_id,
        budget,
        ledger(_claim("sibling", "operation.runtime", "other-binding", settled=False)),
    ) is (corruption in {None, "unstarted", "never_activated"})


@pytest.mark.asyncio
@pytest.mark.parametrize("amount", [0, 1])
async def test_never_activated_nested_body_persists_zero_usage_and_removes_empty_reservation(
    amount,
):
    from mission_control.application.programs.nested_bodies import (
        InMemoryNestedActivationStore,
        NestedProgramService,
    )
    from mission_control.domain.programs.nested import NestedSettlementRequest
    from tests.unit.orchestration.test_wi13_nested_runtime import (
        NOW,
        SCOPE,
        body,
        parent_with_reservation,
    )
    from tests.unit.run_control.test_run_control import service

    control, _ = service()
    parent = await parent_with_reservation(control, amount=amount)
    nested = NestedProgramService(
        run_control=control,
        launcher=None,
        outputs=None,
        controls=None,
        activations=InMemoryNestedActivationStore(),
    )
    candidate = NestedSettlementRequest(
        request_scope=SCOPE,
        parent_run_id=parent,
        host_id="research",
        semantic_attempt_id="attempt-1",
        parent_reservation_id="unit-1",
        body=body(),
        child_run_id="",
        end="failed",
        family_result=None,
        occurred_at=NOW,
        cause="nested_execution_unavailable",
    )
    first = await nested.settle(candidate)
    budget = await control.get_budget(SCOPE, parent)
    assert "unit-1" not in budget.reservations
    proof = budget.usage_records["nested-usage:unit-1"]
    assert proof.reservation_id == "unit-1" and not proof.actual_amounts
    assert not proof.pending_external_amounts
    assert (await nested.settle(candidate)).projection == first.projection
    assert (await control.get_budget(SCOPE, parent)).usage_records == budget.usage_records
