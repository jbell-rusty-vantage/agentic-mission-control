"""Carry a reused unit's accepted named outputs into the fork-derived run (F1-G4, EXEC-012).

A fork-derived unit inside the reuse frontier settles by the immutable source result
(``OperationExecutionService._settle_reused``). Under output contracts (release 1.7.0) the
source's outputs are obligation revisions and accepted heads of the *source* run, never
``output_refs``, so without this act the derived run holds no accepted revision for the reused
stage's promises: its consumers are never released and the family concludes ``failed``.

``ForkOutputCarry.carry`` runs once per reused unit, before its settlement:

1. it opens one host invocation of the derived unit (same operation, attempt and generation as
   the unit, origin lane ``fork_reuse``) and pins the derived run's promise revisions;
2. for every promise the reused stage owns in the derived run, it adopts the source run's
   exact *accepted* revisions through the one adoption act (``OutputAdoptionService``: the
   source must be accepted with exactly that digest; the target contract's checks apply; an
   ``adopter`` lineage fact on the source names ``fork_reuse:<fork request id>``);
3. it finalizes that invocation without the assessment handoff, and promotes each adopted
   revision directly to the derived run's accepted head. The source's acceptance stands: the
   carried bytes are the accepted bytes, so they are never judged again (REQ-CP-EXEC-012).

Idempotent: the adoption key binds the exact sources, the finalization is one row per
invocation and a head that already names the revision is left alone, so an Activity retry
returns the same revisions. Only Stage Graph units carry (a Goal Loop's promises are owned by
its root and promoted per accepted iteration; reusing one iteration does not decide them).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from mission_control.application.knowledge.access import InvocationAccess, InvocationIdentity
from mission_control.application.outputs.adoption import AdoptionSource, OutputAdoptionService
from mission_control.application.outputs.fulfillment import (
    HostAccess,
    OutputFulfillmentService,
    PromoteOutput,
)
from mission_control.application.ports.outputs import OutputContractStore
from mission_control.domain.execution.contracts import OperationExecutionBinding, ReusedResultRef
from mission_control.domain.graph_runtime.identities import StageGraphUnitLocation
from mission_control.domain.policies.forks import ForkOutputsNotCarried

FORK_REUSE_LANE = "fork_reuse"
FORK_REUSE_ACTOR = "mission-control:fork-reuse"
FORK_REUSE_ORIGIN = "mc-host:fork-reuse"


class CarryInvocations(Protocol):
    """The part of the knowledge toolset the carry uses (``KnowledgeToolset``)."""

    async def begin(self, live: Any) -> Any: ...

    def access(self, live: Any) -> InvocationAccess: ...


class CarryFinalization(Protocol):
    async def finalize(
        self,
        invocation: InvocationIdentity,
        access: InvocationAccess | None = None,
        *,
        unresolved_effects: tuple[str, ...] = (),
        attempt_failed: bool = False,
        owes_nothing: bool = False,
    ) -> Any: ...


@dataclass(frozen=True)
class CarriedOutputs:
    """What one carry recorded in the derived run: ``output:<revision>@<digest>`` refs."""

    revisions: tuple[str, ...] = ()


class ForkOutputCarry:
    def __init__(
        self,
        *,
        invocations: CarryInvocations,
        finalization: CarryFinalization,
        adoption: OutputAdoptionService,
        fulfillment: OutputFulfillmentService,
        outputs: OutputContractStore,
        live_factory: Callable[..., Any],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._invocations = invocations
        self._finalization = finalization
        self._adoption = adoption
        self._fulfillment = fulfillment
        self._outputs = outputs
        self._live = live_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    async def carry(
        self, binding: OperationExecutionBinding, reused: ReusedResultRef
    ) -> CarriedOutputs:
        unit = binding.runtime_unit
        if unit is None or not isinstance(unit.location, StageGraphUnitLocation):
            return CarriedOutputs()
        scope, derived_run = binding.request_scope, binding.run_id
        position = unit.location.stage_id
        if await self._outputs.promise_set(scope, derived_run) is None:
            return CarriedOutputs()
        owned = {
            item.key
            for item in await self._outputs.active_obligations(scope, derived_run)
            if item.owner_position == position
        }
        if not owned:
            return CarriedOutputs()
        sources: dict[str, list[AdoptionSource]] = {}
        for item in await self._outputs.accepted_outputs(scope, reused.source_run_id):
            if item.obligation_key in owned:
                sources.setdefault(item.obligation_key, []).append(
                    AdoptionSource(
                        run_id=reused.source_run_id,
                        revision_id=item.revision_id,
                        content_digest=item.content_digest,
                    )
                )
        if not sources:
            # The source accepted nothing for these promises: nothing is carried, and the
            # consumer's unresolved dependency is reported by the family (typed in inspection).
            return CarriedOutputs()
        dispatch = binding.lane_dispatch
        generation = dispatch.execution_generation if dispatch is not None else 1
        live = await self._invocations.begin(
            self._live(
                request_scope=scope,
                run_id=derived_run,
                operation_id=binding.operation_id,
                operation_attempt=binding.operation_attempt,
                execution_generation=generation,
                lane=FORK_REUSE_LANE,
                position=position,
                unit_key=unit.unit_key,
            )
        )
        access = self._invocations.access(live)
        at = self._clock()
        adopted: list[str] = []
        for key in sorted(sources):
            result = await self._adoption.adopt(
                access,
                position=position,
                target_obligation=key,
                sources=tuple(sources[key]),
                act=f"fork_reuse:{reused.fork_request_id}",
                at=at,
            )
            if not result.adopted:
                raise ForkOutputsNotCarried(result.code, result.detail or key)
            adopted.extend(result.revisions)
        # No assessment handoff: the carried bytes are the source's accepted bytes.
        await self._finalization.finalize(access.identity(tuple(getattr(live, "obligations", ()))))
        host = HostAccess(scope=scope, actor_ref=FORK_REUSE_ACTOR, origin_ref=FORK_REUSE_ORIGIN)
        for ref in adopted:
            revision_id = ref.removeprefix("output:").partition("@")[0]
            revision = await self._outputs.output_revision(scope, revision_id)
            if revision is None:
                raise ForkOutputsNotCarried("carried_revision_missing", ref)
            head = await self._outputs.accepted_head(
                scope, derived_run, revision.obligation_key, revision.deliverable_id
            )
            if head is not None and head.revision_id == revision_id:
                continue
            promoted = await self._fulfillment.promote_output(
                host,
                PromoteOutput(
                    run_id=derived_run,
                    revision_id=revision_id,
                    expected_head=None if head is None else head.revision_id,
                    generation=generation,
                ),
            )
            if promoted.status != "promoted":
                error = promoted.error
                raise ForkOutputsNotCarried(
                    "carried_revision_not_promoted",
                    error.safe_message if error is not None else ref,
                )
        return CarriedOutputs(revisions=tuple(adopted))


__all__ = [
    "FORK_REUSE_LANE",
    "CarriedOutputs",
    "ForkOutputCarry",
    "ForkOutputsNotCarried",
]
