"""The readiness each node role of a mission must reach before its session starts (MO-16).

The start receipt cites the requirements of the run's sealed launch templates. Each one carries
the declaration of the role's sealed binding (`declaration_of`), so every
`mc.environment_preparation.v1` record of that environment carries the same
`declaration_digest`. The sealed binding keeps what the deployment host binding adds to the
manifest (SPEC-01 section 3), such as a network policy reference, and the network policy the
launch resolves into exact hosts (MO-15).

The manifest Validation Report is compiled before any deployment binding is applied. It cites
what the manifest alone declares (`EnvironmentSelections.binding_fields()`), with
`declaration_source="manifest"`. That digest equals the records' digest only when the host
binding adds nothing. Only the claude and codex profiles carry an `mc.environment_binding.v1`,
so a Cursor role declares its lane alone, exactly as its Cursor binding does.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Literal

from mission_control.application.environments.preparation import declaration_of
from mission_control.domain.authoring.manifest import Behavior
from mission_control.domain.authoring.mission_definition import (
    DefinitionNode,
    EnvironmentSelections,
    MissionDefinition,
)
from mission_control.domain.execution.bindings import V2_BINDING_PROFILES, ProviderExecutionBinding
from mission_control.domain.execution.contracts import OperationExecutionRequest
from mission_control.domain.execution.environment_preparation import (
    EnvironmentDeclaration,
    LaunchReadinessPolicy,
    ReadinessRequirement,
)
from mission_control.domain.execution.lanes import PLACEMENT_OF_PROFILE, CursorExecutionBinding

_UNBOUND_LANES = frozenset({"deep_agents"})


def _roles(definition: MissionDefinition) -> Iterator[tuple[DefinitionNode, bool]]:
    """The node roles a run launches: a Goal Loop's executor and verifier, a Stage Graph's
    stages, or the single node."""

    root = definition.program
    if root.behavior is Behavior.GOAL_LOOP:
        yield root, False
        yield root, True
    elif root.behavior is Behavior.STAGE_GRAPH:
        yield from ((child, False) for child in root.nodes)
    else:
        yield root, False


def _role_lane(node: DefinitionNode, verifier: bool) -> str:
    environment = (
        node.verifier_environment
        if verifier and node.verifier_environment is not None
        else node.environment
    )
    return str(environment.lane or node.lane)


def _role_selections(node: DefinitionNode, verifier: bool) -> EnvironmentSelections | None:
    if verifier and node.verifier_selections is not None:
        return node.verifier_selections
    return node.selections


def _role_template(
    definition: MissionDefinition,
    templates: Mapping[str, OperationExecutionRequest],
    node: DefinitionNode,
    verifier: bool,
) -> OperationExecutionRequest | None:
    """The sealed template of a node role: a Goal Loop's `executor`/`verifier`, else any
    `<stage>/<slot>/<variant>` template of the node's stage (one binding per stage)."""

    if definition.program.behavior is Behavior.GOAL_LOOP:
        return templates.get("verifier" if verifier else "executor")
    return next(
        (template for key, template in templates.items() if key.rsplit("/", 2)[0] == node.key),
        None,
    )


def _manifest_declaration(
    lane: str, node: DefinitionNode, verifier: bool
) -> EnvironmentDeclaration:
    selections = _role_selections(node, verifier)
    fields = (
        selections.binding_fields()
        if selections is not None and lane in V2_BINDING_PROFILES
        else None
    )
    return EnvironmentDeclaration.of(lane, fields)


def readiness_requirements(
    definition: MissionDefinition,
    policy: LaunchReadinessPolicy | None = None,
    *,
    templates: Mapping[str, OperationExecutionRequest] | None = None,
) -> tuple[ReadinessRequirement, ...]:
    """One requirement per node role that runs on a lane with an environment. A role whose
    sealed template is given cites its sealed binding; any other role cites the manifest."""

    policy = policy or LaunchReadinessPolicy()
    requirements: list[ReadinessRequirement] = []
    for node, verifier in _roles(definition):
        lane = _role_lane(node, verifier)
        if lane in _UNBOUND_LANES or lane not in PLACEMENT_OF_PROFILE:
            continue
        template = _role_template(definition, templates, node, verifier) if templates else None
        binding = (
            (
                ProviderExecutionBinding.carried_by(template)
                or CursorExecutionBinding.carried_by(template)
            )
            if template is not None
            else None
        )
        source: Literal["manifest", "sealed_binding"]
        if binding is not None:
            declaration = declaration_of(binding)
            source = "sealed_binding"
        else:
            declaration = _manifest_declaration(lane, node, verifier)
            source = "manifest"
        requirements.append(
            ReadinessRequirement(
                mission_key=definition.mission_key,
                node_key=node.key,
                role="verifier" if verifier else "node",
                pointer=node.pointer,
                lane_profile=declaration.lane_profile,
                minimum=policy.minimum(declaration.lane_profile),
                declaration_source=source,
                declaration_digest=declaration.digest,
            )
        )
    return tuple(requirements)


__all__ = ["readiness_requirements"]
