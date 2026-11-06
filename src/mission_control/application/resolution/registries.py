"""The three registries of the resolution seam (ADR-0063) and lane dispatch (SPEC-07 section 3).

`LaneRegistry` maps a Lane Profile to its harness and, for a lane that registers its package's
`LaneRegistration`, to its declaration and pure compile adapter. It is built once per process:
the worker composition registers the executable lanes (`deep_agents` always; Cursor profiles
when a Cursor credential is bound), the API registers describe-only entries for `lane list` and
`lane describe`. `describe` results are cached because they are pure. `ApplicationRegistry`
holds one Application Profile per installed application and `ModelCatalog` one Model Profile
per row; bootstrap composition is the only place any of the three is populated.

Admission: a profile whose describe is not `qualified` is refused unless the application's
policy allows unqualified lanes for local proof (`allow_unqualified`).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import cast

from mission_control.application.execution.harness.protocol import (
    AgentHarness,
    OperationLane,
    UnsupportedHarnessOperations,
)
from mission_control.application.resolution.ports import LaneRegistration
from mission_control.domain.execution.contracts import (
    OperationExecutionBinding,
    OperationExecutionRequest,
)
from mission_control.domain.execution.lanes import (
    DEFAULT_LANE_PROFILE,
    LANE_OF_PROFILE,
    RUNTIMES_OF_LANE,
    LaneDescribe,
)
from mission_control.domain.resolution.profiles import (
    ApplicationProfile,
    ModelProfile,
    below_annex_minimums,
)

# The application policy that admits unqualified lanes for a local proof (Settings field
# `mission_control_allow_unqualified_lanes`).
UNQUALIFIED_LANES_FLAG = "MISSION_CONTROL_ALLOW_UNQUALIFIED_LANES"


class UnknownLaneProfile(LookupError):
    """No harness is registered for the requested lane profile."""

    def __init__(self, lane_profile: str, registered: Iterable[str]) -> None:
        super().__init__(
            f"lane profile {lane_profile!r} is not registered (registered: {sorted(registered)})"
        )
        self.lane_profile = lane_profile


class LaneNotQualified(PermissionError):
    """The lane profile is registered but not qualified, and policy forbids unqualified use."""

    def __init__(self, lane_profile: str) -> None:
        super().__init__(
            f"lane profile {lane_profile!r} is not qualified; admission requires a recorded "
            "qualification (docs/qualification/lanes/README.md, "
            f"`make lane-qualify PROFILE={lane_profile} LIVE=1`) or, for a local proof, "
            f"{UNQUALIFIED_LANES_FLAG}=true on the worker that runs the lane"
        )
        self.lane_profile = lane_profile


class LaneNotExecutable(TypeError):
    """The registered entry describes a lane but cannot execute operations in this process."""


class LaneRegistry:
    def __init__(
        self, harnesses: Iterable[AgentHarness] = (), *, allow_unqualified: bool = False
    ) -> None:
        self._harnesses: dict[str, AgentHarness] = {}
        self._describes: dict[str, LaneDescribe] = {}
        self._registrations: dict[str, LaneRegistration] = {}
        self._allow_unqualified = allow_unqualified
        for harness in harnesses:
            self.register_harness(harness)

    def register(self, registration: LaneRegistration, harness: AgentHarness | None = None) -> None:
        """Register a lane package's `LANE`, with the harness bootstrap composed for it.

        Without `harness`, the registration's factory builds it (a lane whose harness needs no
        composed dependencies). The harness must describe the declared profile exactly.
        """

        runtime = harness if harness is not None else registration.harness_factory(_NO_DEPENDENCIES)
        if runtime.describe() != registration.declaration.describe:
            raise ValueError(
                f"lane {registration.profile}: the harness describe differs from the declaration"
            )
        self.register_harness(runtime)
        self._registrations[registration.profile] = registration

    def register_harness(self, harness: AgentHarness) -> None:
        """A runtime-only entry: a describe-only API process, or a harness without a package
        registration yet. Resolution refuses its profile as `LANE_UNKNOWN`."""

        describe = harness.describe()
        profile = describe.lane_profile
        if profile in self._harnesses:
            raise ValueError(f"lane profile {profile} is already registered")
        self._harnesses[profile] = harness
        self._describes[profile] = describe

    def get(self, profile: str) -> LaneRegistration:
        """The lane's package registration; `KeyError` when it has none (`LANE_UNKNOWN`)."""

        return self._registrations[profile]

    def harness(self, profile: str) -> AgentHarness:
        return self.for_profile(profile)

    @property
    def allow_unqualified(self) -> bool:
        return self._allow_unqualified

    def profiles(self) -> tuple[str, ...]:
        return tuple(sorted(self._harnesses))

    def for_profile(self, lane_profile: str) -> AgentHarness:
        try:
            return self._harnesses[lane_profile]
        except KeyError:
            raise UnknownLaneProfile(lane_profile, self._harnesses) from None

    def describe(self, lane_profile: str) -> LaneDescribe:
        """The package registration's declared describe, else the runtime-only harness's."""

        self.for_profile(lane_profile)
        registration = self._registrations.get(lane_profile)
        if registration is not None:
            return registration.declaration.describe
        return self._describes[lane_profile]

    def describe_all(self) -> tuple[LaneDescribe, ...]:
        return tuple(self._describes[profile] for profile in self.profiles())

    def admit(self, lane_profile: str) -> AgentHarness:
        """The harness for `lane_profile`, refusing an unqualified one unless policy allows."""

        harness = self.for_profile(lane_profile)
        if not self._describes[lane_profile].qualified and not self._allow_unqualified:
            raise LaneNotQualified(lane_profile)
        return harness

    def lane_for(
        self, request: OperationExecutionRequest | OperationExecutionBinding
    ) -> OperationLane:
        """Dispatch by `lane_profile` after the registry's pairing check (OC-R2): the profile's
        describe (its package declaration, else its runtime-only harness's, until R3 registers
        every lane) must serve the request's `execution_runtime`."""

        profile = lane_profile_for(request)
        if not serves_runtime(self.describe(profile), request.execution_runtime):
            raise ValueError(
                f"lane profile {profile} does not serve a {request.execution_runtime} runtime"
            )
        harness = self.admit(profile)
        if not callable(getattr(harness, "execute", None)) or not callable(
            getattr(harness, "requires_checkpoint_lineage", None)
        ):
            raise LaneNotExecutable(f"lane profile {profile} cannot execute in this process")
        return cast(OperationLane, harness)

    def as_mapping(self) -> Mapping[str, LaneDescribe]:
        return dict(self._describes)


def serves_runtime(describe: LaneDescribe, runtime: str) -> bool:
    """Whether a lane's describe serves an execution runtime (the pairing rule, OC-R2)."""

    return runtime in RUNTIMES_OF_LANE[describe.lane]


def lane_profile_for(request: OperationExecutionRequest | OperationExecutionBinding) -> str:
    """The profile an attempt names (absent: its sealed binding's, else `deep_agents`), checked
    against the profile vocabulary's lane before any registry is consulted."""

    profile = request.lane_profile or (
        request.lane_binding.lane_profile
        if request.lane_binding is not None
        else DEFAULT_LANE_PROFILE
    )
    runtime = request.execution_runtime
    lane = LANE_OF_PROFILE.get(profile)
    if lane is None:
        raise UnknownLaneProfile(profile, LANE_OF_PROFILE)
    if runtime not in RUNTIMES_OF_LANE[lane]:
        raise ValueError(f"lane profile {profile} does not serve a {runtime} runtime")
    return profile


class DescribeOnlyLane(UnsupportedHarnessOperations):
    """A registry entry that publishes a lane's describe in a process that cannot run it
    (the public API lists and describes lanes; workers execute them)."""

    def __init__(self, describe: LaneDescribe) -> None:
        self._describe = describe

    def describe(self) -> LaneDescribe:
        return self._describe


def describe_only_lanes(
    *,
    published: Iterable[LaneDescribe],
    registrations: Iterable[LaneRegistration] = (),
    allow_unqualified: bool,
) -> LaneRegistry:
    """The registry of a process that lists lanes but runs none (the public API).

    The caller (bootstrap, `bootstrap/lanes.describe_only_registry`) has already chosen the
    lanes this installation binds: each registration is published with its declared describe
    (OC-R6: the `model_routes` the model listing reads), and each `published` describe whose
    profile has no registration as a runtime-only entry. Nothing here names a lane.
    """

    packaged = {registration.profile: registration for registration in registrations}
    registry = LaneRegistry(
        [
            DescribeOnlyLane(describe)
            for describe in published
            if describe.lane_profile not in packaged
        ],
        allow_unqualified=allow_unqualified,
    )
    for registration in packaged.values():
        registry.register(registration, DescribeOnlyLane(registration.declaration.describe))
    return registry


class _NoDependencies:
    """What a factory receives when bootstrap composed nothing for it."""


_NO_DEPENDENCIES = _NoDependencies()


class ApplicationRegistry:
    """One Application Profile per installed application (`deployments/<app>/application.toml`).

    Registration refuses a profile that weakens the output minimums (an interpretation of annex
    section 5 using KS use classes, `below_annex_minimums`): an
    application may tighten them, never drop a required review or sign-off class.
    """

    def __init__(self, profiles: Iterable[ApplicationProfile] = ()) -> None:
        self._profiles: dict[str, ApplicationProfile] = {}
        for profile in profiles:
            self.register(profile)

    def register(self, profile: ApplicationProfile) -> None:
        if profile.application_id in self._profiles:
            raise ValueError(f"application {profile.application_id} is already registered")
        problems = below_annex_minimums(profile)
        if problems:
            raise ValueError(
                f"application {profile.application_id} weakens the output minimums: "
                + "; ".join(problems)
            )
        self._profiles[profile.application_id] = profile

    def get(self, application_id: str) -> ApplicationProfile:
        return self._profiles[application_id]

    def applications(self) -> tuple[str, ...]:
        return tuple(sorted(self._profiles))


class ModelCatalog:
    """One Model Profile per `models.toml` row; it names no lane (design §3)."""

    def __init__(self, profiles: Iterable[ModelProfile] = ()) -> None:
        self._profiles: dict[str, ModelProfile] = {}
        for profile in profiles:
            self.register(profile)

    def register(self, profile: ModelProfile) -> None:
        if profile.profile in self._profiles:
            raise ValueError(f"model profile {profile.profile} is already registered")
        self._profiles[profile.profile] = profile

    def get(self, profile: str) -> ModelProfile:
        return self._profiles[profile]

    def profiles(self) -> tuple[str, ...]:
        return tuple(sorted(self._profiles))


__all__ = [
    "UNQUALIFIED_LANES_FLAG",
    "ApplicationRegistry",
    "DescribeOnlyLane",
    "LaneNotExecutable",
    "LaneNotQualified",
    "LaneRegistry",
    "ModelCatalog",
    "UnknownLaneProfile",
    "describe_only_lanes",
    "lane_profile_for",
    "serves_runtime",
]
