"""Builders, constants and fakes that other test files import.

Moved from tests/integration/temporal/test_chain_start_idempotent.py.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from mission_control.application.chains.relay import ChainIntent
from mission_control.application.execution.service import RunControlService
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.fixtures import GENERIC_GOAL_DIRECTED
from mission_control.domain.programs.contracts import GoalDirectedRunInput, GoalRevision
from tests.support.ids import canonical_scope

SCOPE = canonical_scope("tenant-1")
NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)


def revision(run_id: str) -> GoalRevision:
    values = {
        "schema_version": "belllabs.goal-revision.v1",
        "revision_id": "goal-revision:1",
        "revision": 1,
        "parent_revision_id": None,
        "envelope_digest": sha256_digest({"chain": "consumer-envelope", "run": run_id}),
        "objective": "Ingest the supplied evidence map",
        "tactical_changes": (),
        "evidence_refs": ("input:chain",),
        "unmet_obligations": (),
        "proposer": "application:chain",
        "deciding_authority": "authority:chain",
        "applicability": "remaining_run",
        "tactics": (),
        "subgoals": (),
        "coverage_emphasis": (),
    }
    return GoalRevision(canonical_digest=sha256_digest(values), **values)  # type: ignore[arg-type]


class AdmittedRunInputs:
    """``ChainLaunchInputPort`` for the test: the admitted run's GoalDirected input."""

    def __init__(self, run_control: RunControlService) -> None:
        self._run_control = run_control
        self.calls = 0

    async def family_input(self, intent: ChainIntent) -> dict[str, Any]:
        self.calls += 1
        run = await self._run_control.get_run(intent.request_scope, intent.run_key)
        budget = await self._run_control.get_budget(intent.request_scope, intent.run_key)
        blueprint = GENERIC_GOAL_DIRECTED
        goal = revision(run.run_id)
        return asdict(
            GoalDirectedRunInput(
                run_id=run.run_id,
                request_scope=run.request_scope,
                effective_configuration_digest=run.effective_configuration_digest,
                blueprint_digest=sha256_digest(blueprint),
                blueprint=blueprint.model_dump(mode="json"),
                envelope_digest=goal.envelope_digest,
                initial_revision=goal,
                initial_run_version=run.version,
                baseline_reservation=dict(budget.reservations.get("baseline", {})),
                semantic_input_binding_ref="semantic-input:chain-consumer",
            )
        )


class OneShotStore:
    """An intent store whose acknowledgement is lost once, so the intent is delivered twice."""

    def __init__(self, intent: ChainIntent) -> None:
        self.intent = intent
        self.deliveries = 0
        self.delivered = False

    async def lease(self, *_args: Any, **_kwargs: Any) -> tuple[ChainIntent, ...]:
        return () if self.delivered else (self.intent,)

    async def mark_delivered(self, *_args: Any, **_kwargs: Any) -> None:
        self.deliveries += 1
        if self.deliveries >= 2:
            self.delivered = True

    async def mark_failed(self, *_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("delivery must not fail")
