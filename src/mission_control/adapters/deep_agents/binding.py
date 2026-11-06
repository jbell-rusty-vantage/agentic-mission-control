"""The Deep Agents lane's own bytes: seal, unseal, template and rebind (OC-R2 / OVE-197).

An operation request carries one opaque `SealedLaneBinding` (ADR-0063, design §6.1). For a
`deep_agent` attempt its payload is the exact `DeepAgentExecutionBinding`
(`belllabs.deep-agent-binding.v1`) as canonical UTF-8 JSON, and this module is where the lane
turns those bytes back into the typed binding:

- :func:`execution_binding` decodes the binding an operation request or bound operation carries
  and verifies it against the operation's authority envelope (identity, configuration digest,
  control revision, workspace, grant, reservation, runtime unit) and the `LaneDispatch` the
  core schedules by; every reader in this package goes through it.
- :class:`DeepAgentsLaneBindings` implements the two application ports of
  `application/resolution/lane_bindings.py`: the template step (``__call__``: a compiled
  `mc.deep_agent_node_binding.v1` plus the launch author's template coordinates become the
  template's exact binding and the neutral request facts) and the per-attempt rebind (the live
  coordinates, outer fields and frozen context values together, SV-01).

It replaces R1's temporary template bridge (`template_bridge.py` and
`application/authoring/lane_templates.py`).
"""

from __future__ import annotations

from mission_control.adapters.deep_agents.compile import (
    DEEP_AGENT_NODE_BINDING_SCHEMA,
    DeepAgentNodeBinding,
)
from mission_control.adapters.deep_agents.lane import LANE_PROFILE
from mission_control.application.resolution.lane_bindings import (
    LaneInvocation,
    LaneTemplate,
    LaneTemplateCoordinates,
)
from mission_control.domain.execution.contracts import (
    CapabilityGrant,
    DeepAgentExecutionBinding,
    ModelPolicy,
    OperationExecutionBinding,
    OperationExecutionRequest,
)
from mission_control.domain.execution.errors import DeepAgentMaterializationError
from mission_control.domain.execution.lanes import LaneDispatch
from mission_control.domain.execution.live_invocation import (
    live_invocation_context_values,
    rebind_deep_agent_invocation,
)
from mission_control.domain.execution.materialization import compile_deep_agent_execution_binding
from mission_control.domain.resolution.sealed import SealedLaneBinding


def seal(binding: DeepAgentExecutionBinding) -> tuple[SealedLaneBinding, LaneDispatch]:
    """The exact binding as this lane's opaque bytes, with the facts the core schedules by."""

    return binding.seal(), binding.lane_dispatch()


def execution_binding(
    operation: OperationExecutionRequest | OperationExecutionBinding,
) -> DeepAgentExecutionBinding:
    """The exact Deep Agents binding an operation carries, verified against its envelope.

    Raises `DeepAgentMaterializationError` for another runtime or lane, a missing binding, or
    bytes that do not belong to this operation.
    """

    sealed = operation.lane_binding
    if (
        operation.execution_runtime != "deep_agent"
        or sealed is None
        or operation.lane_dispatch is None
        or sealed.lane_profile != LANE_PROFILE
    ):
        raise DeepAgentMaterializationError(
            "Deep Agent adapter requires the exact canonical execution binding"
        )
    try:
        # Decodes, and refuses a dispatch the bytes do not state (`carried_by`).
        binding = DeepAgentExecutionBinding.carried_by(operation)
        if binding is None:
            raise ValueError(f"{sealed.schema_id} is not a Deep Agents execution binding")
        binding.verify_operation_envelope(operation)
    except DeepAgentMaterializationError:
        raise
    except ValueError as error:
        raise DeepAgentMaterializationError(str(error)) from error
    return binding


class DeepAgentsLaneBindings:
    """The Deep Agents implementation of `LaneTemplateBinder` and `LaneRebinder`."""

    def __call__(
        self, binding: SealedLaneBinding, coordinates: LaneTemplateCoordinates
    ) -> LaneTemplate:
        """One template's exact binding and request facts, from the compiled node bytes."""

        if (
            binding.lane_profile != LANE_PROFILE
            or binding.schema_id != DEEP_AGENT_NODE_BINDING_SCHEMA
        ):
            raise ValueError(
                f"the deep_agents template step reads {DEEP_AGENT_NODE_BINDING_SCHEMA} bindings, "
                f"not {binding.lane_profile} {binding.schema_id}"
            )
        node = DeepAgentNodeBinding.model_validate_json(binding.payload)
        profile = node.profile
        grant = CapabilityGrant(
            capabilities=coordinates.capabilities,
            tool_ids=frozenset(item.tool_name for item in profile.tools),
            mcp_server_ids=frozenset(item.server_name for item in profile.mcp_servers),
            network_hosts=coordinates.network_hosts,
        )
        # Template coordinates only; each family rebinds them per live attempt (SV-01).
        values = live_invocation_context_values(
            node.context_values,
            {
                "run_id": coordinates.run_id,
                "operation_id": coordinates.operation_id,
                "operation_attempt": coordinates.operation_attempt,
                "execution_generation": coordinates.execution_generation,
                "control_revision": coordinates.control_revision,
            },
        )
        exact = compile_deep_agent_execution_binding(
            profile=profile,
            placement=node.placement,
            state_schema=node.state_schema,
            context_schema=node.context_schema,
            context_values=values,
            run_id=coordinates.run_id,
            operation_id=coordinates.operation_id,
            operation_attempt=coordinates.operation_attempt,
            execution_generation=coordinates.execution_generation,
            erc_digest=coordinates.erc_digest,
            control_revision=coordinates.control_revision,
            workspace=coordinates.workspace,
            capability_grant=grant,
            reservation_id=coordinates.reservation_id,
            authority_refs=node.authority_refs,
            redaction_policy_ref=node.redaction_policy_ref,
            initial_context_manifest=node.initial_context_manifest,
            applied_degradations=node.receipt.degradations,
            materialization_receipt=node.receipt,
        )
        sealed, dispatch = seal(exact)
        return LaneTemplate(
            execution_runtime="deep_agent",
            lane_binding=sealed,
            lane_dispatch=dispatch,
            model_policy=ModelPolicy(
                provider=profile.model.provider,
                model=profile.model.model_name,
                reasoning_effort=node.reasoning_effort,
                verbosity=node.verbosity,
            ),
            capability_grant=grant,
            secret_refs=node.secret_refs,
            agent_profile_ref=node.agent_profile_ref,
            tracing_policy_ref=node.tracing_policy_ref,
            sensitive_data_policy_ref=node.sensitive_data_policy_ref,
            snapshot_policy_ref=node.snapshot_policy_ref,
        )

    def rebind(
        self, binding: SealedLaneBinding, dispatch: LaneDispatch, invocation: LaneInvocation
    ) -> tuple[SealedLaneBinding, LaneDispatch]:
        """The template's exact binding bound to one live attempt (SV-01)."""

        template = DeepAgentExecutionBinding.unseal(binding)
        if template.lane_dispatch() != dispatch:
            raise ValueError("the template's lane dispatch differs from its sealed binding")
        return seal(
            rebind_deep_agent_invocation(
                template,
                binding_id=invocation.binding_id,
                run_id=invocation.run_id,
                operation_id=invocation.operation_id,
                operation_attempt=invocation.operation_attempt,
                execution_generation=invocation.execution_generation,
                erc_digest=invocation.erc_digest,
                control_revision=invocation.control_revision,
                workspace=invocation.workspace,
                reservation_id=invocation.reservation_id,
                runtime_unit=invocation.runtime_unit,
                capability_grant=invocation.capability_grant,
            )
        )


DEEP_AGENTS_LANE_BINDINGS = DeepAgentsLaneBindings()

__all__ = [
    "DEEP_AGENTS_LANE_BINDINGS",
    "DeepAgentsLaneBindings",
    "execution_binding",
    "seal",
]
