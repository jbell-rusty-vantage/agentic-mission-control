"""SV-01 (defect E01): the agent's runtime context names the live invocation, never the template.

Manifest launch templates are compiled once with placeholder coordinates
(``manifest-template/<key>``, attempt 1, generation 1). Both program families rebind the
template per admitted attempt; these tests drive the real StageGraph preparation service and
the GoalDirected instantiation over real manifest templates and assert that the frozen
``cognitive_context_values`` -- what a local invocation passes and what a hosted graph freezes
as its context defaults -- carry the live run, operation, attempt and generation.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from mission_control.adapters.deep_agents.materializer import _context_instance, _context_type
from mission_control.application.authoring.manifest_launch_inputs import TEMPLATE_REVISION
from mission_control.application.programs.goal_directed import _instantiate_operation_request
from mission_control.application.programs.service import (
    StageGraphOperationPreparationService,
    StaticStageGraphOperationTemplateProvider,
)
from mission_control.domain.authoring.fixtures import GENERIC_GOAL_DIRECTED
from mission_control.domain.execution.contracts import (
    DeepAgentExecutionBinding,
    OperationExecutionRequest,
)
from mission_control.domain.execution.live_invocation import (
    LIVE_INVOCATION_CONTEXT_FIELDS,
    TemplateInvocationIdentity,
    live_invocation_context_values,
    rebind_deep_agent_invocation,
)
from mission_control.domain.programs.goal_directed import GoalDirectedInterpreter
from mission_control.domain.programs.goal_directed_runtime import GoalOperationPreparationRequest
from tests.fixtures.lane_bindings import LANE_REBINDERS, lane_fields
from tests.integration.temporal.test_wp_bp_010_temporal import RecordingOperationBindings
from tests.integration.temporal.test_wp_bp_020_temporal import _run_input
from tests.unit.authoring.manifest_launch_fixture import (
    deep_agents_chain,
    fixture_bindings,
    pubmed_bound,
)
from tests.unit.authoring.test_manifest_launch_inputs import (
    MINIMAL,
    MISSION_2,
    admitted,
    compile_programs,
    pubmed_digest,
    pubmed_resolver,
    resolver,
    served_with_mcp,
)
from tests.unit.operations.test_ft_b2_stage_handoff import _downstream_request

TEMPLATE_PREFIX = "manifest-template/"


@pytest.fixture(scope="module")
def stage_template() -> OperationExecutionRequest:
    definitions, programs = asyncio.run(compile_programs(MINIMAL.read_text(encoding="utf-8")))
    definition, program = definitions[0], programs[0]
    bindings = pubmed_bound(fixture_bindings(), pubmed_digest(definition))
    templates = resolver(bindings, served=served_with_mcp(bindings)).stage_templates(
        definition, admitted(program)
    )
    return templates["collect/execute/default"]


@pytest.fixture(scope="module")
def goal_templates() -> dict[str, OperationExecutionRequest]:
    definitions, programs = asyncio.run(
        compile_programs(deep_agents_chain(MISSION_2.read_text(encoding="utf-8")))
    )
    research = next(item for item in definitions if item.mission_key == "research")
    program = next(item for item in programs if item.mission_key == "research")
    return dict(pubmed_resolver(research).goal_templates(research, admitted(program)))


def _template_binding(template: OperationExecutionRequest) -> DeepAgentExecutionBinding:
    binding = DeepAgentExecutionBinding.carried_by(template)
    assert binding is not None
    # Precondition: the template really carries placeholder coordinates in its context.
    assert binding.operation_id.startswith(TEMPLATE_PREFIX)
    assert str(binding.cognitive_context_values["operation_id"]).startswith(TEMPLATE_PREFIX)
    return binding


def _hosted(binding: DeepAgentExecutionBinding) -> DeepAgentExecutionBinding:
    values = binding.model_dump(mode="python", exclude={"binding_digest"})
    values.update(
        placement="remote_langsmith_deployment",
        checkpoint_behavior="remote_managed",
        cancellation_behavior="remote_reconcile",
        message_injection_behavior="remote_thread",
        reconnect_behavior="remote_run_reconnect",
    )
    return DeepAgentExecutionBinding.create(**values)


def _assert_live(
    binding: DeepAgentExecutionBinding | None,
    *,
    run_id: str,
    operation_id: str,
    attempt: int,
    generation: int,
) -> DeepAgentExecutionBinding:
    assert binding is not None
    context = binding.cognitive_context_values
    expected = {
        "run_id": run_id,
        "operation_id": operation_id,
        "operation_attempt": attempt,
        "execution_generation": generation,
    }
    assert {name: context[name] for name in expected} == expected
    assert {name: getattr(binding, name) for name in expected} == expected
    assert binding.runtime_unit is not None
    assert binding.runtime_unit.semantic_attempt == attempt
    # No template identity survives anywhere in the bound cognition inputs.
    assert TEMPLATE_PREFIX not in binding.model_dump_json()
    # Local cognition passes an explicit context instance built from the frozen values ...
    local = _context_instance(
        _context_type(binding.cognitive_context_schema),
        binding.cognitive_context_schema,
        context,
    )
    # ... and a hosted graph freezes the same values as dataclass defaults.
    hosted = _context_type(binding.cognitive_context_schema, defaults=context)()
    for name, value in expected.items():
        assert getattr(local, name) == value
        assert getattr(hosted, name) == value
    return binding


# --- StageGraph ---------------------------------------------------------------------------------


async def _stage_materialize(
    template: OperationExecutionRequest, *, attempt: int, generation: int
) -> tuple[Any, DeepAgentExecutionBinding]:
    request = _downstream_request(["workspace-candidate://cand-fast-result"])
    proposal = request.proposal
    request = replace(
        request,
        proposal=replace(
            proposal,
            identity=replace(
                proposal.identity, semantic_attempt=attempt, execution_generation=generation
            ),
        ),
    )
    preparation = StageGraphOperationPreparationService(
        lane_bindings=LANE_REBINDERS,
        templates=StaticStageGraphOperationTemplateProvider(
            {request.proposal.operation_request_key: template}
        ),
        operation_bindings=RecordingOperationBindings(),  # type: ignore[arg-type]
    )
    prepared = await preparation.materialize(request)
    binding = DeepAgentExecutionBinding.carried_by(prepared.operation)
    assert binding is not None
    return request, binding


@pytest.mark.parametrize(("attempt", "generation"), [(1, 1), (2, 1), (2, 3)])
async def test_stagegraph_binds_the_live_attempt_into_the_agent_context(
    stage_template: OperationExecutionRequest, attempt: int, generation: int
) -> None:
    _template_binding(stage_template)
    request, binding = await _stage_materialize(
        stage_template, attempt=attempt, generation=generation
    )
    identity = request.proposal.identity
    _assert_live(
        binding,
        run_id=request.run_id,
        operation_id=identity.operation_id,
        attempt=attempt,
        generation=generation,
    )


async def test_stagegraph_retry_and_later_generation_change_the_binding_digest(
    stage_template: OperationExecutionRequest,
) -> None:
    _, first = await _stage_materialize(stage_template, attempt=1, generation=1)
    _, retry = await _stage_materialize(stage_template, attempt=2, generation=1)
    _, later = await _stage_materialize(stage_template, attempt=2, generation=2)
    digests = {first.binding_digest, retry.binding_digest, later.binding_digest}
    assert len(digests) == 3
    assert DeepAgentExecutionBinding.carried_by(stage_template) is not None
    assert DeepAgentExecutionBinding.carried_by(stage_template).binding_digest not in digests


async def test_stagegraph_hosted_placement_freezes_live_context_defaults(
    stage_template: OperationExecutionRequest,
) -> None:
    hosted_template = stage_template.model_copy(
        update={**lane_fields(_hosted(_template_binding(stage_template)))}
    )
    request, binding = await _stage_materialize(hosted_template, attempt=2, generation=2)
    assert binding.placement == "remote_langsmith_deployment"
    _assert_live(
        binding,
        run_id=request.run_id,
        operation_id=request.proposal.identity.operation_id,
        attempt=2,
        generation=2,
    )


# --- GoalDirected -------------------------------------------------------------------------------


def _goal_preparation(
    role: str, *, attempt: int, generation: int
) -> GoalOperationPreparationRequest:
    run = _run_input()
    interpreter = GoalDirectedInterpreter(GENERIC_GOAL_DIRECTED)
    _, claim = interpreter.claim_execution(interpreter.initial_state(run))
    suffix = ":verifier" if role == "verifier" else ""
    return GoalOperationPreparationRequest(
        request_scope="tenant-1",
        run_id=run.run_id,
        effective_configuration_digest=run.effective_configuration_digest,
        semantic_input_binding_ref=run.semantic_input_binding_ref,
        goal_revision_id=run.initial_revision.revision_id,
        goal_revision_digest=run.initial_revision.canonical_digest,
        goal_revision=run.initial_revision,
        goal_iteration=1,
        operation_role=role,
        operation_attempt=attempt,
        execution_generation=generation,
        expected_run_version=2,
        expected_family_version=1,
        reservation_id=f"reservation:{role}",
        reservation={"goal.iterations": 1},
        session_id=claim.session_id + suffix,
        workspace_id=claim.workspace_namespace + suffix,
        read_workspace_id=claim.workspace_namespace if role == "verifier" else None,
        verifier_input_refs=("workspace-candidate://goal-output",) if role == "verifier" else (),
        decided_at=datetime(2026, 10, 24, tzinfo=UTC),
        agent_run=1,
        session_generation=1,
    )


@pytest.mark.parametrize("role", ["executor", "verifier"])
@pytest.mark.parametrize(("attempt", "generation"), [(1, 1), (2, 1), (2, 3)])
def test_goal_directed_binds_the_live_attempt_into_the_agent_context(
    goal_templates: dict[str, OperationExecutionRequest], role: str, attempt: int, generation: int
) -> None:
    template = goal_templates[role]
    _template_binding(template)
    request = _goal_preparation(role, attempt=attempt, generation=generation)
    operation = _instantiate_operation_request(
        template, request, bound_revision=3, lane_bindings=LANE_REBINDERS
    )
    binding = _assert_live(
        DeepAgentExecutionBinding.carried_by(operation),
        run_id=request.run_id,
        operation_id=operation.identity.operation_id,
        attempt=attempt,
        generation=generation,
    )
    assert operation.identity.operation_id == f"goal-iteration/1/{role}"
    assert binding.control_revision == 3


def test_goal_directed_retry_and_later_generation_change_the_binding_digest(
    goal_templates: dict[str, OperationExecutionRequest],
) -> None:
    template = goal_templates["executor"]
    digests = set()
    for attempt, generation in ((1, 1), (2, 1), (2, 2)):
        request = _goal_preparation("executor", attempt=attempt, generation=generation)
        operation = _instantiate_operation_request(
            template, request, bound_revision=3, lane_bindings=LANE_REBINDERS
        )
        assert DeepAgentExecutionBinding.carried_by(operation) is not None
        digests.add(DeepAgentExecutionBinding.carried_by(operation).binding_digest)
    assert len(digests) == 3


def test_goal_directed_hosted_placement_freezes_live_context_defaults(
    goal_templates: dict[str, OperationExecutionRequest],
) -> None:
    template = goal_templates["executor"]
    hosted = template.model_copy(update={**lane_fields(_hosted(_template_binding(template)))})
    request = _goal_preparation("executor", attempt=2, generation=2)
    operation = _instantiate_operation_request(
        hosted, request, bound_revision=3, lane_bindings=LANE_REBINDERS
    )
    assert DeepAgentExecutionBinding.carried_by(operation) is not None
    assert (
        DeepAgentExecutionBinding.carried_by(operation).placement == "remote_langsmith_deployment"
    )
    _assert_live(
        DeepAgentExecutionBinding.carried_by(operation),
        run_id=request.run_id,
        operation_id=operation.identity.operation_id,
        attempt=2,
        generation=2,
    )


# --- the shared helper --------------------------------------------------------------------------


def test_only_declared_fields_are_refreshed_and_none_are_added() -> None:
    values = {"run_id": "old", "operation_attempt": 1, "workspace_handle": "handle:w"}
    refreshed = live_invocation_context_values(
        values,
        {"run_id": "live", "operation_attempt": 2, "execution_generation": 4, "x": "y"},
    )
    assert refreshed == {"run_id": "live", "operation_attempt": 2, "workspace_handle": "handle:w"}
    assert set(LIVE_INVOCATION_CONTEXT_FIELDS) >= {
        "run_id",
        "operation_id",
        "operation_attempt",
        "execution_generation",
    }


def test_template_revision_is_only_the_template_control_revision(
    stage_template: OperationExecutionRequest,
) -> None:
    assert _template_binding(stage_template).control_revision == TEMPLATE_REVISION


def test_a_live_binding_refuses_template_identity(
    stage_template: OperationExecutionRequest,
) -> None:
    template = _template_binding(stage_template)
    assert template.runtime_unit is None
    with pytest.raises(TemplateInvocationIdentity):
        rebind_deep_agent_invocation(
            template,
            binding_id="b",
            run_id=template.run_id,
            operation_id=template.operation_id,
            operation_attempt=1,
            execution_generation=1,
            erc_digest=template.erc_digest,
            control_revision=2,
            workspace=template.workspace,
            reservation_id=template.reservation_id,
            runtime_unit=None,  # type: ignore[arg-type]
        )


# --- continuation / fork (Checkpoint A addendum, SV-01 deviation a) -----------------------------


@pytest.mark.parametrize("family", ["stage_graph", "goal_directed"])
async def test_a_continuation_run_from_a_parent_binding_keeps_no_parent_identity(
    stage_template: OperationExecutionRequest,
    goal_templates: dict[str, OperationExecutionRequest],
    family: str,
) -> None:
    """A continuation (or seeded fork) run is bound from the parent's *live* binding as its
    template; the child's agent context, runtime unit and session namespace name the child
    run only, so no stale parent identity reaches the agent or a knowledge origin."""

    if family == "stage_graph":
        _request, parent = await _stage_materialize(stage_template, attempt=2, generation=3)
    else:
        request = _goal_preparation("executor", attempt=2, generation=3)
        operation = _instantiate_operation_request(
            goal_templates["executor"], request, bound_revision=3, lane_bindings=LANE_REBINDERS
        )
        assert DeepAgentExecutionBinding.carried_by(operation) is not None
        parent = DeepAgentExecutionBinding.carried_by(operation)
    assert parent.runtime_unit is not None and parent.cognitive_session_namespace is not None
    child_run = "99999999-9999-4999-8999-999999999999"
    assert child_run != parent.run_id
    child_unit = parent.runtime_unit.model_copy(
        update={"belllabs_run_id": child_run, "semantic_attempt": 1}
    )
    child = rebind_deep_agent_invocation(
        parent,
        binding_id="binding:continuation",
        run_id=child_run,
        operation_id=parent.operation_id,
        operation_attempt=1,
        execution_generation=1,
        erc_digest=parent.erc_digest,
        control_revision=parent.control_revision,
        workspace=parent.workspace,
        reservation_id="reservation:continuation",
        runtime_unit=child_unit,
    )
    _assert_live(
        child,
        run_id=child_run,
        operation_id=parent.operation_id,
        attempt=1,
        generation=1,
    )
    assert child.cognitive_session_namespace != parent.cognitive_session_namespace
    surfaces = child.model_dump(
        mode="json", include={"cognitive_context_values", "runtime_unit", "run_id"}
    )
    assert parent.run_id not in json.dumps(surfaces)
    assert parent.cognitive_session_namespace not in json.dumps(child.cognitive_context_values)
    assert child.binding_digest != parent.binding_digest
