"""Live invocation coordinates for a Deep Agents execution binding (SV-01, defect E01).

A launch template is compiled once with placeholder coordinates (operation
``manifest-template/<key>``, attempt 1, generation 1). Both program families rebind that
template to the live attempt; the frozen ``cognitive_context_values`` the agent receives
must be rebound with it, or the agent (and, for a hosted graph, the dataclass defaults the
Agent Server instantiates) sees the template's stale identity. This module is the one
place both families rebind, so outer fields and context coordinates cannot drift apart.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from mission_control.domain.execution.checkpoint_lineage import cognitive_session_namespace
from mission_control.domain.execution.contracts import (
    CapabilityGrant,
    DeepAgentExecutionBinding,
    WorkspaceContract,
)
from mission_control.domain.graph_runtime.identities import RuntimeUnitIdentity

TEMPLATE_OPERATION_PREFIX: Final = "manifest-template/"

# Context fields that name the live invocation. A context schema contributes any subset;
# each present field is refreshed from the binding field of the same name.
LIVE_INVOCATION_CONTEXT_FIELDS: Final[tuple[str, ...]] = (
    "run_id",
    "operation_id",
    "operation_attempt",
    "execution_generation",
    "control_revision",
    "cognitive_session_namespace",
)


class TemplateInvocationIdentity(ValueError):
    """A live binding still names a launch template's placeholder operation."""


def live_invocation_context_values(
    values: Mapping[str, object], coordinates: Mapping[str, object]
) -> dict[str, object]:
    """Return ``values`` with every live coordinate field replaced from ``coordinates``.

    Fields the schema does not declare are not added (the binding requires the value set
    to match the frozen schema exactly); fields the schema declares are always refreshed.
    """

    refreshed = dict(values)
    for name in LIVE_INVOCATION_CONTEXT_FIELDS:
        if name in refreshed and name in coordinates:
            refreshed[name] = coordinates[name]
    return refreshed


def rebind_deep_agent_invocation(
    template: DeepAgentExecutionBinding,
    *,
    binding_id: str,
    run_id: str,
    operation_id: str,
    operation_attempt: int,
    execution_generation: int,
    erc_digest: str,
    control_revision: int,
    workspace: WorkspaceContract,
    reservation_id: str,
    runtime_unit: RuntimeUnitIdentity,
    capability_grant: CapabilityGrant | None = None,
) -> DeepAgentExecutionBinding:
    """Bind ``template`` to one live attempt, outer fields and context coordinates together.

    The result carries a new content digest whenever any coordinate changes, because the
    refreshed context values are part of the binding digest.
    """

    if operation_id.startswith(TEMPLATE_OPERATION_PREFIX):
        raise TemplateInvocationIdentity(
            f"live Deep Agents binding cannot carry template operation {operation_id!r}"
        )
    namespace = cognitive_session_namespace(runtime_unit, execution_generation)
    values = template.model_dump(mode="python", exclude={"binding_digest"})
    values.update(
        {
            "binding_id": binding_id,
            "run_id": run_id,
            "operation_id": operation_id,
            "operation_attempt": operation_attempt,
            "execution_generation": execution_generation,
            "erc_digest": erc_digest,
            "control_revision": control_revision,
            "workspace": workspace,
            "reservation_id": reservation_id,
            "runtime_unit": runtime_unit,
            "cognitive_session_namespace": namespace,
        }
    )
    if capability_grant is not None:
        values["capability_grant"] = capability_grant
    values["cognitive_context_values"] = live_invocation_context_values(
        template.cognitive_context_values, values
    )
    return DeepAgentExecutionBinding.create(**values)


__all__ = [
    "LIVE_INVOCATION_CONTEXT_FIELDS",
    "TEMPLATE_OPERATION_PREFIX",
    "TemplateInvocationIdentity",
    "live_invocation_context_values",
    "rebind_deep_agent_invocation",
]
