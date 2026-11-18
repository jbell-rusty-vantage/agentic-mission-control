"""Builders, constants and fakes that other test files import.

Moved from tests/unit/run_control/test_atomic_family_admission.py.
"""

from __future__ import annotations

from pydantic import Field

from mission_control.application.execution.run_control_repository import (
    InMemoryRunControlRepository,
)
from mission_control.application.execution.service import (
    AdmissionPolicyRegistry,
    FamilyAdmissionRegistry,
    RunControlService,
)
from mission_control.domain.policies.contracts import (
    AcceptedObligationEvidence,
    AcceptedOutputEvidence,
    ApplyAuthorityBatchAction,
    EffectDisposition,
    EffectSettlementOutcome,
    ObserveEffectAction,
    RecordObligationEvidenceAction,
    RecordOutputEvidenceAction,
    RecordUsageAction,
    SettleEffectAction,
    SettlePendingUsageAction,
)
from mission_control.domain.policies.family_admission import AtomicFamilyMutation
from tests.support.run_control import ConfigurationVerifier, request


class FixtureFamilyMutation(AtomicFamilyMutation):
    candidate_ref: str = Field(min_length=1)
    cursor: tuple[str, ...] = ()


def validate_test_family_batch(
    mutation: AtomicFamilyMutation,
    batch: ApplyAuthorityBatchAction,
) -> str | None:
    if not isinstance(mutation, FixtureFamilyMutation):
        return "unexpected mutation type"
    output_refs = tuple(
        action.evidence.output_ref
        for action in batch.actions
        if isinstance(action, RecordOutputEvidenceAction)
    )
    if output_refs != (mutation.candidate_ref,):
        return "accepted output evidence does not match the family mutation candidate"
    return None


def registered_family_registry() -> FamilyAdmissionRegistry:
    families = FamilyAdmissionRegistry()
    families.register(
        FixtureFamilyMutation,
        family_kind="test_family",
        mutation_kind="candidate_admitted",
        required_permission="workflow_run.reserve_budget",
        allowed_action_kinds=frozenset({"reserve_budget", "apply_authority_batch"}),
        allowed_batch_action_kinds=frozenset(
            {
                "record_usage",
                "settle_pending_usage",
                "observe_effect",
                "settle_effect",
                "record_obligation_evidence",
                "record_output_evidence",
            }
        ),
        required_batch_action_kinds=frozenset(
            {
                "record_usage",
                "settle_pending_usage",
                "observe_effect",
                "settle_effect",
                "record_obligation_evidence",
                "record_output_evidence",
            }
        ),
        batch_binding_validator=validate_test_family_batch,
    )
    return families


def admission_policies() -> AdmissionPolicyRegistry:
    policies = AdmissionPolicyRegistry()
    policies.register("contract:input@1", lambda _request, _configuration: None)
    policies.register("contract:invariant@1", lambda _request, _configuration: None)
    return policies


def family_service(
    repository: InMemoryRunControlRepository | None = None,
    *,
    register: bool = True,
) -> tuple[RunControlService, InMemoryRunControlRepository]:
    repository = repository or InMemoryRunControlRepository()
    policies = admission_policies()
    families = registered_family_registry() if register else FamilyAdmissionRegistry()
    return (
        RunControlService(repository, ConfigurationVerifier(), policies, families),
        repository,
    )


def family_mutation(
    run_id: str,
    *,
    mutation_id: str = "family-mutation-1",
    expected_family_version: int = 0,
    candidate_ref: str = "output:accepted",
    request_scope: str = "tenant-1",
) -> FixtureFamilyMutation:
    return FixtureFamilyMutation(
        family_kind="test_family",
        mutation_kind="candidate_admitted",
        mutation_id=mutation_id,
        request_scope=request_scope,
        run_id=run_id,
        expected_family_version=expected_family_version,
        exact_operation_request_ref="operation-request:sha256-test",
        decided_at=request().requested_at,
        candidate_ref=candidate_ref,
        cursor=("group:a", "candidate:a"),
    )


def authority_batch() -> ApplyAuthorityBatchAction:
    return ApplyAuthorityBatchAction(
        actions=(
            RecordUsageAction(
                usage_id="accepted-usage",
                authority_ref="operation:1",
                reservation_id="effect-reservation",
                actual_amounts={"tokens.total": 3},
                pending_external_amounts={"tokens.total": 5},
                release_amounts={"tokens.total": 2},
            ),
            SettlePendingUsageAction(
                settlement_id="accepted-usage-settlement",
                usage_id="accepted-usage",
                actual_amounts={"tokens.total": 5},
            ),
            ObserveEffectAction(
                effect_id="effect-1",
                observation_id="effect-observation-1",
                disposition=EffectDisposition.SUCCEEDED,
                evidence_refs=("evidence:effect-observed",),
            ),
            SettleEffectAction(
                effect_id="effect-1",
                settlement_id="effect-settlement-1",
                observation_id="effect-observation-1",
                outcome=EffectSettlementOutcome.SUCCEEDED,
                usage_settlement_ref="accepted-usage-settlement",
                evidence_refs=("evidence:effect-settled",),
            ),
            RecordObligationEvidenceAction(
                evidence=AcceptedObligationEvidence(
                    obligation_ref="obligation:required",
                    evidence_digest="sha256:" + "d" * 64,
                    accepted_by_authority_ref="authority:lifecycle",
                )
            ),
            RecordOutputEvidenceAction(
                evidence=AcceptedOutputEvidence(
                    output_ref="output:accepted",
                    evidence_digest="sha256:" + "e" * 64,
                    accepted_by_authority_ref="authority:lifecycle",
                )
            ),
        )
    )
