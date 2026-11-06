"""A stub lane that passes the compile suite: the R0 proof that the frozen shapes are usable.

It is not a lane. It borrows the declared `deep_agents` describe (a `LaneDeclaration` needs a
real describe) and the Deep Agents item cells of design D10 (kits unsupported, middleware
native), and seals the configuration as canonical JSON. R1 replaces it in the registry with the
real Deep Agents compile adapter.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Final

from mission_control.application.agentic_components.layering import RepoView
from mission_control.application.execution.harness.describe import declared_matrix
from mission_control.domain.agentic_components.projection import HostProjection
from mission_control.domain.execution.materialization_receipt import (
    MaterializationItem,
    MaterializationReceipt,
)
from mission_control.domain.resolution.configuration import AgentConfiguration
from mission_control.domain.resolution.profiles import ItemSupport, LaneDeclaration, ModelRoute
from mission_control.domain.resolution.resolved import (
    LaneCompileRefused,
    ResolutionRefused,
    SealedLaneBinding,
)
from tests.conformance.lanes.compile.contract import CompileCheck
from tests.conformance.lanes.contract import DeclaredException

STUB_PROFILE: Final = "deep_agents"
STUB_SCHEMA: Final = "mc.stub_lane_binding.v1"

STUB_DECLARATION: Final = LaneDeclaration(
    describe=declared_matrix(STUB_PROFILE),
    model_routes=(
        ModelRoute(vendor="anthropic", verdict="native", mechanism="stub_factory"),
        ModelRoute(vendor="openai", verdict="native", mechanism="stub_factory"),
    ),
    items={
        "skill_bundle": "native",
        "mcp_server": "native",
        "tool": "native",
        "hook_script": "emulated",
        "subagent_profile": "native",
        "environment_kit": "unsupported",
        "context_bundle": "native",
        "middleware": "native",
        "sandbox_profile": "native",
    },
    families={
        "StageGraph": "native",
        "GoalDirected": "native",
        "ParallelSwarm": "unqualified",
        "EvaluatorOptimizer": "unqualified",
    },
)


NARROW_PROFILE: Final = "claude_agent_sdk"

# A second stub with an unsupported vendor, a degraded cell and two unsupported kinds, so every
# branch of the suite runs before a real lane reaches it.
NARROW_DECLARATION: Final = LaneDeclaration(
    describe=declared_matrix(NARROW_PROFILE),
    model_routes=(
        ModelRoute(vendor="anthropic", verdict="native", mechanism="stub_cli"),
        ModelRoute(vendor="openai", verdict="unsupported", mechanism="none"),
    ),
    items={
        **STUB_DECLARATION.items,
        "hook_script": "native",
        "middleware": "unsupported",
        "environment_kit": "native",
        "subagent_profile": "unsupported",
    },
    families={
        **STUB_DECLARATION.families,
        "GoalDirected": "unqualified",
        "EvaluatorOptimizer": "unsupported",
    },
)
# The option keys a stub accepts; any other key is LANE_OPTIONS_INVALID.
STUB_OPTION_KEYS: Final = frozenset({"strict"})


class StubLaneAdapter:
    def __init__(
        self,
        declaration: LaneDeclaration = STUB_DECLARATION,
        *,
        degrade: frozenset[str] = frozenset(),
        served_pins: frozenset[str] | None = None,
    ) -> None:
        self._declaration = declaration
        # Item kinds this stub materializes with a documented loss.
        self._degrade = degrade
        # The pins this stub's deployment can materialize; `None` serves every pin.
        self._served_pins = served_pins

    @property
    def profile(self) -> str:
        return self._declaration.lane_profile

    def compile(
        self, agent: AgentConfiguration, lane_options: Mapping[str, Any]
    ) -> tuple[SealedLaneBinding, MaterializationReceipt]:
        for key in sorted(set(lane_options) - STUB_OPTION_KEYS):
            raise LaneCompileRefused(
                ResolutionRefused(
                    code="LANE_OPTIONS_INVALID",
                    pointer=f"/provider_options/{self.profile}/{key}",
                    lane_profile=self.profile,
                    reason=f"option {key} is not a {self.profile} option",
                    remedy=f"use only {sorted(STUB_OPTION_KEYS)}",
                )
            )
        route = self._declaration.route(agent.model.vendor)
        if route is None or route.verdict == "unsupported":
            raise LaneCompileRefused(
                ResolutionRefused(
                    code="MODEL_ROUTE_UNSUPPORTED",
                    pointer="/model/profile",
                    lane_profile=self.profile,
                    reason=f"no route for vendor {agent.model.vendor}",
                    remedy="choose a model profile whose vendor this lane routes",
                )
            )
        rows = [
            MaterializationItem(
                kind="model",
                name=agent.model.profile,
                verdict=route.verdict,
                native_locator=route.mechanism,
            )
        ]
        for index, item in enumerate(agent.items):
            if self._served_pins is not None and item.pin not in self._served_pins:
                raise LaneCompileRefused(
                    ResolutionRefused(
                        code="ITEM_PIN_UNSERVED",
                        pointer=f"/items/{index}",
                        lane_profile=self.profile,
                        reason=f"no deployment component serves {item.pin}",
                        remedy="pin a version this deployment serves, or register the component",
                    )
                )
            cell: ItemSupport = self._declaration.items[item.kind]
            if cell == "unsupported" and item.required:
                raise LaneCompileRefused(
                    ResolutionRefused(
                        code="ITEM_UNSUPPORTED_ON_LANE",
                        pointer=f"/items/{index}",
                        lane_profile=self.profile,
                        reason=f"{item.kind} {item.name} is unsupported on {self.profile}",
                        remedy="drop the requirement or choose a lane that supports the item",
                    )
                )
            degraded = cell != "unsupported" and item.kind in self._degrade
            reason = None
            if cell == "unsupported":
                reason = f"{item.kind} is unsupported on this lane"
            elif degraded:
                reason = f"{item.kind} loses its event filter on this stub"
            rows.append(
                MaterializationItem(
                    kind=item.receipt_kind,
                    name=item.name,
                    verdict="degraded" if degraded else cell,
                    digest=item.digest,
                    reason=reason,
                )
            )
        payload = json.dumps(
            {"agent": agent.model_dump(mode="json"), "options": dict(lane_options)},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        binding = SealedLaneBinding.seal(
            lane_profile=self.profile, schema_id=STUB_SCHEMA, payload=payload
        )
        return binding, MaterializationReceipt.create(lane_profile=self.profile, items=rows)

    def project(
        self, agent: AgentConfiguration, repo_view: RepoView | None
    ) -> HostProjection | None:
        return None


class StubCompileConformance:
    @property
    def profile(self) -> str:
        return STUB_PROFILE

    def adapter(self) -> StubLaneAdapter:
        return StubLaneAdapter()

    def declaration(self) -> LaneDeclaration:
        return STUB_DECLARATION

    def options(self) -> Mapping[str, Any]:
        return {}

    @property
    def exceptions(self) -> Mapping[CompileCheck, DeclaredException]:
        return {}


class NarrowStubCompileConformance:
    @property
    def profile(self) -> str:
        return NARROW_PROFILE

    def adapter(self) -> StubLaneAdapter:
        return StubLaneAdapter(NARROW_DECLARATION, degrade=frozenset({"hook_script"}))

    def declaration(self) -> LaneDeclaration:
        return NARROW_DECLARATION

    def options(self) -> Mapping[str, Any]:
        return {}

    @property
    def exceptions(self) -> Mapping[CompileCheck, DeclaredException]:
        return {}


__all__ = [
    "NARROW_DECLARATION",
    "STUB_DECLARATION",
    "NarrowStubCompileConformance",
    "StubCompileConformance",
    "StubLaneAdapter",
]
