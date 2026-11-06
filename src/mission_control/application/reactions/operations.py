"""A reaction activation as an ordinary admitted operation (WI-22; ADR-0062, ADR-0063).

:class:`AdmittedReactionOperations` is the production :class:`ReactionOperationPort`. It does what
a family does for one of its units, with the activation as the unit:

1. resolve the reaction's operation template from the run's admitted templates
   (:class:`ReactionTemplatePort`, keyed by the run's semantic input binding and the template's
   operation request key);
2. refuse ``GRANT_EXCEEDED`` when the template's tools or MCP servers exceed the reaction's
   declared grants;
3. refuse a template whose lane does not admit the run's data class (the event facts are run
   data of that class), then reserve the activation's spend through run control
   (:class:`ReactionBudgetPort`; idempotent per activation, so a redelivered dispatch reserves
   once, and released when the activation is refused after it reserved);
4. bind the template to the activation (:func:`reaction_operation_request`): identity
   ``reaction-<activation>`` attempt 1, a runtime unit, the lane's own rebind of its sealed
   binding (OC-R2 ``LaneRebinders``), the reservation and its control revision, and one
   admitted-input prompt segment with the bounded event, the purpose and the promised outputs;
5. persist the exact binding before the start, as every family does
   (``SemanticOperationBindingRepository``);
6. start the operation workflow through :class:`OperationStartPort`, whose Temporal adapter starts
   ``mc.operation.v1`` under the run-derived operation id with reject-duplicate / use-existing.

Trust model. The template is one the run already admitted: run admission resolved its lane,
model route, grants and credentials (``RuntimeResolver``, the sealed lane binding) and its
data class. Dispatch does not resolve them again; it re-checks only what can have changed or
what the reaction narrows: the reaction's grant subset, the run's data class against the
template's lane, the run's current authority (stop fence, generation, terminal state) and the
binding's generation and lifetime. Credentials are delivered by the lane when the operation
runs, exactly as for a family operation, never by the reaction.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from mission_control.application.execution.operations.operation_execution import (
    bind_operation_execution_request,
)
from mission_control.application.execution.operations.semantic_operation_bindings import (
    SemanticOperationBindingRepository,
)
from mission_control.application.reactions.service import (
    ReactionDispatchReceipt,
    ReactionDispatchRefused,
)
from mission_control.application.resolution.lane_bindings import LaneInvocation, LaneRebinders
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.execution.contracts import (
    OperationAttemptIdentity,
    OperationExecutionRequest,
    OperationWorkflowRequest,
    PromptSegment,
)
from mission_control.domain.execution.data_class import (
    DEFAULT_DATA_CLASS_POLICY,
    DataClassPolicy,
    admit_data_class,
)
from mission_control.domain.execution.heartbeats import (
    DEFAULT_OPERATION_HEARTBEATS,
    OperationHeartbeatPolicy,
)
from mission_control.domain.execution.lane_turns import default_lane_profile
from mission_control.domain.graph_runtime.identities import (
    NO_MAPPED_INSTANCE,
    RuntimeUnitIdentity,
    StageGraphUnitLocation,
)
from mission_control.domain.policies.contracts import (
    ActorContext,
    CommandResult,
    CommandStatus,
    LifecycleAction,
    LifecycleCommand,
    RecordUsageAction,
    ReserveBudgetAction,
    RunProjection,
)
from mission_control.domain.reactions.contracts import (
    DurableTransition,
    ReactionActivation,
    ReactionBinding,
)

BUDGET_KEY = "tokens.total"
REACTION_ISSUER = "mission-control:reactions"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ReactionTemplatePort(Protocol):
    async def get_template(
        self,
        *,
        request_scope: str,
        run_id: str,
        template: str,
        semantic_input_binding_ref: str | None,
    ) -> OperationExecutionRequest:
        """The run's admitted operation template; raise ``LookupError`` when it has none."""
        ...


class ReactionBudgetPort(Protocol):
    async def reserve(
        self, scope: str, run_id: str, *, reservation_id: str, amounts: dict[str, int]
    ) -> int:
        """Reserve once per reservation id; return the run-control revision the operation is
        admitted at. Raise :class:`ReactionDispatchRefused` when run control refuses."""
        ...

    async def release(
        self, scope: str, run_id: str, *, reservation_id: str, amounts: dict[str, int]
    ) -> None:
        """Release the whole reservation with no usage (idempotent per reservation id)."""
        ...


class OperationStartPort(Protocol):
    async def start(
        self, scope: str, run_id: str, request: OperationWorkflowRequest
    ) -> ReactionDispatchReceipt: ...


def reaction_unit(scope: str, activation: ReactionActivation) -> RuntimeUnitIdentity:
    """The activation's runtime unit: a stage operation at ``reaction.<reaction id>``."""

    return RuntimeUnitIdentity(
        request_scope=scope,
        belllabs_run_id=activation.run_id,
        execution_epoch=1,
        family="stage_graph",
        unit_kind="stage_operation",
        semantic_operation_id=activation.operation_id,
        semantic_attempt=1,
        location=StageGraphUnitLocation(
            stage_id=f"reaction.{activation.reaction_id}",
            mapped_instance_id=NO_MAPPED_INSTANCE,
            workflow_cycle_ordinal=0,
            stage_cycle_ordinal=0,
            operation_slot_id="default",
        ),
    )


def reaction_segment(
    activation: ReactionActivation, binding: ReactionBinding, transition: DurableTransition
) -> PromptSegment:
    descriptor = binding.descriptor
    content = json.dumps(
        {
            "schema_version": "mc.reaction_input.v1",
            "reaction_id": descriptor.reaction_id,
            "purpose": descriptor.operation.purpose,
            "event": {
                "kind": transition.kind.value,
                "version": transition.version,
                "source_ref": transition.source_ref,
                "facts": transition.facts,
            },
            "outputs": list(descriptor.outputs),
            "activation": {"id": activation.activation_id, "depth": activation.depth},
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return PromptSegment(
        source_ref=f"reaction-input:{activation.activation_id}",
        source_revision=1,
        # The event snapshot is host-captured run data admitted with the reaction, not a
        # privileged prompt definition.
        trust_class="admitted_input",
        content=content,
        rendered_digest=sha256_digest(content),
    )


def reaction_operation_request(
    template: OperationExecutionRequest,
    *,
    scope: str,
    activation: ReactionActivation,
    binding: ReactionBinding,
    transition: DurableTransition,
    reservation_id: str,
    amounts: dict[str, int],
    control_revision: int,
    requested_at: datetime,
    lane_bindings: LaneRebinders,
) -> OperationExecutionRequest:
    identity = OperationAttemptIdentity(
        run_id=activation.run_id, operation_id=activation.operation_id, operation_attempt=1
    )
    unit = reaction_unit(scope, activation)
    workspace = template.workspace.model_copy(
        update={
            "namespace_id": template.workspace.namespace_id.replace("{run_id}", activation.run_id),
            "workspace_id": template.workspace.workspace_id.replace("{run_id}", activation.run_id),
        }
    )
    generation = activation.run_generation or 1
    lane_binding, lane_dispatch = template.lane_binding, template.lane_dispatch
    if lane_binding is not None and lane_dispatch is not None:
        lane_binding, lane_dispatch = lane_bindings.rebind(
            lane_binding,
            lane_dispatch,
            LaneInvocation(
                binding_id=f"deep-agent:{identity.semantic_key}",
                run_id=activation.run_id,
                operation_id=identity.operation_id,
                operation_attempt=identity.operation_attempt,
                execution_generation=generation,
                erc_digest=template.effective_configuration_digest,
                control_revision=control_revision,
                workspace=workspace,
                reservation_id=reservation_id,
                runtime_unit=unit,
                capability_grant=template.capability_grant,
            ),
        )
    return OperationExecutionRequest.model_validate(
        {
            **template.model_dump(mode="python"),
            "identity": identity,
            "request_scope": scope,
            "run_control_revision": control_revision,
            "workspace": workspace,
            "lane_binding": lane_binding,
            "lane_dispatch": lane_dispatch,
            "transfer": None,
            "budget_reservation_id": reservation_id,
            "budget_limits": amounts,
            "prompt_segments": (
                *template.prompt_segments,
                reaction_segment(activation, binding, transition),
            ),
            "prior_binding_id": None,
            "requested_at": requested_at,
            "idempotency_key": f"reaction:{activation.activation_id}",
            "runtime_unit": unit,
        }
    )


def grant_refusal(template: OperationExecutionRequest, binding: ReactionBinding) -> str | None:
    grants = binding.descriptor.grants
    tools = {tool.tool_id for tool in template.tools}
    servers = {server.server_id for server in template.mcp_servers}
    if not tools <= set(grants.tools) or not servers <= set(grants.mcp_servers):
        return "GRANT_EXCEEDED"
    return None


class AdmittedReactionOperations:
    """``ReactionOperationPort``: the activation through the ordinary operation path."""

    def __init__(
        self,
        *,
        templates: ReactionTemplatePort,
        budget: ReactionBudgetPort,
        starter: OperationStartPort,
        operation_bindings: SemanticOperationBindingRepository | None = None,
        lane_bindings: LaneRebinders | None = None,
        heartbeats: OperationHeartbeatPolicy = DEFAULT_OPERATION_HEARTBEATS,
        data_classes: DataClassPolicy = DEFAULT_DATA_CLASS_POLICY,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._templates = templates
        self._budget = budget
        self._starter = starter
        self._bindings = operation_bindings
        self._lanes = lane_bindings or LaneRebinders()
        self._heartbeats = heartbeats
        self._data_classes = data_classes
        self._clock = clock

    async def materialize(
        self,
        scope: str,
        activation: ReactionActivation,
        binding: ReactionBinding,
        transition: DurableTransition,
    ) -> OperationWorkflowRequest:
        descriptor = binding.descriptor
        try:
            template = await self._templates.get_template(
                request_scope=scope,
                run_id=activation.run_id,
                template=descriptor.operation.template,
                semantic_input_binding_ref=binding.semantic_input_binding_ref,
            )
        except LookupError as error:
            raise ReactionDispatchRefused("TEMPLATE_UNAVAILABLE", str(error)) from error
        refused = grant_refusal(template, binding)
        if refused is not None:
            raise ReactionDispatchRefused(
                refused, "the operation template exceeds the reaction's declared grants"
            )
        # The facts are run data of the run's declared class; the template's lane must admit it.
        issue = admit_data_class(
            default_lane_profile(template), binding.data_class, policy=self._data_classes
        )
        if issue is not None:
            raise ReactionDispatchRefused(issue.code, issue.message)
        reservation_id = f"reaction:{activation.activation_id}"
        amounts = {BUDGET_KEY: activation.reserved_tokens}
        revision = await self._budget.reserve(
            scope, activation.run_id, reservation_id=reservation_id, amounts=amounts
        )
        try:
            operation = reaction_operation_request(
                template,
                scope=scope,
                activation=activation,
                binding=binding,
                transition=transition,
                reservation_id=reservation_id,
                amounts=amounts,
                control_revision=revision,
                requested_at=activation.admitted_at,
                lane_bindings=self._lanes,
            )
            if self._bindings is not None:
                exact = bind_operation_execution_request(operation)
                persisted = await self._bindings.create_binding(exact, request_scope=scope)
                if persisted != exact:
                    raise ReactionDispatchRefused(
                        "BINDING_CONFLICT",
                        "a different operation binding exists for this activation",
                    )
        except ReactionDispatchRefused:
            # The activation is cancelled, so its reservation is released before it is: a
            # cancelled activation never holds spend (a failed release is retried by the relay,
            # and the redelivery finds the reservation recorded and refuses again).
            await self._budget.release(
                scope, activation.run_id, reservation_id=reservation_id, amounts=amounts
            )
            raise
        return OperationWorkflowRequest(
            semantic_attempt_id=operation.identity.semantic_key,
            execution_generation=(
                operation.lane_dispatch.execution_generation
                if operation.lane_dispatch is not None
                else 1
            ),
            operation_kind="bound_operation",
            operation=operation,
            timeout_seconds=descriptor.limits.time.operation_seconds,
            heartbeat_timeout_seconds=self._heartbeats.timeout_for(operation),
            segments=self._heartbeats.segments_for(operation),
            capacity_wait=self._heartbeats.capacity_wait,
        )

    async def dispatch(
        self,
        scope: str,
        activation: ReactionActivation,
        binding: ReactionBinding,
        transition: DurableTransition,
    ) -> ReactionDispatchReceipt:
        request = await self.materialize(scope, activation, binding, transition)
        return await self._starter.start(scope, activation.run_id, request)


class ReactionRunControl(Protocol):
    """The run-control calls the budget port makes (``RunControlService``)."""

    async def get_run(self, request_scope: str, run_id: str) -> RunProjection: ...

    async def get_command_result(
        self, request_scope: str, run_id: str, idempotency_issuer: str, command_id: str
    ) -> CommandResult | None: ...

    async def execute(self, command: LifecycleCommand) -> CommandResult: ...


STALE_RUN_VERSION = "stale_run_version"
# Commands one delivery tries against a busy run, and the bound over all deliveries (each
# attempt is its own command id, so a recorded stale attempt is never replayed as the answer).
ATTEMPTS_PER_DELIVERY = 8
MAX_COMMAND_ATTEMPTS = 64


class ReactionBudgetContended(RuntimeError):
    """Every attempt of this delivery met a newer run version; the relay retries later."""


class RunControlReactionBudget:
    """``ReactionBudgetPort`` over run control.

    A reservation is one ``reserve_budget`` command and a release one zero-usage
    ``record_usage`` that releases it. Each is issued under attempt-numbered command ids
    (``reserve:<reservation>:<n>``): a ``stale_run_version`` answer is recorded for its own id and
    the next attempt reads the run's version again, so a concurrent command never turns into a
    permanent refusal. A redelivery first walks the recorded attempts and returns the accepted
    one, so the reservation is made once.
    """

    def __init__(
        self, run_control: ReactionRunControl, *, clock: Callable[[], datetime] = _utcnow
    ) -> None:
        self._run_control = run_control
        self._clock = clock

    async def reserve(
        self, scope: str, run_id: str, *, reservation_id: str, amounts: dict[str, int]
    ) -> int:
        result = await self._issue(
            scope,
            run_id,
            prefix=f"reserve:{reservation_id}",
            action=ReserveBudgetAction(reservation_id=reservation_id, amounts=amounts),
            permission="workflow_run.reserve_budget",
            reason="durable transition reaction admitted",
            correlation=reservation_id,
        )
        if result.status != CommandStatus.ACCEPTED:
            raise ReactionDispatchRefused(
                "BUDGET_REFUSED", f"run control refused the reservation: {result.reason_code}"
            )
        return int(result.resulting_run_version)

    async def release(
        self, scope: str, run_id: str, *, reservation_id: str, amounts: dict[str, int]
    ) -> None:
        result = await self._issue(
            scope,
            run_id,
            prefix=f"release:{reservation_id}",
            action=RecordUsageAction(
                usage_id=f"release:{reservation_id}",
                actual_amounts={},
                reservation_id=reservation_id,
                release_amounts=amounts,
            ),
            permission="workflow_run.report_usage",
            reason="durable transition reaction cancelled after it reserved",
            correlation=reservation_id,
        )
        if result.status != CommandStatus.ACCEPTED:
            # Not a refusal of the activation: the release must happen, so the relay retries.
            raise RuntimeError(f"run control refused the release: {result.reason_code}")

    async def _issue(
        self,
        scope: str,
        run_id: str,
        *,
        prefix: str,
        action: LifecycleAction,
        permission: str,
        reason: str,
        correlation: str,
    ) -> CommandResult:
        run_control = self._run_control
        attempt, tried = 0, 0
        while attempt < MAX_COMMAND_ATTEMPTS:
            command_id = f"{prefix}:{attempt}"
            recorded = await run_control.get_command_result(
                scope, run_id, REACTION_ISSUER, command_id
            )
            if recorded is None:
                if tried >= ATTEMPTS_PER_DELIVERY:
                    raise ReactionBudgetContended(f"{prefix}: the run kept moving")
                tried += 1
                run = await run_control.get_run(scope, run_id)
                recorded = await run_control.execute(
                    LifecycleCommand(
                        command_id=command_id,
                        idempotency_issuer=REACTION_ISSUER,
                        request_scope=scope,
                        run_id=run_id,
                        expected_run_version=run.version,
                        actor=ActorContext(
                            actor_id=REACTION_ISSUER,
                            authority_refs=frozenset({f"authority:{REACTION_ISSUER}"}),
                            permissions=frozenset({permission}),
                        ),
                        action=action,
                        reason=reason,
                        occurred_at=self._clock(),
                        correlation_id=correlation,
                    )
                )
            if recorded.status == CommandStatus.STALE and recorded.reason_code == STALE_RUN_VERSION:
                attempt += 1
                continue
            return recorded
        raise ReactionDispatchRefused(
            "BUDGET_CONTENDED", f"{prefix}: {MAX_COMMAND_ATTEMPTS} attempts met a newer run"
        )


__all__ = [
    "BUDGET_KEY",
    "AdmittedReactionOperations",
    "OperationStartPort",
    "ReactionBudgetContended",
    "ReactionBudgetPort",
    "ReactionRunControl",
    "ReactionTemplatePort",
    "RunControlReactionBudget",
    "grant_refusal",
    "reaction_operation_request",
    "reaction_segment",
    "reaction_unit",
]
