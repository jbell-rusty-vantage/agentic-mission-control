"""Production composition of recursive composition (OVE-176): the launcher and its adapters.

``ManifestNestedRunLauncher`` (the ``NestedRunLauncher``) admits one nested body's child run:

1. the lineage depth: the parent's own activation chain (``by_child``) must place the body at
   exactly its compiled depth, within its governor;
2. the body: derived from the parent mission revision's committed definition at the body's
   absolute position (``nested_definition_at``) and refused unless both sealed digests (its
   sub-definition and its own lowering, with the same output schemas and the parent's pinned
   runtime capabilities) are exactly the compiled ones;
3. compile (content addressed, idempotent) and admission into the parent's mission revision
   (same installation, application and tenant), with a budget whose spend dimensions never
   exceed the hosting unit's reservation, verified by run control's ordinary admission checks;
4. the activation lineage is recorded before the launch input is authored, so the launch author
   reads the child run's definition as the derived body (``NestedRunDefinitions``);
5. the admitted promises are registered and the ``mc.mission_run.v1`` root input is returned.

The launch input comes from the body's own definition only: a body that reads a producer outside
itself refuses at compile, so the hosting unit's sealed transfer plan carries nothing the child
needs. Idempotent per unit attempt (``nested_request_id``).

Adapters: ``NestedRunDefinitions`` (the launch author's definition view), ``StoreNestedOutputs``
(accepted heads), ``RunControlNestedControls`` (governed cancel/pause/resume of the child run)
and ``ToolsetNestedAdoption`` (adopts accepted exports into the parent unit's invocation through
``OutputAdoptionService`` and settles that invocation like any other unit).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, replace
from datetime import datetime
from typing import Any, Protocol

from mission_control.application.authoring.manifest_submit import budget_envelope
from mission_control.application.execution.boundary_interventions import (
    BoundaryInterventionService,
)
from mission_control.application.execution.run_launch import (
    GOAL_INPUT_ADAPTER,
    STAGE_INPUT_ADAPTER,
)
from mission_control.application.execution.service import RunControlService
from mission_control.application.knowledge.toolset import KnowledgeToolset, LiveInvocation
from mission_control.application.outputs.adoption import (
    AdoptionSource,
    OutputAdoptionService,
    exact_ref,
)
from mission_control.application.programs.nested_bodies import (
    NestedActivationRecord,
    NestedActivationStore,
    NestedAdoptionRefused,
    NestedLaunch,
    NestedLaunchRefused,
)
from mission_control.application.programs.service import (
    ORCHESTRATION_AUTHORITY_REF,
    orchestration_lifecycle_actor,
)
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import EffectiveRunConfiguration, ExactDefinitionRef
from mission_control.domain.authoring.manifest_lowering import LoweredMission, lower_mission
from mission_control.domain.authoring.mission_definition import MissionDefinition
from mission_control.domain.authoring.nested_bodies import (
    GOAL_EXECUTOR_HOST,
    MAX_NESTING_DEPTH,
    NestedBodyError,
)
from mission_control.domain.authoring.nested_lowering import nested_definition_at
from mission_control.domain.outputs.contracts import OutputPromiseSet
from mission_control.domain.policies.contracts import (
    ActorContext,
    BudgetApplicability,
    BudgetDimensionLimit,
    BudgetEnvelope,
    CancelAction,
    CommandStatus,
    LifecycleCommand,
    PauseAction,
    PauseDecision,
    ResumeAction,
    ResumeDecision,
    RunPhase,
    RunRequest,
)
from mission_control.domain.programs.completion import OutputSchemaBinding
from mission_control.domain.programs.contracts import BellLabsRunInput
from mission_control.domain.programs.nested import (
    NESTED_ISSUER,
    SPEND_DIMENSIONS,
    NestedActivationRequest,
    NestedControlReceipt,
    NestedControlRequest,
    NestedProjection,
    NestedSettlementRequest,
    contained_ceiling,
)

NESTED_ACTOR_ID = "mc:nested-program"
NESTED_LANE = "nested_body"


def nested_actor() -> ActorContext:
    return ActorContext(
        actor_id=NESTED_ACTOR_ID,
        permissions=frozenset({"workflow_run.admit", "workflow_run.start"}),
        authority_refs=frozenset({f"authority:{NESTED_ACTOR_ID}"}),
    )


class RunDefinitions(Protocol):
    async def run_subscriptions(self, request_scope: str, run_key: str) -> Any: ...


class ProgramCompiler(Protocol):
    async def compile(
        self,
        lowered: LoweredMission,
        *,
        request_scope: str,
        actor_id: str,
        at: datetime,
        persist: bool,
        compilation_suffix: str | None = None,
    ) -> tuple[EffectiveRunConfiguration, ExactDefinitionRef]: ...


class ConfigurationReader(Protocol):
    async def retrieve_for_admission(self, digest: str) -> EffectiveRunConfiguration: ...


class NestedRunAdmissions(Protocol):
    """Admit the child run into the parent run's mission revision (idempotent per request)."""

    async def admit(
        self, request_scope: str, parent_run_id: str, request: RunRequest, verified: Any
    ) -> str: ...


class LaunchInputs(Protocol):
    async def family_input(
        self, *, request_scope: str, run_id: str, family: Any, initial_goal: str | None
    ) -> dict[str, Any]: ...


OutputSchemas = Callable[[MissionDefinition], Awaitable[Mapping[str, OutputSchemaBinding]]]
PromiseRegistrar = Callable[[str, str, str, OutputPromiseSet], Awaitable[None]]


def contained_envelope(envelope: BudgetEnvelope, reservation: Mapping[str, int]) -> BudgetEnvelope:
    """The compiled envelope with every bounded or reserved spend dimension capped at the
    unit's reservation (a bounded dimension the unit did not reserve is capped at zero)."""

    limits = []
    for limit in envelope.dimensions:
        if limit.dimension not in SPEND_DIMENSIONS or (
            limit.hard_cap is None and limit.dimension not in reservation
        ):
            # Governor counters, and spend the mission leaves unbounded and the unit therefore
            # does not reserve (charged to the unit at settlement), keep the compiled limit.
            limits.append(limit)
            continue
        reserved = reservation.get(limit.dimension, 0)
        cap = reserved if limit.hard_cap is None else min(limit.hard_cap, reserved)
        soft = None if limit.soft_limit is None else min(limit.soft_limit, cap)
        limits.append(
            BudgetDimensionLimit(
                dimension=limit.dimension,
                applicability=BudgetApplicability.BOUNDED,
                soft_limit=soft,
                hard_cap=cap,
            )
        )
    return envelope.model_copy(update={"dimensions": tuple(limits), "baseline_reservations": {}})


class ManifestNestedRunLauncher:
    def __init__(
        self,
        *,
        run_control: RunControlService,
        definitions: RunDefinitions,
        configurations: ConfigurationReader,
        output_schemas: OutputSchemas,
        programs: ProgramCompiler,
        admissions: NestedRunAdmissions,
        activations: NestedActivationStore,
        launch_inputs: LaunchInputs,
        promises: PromiseRegistrar | None,
        family_task_queues: Mapping[str, str],
    ) -> None:
        self._run_control = run_control
        self._definitions = definitions
        self._configurations = configurations
        self._output_schemas = output_schemas
        self._programs = programs
        self._admissions = admissions
        self._activations = activations
        self._launch_inputs = launch_inputs
        self._promises = promises
        self._queues = dict(family_task_queues)

    async def lineage_depth(self, scope: str, parent_run_id: str) -> int:
        depth, current = 0, parent_run_id
        while depth <= MAX_NESTING_DEPTH:
            record = await self._activations.by_child(scope, current)
            if record is None:
                return depth
            depth, current = depth + 1, record.parent_run_id
        raise NestedLaunchRefused("nested_depth_exceeded", "the activation chain is unbounded")

    async def launch(self, request: NestedActivationRequest) -> NestedLaunch:
        body, scope = request.body, request.request_scope
        depth = await self.lineage_depth(scope, request.parent_run_id) + 1
        if depth != body.depth or depth > body.max_depth:
            raise NestedLaunchRefused(
                "nested_depth_lineage_mismatch" if depth != body.depth else "nested_depth_exceeded",
                f"the parent chain places the body at depth {depth}; compiled {body.depth} "
                f"of at most {body.max_depth}",
            )
        family_queue = self._queues.get(body.family)
        if not family_queue:
            raise NestedLaunchRefused("nested_family_unserved", f"no queue serves {body.family}")
        info = await self._definitions.run_subscriptions(scope, request.parent_run_id)
        if info is None:
            raise NestedLaunchRefused(
                "nested_parent_not_manifest", "the parent run was not submitted from a manifest"
            )
        root = MissionDefinition.model_validate(info["definition"])
        try:
            derived = nested_definition_at(root, body.position)
        except NestedBodyError as error:
            raise NestedLaunchRefused(error.reason, str(error)) from None
        if derived.digest != body.definition_digest:
            raise NestedLaunchRefused(
                "nested_body_digest_mismatch", "the body differs from its compiled definition"
            )
        parent = await self._run_control.get_run(scope, request.parent_run_id)
        parent_configuration = await self._configurations.retrieve_for_admission(
            parent.effective_configuration_digest
        )
        lowered = lower_mission(
            derived,
            capability_refs=parent_configuration.runtime_profile.operation_binding_refs,
            output_schemas=await self._output_schemas(root),
            position=body.position,
            depth=body.depth,
        )
        if lowered.blueprint_digest != body.blueprint_digest:
            raise NestedLaunchRefused(
                "nested_body_digest_mismatch", "the body lowers to another blueprint than compiled"
            )
        configuration, workflow_ref = await self._programs.compile(
            lowered,
            request_scope=scope,
            actor_id=NESTED_ACTOR_ID,
            at=request.occurred_at,
            persist=True,
            compilation_suffix=request.request_id,
        )
        run_request = RunRequest(
            request_scope=scope,
            idempotency_issuer=NESTED_ISSUER,
            request_id=request.request_id,
            actor=nested_actor(),
            effective_configuration_digest=configuration.digest,
            workflow_type_ref=workflow_ref,
            input_manifest=configuration.input_manifest,
            budget_envelope=contained_envelope(
                budget_envelope(configuration), request.parent_reservation
            ),
            requested_at=request.occurred_at,
            correlation_id=request.correlation_id or f"nested:{request.parent_run_id}",
            sponsorship_ref=f"nested:{request.parent_run_id}:{request.host_id}",
            admission_evidence_refs=(
                f"manifest:{root.manifest_digest}",
                f"nested-body:{body.blueprint_digest}",
            ),
        )
        verified = await self._run_control.verify_admission(run_request)
        child_run_id = await self._admissions.admit(
            scope, request.parent_run_id, run_request, verified
        )
        ceiling = contained_ceiling(
            request.parent_reservation, configuration.effective_authority.budgets.dimensions
        )
        await self._activations.record(
            NestedActivationRecord(
                request_scope=scope,
                parent_run_id=request.parent_run_id,
                host_id=request.host_id,
                semantic_attempt_id=request.semantic_attempt_id,
                position=body.position,
                family=body.family,
                depth=body.depth,
                child_run_id=child_run_id,
                budget_ceiling=ceiling,
                body_digest=sha256_digest(body),
                activated_at=request.occurred_at,
            )
        )
        child = await self._run_control.get_run(scope, child_run_id)
        payload = await self._launch_inputs.family_input(
            request_scope=scope,
            run_id=child_run_id,
            family=body.family,
            initial_goal=lowered.initial_goal,
        )
        family_input: Any = (
            STAGE_INPUT_ADAPTER.validate_python(payload)
            if body.family == "StageGraph"
            else GOAL_INPUT_ADAPTER.validate_python(payload)
        )
        if family_input.run_id != child_run_id or family_input.request_scope != scope:
            raise NestedLaunchRefused("nested_launch_identity", "launch input names another run")
        promised = family_input.blueprint.get("output_promises")
        if promised is not None:
            if self._promises is None:
                raise NestedLaunchRefused(
                    "promises_unwired", "the body promises named outputs but none register"
                )
            await self._promises(
                scope,
                child_run_id,
                family_input.effective_configuration_digest,
                OutputPromiseSet.model_validate(promised),
            )
        if body.family == "GoalDirected":
            family_input = replace(
                family_input, workflow_type_digest=child.workflow_type_ref.digest
            )
        root_input = BellLabsRunInput(
            schema_version="mc.mission_run.v1",
            run_id=child_run_id,
            request_scope=scope,
            effective_configuration_digest=family_input.effective_configuration_digest,
            workflow_type_digest=child.workflow_type_ref.digest,
            family=body.family,
            family_input=asdict(replace(family_input, durable_operation_children=True)),
            family_task_queue=family_queue,
            parent_run_id=request.parent_run_id,
        )
        root_input.validate_mission_binding()
        return NestedLaunch(
            child_run_id=child_run_id, child_root=root_input, budget_ceiling=ceiling
        )


class NestedRunDefinitions:
    """The launch author's view of run definitions: a nested child run (attached to its parent's
    mission revision) reads as its derived body; every other run as the base view does."""

    def __init__(self, base: RunDefinitions, activations: NestedActivationStore) -> None:
        self._base = base
        self._activations = activations

    async def run_subscriptions(self, request_scope: str, run_key: str) -> Any:
        info = await self._base.run_subscriptions(request_scope, run_key)
        if info is None:
            return None
        record = await self._activations.by_child(request_scope, run_key)
        if record is None:
            return info
        root = MissionDefinition.model_validate(info["definition"])
        derived = nested_definition_at(root, record.position)
        return {**info, "definition": derived.model_dump(mode="json")}


class AcceptedOutputStore(Protocol):
    async def promise_set(self, scope: str, run_id: str) -> Any: ...

    async def accepted_outputs(self, scope: str, run_id: str) -> Any: ...


class StoreNestedOutputs:
    """The child run's accepted heads by obligation key (exact ``output:<id>@<digest>`` refs)."""

    def __init__(self, store: AcceptedOutputStore) -> None:
        self._store = store

    async def accepted(self, scope: str, run_id: str) -> dict[str, tuple[str, ...]] | None:
        if await self._store.promise_set(scope, run_id) is None:
            return None
        found: dict[str, list[str]] = {}
        for item in await self._store.accepted_outputs(scope, run_id):
            found.setdefault(item.obligation_key, []).append(exact_ref(item))
        return {key: tuple(values) for key, values in found.items()}


class RunControlNestedControls:
    """Governed cancel/pause/resume of a child run through its own run control and delivery."""

    def __init__(self, interventions: BoundaryInterventionService, run_control: RunControlService):
        self._interventions = interventions
        self._run_control = run_control

    async def command(self, request: NestedControlRequest) -> NestedControlReceipt:
        pause_id = f"nested-pause:{request.command_ref}"
        action: Any
        if request.kind == "cancel":
            action = CancelAction()
        elif request.kind == "pause":
            action = PauseAction(
                decision=PauseDecision(
                    decision_id=pause_id,
                    scope=frozenset({"run"}),
                    reason=request.reason,
                    authority_ref=ORCHESTRATION_AUTHORITY_REF,
                ),
                runnable_work_remains=False,
            )
        else:
            action = ResumeAction(
                decision=ResumeDecision(
                    decision_id=f"nested-resume:{request.command_ref}",
                    pause_decision_id=pause_id,
                    reason=request.reason,
                    authority_ref=ORCHESTRATION_AUTHORITY_REF,
                )
            )
        for attempt in range(4):
            child = await self._run_control.get_run(request.request_scope, request.child_run_id)
            if child.phase == RunPhase.TERMINAL:
                return NestedControlReceipt(False, status="child_terminal")
            result = await self._interventions.execute(
                LifecycleCommand(
                    command_id=f"nested:{request.kind}:{request.command_ref}"
                    + ("" if attempt == 0 else f":at-version:{child.version}"),
                    idempotency_issuer=NESTED_ISSUER,
                    request_scope=request.request_scope,
                    run_id=request.child_run_id,
                    expected_run_version=child.version,
                    actor=orchestration_lifecycle_actor(),
                    action=action,
                    reason=request.reason,
                    occurred_at=request.occurred_at,
                    correlation_id=f"nested:{request.parent_run_id}:{request.host_id}",
                )
            )
            if result.status != CommandStatus.STALE:
                return NestedControlReceipt(
                    result.status == CommandStatus.ACCEPTED,
                    status=result.status.value,
                    reason_code=result.reason_code,
                )
        return NestedControlReceipt(False, status="stale", reason_code="stale_run_version")


def host_position(request: NestedSettlementRequest) -> str:
    """The owner position of the parent promises a body adopts into: the composite stage's own
    position, or the hosting Goal Loop's (the body position's parent)."""

    position = request.body.position
    if request.body.host_id == GOAL_EXECUTOR_HOST:
        return position.rsplit("/", 1)[0]
    return position


class ToolsetNestedAdoption:
    """Adopt accepted exports into the hosting unit's invocation, then settle that invocation
    exactly as any unit is settled (finalization, assessment hand-off, trusted settlement)."""

    def __init__(self, toolset: KnowledgeToolset, adoption: OutputAdoptionService) -> None:
        self._toolset = toolset
        self._adoption = adoption

    async def adopt(
        self, request: NestedSettlementRequest, projection: NestedProjection
    ) -> tuple[str, ...]:
        if not request.operation_id:
            raise NestedAdoptionRefused("adoption_without_invocation", "no host unit invocation")
        live = await self._toolset.begin(
            LiveInvocation(
                request_scope=request.request_scope,
                run_id=request.parent_run_id,
                operation_id=request.operation_id,
                operation_attempt=request.operation_attempt,
                execution_generation=request.execution_generation,
                lane=NESTED_LANE,
                position=host_position(request),
            )
        )
        access = self._toolset.access(live)
        targets = {item.output: item.adopt_into for item in request.body.exports}
        revisions: list[str] = []
        try:
            for export in projection.exports:
                target = targets.get(export.output)
                if not target:
                    continue
                result = await self._adoption.adopt(
                    access,
                    position=host_position(request),
                    target_obligation=target,
                    sources=tuple(
                        AdoptionSource.parse(request.child_run_id, ref) for ref in export.refs
                    ),
                    act="nested_export",
                    at=request.occurred_at,
                )
                if not result.adopted:
                    raise NestedAdoptionRefused(result.code, result.detail)
                revisions.extend(result.revisions)
        finally:
            # The begun invocation is always settled (finalized with whatever it submitted),
            # also when an adoption refuses: it never stays open.
            await self._toolset.settle_saved(live)
        return tuple(revisions)


__all__ = [
    "ManifestNestedRunLauncher",
    "NestedRunDefinitions",
    "RunControlNestedControls",
    "StoreNestedOutputs",
    "ToolsetNestedAdoption",
    "contained_envelope",
    "host_position",
    "nested_actor",
]
