"""The time-travel lane port: `read_as_of`, `seed_fork` and `collect_points` over
`mc.cognition_coordinate.v1`.

DESIGN P1-S4: the kernel owns the coordinate, the index and these behaviours; the lane owns
their native semantics. A lane implements `TimeTravelLane` for the point kinds it writes and
declares the levels it reaches in its describe (`time_travel: {read, fork}`).
`collect_points` (1.4.4, TR-D6) re-derives the points of one settled unit generation from
the lane's native lineage so the reconciler can repair an index a crash left short.
`TimeTravelRegistry` is the one router from a lane profile to its implementation; nothing
else switches on the lane for a time-travel read, seed or re-derivation.

Cross-provider control (K3, 2026-11-05). Every composed lane registers its `TimeTravelLane`
(`TimeTravelRegistry.register_all` takes what each lane package's composition returns). A
Session Lane's reads and seeds are over its persisted frames and snapshots, which are tenant
scoped rows: such a lane implements `ScopedTimeTravelLane` and the registry binds it to the
caller's request scope on `lane(profile, request_scope=...)`. The Deep Agents lane reads a
saver by qualified key and needs no scope. `collect_points` of a session lane takes
`namespace=<harness execution id>` and `checkpointer_ref_digest=<generation>` (see the
port's docstring).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from mission_control.domain.execution.cognition_points import (
    CognitionCoordinate,
    CognitionPointObservation,
    CognitionPointRecord,
    StateAsOf,
)
from mission_control.domain.execution.lanes import RestoreLevel

# Tracing Stage 3 (R2-1): the `ForkSeedReceipt.native_artifacts` entry in which a lane
# reports the message count of the seed head it created (the `fork_seed` point records it).
SEED_HEAD_MESSAGE_COUNT = "seed_head_message_count"


class TimeTravelUnsupported(LookupError):
    """No lane implements time travel for this profile (or this point kind)."""

    def __init__(
        self,
        lane_profile: str,
        reason: str = "time_travel_unsupported",
        *,
        saver: str | None = None,
    ) -> None:
        super().__init__(f"{reason} on lane profile {lane_profile}")
        self.lane_profile = lane_profile
        self.reason = reason
        # 1.4.4 (P6.1): the checkpointer the outcome is about (`saver_unreachable`,
        # `saver_not_served`), for the typed 503 and the fork refusal.
        self.saver = saver


class ForkSeedRequest(BaseModel):
    """Seed a derived unit's native state from a source point (P1-S6)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: CognitionPointRecord
    derived_run_id: str = Field(min_length=1, max_length=512)
    derived_unit_key: str = Field(min_length=1, max_length=512)
    derived_namespace: str = Field(min_length=1, max_length=1024)
    derived_invocation_id: str = Field(min_length=1, max_length=256)
    # Known at launch, not at fork time; the lane reads them from the point when absent.
    binding_digest: str | None = None
    state_schema_digest: str | None = None
    fork_request_id: str = Field(min_length=1, max_length=512)
    # The fork patch applied at the point: an added human message and extra files.
    message: str | None = Field(default=None, max_length=65_536)
    files: dict[str, str] = Field(default_factory=dict)
    # K3 (2026-11-05): the caller's request scope, for a session lane whose seed reads its
    # frames and snapshots (scoped rows); the Deep Agents saver copy ignores it.
    request_scope: str | None = Field(default=None, min_length=1, max_length=512)


class ForkSeedReceipt(BaseModel):
    """What the lane created: the derived point the first attempt pins to, and how far it
    restored."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    restore_level: RestoreLevel
    history: str = Field(default="native", pattern=r"^(native|reconstructed)$")
    derived: CognitionCoordinate
    copied_checkpoints: int = Field(ge=0)
    native_artifacts: dict[str, str] = Field(default_factory=dict)


@runtime_checkable
class TimeTravelLane(Protocol):
    """A lane's exact reads and seeds over the points it writes."""

    @property
    def lane_profile(self) -> str: ...

    async def read_as_of(self, record: CognitionPointRecord) -> StateAsOf: ...

    async def seed_fork(self, request: ForkSeedRequest) -> ForkSeedReceipt: ...

    async def collect_points(
        self,
        *,
        namespace: str,
        checkpointer_ref_digest: str,
        source_locator: str | None,
        result_locator: str,
    ) -> tuple[CognitionPointObservation, ...]:
        """Re-derive one settled generation's points from the lane's native lineage: the
        points from `result_locator` back to (excluding) `source_locator` in `namespace`,
        oldest first, exactly as the settlement would have observed them. Raises the lane's
        lineage error (`CheckpointLineageInDoubt`) or `TimeTravelUnsupported` when the
        native state cannot be read.

        Deep Agents: `namespace` is the LangGraph thread, `checkpointer_ref_digest` the
        saver's digest and the locators checkpoint ids.

        Session lanes (K3 convention, 2026-11-05): `namespace` is the harness execution id
        (the UUID string) and `checkpointer_ref_digest` the execution generation as a decimal
        string (`str(generation)`); `source_locator` is the previous generation's result
        locator (or None) and `result_locator` the settled result point's locator. The lane
        reads the generation's persisted frames (bound to the caller's request scope through
        `ScopedTimeTravelLane`) and folds them with the same `fold_generation_points` the
        settlement used, so the re-derived rows have the settlement's ids."""
        ...


@runtime_checkable
class ScopedTimeTravelLane(Protocol):
    """A lane whose reads and seeds need the caller's request scope (frames and snapshots are
    tenant-scoped rows): `for_scope` returns the same lane bound to that scope."""

    def for_scope(self, request_scope: str) -> TimeTravelLane: ...


class ScopedLaneFactory:
    """K3: a `ScopedTimeTravelLane` over a factory that builds the lane for one request
    scope (a hosted lane composed with a scope-bound frame reader). The unbound object
    answers `lane_profile` and refuses reads and seeds with `request_scope_unbound`; the
    registry binds it per call (`lane(profile, request_scope=...)`)."""

    def __init__(self, lane_profile: str, factory: Callable[[str], TimeTravelLane]) -> None:
        self._profile = lane_profile
        self._factory = factory

    @property
    def lane_profile(self) -> str:
        return self._profile

    def for_scope(self, request_scope: str) -> TimeTravelLane:
        return self._factory(request_scope)

    async def read_as_of(self, record: CognitionPointRecord) -> StateAsOf:
        raise TimeTravelUnsupported(self._profile, reason="request_scope_unbound")

    async def seed_fork(self, request: ForkSeedRequest) -> ForkSeedReceipt:
        if request.request_scope is not None:
            return await self._factory(request.request_scope).seed_fork(request)
        raise TimeTravelUnsupported(self._profile, reason="request_scope_unbound")

    async def collect_points(
        self,
        *,
        namespace: str,
        checkpointer_ref_digest: str,
        source_locator: str | None,
        result_locator: str,
    ) -> tuple[CognitionPointObservation, ...]:
        raise TimeTravelUnsupported(self._profile, reason="request_scope_unbound")


def scoped_lane(lane_profile: str, factory: Callable[[str], TimeTravelLane]) -> TimeTravelLane:
    """The registry entry for a lane composed per request scope."""

    return ScopedLaneFactory(lane_profile, factory)


class TimeTravelRegistry:
    """Lane profile → `TimeTravelLane` (the one router; PROCESS §2.2 rule 2)."""

    def __init__(self, lanes: Mapping[str, TimeTravelLane] | None = None) -> None:
        self._lanes: dict[str, TimeTravelLane] = dict(lanes or {})

    def register(self, lane: TimeTravelLane) -> None:
        self._lanes[lane.lane_profile] = lane

    def register_all(self, lanes: Iterable[TimeTravelLane | None]) -> TimeTravelRegistry:
        """K3: register what each lane package's composition returned (None entries are
        lanes that process did not compose); returns the registry for chaining."""

        for lane in lanes:
            if lane is not None:
                self.register(lane)
        return self

    def lane(self, lane_profile: str, *, request_scope: str | None = None) -> TimeTravelLane:
        """The lane's implementation; a `ScopedTimeTravelLane` is bound to `request_scope`
        when the caller gives one (a read service, the seed service, the reconciler)."""

        try:
            lane = self._lanes[lane_profile]
        except KeyError:
            raise TimeTravelUnsupported(lane_profile) from None
        if request_scope is not None and isinstance(lane, ScopedTimeTravelLane):
            return lane.for_scope(request_scope)
        return lane

    def supports(self, lane_profile: str) -> bool:
        return lane_profile in self._lanes

    @staticmethod
    def resolve(
        source: TimeTravelRegistry | Callable[[], TimeTravelRegistry | None] | None,
    ) -> TimeTravelRegistry | None:
        """Tracing Stage 3: the registry a composition handed over, given directly or as a
        late-bound factory (the worker composes time travel after its consumers)."""

        if source is None or isinstance(source, TimeTravelRegistry):
            return source
        return source()

    @property
    def lane_profiles(self) -> tuple[str, ...]:
        return tuple(sorted(self._lanes))


__all__ = [
    "SEED_HEAD_MESSAGE_COUNT",
    "ForkSeedReceipt",
    "ForkSeedRequest",
    "ScopedTimeTravelLane",
    "TimeTravelLane",
    "TimeTravelRegistry",
    "TimeTravelUnsupported",
]
