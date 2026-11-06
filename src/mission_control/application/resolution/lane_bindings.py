"""The two steps a sealed lane binding takes after compile, each behind a port its lane implements.

A lane's compile (`LaneAdapter.compile`) seals one node role. Two later steps need coordinates
the node-level compile cannot know, and only the lane that produced the bytes may perform them
(ADR-0063, design §6.1; OC-R2 / OVE-197):

- **Template** (`LaneTemplateBinder`): the launch author freezes one operation template per node
  and passes the template coordinates it owns (run, placeholder operation, workspace, authority,
  reservation). The lane returns the template's `lane_binding` with its `LaneDispatch`, and the
  neutral request facts it derived from its own bytes: model policy, capability grant, the
  lane's own secret references and the scaffold's agent-profile, tracing, sensitive-data and
  snapshot policy references. These already are neutral request fields (every lane fills them),
  so the two-lane rule keeps them on the request and the author never parses the bytes.
- **Rebind** (`LaneRebinder`): a family (Stage Graph, Goal Directed) binds a template to one live
  attempt. It names the template binding by digest and the live coordinates it owns; a lane
  whose bytes carry attempt coordinates (Deep Agents) reseals them, and a lane whose bytes carry
  none (Cursor, claude/codex today) keeps its binding. `LaneRebinders` dispatches by the sealed
  binding's lane profile; the family never reads the payload.

Bootstrap composes both from the lane packages; the application imports only these protocols.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from mission_control.domain.authoring.contracts import ExactDefinitionRef, SecretRef
from mission_control.domain.execution.contracts import (
    CapabilityGrant,
    ModelPolicy,
    WorkspaceContract,
)
from mission_control.domain.execution.lanes import ExecutionRuntime, LaneDispatch
from mission_control.domain.graph_runtime.identities import RuntimeUnitIdentity
from mission_control.domain.resolution.sealed import SealedLaneBinding


@dataclass(frozen=True)
class LaneTemplateCoordinates:
    """What a frozen operation template fixes that the node-level compile could not know."""

    run_id: str
    operation_id: str
    operation_attempt: int
    execution_generation: int
    control_revision: int
    erc_digest: str
    workspace: WorkspaceContract
    # The admitted authority's capabilities; the lane adds the tool and MCP server ids it binds.
    capabilities: frozenset[str]
    reservation_id: str
    # Exact finite egress resolved from the node's authored environment; no deployment default.
    network_hosts: frozenset[str] = frozenset()


@dataclass(frozen=True)
class LaneTemplate:
    """The fields of an `OperationExecutionRequest` template a lane derives from its bytes."""

    execution_runtime: ExecutionRuntime
    lane_binding: SealedLaneBinding
    lane_dispatch: LaneDispatch
    model_policy: ModelPolicy
    capability_grant: CapabilityGrant
    # The lane's own references (sandbox, seeded MCP and async deployment credentials); the
    # launch author prepends the model vendor's credential.
    secret_refs: tuple[SecretRef, ...]
    agent_profile_ref: ExactDefinitionRef
    tracing_policy_ref: str
    sensitive_data_policy_ref: str
    snapshot_policy_ref: str


class LaneTemplateBinder(Protocol):
    """Implemented by the lane package whose compile sealed the node binding."""

    def __call__(
        self, binding: SealedLaneBinding, coordinates: LaneTemplateCoordinates
    ) -> LaneTemplate: ...


@dataclass(frozen=True)
class LaneInvocation:
    """The live attempt a family binds a template to (the coordinates the family owns)."""

    binding_id: str
    run_id: str
    operation_id: str
    operation_attempt: int
    execution_generation: int
    erc_digest: str
    control_revision: int
    workspace: WorkspaceContract
    reservation_id: str
    runtime_unit: RuntimeUnitIdentity
    capability_grant: CapabilityGrant


class LaneRebinder(Protocol):
    """Implemented by a lane whose sealed bytes carry attempt coordinates."""

    def rebind(
        self, binding: SealedLaneBinding, dispatch: LaneDispatch, invocation: LaneInvocation
    ) -> tuple[SealedLaneBinding, LaneDispatch]: ...


class LaneRebinders:
    """The families' one rebind port: dispatch by the sealed binding's lane profile.

    A profile without a rebinder keeps its bytes; only the dispatch's generation follows the
    attempt (the lane stated every other dispatch fact when it sealed the template).
    """

    def __init__(self, rebinders: Mapping[str, LaneRebinder] | None = None) -> None:
        self._rebinders = dict(rebinders or {})

    def rebind(
        self, binding: SealedLaneBinding, dispatch: LaneDispatch, invocation: LaneInvocation
    ) -> tuple[SealedLaneBinding, LaneDispatch]:
        rebinder = self._rebinders.get(binding.lane_profile)
        if rebinder is not None:
            return rebinder.rebind(binding, dispatch, invocation)
        return binding, dispatch.model_copy(
            update={"execution_generation": invocation.execution_generation}
        )


__all__ = [
    "LaneInvocation",
    "LaneRebinder",
    "LaneRebinders",
    "LaneTemplate",
    "LaneTemplateBinder",
    "LaneTemplateCoordinates",
]
