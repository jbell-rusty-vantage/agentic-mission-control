"""`mission/v2` compile admission (VALIDATION V01; ARCHITECTURE "Profile identity and
capability admission").

Every node role of a ``mission/v2`` manifest is admitted against its lane profile's
**declared** matrix (``harness.describe.declared_matrix``): its ``requires`` controls and
observation features through ``admit_requirements``, its approvals and ``all_writes_gated``
through ``admit_gate_coverage``. Each refusal is a blocker whose JSON pointer names the manifest
entry that required the feature (the nearest environment that set it), raised at compile,
before anything is submitted or any provider is created; nothing degrades to a weaker lane or
mode. The provider-hosted products compile structurally, but a warning records that their
launch is refused (MP-18/19 are evidence-blocked; the evidence is each lane package's,
``describe.LAUNCH_BLOCKED_EVIDENCE``); so do the hosted agent APIs until their lanes land
(ADR-0050, ``describe.DESCRIBE_ONLY_LAUNCH_EVIDENCE``). A lane runs the behaviors its package
declaration's families admit (``lane_behaviors``, OC-R3). An authored workspace
policy is admitted per local profile (``workspaces.policy.admit_policy``). The mission's Data
Class is admitted per node lane (``domain.execution.data_class``, SPEC-06 section 8): a PHI or
secret mission, or one that declares no class, is refused on a lane that is not ZDR-eligible.
The policy is the compiling Application's (its Application Binding's widening over the
defaults, HL-18); without one, the defaults apply.

The environment additions (materialization SPEC-01 §3) are admitted here too: a pinned
Environment Kit's ``requires`` must be satisfied by the node's declared variables, secrets,
egress and git repositories, and every ``value_ref`` must name installation configuration
whose key is not secret-like (``config_secret_like``, on the key alone, before resolution).
Kit requirements and configuration keys arrive already resolved (the compile service asks its
environment-inputs port); an unresolved kit or key is a blocker, never a default. With the
kits resolved, a node role that switches the kit its allowlist includes is compared host by
host with the inherited policy (MO-15): only hosts the parent does not allow widen.

Pure over its inputs: the program tree, the resolved node environments and those resolutions.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Final

from mission_control.application.execution.approvals_coverage import (
    GATE_COVERAGE_UNENFORCEABLE,
    GateCoverageRequirement,
    admit_gate_coverage,
)
from mission_control.application.execution.harness.describe import (
    DESCRIBE_ONLY_LAUNCH_EVIDENCE,
    LAUNCH_BLOCKED_EVIDENCE,
    declared_lane,
    declared_matrix,
)
from mission_control.application.workspaces.errors import WorkspaceError
from mission_control.application.workspaces.policy import admit_policy, policy_pin
from mission_control.domain.authoring.manifest import (
    Behavior,
    Lane,
    ManifestErrorCode,
    ManifestIssue,
    MissionBlock,
    NodeEnvironment,
    walk_program,
)
from mission_control.domain.authoring.manifest_v2 import (
    EnvironmentV2,
    MissionBlockV2,
    RequiredFeatures,
)
from mission_control.domain.authoring.mission_environment import (
    ENVIRONMENT_ADDITIONS,
    KitRequirements,
    is_secret_like_config_key,
    kit_requirement_issues,
    kit_switch_issues,
)
from mission_control.domain.execution.data_class import (
    DEFAULT_DATA_CLASS_POLICY,
    DataClassPolicy,
    admit_data_class,
)
from mission_control.domain.execution.lane_requirements import (
    RequirementIssue,
    RequirementSet,
    admit_requirements,
)
from mission_control.domain.execution.lanes import HOSTED_PROFILES
from mission_control.domain.resolution.configuration import Family

# The family each program behavior runs as (the resolution vocabulary, design §4 step 2).
FAMILY_OF_BEHAVIOR: Final[Mapping[Behavior, Family]] = {
    Behavior.STAGE_GRAPH: "StageGraph",
    Behavior.GOAL_LOOP: "GoalDirected",
    Behavior.PARALLEL_SWARM: "ParallelSwarm",
    Behavior.EVALUATOR_OPTIMIZER: "EvaluatorOptimizer",
}


def lane_behaviors(lane_profile: str) -> frozenset[Behavior]:
    """The behaviors a lane runs, from its package declaration (OC-R3): a program behavior
    whose family the lane does not declare `unsupported`, and every executor, wait and gate
    behavior (program-only behaviors such as swarm and evaluator stay with the lanes that
    declare their families)."""

    families = declared_lane(lane_profile).families
    return frozenset(
        behavior
        for behavior in Behavior
        if (family := FAMILY_OF_BEHAVIOR.get(behavior)) is None or families[family] != "unsupported"
    )


V2_LANE_BEHAVIORS: Final[Mapping[Lane, frozenset[Behavior]]] = {
    lane: lane_behaviors(lane.value) for lane in Lane
}


# Environment fields whose manifest location an environment-additions issue names.
ENVIRONMENT_INPUT_FIELDS: Final = ("kit", "variables", "secrets", "network", "git")


def _issue(pointer: str, message: str, reason: str) -> ManifestIssue:
    return ManifestIssue(
        code=ManifestErrorCode.UNSUPPORTED_BEHAVIOR, pointer=pointer, message=message, reason=reason
    )


def environment_chains(
    block: MissionBlock, mission_pointer: str, nodes: Sequence[NodeEnvironment]
) -> dict[tuple[str, str], tuple[tuple[str, Mapping[str, str]], ...]]:
    """Per node role, its environment pointers and field provenance from itself to the root.

    The first entry whose provenance marks a field ``overlay`` is the manifest location that
    set it; a field inherited all the way comes from the mission environment.
    """

    by_role = {(node.node_key, node.role): node for node in nodes}
    parents = _parents(block, mission_pointer)
    chains: dict[tuple[str, str], tuple[tuple[str, Mapping[str, str]], ...]] = {}
    for (key, role), node in by_role.items():
        chain: list[tuple[str, Mapping[str, str]]] = [
            (f"{node.pointer}/environment", node.field_provenance)
        ]
        current: str | None = key if role == "verifier" else parents.get(key)
        while current is not None:
            ancestor = by_role.get((current, "node"))
            if ancestor is None:
                break
            chain.append((f"{ancestor.pointer}/environment", ancestor.field_provenance))
            current = parents.get(current)
        chain.append((f"{mission_pointer}/environment", {}))
        chains[(key, role)] = tuple(chain)
    return chains


def _parents(block: MissionBlock, mission_pointer: str) -> dict[str, str | None]:
    return {
        visit.node.key: visit.parent_key
        for visit in walk_program(block.program, f"{mission_pointer}/program")
    }


def field_source(chain: Sequence[tuple[str, Mapping[str, str]]], field: str) -> str:
    """The environment pointer (``.../environment``) that set ``field`` for this node role."""

    for pointer, provenance in chain[:-1]:
        if any(
            origin == "overlay" and (name == field or name.startswith(field + "."))
            for name, origin in provenance.items()
        ):
            return pointer
    return chain[-1][0]


def _converted(
    issues: Sequence[RequirementIssue], pointer: str | None = None
) -> list[ManifestIssue]:
    return [
        _issue(pointer or item.pointer, f"{item.code}: {item.message}", item.code)
        for item in issues
    ]


def admit_node(
    node: NodeEnvironment, chain: Sequence[tuple[str, Mapping[str, str]]]
) -> tuple[list[ManifestIssue], list[ManifestIssue]]:
    """V01 for one node role: blockers and warnings, every one pointed."""

    blockers: list[ManifestIssue] = []
    warnings: list[ManifestIssue] = []
    environment = node.effective_environment
    if not isinstance(environment, EnvironmentV2):
        return blockers, warnings
    lane = node.lane
    describe = declared_matrix(lane.value)
    requires = environment.requires or RequiredFeatures()
    for group in ("controls", "observation"):
        values = getattr(requires, group)
        if values:
            base = field_source(chain, f"requires.{group}") + "/requires"
            blockers.extend(
                _converted(
                    admit_requirements(describe, RequirementSet(**{group: values}), pointer=base)
                )
            )
    if requires.approvals:
        base = field_source(chain, "requires.approvals") + "/requires"
        blockers.extend(
            _converted(
                admit_gate_coverage(
                    describe,
                    GateCoverageRequirement(approvals=requires.approvals),
                    pointer=base,
                )
            )
        )
    if requires.all_writes_gated:
        gate = field_source(chain, "requires.all_writes_gated") + "/requires/all_writes_gated"
        coverage = admit_gate_coverage(
            describe, GateCoverageRequirement(all_writes_gated=True), pointer=gate
        )
        blockers.extend(
            _converted(
                [item for item in coverage if item.code == GATE_COVERAGE_UNENFORCEABLE], gate
            )
        )
    policy = environment.workspace.policy if environment.workspace is not None else None
    if policy is not None and lane.value not in HOSTED_PROFILES:
        try:
            admit_policy(lane.value, policy_pin(policy))
        except WorkspaceError as error:
            blockers.append(
                _issue(
                    field_source(chain, "workspace.policy") + "/workspace/policy",
                    error.message,
                    error.code,
                )
            )
    if lane is Lane.DEEP_AGENTS:
        warnings.extend(
            _issue(
                field_source(chain, name) + f"/{name}",
                (
                    "lane deep_agents requires exact worker-tool network hosts; unrestricted "
                    "or wildcard policies do not enable executable sandbox networking"
                    if name == "network"
                    else f"lane deep_agents does not materialize {name}; its sandbox profile "
                    "governs this node's environment"
                ),
                "not_materialized",
            )
            for name in ENVIRONMENT_ADDITIONS
            if getattr(environment, name) is not None
            and not (
                name == "network"
                and environment.network is not None
                and environment.network.mode in {"none", "allowlist"}
                and not any(host.startswith("*.") for host in environment.network.allow)
            )
        )
    if lane.value in LAUNCH_BLOCKED_EVIDENCE:
        warnings.append(
            ManifestIssue(
                code=ManifestErrorCode.UNSUPPORTED_BEHAVIOR,
                pointer=field_source(chain, "lane") + "/lane",
                message=(
                    f"lane {lane.value} compiles structurally but its launch is refused: the "
                    f"provider-hosted lifecycle is evidence-blocked "
                    f"({LAUNCH_BLOCKED_EVIDENCE[lane.value]})"
                ),
                reason="hosted_launch_refused",
            )
        )
    elif lane.value in DESCRIBE_ONLY_LAUNCH_EVIDENCE:
        warnings.append(
            ManifestIssue(
                code=ManifestErrorCode.UNSUPPORTED_BEHAVIOR,
                pointer=field_source(chain, "lane") + "/lane",
                message=(
                    f"lane {lane.value} compiles structurally but its launch is refused: the "
                    f"profile is declared describe-only until its lane lands "
                    f"({DESCRIBE_ONLY_LAUNCH_EVIDENCE[lane.value]}, ADR-0050)"
                ),
                reason="hosted_launch_refused",
            )
        )
    return blockers, warnings


def admit_data_classes(
    block: MissionBlock,
    mission_pointer: str,
    nodes: Sequence[NodeEnvironment],
    chains: Mapping[tuple[str, str], Sequence[tuple[str, Mapping[str, str]]]],
    *,
    policy: DataClassPolicy = DEFAULT_DATA_CLASS_POLICY,
) -> list[ManifestIssue]:
    """SPEC-06 section 8: one blocker per node role whose lane does not admit the mission's
    Data Class under the Application's ``policy``, pointed at the lane that chose it (the class
    is in the message)."""

    data_class = block.data_class if isinstance(block, MissionBlockV2) else None
    blockers: list[ManifestIssue] = []
    for node in nodes:
        refused = admit_data_class(
            node.lane.value,
            data_class,
            policy=policy,
            pointer=field_source(chains[(node.node_key, node.role)], "lane") + "/lane",
        )
        if refused is not None:
            blockers.append(
                _issue(
                    refused.pointer,
                    f"{refused.code}: {refused.message} (declared at {mission_pointer}/data_class)",
                    refused.code,
                )
            )
    return blockers


def admit_environment_inputs(
    node: NodeEnvironment,
    chain: Sequence[tuple[str, Mapping[str, str]]],
    *,
    kits: Mapping[str, KitRequirements | None],
    config_keys: frozenset[str],
) -> list[ManifestIssue]:
    """A node role's kit requirements and ``value_ref`` keys, every issue pointed at the
    environment that set the field an author would edit."""

    environment = node.effective_environment
    if not isinstance(environment, EnvironmentV2) or node.lane is Lane.DEEP_AGENTS:
        return []
    pointers = {name: field_source(chain, name) for name in ENVIRONMENT_INPUT_FIELDS}
    issues: list[ManifestIssue] = []
    if environment.kit is not None:
        requirements = kits.get(environment.kit.pin)
        if requirements is None:
            issues.append(
                ManifestIssue(
                    code=ManifestErrorCode.CAPABILITY_UNAVAILABLE,
                    pointer=f"{pointers['kit']}/kit/pin",
                    message=f"environment kit {environment.kit.pin} does not resolve to a "
                    "published kit",
                    reason="kit_unresolved",
                )
            )
        else:
            issues.extend(kit_requirement_issues(environment, requirements, pointers))
    for index, variable in enumerate(environment.variables or ()):
        key = variable.config_key
        if key is None:
            continue
        pointer = f"{pointers['variables']}/variables/{index}/value_ref"
        if is_secret_like_config_key(key):
            # Configuration is non-secret: a credential-like key is refused on the key alone,
            # whether or not any source supplies it (the installation loader refuses one too).
            issues.append(
                ManifestIssue(
                    code=ManifestErrorCode.INVALID_DEFINITION,
                    pointer=pointer,
                    message=f"{variable.value_ref} names a secret-like key; installation "
                    "configuration is non-secret, declare the credential under secrets",
                    reason="config_secret_like",
                )
            )
        elif key not in config_keys:
            issues.append(
                ManifestIssue(
                    code=ManifestErrorCode.INVALID_DEFINITION,
                    pointer=pointer,
                    message=f"{variable.value_ref} names no installation configuration value",
                    reason="config_unresolved",
                )
            )
    return issues


def admit_kit_switches(
    block: MissionBlock,
    mission_pointer: str,
    nodes: Sequence[NodeEnvironment],
    chains: Mapping[tuple[str, str], Sequence[tuple[str, Mapping[str, str]]]],
    *,
    kits: Mapping[str, KitRequirements | None],
) -> list[ManifestIssue]:
    """A node role whose allowlist includes another kit than its parent's may bring only hosts
    the inherited policy allows, compared on the resolved kits (an unresolved kit is its own
    blocker). The parent of a root node is the mission environment, of a verifier its node. A
    node that also changes lane is compared the same way: no lane widens ``network.allow``."""

    by_role = {(node.node_key, node.role): node for node in nodes}
    parents = _parents(block, mission_pointer)
    issues: list[ManifestIssue] = []
    for node in nodes:
        environment = node.effective_environment
        if (
            not isinstance(environment, EnvironmentV2)
            or node.lane is Lane.DEEP_AGENTS
            or environment.kit is None
        ):
            continue
        parent_key = node.node_key if node.role == "verifier" else parents.get(node.node_key)
        parent = by_role.get((parent_key, "node")) if parent_key is not None else None
        inherited = parent.effective_environment if parent is not None else block.environment
        child_kit = kits.get(environment.kit.pin)
        if not isinstance(inherited, EnvironmentV2) or child_kit is None:
            continue
        parent_kit = kits.get(inherited.kit.pin) if inherited.kit is not None else None
        issues.extend(
            kit_switch_issues(
                inherited,
                environment,
                parent_kit_egress=parent_kit.egress if parent_kit is not None else (),
                child_kit_egress=child_kit.egress,
                pointer=field_source(chains[(node.node_key, node.role)], "kit") + "/kit/pin",
            )
        )
    return issues


def admit_mission(
    block: MissionBlock,
    mission_pointer: str,
    nodes: Sequence[NodeEnvironment],
    *,
    kits: Mapping[str, KitRequirements | None] | None = None,
    config_keys: frozenset[str] = frozenset(),
    data_class_policy: DataClassPolicy = DEFAULT_DATA_CLASS_POLICY,
) -> tuple[list[ManifestIssue], list[ManifestIssue]]:
    blockers: list[ManifestIssue] = []
    warnings: list[ManifestIssue] = []
    chains = environment_chains(block, mission_pointer, nodes)
    for node in nodes:
        chain = chains[(node.node_key, node.role)]
        node_blockers, node_warnings = admit_node(node, chain)
        blockers.extend(node_blockers)
        blockers.extend(
            admit_environment_inputs(node, chain, kits=kits or {}, config_keys=config_keys)
        )
        warnings.extend(node_warnings)
    blockers.extend(admit_kit_switches(block, mission_pointer, nodes, chains, kits=kits or {}))
    blockers.extend(
        admit_data_classes(block, mission_pointer, nodes, chains, policy=data_class_policy)
    )
    return blockers, warnings


__all__ = [
    "ENVIRONMENT_INPUT_FIELDS",
    "FAMILY_OF_BEHAVIOR",
    "V2_LANE_BEHAVIORS",
    "admit_data_classes",
    "admit_environment_inputs",
    "admit_kit_switches",
    "admit_mission",
    "admit_node",
    "environment_chains",
    "field_source",
    "lane_behaviors",
]
