"""Builders, constants and fakes that other test files import.

Moved from tests/unit/orchestration/test_completion_validation_service.py.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from mission_control.application.execution.run_control_repository import (
    InMemoryRunControlRepository,
    RunControlRepository,
)
from mission_control.application.execution.service import FamilyAdmissionRegistry, RunControlService
from mission_control.application.programs.service import (
    StageGraphDecisionService,
    register_stagegraph_family_mutations,
)
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import StageGraphBlueprint, StageOutputSlot
from mission_control.domain.authoring.graph_routes import (
    GRAPH_SEMANTICS_V1,
    FactPredicate,
    RevisitRegion,
    RouteBranch,
    StageFact,
    StageRoute,
)
from mission_control.domain.authoring.stagegraph_builder import (
    StageGraphStageSpec,
    build_stagegraph_v2,
)
from mission_control.domain.execution.contracts import (
    OperationAttemptIdentity,
    OperationExecutionRequest,
    OperationWorkflowRequest,
)
from mission_control.domain.policies.contracts import (
    BudgetApplicability,
    CommandStatus,
    RecordUsageAction,
    StartAction,
)
from mission_control.domain.programs.completion import OutputSchemaBinding, SchemaCriterion
from mission_control.domain.programs.contracts import (
    ExecutionIdentity,
    LateResultFacts,
    StageGraphAdmissionActivityRequest,
    StageGraphDecisionMutation,
    StageGraphResultActivityRequest,
    StageResultObservation,
)
from mission_control.domain.programs.interpreter import StageGraphInterpreter
from tests.support.operations import operation_request
from tests.support.run_control import ConfigurationVerifier, command, request
from tests.support.unit.orchestration.artifact_schema_validation import SCHEMA, Custody, captured
from tests.support.unit.run_control.atomic_family_admission import admission_policies

SCOPE = "tenant-1"
OUTPUT = "workspace-candidate://report"


@dataclass
class Prepared:
    run_control: RunControlService
    repository: RunControlRepository
    service: StageGraphDecisionService
    custody: Custody
    result: StageGraphResultActivityRequest
    scope: str = SCOPE
    operation: OperationExecutionRequest | None = None

    async def journal(self) -> StageGraphDecisionMutation:
        head = await self.repository.get_family_head(
            self.scope, self.result.run_id, "stagegraph", StageGraphDecisionMutation
        )
        assert head is not None
        return head


async def prepared(
    repository: RunControlRepository | None = None,
    scope: str = SCOPE,
    operation_template: OperationExecutionRequest | None = None,
    release_usage: bool = True,
    currency_reservation: int = 0,
    revisit: bool = False,
    named_promises: Any = None,
    route: bool = False,
) -> Prepared:
    repository = repository if repository is not None else InMemoryRunControlRepository()
    registry = FamilyAdmissionRegistry()
    register_stagegraph_family_mutations(registry)
    control = RunControlService(
        repository, ConfigurationVerifier(frozenset({"goal"})), admission_policies(), registry
    )
    run_request = request(request_scope=scope)
    envelope = run_request.budget_envelope.model_copy(
        update={
            "dimensions": tuple(
                item.model_copy(update={"applicability": BudgetApplicability.UNBOUNDED})
                if item.dimension == "operation.attempts"
                or (currency_reservation and item.dimension == "currency.estimated_micros")
                else item
                for item in run_request.budget_envelope.dimensions
            )
        }
    )
    admitted = await control.admit(run_request.model_copy(update={"budget_envelope": envelope}))
    assert admitted.run_id is not None
    run_id = admitted.run_id
    started = await control.execute(
        command(run_id, 1, "start", StartAction()).model_copy(update={"request_scope": scope})
    )
    assert started.status == CommandStatus.ACCEPTED
    schema = OutputSchemaBinding(
        schema_ref="schema:report@1",
        source_digest="sha256:" + "a" * 64,
        schema_digest=sha256_digest(SCHEMA),
        json_schema=SCHEMA,
    )
    graph = build_stagegraph_v2(
        logical_id="test.completion.service",
        title="Completion service",
        description="Validate custody through the family decision service",
        stages=(
            StageGraphStageSpec(
                "final",
                output_slots=("report",),
                obligation_refs=("goal",),
                reservation={
                    "tokens.total": 1,
                    **(
                        {"currency.estimated_micros": currency_reservation}
                        if currency_reservation
                        else {}
                    ),
                },
                output_declarations=(
                    StageOutputSlot(
                        output_slot_id="report",
                        output_contract_ref="schema:report@1",
                        required=True,
                        validation_schema=schema,
                    ),
                ),
                schema_criteria=(
                    SchemaCriterion(
                        criterion_key="report-valid",
                        obligation_ref="goal",
                        schema_ref="schema:report@1",
                        output_slots=("report",),
                    ),
                ),
                # OVE-171 slice D: the `count` fact a one-stage Revisit Region stops on.
                facts=(
                    StageFact(
                        fact_id="count",
                        output_slot_id="report",
                        pointer="/count",
                        value_type="integer",
                    ),
                )
                if revisit or route
                else (),
            ),
            # L1-02: the targets of an ordered first_match route over the `count` fact.
            *(
                (
                    StageGraphStageSpec("deep", output_slots=("out",)),
                    StageGraphStageSpec("archive", output_slots=("out",)),
                )
                if route
                else ()
            ),
        ),
        routes=(
            StageRoute(
                route_id="final_route",
                mode="first_match",
                branches=(
                    RouteBranch(
                        branch_id="counted",
                        predicates=(
                            FactPredicate(stage_id="final", fact_id="count", op="ge", value=1),
                        ),
                        target_stage_ids=("deep",),
                    ),
                ),
                else_stage_ids=("archive",),
            ),
        )
        if route
        else (),
        graph_semantics=GRAPH_SEMANTICS_V1 if revisit or route else None,
    )
    if revisit:
        graph = StageGraphBlueprint.model_validate(
            {
                **graph.model_dump(mode="python"),
                "revisit_regions": (
                    RevisitRegion(
                        region_id="refine",
                        stage_ids=("final",),
                        entry_stage_id="final",
                        exit_stage_id="final",
                        max_visits=2,
                        until=(FactPredicate(stage_id="final", fact_id="count", op="ge", value=2),),
                    ),
                ),
            }
        )
    if named_promises is not None:
        graph = graph.model_copy(update={"output_promises": named_promises})
    interpreter = StageGraphInterpreter(graph, effective_max_concurrency=1)
    projection = interpreter.initial_projection(
        ExecutionIdentity(run_id), run_version=started.resulting_run_version
    )
    proposal = interpreter.frontier(projection, available_concurrency=1)[0]
    operation = (operation_template or operation_request()).model_copy(
        update={
            "identity": OperationAttemptIdentity(
                run_id=run_id,
                operation_id=proposal.identity.operation_id,
                operation_attempt=proposal.identity.semantic_attempt,
            ),
            "budget_reservation_id": proposal.reservation_id,
            "run_control_revision": projection.run_version + 1,
            "request_scope": scope,
        }
    )
    custody = Custody(captured(source_ref=OUTPUT))
    service = StageGraphDecisionService(control, repository, artifacts=custody)
    now = datetime.now(UTC)
    accepted = await service.admit_operation(
        StageGraphAdmissionActivityRequest(
            run_id=run_id,
            request_scope=scope,
            projection=projection,
            proposal=proposal,
            operation=OperationWorkflowRequest(
                semantic_attempt_id=proposal.identity.semantic_key,
                operation_kind="bound_operation",
                operation=operation,
            ),
            blueprint=graph.model_dump(mode="json"),
            effective_max_concurrency=1,
            occurred_at=now,
            idempotency_issuer="operator",
            correlation_id="completion-test",
        )
    )
    assert accepted.accepted, accepted.reason_code
    if release_usage:
        await _release_fixture_usage(control, scope, run_id, accepted, proposal)
    result = StageGraphResultActivityRequest(
        run_id=run_id,
        request_scope=scope,
        projection=accepted.projection,
        observation=StageResultObservation(
            proposal.identity, {"output_refs": [OUTPUT]}, True, True, True, True, 1
        ),
        late_facts=LateResultFacts(),
        blueprint=graph.model_dump(mode="json"),
        effective_max_concurrency=1,
        occurred_at=now,
        idempotency_issuer="operator",
        correlation_id="completion-test",
    )
    assert accepted.operation is not None and accepted.operation.operation is not None
    return Prepared(
        control, repository, service, custody, result, scope, accepted.operation.operation
    )


async def _release_fixture_usage(control, scope, run_id, accepted, proposal):
    settled = await control.execute(
        command(
            run_id,
            accepted.projection.run_version,
            "settle-producer-usage",
            RecordUsageAction(
                usage_id="producer-usage",
                reservation_id=proposal.reservation_id,
                actual_amounts={},
                release_amounts=proposal.reservation,
            ),
        ).model_copy(update={"request_scope": scope})
    )
    assert settled.status == CommandStatus.ACCEPTED
