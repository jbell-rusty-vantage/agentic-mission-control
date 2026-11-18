"""Builders, constants and fakes that other test files import.

Moved from tests/unit/orchestration/test_wi08_graph_routes.py.
"""

from __future__ import annotations

from typing import Any

from mission_control.domain.authoring.contracts import StageGraphBlueprint
from mission_control.domain.programs.contracts import (
    ExecutionIdentity,
    LateResultFacts,
    StageGraphAcceptedProjection,
    StageResultObservation,
)
from mission_control.domain.programs.interpreter import StageGraphInterpreter
from mission_control.domain.programs.routing import ROUTE_FACTS_KEY

RUN = "run-wi08"


class Driver:
    """Admit and decide stages one at a time against the pure interpreter."""

    def __init__(self, blueprint: StageGraphBlueprint) -> None:
        self.interpreter = StageGraphInterpreter(blueprint, effective_max_concurrency=8)
        self.projection: StageGraphAcceptedProjection = self.interpreter.initial_projection(
            ExecutionIdentity(RUN), run_version=1
        )
        self.order = 0
        self.proposals: dict[str, Any] = {}

    def ready(self) -> set[str]:
        return {
            item.identity.stage_id
            for item in self.interpreter.frontier(self.projection, available_concurrency=8)
        }

    def admit(self, stage_id: str) -> Any:
        frontier = self.interpreter.frontier(self.projection, available_concurrency=8)
        proposal = next(item for item in frontier if item.identity.stage_id == stage_id)
        self.projection = self.interpreter.apply_admission(
            self.projection,
            proposal,
            next_run_version=self.projection.run_version + 1,
            next_family_version=self.projection.family_version + 1,
        )
        self.proposals[stage_id] = proposal
        return proposal

    def finish(
        self,
        stage_id: str,
        *,
        facts: dict[str, Any] | None = None,
        outcome: str = "completed",
        ref: str | None = None,
        obligations: tuple[str, ...] = (),
    ) -> None:
        proposal = self.proposals[stage_id]
        self.order += 1
        result: dict[str, Any] = {"output_refs": [ref or f"artifact://{stage_id}/out"]}
        if obligations:
            result["obligation_refs"] = list(obligations)
        if facts is not None:
            result[ROUTE_FACTS_KEY] = {
                key: {"status": "known", "value": value, "evidence_ref": f"ev:{stage_id}:{key}"}
                if value is not None
                else {"status": "unknown", "reason": "fact_pointer_absent"}
                for key, value in facts.items()
            }
        consumers = {
            edge.consumer_stage_id
            for edge in self.interpreter.blueprint.dependencies
            if edge.producer_stage_id == stage_id
        }
        admitted = any(
            item.candidate.stage_id in consumers
            and item.status not in {"blocked", "ready", "structurally_unavailable"}
            for item in self.projection.stages.values()
        )
        decision = self.interpreter.result_decision(
            proposal.identity,
            LateResultFacts(consumer_already_admitted=admitted),
            operation_disposition=outcome,
            operation_result=result if outcome == "completed" else None,
        )
        self.projection = self.interpreter.apply_result_decision(
            self.projection,
            StageResultObservation(
                identity=proposal.identity,
                operation_result=result,
                child_closed_or_quiesced=True,
                reservations_and_usage_settled=True,
                effects_settled=True,
                cancellation_reconciled=True,
                accepted_order=self.order,
                operation_disposition=outcome,
            ),
            decision,
            next_run_version=self.projection.run_version + 1,
            next_family_version=self.projection.family_version + 1,
        )

    def run(self, stage_id: str, **kwargs: Any) -> Any:
        proposal = self.admit(stage_id)
        self.finish(stage_id, **kwargs)
        return proposal
