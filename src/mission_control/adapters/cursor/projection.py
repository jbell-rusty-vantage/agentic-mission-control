"""The Cursor binding's view of the Host Projection placed into its workspace (FT-G3).

SPEC-07 section 5.1: the lane only *places* what SPEC-01 renders, through the lane-neutral
placement helpers (``application/agentic_components/placement.py``): `.cursor/rules/mc-mission.mdc`
with `alwaysApply`, `.cursor/skills`, `.cursor/agents`, `.cursor/mcp.json` with secret
references only (cursor_local; cursor_cloud sends its servers inline) and `.cursor/hooks.json`
with Kernel Hooks first and fail-closed. The repository's own `AGENTS.md` is never touched and
its `.cursor/hooks.json` / `.cursor/mcp.json` are merged, not replaced (MO-02 layering).

What is Cursor's own: `CatalogRows` resolves a Cursor binding's exact pins, and
`projection_digests` are recorded on the Materialization; a digest that differs from the
binding's pin is `CAPABILITY_DRIFT` and nothing runs.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from mission_control.application.agentic_components.placement import (
    CAPABILITY_DRIFT,
    LaneProjectionError,
)
from mission_control.application.capabilities.bundle_custody import BundleMaterializer
from mission_control.application.capabilities.catalog import resolved_capability
from mission_control.application.environments.network import (
    LaneNetworkContext,
    NetworkProjection,
    project_network_policy,
)
from mission_control.domain.agentic_components.projection import (
    HostProjection,
    ResolvedCapability,
)
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.capabilities.pins import CapabilityPin
from mission_control.domain.context.render import bytes_digest
from mission_control.domain.execution.contracts import OperationExecutionRequest
from mission_control.domain.execution.lanes import CursorExecutionBinding


class CatalogRows:
    """Resolve a Cursor binding's exact catalog pins (skills, MCP servers, subagents, hook
    scripts, plugins) in ``projected_pins`` order."""

    def __init__(self, definitions: object, *, bundles: BundleMaterializer | None) -> None:
        self._definitions = definitions
        self._bundles = bundles

    async def __call__(self, operation: OperationExecutionRequest) -> Sequence[ResolvedCapability]:
        binding = CursorExecutionBinding.carried_by(operation)
        if binding is None:
            return ()
        rows: list[ResolvedCapability] = []
        for text in binding.projected_pins():
            rows.append(
                await resolved_capability(
                    self._definitions, CapabilityPin.parse(text), bundles=self._bundles
                )
            )
        return tuple(rows)


def _file(projection: HostProjection, path: str) -> bytes | None:
    try:
        return projection.file(path).content
    except KeyError:
        return None


def projection_digests(projection: HostProjection) -> dict[str, str]:
    """The digests a Cursor binding pins: the rule, the agents and the hooks, as rendered
    (before layering merges them into the repository's own files), and the plugin expansion
    (each plugin and the members it took) when plugins expanded."""

    agents = sorted(
        (item.path, bytes_digest(item.content))
        for item in projection.files
        if item.path.startswith(".cursor/agents/")
    )
    digests = {
        "rules_digest": bytes_digest(_file(projection, ".cursor/rules/mc-mission.mdc") or b""),
        "agents_digest": sha256_digest([list(item) for item in agents]),
        "hooks_digest": bytes_digest(_file(projection, ".cursor/hooks.json") or b""),
    }
    expansions = projection.report.plugin_expansions
    if expansions:
        digests["plugin_expansion_digest"] = sha256_digest(
            [[plugin, list(members)] for plugin, members in expansions]
        )
    return digests


def verify_projection(binding: CursorExecutionBinding, digests: Mapping[str, str]) -> None:
    pinned = binding.projections
    for name, expected in (
        ("rules_digest", pinned.rules_digest),
        ("agents_digest", pinned.agents_digest),
        ("hooks_digest", pinned.hooks_digest),
        ("plugin_expansion_digest", pinned.plugin_expansion_digest),
    ):
        if digests.get(name) != expected:
            raise LaneProjectionError(
                CAPABILITY_DRIFT, f"{name} of the rendered projection differs from the binding"
            )


def network_projection(binding: CursorExecutionBinding) -> NetworkProjection | None:
    """MO-15: the binding's resolved network policy as this Cursor lane projects it. A cloud
    agent's egress is its environment's: written by Mission Control into a synced environment
    (MO-13), generated for the owner, or the owner's own when the environment is bound or
    unspecified (advisory)."""

    if binding.network is None:
        return None
    provider = binding.cloud.provider_environment if binding.cloud is not None else None
    return project_network_policy(
        binding.lane_profile,
        binding.network,
        LaneNetworkContext(
            cursor_sandbox=binding.sandbox_enabled,
            strategy=provider.strategy if provider is not None else None,
        ),
    )


__all__ = [
    "CatalogRows",
    "network_projection",
    "projection_digests",
    "verify_projection",
]
