"""The resolution ports: the lane adapter, its registration and the three registries (ADR-0063).

Frozen by OC-R0 (OVE-195). One package per lane exports a `LANE: LaneRegistration`; bootstrap
composition registers it, one application per `deployments/<app>/application.toml` and one
model per `models.toml` row. Those registries are the only place a variant is named; the
resolver reads them and callers never branch (SELECTION-AND-ROUTING-DESIGN §§2, 4, 6.1).

A `LaneAdapter` is pure: it reads the neutral configuration and its own options block, never
another lane's, and returns an opaque sealed binding with the receipt it signed. The runtime side
stays `AgentHarness` and its optional capability protocols; `isinstance` on one of those is the
sanctioned way to ask what a lane can do.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from mission_control.application.agentic_components.layering import RepoView
from mission_control.application.execution.harness.protocol import AgentHarness
from mission_control.domain.agentic_components.projection import HostProjection
from mission_control.domain.execution.materialization_receipt import MaterializationReceipt
from mission_control.domain.resolution.configuration import AgentConfiguration
from mission_control.domain.resolution.profiles import (
    ApplicationProfile,
    LaneDeclaration,
    ModelProfile,
)
from mission_control.domain.resolution.resolved import SealedLaneBinding


@runtime_checkable
class LaneAdapter(Protocol):
    """Pure compile side of one lane. Raises `LaneCompileRefused` to refuse."""

    @property
    def profile(self) -> str: ...

    def compile(
        self, agent: AgentConfiguration, lane_options: Mapping[str, Any]
    ) -> tuple[SealedLaneBinding, MaterializationReceipt]: ...

    def project(
        self, agent: AgentConfiguration, repo_view: RepoView | None
    ) -> HostProjection | None:
        """`None` for in-process lanes (Deep Agents) and hosted API lanes without files."""
        ...


class LaneRuntimeDependencies(Protocol):
    """What bootstrap composition hands a lane's harness factory (stores, settings, clients).

    Deliberately open here: its concrete members are bootstrap's, and a lane reads only what its
    own factory needs. R1 composes it; the core never constructs one.
    """


HarnessFactory = Callable[[LaneRuntimeDependencies], AgentHarness]


@dataclass(frozen=True, slots=True)
class LaneRegistration:
    """What one lane package exports as `LANE`.

    Conformance (`LaneConformance`, `DescribeOnlyConformance`, `CompileConformance`) is keyed
    by `profile` in `tests/conformance/lanes/`; runtime code never imports tests (recorded R0
    deviation from the sketch). R1 adds the registry test that every registered profile has a
    compile conformance entry.
    """

    profile: str
    declaration: LaneDeclaration
    adapter: LaneAdapter
    harness_factory: HarnessFactory

    def __post_init__(self) -> None:
        if self.declaration.lane_profile != self.profile:
            raise ValueError(
                f"lane {self.profile} registers the declaration of {self.declaration.lane_profile}"
            )
        if self.adapter.profile != self.profile:
            raise ValueError(f"lane {self.profile} registers the adapter of {self.adapter.profile}")


class LaneRegistry(Protocol):
    def register(self, registration: LaneRegistration) -> None:
        """Bootstrap only; a duplicate profile is an error."""
        ...

    def get(self, profile: str) -> LaneRegistration:
        """`KeyError` -> `LANE_UNKNOWN`."""
        ...

    def profiles(self) -> tuple[str, ...]: ...

    def harness(self, profile: str) -> AgentHarness:
        """Today's `LaneRegistry.for_profile` / `lane_for`."""
        ...


class ApplicationRegistry(Protocol):
    def register(self, profile: ApplicationProfile) -> None: ...

    def get(self, application_id: str) -> ApplicationProfile:
        """`KeyError` -> `APPLICATION_UNKNOWN`."""
        ...

    def applications(self) -> tuple[str, ...]: ...


class ModelCatalog(Protocol):
    def register(self, profile: ModelProfile) -> None: ...

    def get(self, profile: str) -> ModelProfile:
        """`KeyError` -> `MODEL_UNKNOWN`."""
        ...

    def profiles(self) -> tuple[str, ...]: ...


__all__ = [
    "ApplicationRegistry",
    "HarnessFactory",
    "LaneAdapter",
    "LaneRegistration",
    "LaneRegistry",
    "LaneRuntimeDependencies",
    "ModelCatalog",
]
