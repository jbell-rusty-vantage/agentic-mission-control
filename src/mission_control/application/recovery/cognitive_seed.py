"""Cognitive seeds for forks (P1 turn 4, WP-2; DESIGN P1-S6).

A fork may name a `cognitive_seed`: the point of a settled source unit the derived unit
should continue from. The kernel admits it only when the point exists in the index, is
`seedable`, and the lane that wrote it declares `time_travel.fork` at R3. After the fork
saga admitted the derived run, the seed service asks the lane to restore the point into the
derived unit's own namespace (`seed_fork`: on Deep Agents, a copy of the source thread up to
the point, never a write to the source), sets that namespace's head to the restored point so
the derived unit's first attempt pins to it (`record_attempt` reads the head as its expected
source), and records a `fork_seed` point on the derived run that names the source coordinate
and the restore level. The fork instruction still travels as the derived run's first queued
instruction (`fork_seed.py`), so the derived unit's first packet carries it.

A Goal Directed seed continues the derived run's executor *role thread* from the point (the
iterations before it settle by reference, P5.4); a seed at a verifier point is refused
(Tracing Stage 3, R2-6: the verifier of the fork iteration runs fresh after the seeded
executor, so a seeded verifier thread would be continued by no unit). Stage Graph seeds
continue the invalidated stage's own fresh thread.

Cross-provider control (K2, 2026-11-05): a seed is admitted at every declared
`time_travel.fork` level at or above R1. A Session Lane's `seed_fork` returns no LangGraph
head: there is no namespace to seed, so the service records an `mc.lane_seed_head.v1`
(`LaneSeedHead`: the source coordinate, the restore level and history the lane reached, its
`native_artifacts`, the injected message) in the derived run's `fork_seed` point under
`channel_facts["seed_head"]`; `LaneTurnService` hands it to the lane's `prepare`/`start`
as `seed=` when the derived unit's first generation starts. The receipt's `restore_level`
and `history` are recorded on the point for every lane.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from mission_control.application.execution.cognition_points import CognitionPointRepository
from mission_control.application.execution.harness.describe import declared_matrix
from mission_control.application.execution.harness.time_travel import (
    SEED_HEAD_MESSAGE_COUNT,
    ForkSeedReceipt,
    ForkSeedRequest,
    TimeTravelRegistry,
    TimeTravelUnsupported,
)
from mission_control.application.execution.operations.checkpoint_lineage import (
    CheckpointLineageRepository,
)
from mission_control.domain.execution.checkpoint_lineage import (
    NamespaceClaim,
    cognitive_session_namespace,
    namespace_owner,
    submission_invocation_id,
)
from mission_control.domain.execution.cognition_points import (
    CheckpointPoint,
    CognitionCoordinate,
    CognitionPointFilter,
    CognitionPointRecord,
    location_facts,
    point_id_for,
)
from mission_control.domain.execution.lanes import LaneSeedHead
from mission_control.domain.graph_runtime.identities import (
    QualifiedCheckpointKey,
    RuntimeUnitIdentity,
)
from mission_control.domain.policies.forks import (
    AnyCognitiveSeed,
    CognitiveSeed,
    ForkRejected,
    RunForkReceipt,
    RunForkRequest,
)

DERIVED_GENERATION = 1
# 1.4.4 (P6.1): a seed refused because the saver did not answer, not because it is unsupported.
SAVER_OUTCOMES = frozenset({"saver_unreachable", "saver_not_served", "copy_incomplete"})


class ForkSeedRunner(Protocol):
    """1.4.4 (P6.1): runs the lane's copy somewhere that holds the savers (the maintenance
    worker's `mc.fork_seed.v1`), so the API request thread never walks the remote saver."""

    async def seed_fork(self, request: ForkSeedRequest) -> ForkSeedReceipt: ...


class CognitiveSeedService:
    def __init__(
        self,
        *,
        points: CognitionPointRepository,
        lineage: CheckpointLineageRepository,
        time_travel: TimeTravelRegistry | Callable[[], TimeTravelRegistry | None],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        seed_runner: ForkSeedRunner | None = None,
    ) -> None:
        self._points = points
        self._lineage = lineage
        self._time_travel = time_travel
        self._clock = clock
        # 1.4.4 (P6.1): with a runner the copy runs on a worker activity; the API's own
        # registry (when composed) is then only the describe-level check.
        self._seed_runner = seed_runner

    def _registry(self) -> TimeTravelRegistry | None:
        registry = TimeTravelRegistry.resolve(self._time_travel)
        if registry is None and self._seed_runner is None:
            raise ForkRejected(
                "cognitive_seed_not_supported",
                "time travel is not composed on this API; cognition starts fresh",
            )
        return registry

    async def resolve(
        self, request_scope: str, source_run_id: str, seed: AnyCognitiveSeed
    ) -> CognitionPointRecord:
        """The seedable point the seed names, on a lane that forks at R3; else a typed refusal."""

        record = await self._points.find_point(
            request_scope, source_run_id, kind=seed.kind, locator=seed.locator
        )
        if record is None or record.coordinate.unit_key != seed.unit_key:
            raise ForkRejected(
                "cognitive_seed_not_supported",
                "the cognitive seed names no recorded point of that unit",
                reasons=(seed.unit_key, seed.locator),
            )
        point = record.coordinate.point
        # Tracing Stage 3 (R2-13): the saver locator digest names where the saver lives (it
        # is recorded on the point, and a caller may copy the key with or without it); the
        # checkpoint identity is the rest of the key. A seed given as a point (cross-provider
        # control, 2026-11-05) must equal the recorded point exactly.
        if isinstance(seed, CognitiveSeed):
            if not isinstance(point, CheckpointPoint) or _without_locator(
                point.key
            ) != _without_locator(seed.checkpoint):
                raise ForkRejected(
                    "cognitive_seed_not_supported",
                    "the cognitive seed's checkpoint key differs from the recorded point",
                    reasons=(seed.locator,),
                )
        elif point != seed.point:
            raise ForkRejected(
                "cognitive_seed_not_supported",
                "the cognitive seed's point differs from the recorded point",
                reasons=(seed.locator,),
            )
        if not record.seedable:
            raise ForkRejected(
                "cognitive_seed_not_supported",
                "the point is not seedable (unverified or pending lineage)",
                reasons=(record.point_id,),
            )
        if record.location.family == "goal_directed" and record.location.node_key == "verifier":
            # Tracing Stage 3 (R2-6): the derived run re-runs the fork iteration's executor
            # first (its thread is the one seeded) and its verifier fresh; a verifier point
            # names a thread no derived unit continues from.
            raise ForkRejected(
                "cognitive_seed_not_supported",
                "a Goal Directed seed names an executor point; verifier threads are not seeded",
                reasons=(record.point_id, "verifier"),
            )
        describe = declared_matrix(record.lane_profile)
        if describe.time_travel is None or describe.time_travel.fork == "R0":
            # K2: every declared fork level from R1 up is admitted; the receipt records
            # what the lane actually restored.
            raise ForkRejected(
                "cognitive_seed_not_supported",
                f"lane {record.lane_profile} declares no fork restore level (R1 or above)",
                reasons=(record.lane_profile,),
            )
        registry = self._registry()
        if registry is not None and not registry.supports(record.lane_profile):
            raise ForkRejected(
                "cognitive_seed_not_supported",
                f"lane {record.lane_profile} has no time-travel implementation composed",
            )
        return record

    async def seed(self, request: RunForkRequest, receipt: RunForkReceipt) -> CognitionPointRecord:
        """Restore the seed into the derived unit's namespace and record the `fork_seed` point."""

        seed = request.patch.cognitive_seed
        assert seed is not None
        source = await self.resolve(request.request_scope, request.source_run_id, seed)
        decision = next(
            (item for item in request.reuse_decisions if item.source_unit_key == seed.unit_key),
            None,
        )
        if decision is None or decision.decision != "invalidated":
            raise ForkRejected(
                "cognitive_seed_not_supported",
                "the seed's unit is not re-run by the derived run",
                reasons=(seed.unit_key, decision.decision if decision else "absent"),
            )
        derived_unit = decision.derived_unit
        recorded = await self._recorded_seed(
            request.request_scope, receipt.target_run_id, derived_unit
        )
        if recorded is not None:
            # K2: a seed re-run after a crash between the lane's copy and the receipt (or on
            # another process) replays the recorded `fork_seed` point; the lane's own copy is
            # idempotent too, but nothing needs to reach it again.
            return recorded
        derived_namespace = cognitive_session_namespace(derived_unit, DERIVED_GENERATION)
        owner_kind, owner_digest = namespace_owner(derived_unit, DERIVED_GENERATION)
        # 1.4.4 (P5.3): the injected message becomes the seed head's last human message.
        message = request.message_text if request.message_delivery == "seed_head" else None
        seed_request = ForkSeedRequest(
            source=source,
            derived_run_id=receipt.target_run_id,
            derived_unit_key=derived_unit.unit_key,
            derived_namespace=derived_namespace,
            derived_invocation_id=submission_invocation_id(
                derived_unit.unit_key, DERIVED_GENERATION
            ),
            fork_request_id=receipt.request_id,
            message=message,
            request_scope=request.request_scope,
        )
        try:
            if self._seed_runner is not None:
                # 1.4.4 (P6.1): the copy runs on the maintenance worker's activity.
                restored = await self._seed_runner.seed_fork(seed_request)
            else:
                registry = self._registry()
                assert registry is not None
                restored = await registry.lane(
                    source.lane_profile, request_scope=request.request_scope
                ).seed_fork(seed_request)
        except TimeTravelUnsupported as error:
            if error.reason in SAVER_OUTCOMES:
                # 1.4.4 (P6.1): the saver did not answer (or serves another location); the
                # fork is refused before the derived run is launched, and may be retried.
                raise ForkRejected(
                    "cognitive_seed_unavailable",
                    f"the seed's saver is unavailable: {error.reason}",
                    reasons=(error.reason, error.saver or ""),
                ) from error
            raise ForkRejected(
                "cognitive_seed_not_supported", f"the lane could not seed: {error.reason}"
            ) from error
        head = restored.derived.point
        now = self._clock()
        seed_head: LaneSeedHead | None = None
        if isinstance(head, CheckpointPoint):
            # 1.4.4 (P6.2): the lineage head names the checkpoint only; the saver's locator
            # digest lives on the point record (lineage keys are compared by value against
            # the adapter's own keys, which never carry a locator).
            await self._lineage.seed_namespace_head(
                request.request_scope,
                NamespaceClaim(
                    namespace=derived_namespace,
                    owner_kind=owner_kind,
                    owner_digest=owner_digest,
                    binding_digest=restored.native_artifacts["binding_digest"],
                    state_schema_digest=restored.native_artifacts["state_schema_digest"],
                ),
                head.key.model_copy(update={"saver_locator_digest": None}),
                observed_at=now,
            )
        else:
            # K2: a Session Lane has no namespace head; the derived unit's first session
            # continues from the lane's seed head, handed to `prepare`/`start` by the turn
            # service from this point's `channel_facts.seed_head`.
            seed_head = LaneSeedHead(
                source_run_id=source.coordinate.run_id,
                source_unit_key=source.coordinate.unit_key,
                source_execution_generation=source.coordinate.execution_generation,
                point_kind=source.coordinate.kind,
                point_locator=source.coordinate.locator,
                point=source.coordinate.point.model_dump(mode="json"),
                restore_level=restored.restore_level,
                history="native" if restored.history == "native" else "reconstructed",
                native_artifacts=dict(restored.native_artifacts),
                message=message,
                fork_request_id=receipt.request_id,
            )
        record = CognitionPointRecord(
            point_id=point_id_for(
                receipt.target_run_id,
                derived_unit.unit_key,
                DERIVED_GENERATION,
                head.kind,
                head.locator,
            ),
            coordinate=CognitionCoordinate(
                run_id=receipt.target_run_id,
                unit_key=derived_unit.unit_key,
                execution_generation=DERIVED_GENERATION,
                point=head,
            ),
            lane_profile=source.lane_profile,
            location=location_facts(derived_unit),
            parent_coordinate=source.coordinate,
            ordinal=source.ordinal,
            source="fork",
            roles=("fork_seed",),
            message_count=_head_message_count(restored, source, message),
            channel_facts={
                **dict(source.channel_facts),
                **(
                    {"fork_message": {"delivery": "seed_head", "bytes": len(message.encode())}}
                    if message is not None
                    else {}
                ),
                **({"seed_head": seed_head.model_dump(mode="json")} if seed_head else {}),
            },
            files_digest=source.files_digest,
            seedable=True,
            written_by="fork_seed",
            recorded_at=now,
            restore_level=restored.restore_level,
            history="native" if restored.history == "native" else "reconstructed",
        )
        (stored,) = await self._points.record(
            request.request_scope, [record], frame_keys={}, turn_refs={}
        )
        return stored

    async def _recorded_seed(
        self, request_scope: str, derived_run_id: str, derived_unit: RuntimeUnitIdentity
    ) -> CognitionPointRecord | None:
        page = await self._points.list_points(
            request_scope,
            derived_run_id,
            selection=CognitionPointFilter(
                unit_key=derived_unit.unit_key,
                execution_generation=DERIVED_GENERATION,
                role="fork_seed",
            ),
            limit=5,
            cursor=None,
        )
        return page.entries[0] if page.entries else None


def _without_locator(key: QualifiedCheckpointKey) -> QualifiedCheckpointKey:
    return key.model_copy(update={"saver_locator_digest": None})


def _head_message_count(
    restored: ForkSeedReceipt, source: CognitionPointRecord, message: str | None
) -> int | None:
    """Tracing Stage 3 (R2-1): the message count the lane read at the seed head; without a
    message the head is the source point itself; a lane that does not report the count of
    an injected head leaves it unknown rather than guessed."""

    if message is None:
        return source.message_count
    reported = restored.native_artifacts.get(SEED_HEAD_MESSAGE_COUNT)
    return int(reported) if reported is not None and reported.isdigit() else None


__all__ = ["DERIVED_GENERATION", "CognitiveSeedService", "ForkSeedRunner"]
