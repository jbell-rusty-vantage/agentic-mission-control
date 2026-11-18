"""Builders, constants and fakes that other test files import.

Moved from tests/unit/run_control/test_run_control.py.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from mission_control.application.execution.run_control_repository import (
    InMemoryRunControlRepository,
)
from mission_control.application.execution.service import AdmissionPolicyRegistry, RunControlService
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import (
    DefinitionKind,
    ExactDefinitionRef,
    RunInputManifestRef,
)
from mission_control.domain.graph_runtime.identities import QualifiedCheckpointKey
from mission_control.domain.policies.contracts import (
    ActorContext,
    BudgetApplicability,
    BudgetDimensionLimit,
    BudgetEnvelope,
    LifecycleCommand,
    ReconcileUnitAction,
    RunRequest,
    VerifiedRunConfiguration,
    WaitCondition,
    operator_reconciliation_condition_id,
)

NOW = datetime(2026, 7, 19, 18, 0, tzinfo=UTC)
DIGEST = "sha256:" + "a" * 64
MANIFEST_DIGEST = "sha256:" + "b" * 64
WORKFLOW_DIGEST = "sha256:" + "c" * 64
ALL_PERMISSIONS = frozenset(
    {
        "workflow_run.admit",
        "workflow_run.start",
        "workflow_run.observe_wait",
        "workflow_run.pause",
        "workflow_run.resume",
        "workflow_run.cancel",
        "workflow_run.reserve_budget",
        "workflow_run.report_usage",
        "workflow_run.settle_usage",
        "workflow_run.claim_effect",
        "workflow_run.observe_effect",
        "workflow_run.settle_effect",
        "workflow_run.register_async_child",
        "workflow_run.observe_async_child",
        "workflow_run.decide_async_child",
        "workflow_run.propose_continuation",
        "workflow_run.decide_continuation",
        "workflow_run.accept_finalization",
        "workflow_run.record_finalization",
        "workflow_run.accept_obligation_evidence",
        "workflow_run.accept_output_evidence",
        "workflow_run.terminalize",
        "workflow_run.decide_readiness",
    }
)
EMPTY_EVIDENCE_DIGEST = sha256_digest([])
INITIAL_EVIDENCE_FRONTIER = sha256_digest(
    {
        "input_manifest_digest": MANIFEST_DIGEST,
        "obligation_evidence": [],
        "output_evidence": [],
    }
)


def actor() -> ActorContext:
    return ActorContext(
        actor_id="operator",
        authority_refs=frozenset({"authority:lifecycle"}),
        permissions=ALL_PERMISSIONS,
    )


def workflow_ref() -> ExactDefinitionRef:
    return ExactDefinitionRef(
        kind=DefinitionKind.WORKFLOW_TYPE,
        logical_id="generic.workflow",
        revision=1,
        digest=WORKFLOW_DIGEST,
    )


def manifest_ref() -> RunInputManifestRef:
    return RunInputManifestRef(
        manifest_id="manifest-1",
        revision=1,
        digest=MANIFEST_DIGEST,
    )


def request(
    *,
    request_scope: str = "tenant-1",
    request_id: str = "request-1",
    hard_cap: int = 100,
) -> RunRequest:
    return RunRequest(
        request_scope=request_scope,
        idempotency_issuer="operator",
        request_id=request_id,
        actor=actor(),
        effective_configuration_digest=DIGEST,
        workflow_type_ref=workflow_ref(),
        input_manifest=manifest_ref(),
        budget_envelope=BudgetEnvelope(
            dimensions=(
                BudgetDimensionLimit(
                    dimension="tokens.total",
                    applicability=BudgetApplicability.BOUNDED,
                    soft_limit=60,
                    hard_cap=hard_cap,
                ),
                BudgetDimensionLimit(
                    dimension="external.openai",
                    applicability=BudgetApplicability.BOUNDED,
                    hard_cap=20,
                ),
                BudgetDimensionLimit(
                    dimension="currency.usd_micros",
                    applicability=BudgetApplicability.UNBOUNDED,
                ),
                BudgetDimensionLimit(
                    dimension="concurrency.slots",
                    applicability=BudgetApplicability.BOUNDED,
                    hard_cap=2,
                ),
                *(
                    BudgetDimensionLimit(
                        dimension=dimension,
                        applicability=BudgetApplicability.NOT_APPLICABLE,
                    )
                    for dimension in sorted(
                        {
                            "currency.estimated_micros",
                            "currency.actual_micros",
                            "tokens.input",
                            "tokens.output",
                            "time.elapsed_ms",
                            "time.active_compute_ms",
                            "model.turns",
                            "tool.calls.total",
                            "mcp.calls.total",
                            "external.quotas.total",
                            "stage.cycles",
                            "workflow.cycles",
                            "goal.iterations",
                            "operation.attempts",
                            "subagent.spawns",
                        }
                    )
                ),
            ),
            baseline_reservations={"tokens.total": 20},
        ),
        requested_at=NOW,
        correlation_id="correlation-1",
        sponsorship_ref="sponsorship:test",
        approval_refs=("approval:test",),
        delegation_authority_refs=frozenset({"authority:lifecycle"}),
    )


class ConfigurationVerifier:
    def __init__(self, required_obligations: frozenset[str] = frozenset()) -> None:
        self._required_obligations = required_obligations

    async def verify(self, run_request: RunRequest) -> VerifiedRunConfiguration:
        return VerifiedRunConfiguration(
            effective_configuration_digest=run_request.effective_configuration_digest,
            workflow_type_ref=run_request.workflow_type_ref,
            input_manifest=run_request.input_manifest,
            effective_budget_ceilings={"tokens.total": 100, "external.openai": 20},
            max_concurrency=2,
            input_admission_contract="contract:input@1",
            invariant_refs=frozenset({"contract:invariant@1"}),
            obligation_revision="obligations:1",
            required_obligation_refs=self._required_obligations,
        )


def service(
    repository: InMemoryRunControlRepository | None = None,
    *,
    reject_input: bool = False,
    required_obligations: frozenset[str] = frozenset(),
) -> tuple[RunControlService, InMemoryRunControlRepository]:
    repository = repository or InMemoryRunControlRepository()
    policies = AdmissionPolicyRegistry()
    policies.register(
        "contract:input@1",
        lambda _request, _configuration: "input rejected" if reject_input else None,
    )
    policies.register("contract:invariant@1", lambda _request, _configuration: None)
    return (
        RunControlService(
            repository,
            ConfigurationVerifier(required_obligations),
            policies,
        ),
        repository,
    )


def command(run_id: str, version: int, command_id: str, action: object) -> LifecycleCommand:
    return LifecycleCommand(
        command_id=command_id,
        idempotency_issuer="operator",
        request_scope="tenant-1",
        run_id=run_id,
        expected_run_version=version,
        actor=actor(),
        action=action,  # type: ignore[arg-type]
        reason=f"test {command_id}",
        occurred_at=NOW + timedelta(minutes=version),
        correlation_id="correlation-1",
    )


UNIT_KEY = "bl-unit-v1:" + "e" * 64
# `reconcile_unit` is privileged: the ordinary operator fixture does not hold it.
RECONCILE_PERMISSIONS = ALL_PERMISSIONS | {"workflow_run.reconcile_unit"}


def reconciler_command(
    run_id: str, version: int, command_id: str, action: object
) -> LifecycleCommand:
    return command(run_id, version, command_id, action).model_copy(
        update={"actor": actor().model_copy(update={"permissions": RECONCILE_PERMISSIONS})}
    )


INCIDENT_ID = "unit-in-doubt:fixture"


def operator_wait(unit_key: str = UNIT_KEY, generation: int = 1) -> WaitCondition:
    return WaitCondition(
        condition_id=operator_reconciliation_condition_id(unit_key, generation),
        kind="operator_reconciliation",
        scope=frozenset({unit_key}),
        verification_ref=INCIDENT_ID,
        timeout_policy_ref="operator-reconciliation:no-timeout",
    )


def reconcile(
    decision: str = "abandon_unit",
    *,
    generation: int = 1,
    incident_id: str = INCIDENT_ID,
    accepted: QualifiedCheckpointKey | None = None,
) -> ReconcileUnitAction:
    return ReconcileUnitAction(
        unit_key=UNIT_KEY,
        execution_generation=generation,
        incident_id=incident_id,
        decision=decision,  # type: ignore[arg-type]
        accepted_checkpoint=accepted,
    )
