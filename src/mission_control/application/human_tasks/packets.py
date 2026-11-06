"""Resolve authored review sources to the run's exact accepted named outputs."""

from __future__ import annotations

from typing import Protocol

from mission_control.domain.outputs.contracts import ExactOutput, OutputObligation
from mission_control.domain.programs.human_gate import (
    HumanGateActivation,
    NamedReviewPacketRequest,
    ReviewPacketItem,
    open_activation,
)


class ReviewOutputs(Protocol):
    async def active_obligations(self, scope: str, run_id: str) -> tuple[OutputObligation, ...]: ...

    async def accepted_outputs(self, scope: str, run_id: str) -> tuple[ExactOutput, ...]: ...


class NamedOutputReviewPackets:
    def __init__(self, outputs: ReviewOutputs) -> None:
        self._outputs = outputs

    async def prepare(self, request: NamedReviewPacketRequest) -> HumanGateActivation:
        activation = request.activation
        scope, run_id = activation.request_scope, activation.run_id
        obligations = {
            item.key: item for item in await self._outputs.active_obligations(scope, run_id)
        }
        accepted = await self._outputs.accepted_outputs(scope, run_id)
        packet: list[ReviewPacketItem] = []
        for source in request.sources:
            obligation = obligations.get(source)
            if obligation is None:
                raise ValueError(f"review source {source} is not an active named obligation")
            members = tuple(
                output
                for output in accepted
                if output.obligation_key == source
                and output.obligation_revision == obligation.revision
                and output.run_id == run_id
            )
            if not members:
                raise ValueError(f"review source {source} has no exact accepted output")
            packet.extend(
                ReviewPacketItem(
                    source=source,
                    ref=f"output-revision:{output.revision_id}#digest={output.content_digest}",
                    digest=output.content_digest,
                )
                for output in members
            )
        return open_activation(
            request_scope=scope,
            run_id=run_id,
            family=activation.family,
            activation_key=activation.activation_key,
            execution_epoch=activation.execution_epoch,
            review_round=activation.review_round,
            spec=activation.spec,
            packet=tuple(packet),
            opened_at=activation.opened_at,
        )
