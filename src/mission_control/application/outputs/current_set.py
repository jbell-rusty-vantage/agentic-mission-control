"""The goal-wide current-set index as an exact sealed file (WI-07; OUTPUT-CONTRACTS §7).

:class:`CurrentSetIndexResolver` answers the host's ``application_selector`` binding
``mc.current-set@1`` (``domain.outputs.current_set.CURRENT_SET_BINDING``). At the receiver's
seal it pins the run's current accepted set (``pin_set``: the promise revisions and exact heads,
serialized with promotion by the run lock), indexes it with the standing judgments and the
labelled non-head candidates, and returns the canonical JSON as one exact ``value`` member placed
as a file. The plan is sealed once per receiver boundary, so a retry, restart or redelivery reads
the same index bytes; a later iteration's receiver gets the set as it then stands.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from mission_control.application.context.materialization import (
    MC_ISSUER,
    ResolutionContext,
    ResolvedContent,
    refuse,
)
from mission_control.application.outputs.fulfillment import MemberDecisionPort
from mission_control.application.ports.outputs import OutputContractStore
from mission_control.domain.context.transfer import ExactMember, TransferInput
from mission_control.domain.outputs.collections import cited_member_decisions
from mission_control.domain.outputs.contracts import OutputObligation, TrustedValidators
from mission_control.domain.outputs.current_set import (
    CURRENT_SET_FILE,
    CurrentSetIndex,
    build_current_set_index,
)

INDEX_ACTOR = "mission-control:current-set"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class CurrentSetIndexResolver:
    """``application_selector(mc.current-set@1)``: the run's exact current-set index."""

    def __init__(
        self,
        contracts: OutputContractStore,
        *,
        trusted_validators: TrustedValidators,
        member_decisions: MemberDecisionPort | None = None,
        clock: Callable[[], datetime] = _utcnow,
        actor_ref: str = INDEX_ACTOR,
    ) -> None:
        self._member_decisions = member_decisions
        self._trusted_validators = trusted_validators
        self._contracts = contracts
        self._clock = clock
        self._actor_ref = actor_ref

    async def index(self, scope: str, run_id: str) -> CurrentSetIndex | None:
        """Pin the current accepted set and index it; ``None`` for a run without promises."""

        if await self._contracts.promise_set(scope, run_id) is None:
            return None
        pinned = await self._contracts.pin_set(
            scope, run_id, actor_ref=self._actor_ref, at=self._clock()
        )
        obligations: list[OutputObligation] = []
        for key, revision in pinned.obligation_refs:
            obligation = await self._contracts.obligation_revision(scope, run_id, key, revision)
            if obligation is None:
                raise LookupError(f"obligation {key}@{revision} is not recorded")
            obligations.append(obligation)
        assessments = await self._contracts.output_assessments(scope, run_id)
        candidates = await self._contracts.finalized_outputs(scope, run_id)
        cited = {
            item
            for obligation in obligations
            for item in cited_member_decisions(
                obligation,
                [*pinned.members, *candidates],
                assessments,
                trusted_validators=self._trusted_validators,
            )
        }
        verified = (
            await self._member_decisions.standing_member_decisions(scope, sorted(cited))
            if cited and self._member_decisions is not None
            else {}
        )
        return build_current_set_index(
            run_id,
            obligations,
            pinned,
            assessments,
            candidates,
            trusted_validators=self._trusted_validators,
            member_decisions=verified,
        )

    async def resolve(
        self, binding: TransferInput, context: ResolutionContext
    ) -> Sequence[ResolvedContent]:
        index = await self.index(context.scope, context.run_id)
        if index is None:
            refuse(
                "SOURCE_UNRESOLVED",
                binding,
                "the run registered no output promises, so it has no current set",
            )
            raise AssertionError  # pragma: no cover
        content = index.render()
        set_ref = f"output-set:{index.set_id}"
        member = ExactMember(
            member_key=f"{binding.name}/index",
            binding=binding.name,
            part="value",
            source_kind="application_selector",
            source_ref=set_ref,
            revision=f"{set_ref}@{index.set_revision}",
            issuer=MC_ISSUER,
            digest="sha256:" + hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
            media_type="application/json",
            file_name=CURRENT_SET_FILE,
            purpose=binding.purpose,
            required=binding.required,
            access_ref=set_ref,
        )
        return (ResolvedContent(member, content),)


__all__ = ["INDEX_ACTOR", "CurrentSetIndexResolver"]
