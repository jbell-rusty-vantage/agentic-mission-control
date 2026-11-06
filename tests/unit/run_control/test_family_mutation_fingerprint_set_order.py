"""P5d: a family mutation's fingerprint is a pure function of content, whatever its set order.

Run 2 (StageGraph diagnose -> patch) failed every `stagegraph.decide_result` retry with
"family mutation fingerprint does not match mutation content". The decision payload carries
`asdict(next_projection)`, whose `accepted_obligation_evidence` is a frozenset. After the second
stage it held two members ({"diagnosed", "verified"}). The producer fingerprints with
`contract_fingerprint` (sets sorted), while `FamilyAdmissionCommit` re-derived it from a
JSON-mode dump (sets in hash-seed iteration order), so the two disagreed in every process whose
iteration order was not the sorted one.

The same order dependence broke the stored read-back: the PostgreSQL journal stores the
mutation with `model_dump_json()` (sets become lists in the writer's order) and re-checks
`contract_fingerprint` of the re-validated row, which kept list order. The StageGraph mutation
now restores the projection's set-valued fields when it is validated.
"""

from __future__ import annotations

from dataclasses import asdict, replace
from itertools import combinations, permutations

import pytest
from pydantic import Field, TypeAdapter

from mission_control.adapters.postgres.run_control import canonical as mc
from mission_control.application.execution.run_control_repository import (
    InMemoryRunControlRepository,
)
from mission_control.application.execution.service import (
    FamilyAdmissionRegistry,
    RunControlService,
)
from mission_control.domain.authoring.canonical import contract_fingerprint, sha256_digest
from mission_control.domain.policies.contracts import CommandStatus, ReserveBudgetAction
from mission_control.domain.policies.family_admission import AtomicFamilyMutation
from mission_control.domain.programs.contracts import (
    ExecutionIdentity,
    StageGraphAcceptedProjection,
    StageGraphDecisionMutation,
)
from tests.unit.run_control.test_atomic_family_admission import admission_policies
from tests.unit.run_control.test_run_control import ConfigurationVerifier, command, request


class DecisionPayloadMutation(AtomicFamilyMutation):
    __test__ = False
    decision_payload: dict[str, object] = Field(default_factory=dict)


def unsorted_obligations() -> frozenset[str]:
    """Obligation refs whose frozenset iterates out of sorted order in this process.

    Validation rebuilds the set, and with hash collisions iteration order follows insertion
    order, so only a set that iterates the same unsorted way for every insertion order is used.
    """

    names = ("diagnosed", "verified", "reviewed", "owner_review", "patched", "tested")
    for size in (2, 3, 4):
        for chosen in combinations(names, size):
            orders = {tuple(frozenset(order)) for order in permutations(chosen)}
            if len(orders) == 1 and list(orders.pop()) != sorted(chosen):
                return frozenset(chosen)
    raise AssertionError("no insertion-independent unsorted frozenset iteration order found")


def accepted_projection(obligations: frozenset[str]) -> StageGraphAcceptedProjection:
    return StageGraphAcceptedProjection(
        identity=ExecutionIdentity(run_id="run-1", execution_epoch=1),
        run_version=4,
        family_version=4,
        accepted_obligation_evidence=obligations,
        invalidated_stage_ids=obligations,
    )


def projection_payload(obligations: frozenset[str]) -> dict[str, object]:
    return {"projection": asdict(accepted_projection(obligations))}


@pytest.mark.asyncio
async def test_family_admission_accepts_set_valued_payload_in_any_iteration_order() -> None:
    families = FamilyAdmissionRegistry()
    families.register(
        DecisionPayloadMutation,
        family_kind="decision_family",
        mutation_kind="decision_committed",
        required_permission="workflow_run.reserve_budget",
        allowed_action_kinds=frozenset({"reserve_budget"}),
    )
    repository = InMemoryRunControlRepository()
    run_service = RunControlService(
        repository, ConfigurationVerifier(), admission_policies(), families
    )
    admitted = await run_service.admit(request())
    assert admitted.run_id is not None
    run_id = admitted.run_id
    obligations = unsorted_obligations()
    mutation = DecisionPayloadMutation(
        family_kind="decision_family",
        mutation_kind="decision_committed",
        mutation_id="result-patch",
        request_scope="tenant-1",
        run_id=run_id,
        expected_family_version=0,
        exact_operation_request_ref="operation-request:sha256-test",
        decided_at=request().requested_at,
        decision_payload=projection_payload(obligations),
    )
    # The precondition that broke Run 2: the JSON-mode dump is order-dependent.
    assert sha256_digest(
        mutation.model_dump(mode="json", exclude={"decided_at"})
    ) != contract_fingerprint(mutation, exclude={"decided_at"})

    lifecycle = command(
        run_id,
        1,
        "decide-patch",
        ReserveBudgetAction(reservation_id="operation:patch:1", amounts={"tokens.total": 1}),
    )
    receipt = await run_service.execute_family_admission(lifecycle, mutation)

    assert receipt.command_result.status == CommandStatus.ACCEPTED
    assert receipt.family_mutation_fingerprint == contract_fingerprint(
        mutation, exclude={"decided_at"}
    )
    # Re-executing identical content replays the stored receipt (in-memory repository only;
    # the production retry goes through StageGraphDecisionService and the Postgres journal,
    # whose read-back is covered by the round-trip test below).
    assert await run_service.execute_family_admission(lifecycle, mutation) == receipt
    assert (
        await repository.get_family_head(
            "tenant-1", run_id, "decision_family", DecisionPayloadMutation
        )
        == mutation
    )


def test_stagegraph_mutation_fingerprint_survives_the_journal_json_round_trip() -> None:
    obligations = unsorted_obligations()
    prior = accepted_projection(frozenset())
    following = replace(accepted_projection(obligations), family_version=5)
    mutation = StageGraphDecisionMutation(
        mutation_id="result-patch",
        request_scope="tenant-1",
        run_id="run-1",
        expected_family_version=4,
        exact_operation_request_ref="operation-request:sha256-test",
        decided_at=request().requested_at,
        decision_kind="result_decided",
        prior_projection_digest=prior.digest,
        next_projection_digest=following.digest,
        decision_payload={"proposal": {"decision": "admit"}, "projection": asdict(following)},
    )
    fingerprint = contract_fingerprint(mutation, exclude={"decided_at"})

    # Exactly what the PostgreSQL journal writes and reads back (`mc.dump` / `mc.load`).
    stored = mc.load(mc.dump(mutation))
    stored_order = stored["decision_payload"]["projection"]["accepted_obligation_evidence"]
    assert stored_order == list(obligations) != sorted(obligations)

    # Without restoring the sets, the stored list order leaks into the fingerprint.
    unrestored = StageGraphDecisionMutation.model_construct(**stored)
    assert contract_fingerprint(unrestored, exclude={"decided_at"}) != fingerprint

    restored = StageGraphDecisionMutation.model_validate(stored)
    assert contract_fingerprint(restored, exclude={"decided_at"}) == fingerprint
    # Readers rebuild the typed projection from the payload (tuples arrive as JSON lists).
    assert (
        TypeAdapter(StageGraphAcceptedProjection).validate_python(
            restored.decision_payload["projection"]
        )
        == following
    )
    projection = restored.decision_payload["projection"]
    assert isinstance(projection, dict)
    assert projection["accepted_obligation_evidence"] == obligations
    assert projection["invalidated_stage_ids"] == obligations
    # A set-free payload is untouched, and a fresh mutation's fingerprint is unchanged.
    assert restored.decision_payload["proposal"] == {"decision": "admit"}
    assert (
        StageGraphDecisionMutation.model_validate(
            mutation.model_dump(mode="python")
        ).decision_payload
        == mutation.decision_payload
    )


def test_duplicated_stored_set_members_are_not_collapsed_into_a_valid_identity() -> None:
    obligations = unsorted_obligations()
    following = accepted_projection(obligations)
    mutation = StageGraphDecisionMutation(
        mutation_id="result-patch",
        request_scope="tenant-1",
        run_id="run-1",
        expected_family_version=4,
        exact_operation_request_ref="operation-request:sha256-test",
        decided_at=request().requested_at,
        decision_kind="result_decided",
        prior_projection_digest=accepted_projection(frozenset()).digest,
        next_projection_digest=following.digest,
        decision_payload={"projection": asdict(following)},
    )
    stored = mc.load(mc.dump(mutation))
    members = stored["decision_payload"]["projection"]["accepted_obligation_evidence"]
    stored["decision_payload"]["projection"]["accepted_obligation_evidence"] = [
        *members,
        members[0],
    ]
    tampered = StageGraphDecisionMutation.model_validate(stored)
    assert contract_fingerprint(tampered, exclude={"decided_at"}) != contract_fingerprint(
        mutation, exclude={"decided_at"}
    )
