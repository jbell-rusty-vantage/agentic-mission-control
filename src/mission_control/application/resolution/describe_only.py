"""The describe-only compile: a lane's `LaneAdapter` until its full compile exists (OC-R3).

Design D11 and owner decision OC-D199: this sprint touches the lanes other than Deep Agents only
mechanically, so each registers its package with this compile and declared conformance
exceptions; their full compile adapters come in the provider sweep. It is honest about what it
is: it admits the neutral configuration against the lane's declaration and receipts what the
declaration says, nothing more.

- The model's vendor needs a `native` or `emulated` route (`MODEL_ROUTE_UNSUPPORTED`).
- A `required` item whose kind the lane declares `unsupported` refuses at its pointer
  (`ITEM_UNSUPPORTED_ON_LANE`); a non-required one is an `unsupported` row with the reason.
- Every other item is a row with the declared cell; the model is a row with its route.
- The sealed bytes are `mc.describe_only_node_binding.v1`: the configuration digest and the
  receipted verdicts. No runtime reads them; the lane's launch resolver and its projection
  writer still build the binding the lane executes.

Pure: no I/O, no clock, the same input gives the same digest.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from pydantic import BaseModel, ConfigDict

from mission_control.application.agentic_components.layering import RepoView
from mission_control.application.resolution.ports import (
    LaneRegistration,
    LaneRuntimeDependencies,
)
from mission_control.application.resolution.registries import DescribeOnlyLane
from mission_control.domain.agentic_components.projection import HostProjection
from mission_control.domain.execution.materialization_receipt import (
    MaterializationItem,
    MaterializationReceipt,
)
from mission_control.domain.resolution.configuration import AgentConfiguration
from mission_control.domain.resolution.profiles import LaneDeclaration
from mission_control.domain.resolution.resolved import (
    LaneCompileRefused,
    ResolutionRefused,
    SealedLaneBinding,
)

DESCRIBE_ONLY_BINDING_SCHEMA: Final = "mc.describe_only_node_binding.v1"
MODEL_POINTER: Final = "/model/profile"


class DescribeOnlyNodeBinding(BaseModel):
    """What a describe-only compile seals: the admitted configuration and the verdicts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = DESCRIBE_ONLY_BINDING_SCHEMA
    lane_profile: str
    configuration_digest: str
    receipt_digest: str


class DescribeOnlyCompile:
    """`LaneAdapter` over a lane's declaration alone (see the module doc)."""

    def __init__(self, declaration: LaneDeclaration) -> None:
        self._declaration = declaration

    @property
    def profile(self) -> str:
        return self._declaration.lane_profile

    def compile(
        self, agent: AgentConfiguration, lane_options: Mapping[str, Any]
    ) -> tuple[SealedLaneBinding, MaterializationReceipt]:
        profile = self.profile
        route = self._declaration.route(agent.model.vendor)
        if route is None or route.verdict == "unsupported":
            raise LaneCompileRefused(
                ResolutionRefused(
                    code="MODEL_ROUTE_UNSUPPORTED",
                    pointer=MODEL_POINTER,
                    lane_profile=profile,
                    reason=f"lane {profile} has no route for {agent.model.vendor} models",
                    remedy=f"choose a model profile whose vendor {profile} routes",
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
            cell = self._declaration.items[item.kind]
            if cell == "unsupported" and item.required:
                raise LaneCompileRefused(
                    ResolutionRefused(
                        code="ITEM_UNSUPPORTED_ON_LANE",
                        pointer=f"/items/{index}",
                        lane_profile=profile,
                        reason=f"{item.kind} {item.name} is unsupported on {profile}",
                        remedy="drop the requirement or choose a lane that supports the item",
                    )
                )
            rows.append(
                MaterializationItem(
                    kind=item.receipt_kind,
                    name=item.name,
                    verdict=cell,
                    digest=item.digest,
                    reason=(
                        f"{item.kind} is unsupported on {profile}"
                        if cell == "unsupported"
                        else None
                    ),
                )
            )
        receipt = MaterializationReceipt.create(lane_profile=profile, items=rows)
        binding = SealedLaneBinding.seal_contract(
            DescribeOnlyNodeBinding(
                lane_profile=profile,
                configuration_digest=agent.configuration_digest,
                receipt_digest=receipt.receipt_digest,
            ),
            lane_profile=profile,
            schema_id=DESCRIBE_ONLY_BINDING_SCHEMA,
        )
        return binding, receipt

    def project(
        self, agent: AgentConfiguration, repo_view: RepoView | None
    ) -> HostProjection | None:
        """No projection from a neutral configuration yet: the lane's writer renders from the
        catalog rows its launch resolver selects (the provider sweep replaces this)."""

        return None


def describe_only_registration(declaration: LaneDeclaration) -> LaneRegistration:
    """A lane package's `LaneRegistration` with the describe-only compile.

    Its harness factory publishes the declared describe only (a process that compiles or lists
    lanes but runs none); a worker passes the harness it composed to `LaneRegistry.register`.
    """

    def describe_only_harness(_dependencies: LaneRuntimeDependencies) -> DescribeOnlyLane:
        return DescribeOnlyLane(declaration.describe)

    return LaneRegistration(
        profile=declaration.lane_profile,
        declaration=declaration,
        adapter=DescribeOnlyCompile(declaration),
        harness_factory=describe_only_harness,
    )


__all__ = [
    "DESCRIBE_ONLY_BINDING_SCHEMA",
    "DescribeOnlyCompile",
    "DescribeOnlyNodeBinding",
    "describe_only_registration",
]
