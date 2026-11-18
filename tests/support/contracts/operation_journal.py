"""Atomic operation journal contract: `InMemoryAtomicOperationJournalRepository` versus PostgreSQL.

The scenarios commit claim and technical-attempt mutations against a run admitted through the
real run-control service, and assert what a caller observes: acquisition, idempotent replays
(including a regenerated claim identity), refusals with their error types, run-version fencing,
shadow denial and scoping by tenant. Settlements need an accepted authority result and stay with
the dedicated tests in `tests/integration/postgres/test_operation_journal_stage1.py`.

Runners: `tests/unit/operations/test_operation_journal_contract.py` (in memory) and
`tests/integration/postgres/test_operation_journal_contract_postgres.py` (PostgreSQL).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import pytest

from mission_control.application.execution.operations.operation_journal import (
    AtomicOperationJournalRepository,
    OperationJournalMutation,
)
from mission_control.application.execution.run_control_repository import RunControlRepository
from mission_control.domain.execution.journal import (
    OperationEffectClaim,
    OperationTechnicalAttempt,
)
from mission_control.domain.policies.contracts import BudgetState, DecisionStatus, RunProjection
from mission_control.domain.policies.errors import (
    IdempotencyConflict,
    RunControlNotFound,
    RunVersionConflict,
)
from tests.support.integration.postgres.operation_journal_stage1 import attempt as base_attempt
from tests.support.integration.postgres.operation_journal_stage1 import claim as base_claim
from tests.support.run_control import request as unit_request
from tests.support.run_control import service

DIGEST_B = "sha256:" + "b" * 64


@dataclass
class OperationJournalSubject:
    """The journal under test, the run-control repository that admits its runs, and two
    tenant scopes. `seed` tells an in-memory journal about each admitted run; the PostgreSQL
    journal reads the run rows themselves."""

    repository: AtomicOperationJournalRepository
    run_control: RunControlRepository
    scope: str
    other_scope: str
    seed: Callable[[RunProjection, BudgetState], None] | None = None

    async def admit(self, request_id: str, *, scope: str | None = None) -> str:
        run_service, _ = service(self.run_control)  # type: ignore[arg-type]
        scope = scope or self.scope
        decision = await run_service.admit(unit_request(request_scope=scope, request_id=request_id))
        assert decision.status == DecisionStatus.ACCEPTED and decision.run_id is not None
        if self.seed is not None:
            self.seed(
                await self.run_control.get_run(scope, decision.run_id),
                await self.run_control.get_budget(scope, decision.run_id),
            )
        return decision.run_id


Scenario = Callable[[OperationJournalSubject], Awaitable[None]]


def claim(scope: str, run_id: str, **updates: object) -> OperationEffectClaim:
    return base_claim(run_id=run_id).model_copy(update={"request_scope": scope, **updates})


def attempt(scope: str, **updates: object) -> OperationTechnicalAttempt:
    return base_attempt().model_copy(update={"request_scope": scope, **updates})


def mutation(
    scope: str,
    run_id: str,
    effect_claim: OperationEffectClaim,
    *,
    version: int = 1,
    technical_attempt: OperationTechnicalAttempt | None = None,
) -> OperationJournalMutation:
    return OperationJournalMutation(
        request_scope=scope,
        belllabs_run_id=run_id,
        expected_run_version=version,
        claim=effect_claim,
        attempt=technical_attempt,
    )


def _identity(value: OperationEffectClaim | None) -> tuple[object, ...] | None:
    if value is None:
        return None
    return (
        value.effect_claim_id,
        value.request_scope,
        value.belllabs_run_id,
        value.idempotency_key,
        value.request_digest,
        value.semantic_binding_id,
        value.claim_mode,
    )


async def claim_is_acquired_and_readable(subject: OperationJournalSubject) -> None:
    repository = subject.repository
    run_id = await subject.admit("journal-acquire")
    effect_claim = claim(subject.scope, run_id)
    acquired = await repository.commit(mutation(subject.scope, run_id, effect_claim))
    assert acquired.status == "acquired"
    assert _identity(acquired.claim) == _identity(effect_claim)
    assert _identity(await repository.get_claim(subject.scope, "claim-1")) == _identity(
        effect_claim
    )
    assert await repository.get_settlement(subject.scope, "claim-1") is None
    assert await repository.get_claim(subject.scope, "claim-never-made") is None


async def claim_retry_is_idempotent(subject: OperationJournalSubject) -> None:
    repository = subject.repository
    run_id = await subject.admit("journal-retry")
    effect_claim = claim(subject.scope, run_id)
    first = await repository.commit(mutation(subject.scope, run_id, effect_claim))
    replay = await repository.commit(mutation(subject.scope, run_id, effect_claim))
    assert (first.status, replay.status) == ("acquired", "existing")
    assert _identity(replay.claim) == _identity(effect_claim)
    # A retry that regenerated the claim id finds the persisted identity.
    regenerated = effect_claim.model_copy(update={"effect_claim_id": "claim-regenerated"})
    again = await repository.commit(mutation(subject.scope, run_id, regenerated))
    assert again.status == "existing"
    assert again.claim is not None and again.claim.effect_claim_id == "claim-1"
    assert await repository.get_claim(subject.scope, "claim-regenerated") is None


async def claim_conflicting_retry_is_refused(subject: OperationJournalSubject) -> None:
    repository = subject.repository
    run_id = await subject.admit("journal-conflict")
    effect_claim = claim(subject.scope, run_id)
    await repository.commit(mutation(subject.scope, run_id, effect_claim))
    with pytest.raises(IdempotencyConflict):
        await repository.commit(
            mutation(subject.scope, run_id, claim(subject.scope, run_id, request_digest=DIGEST_B))
        )
    regenerated = effect_claim.model_copy(update={"effect_claim_id": "claim-regenerated"})
    with pytest.raises(IdempotencyConflict):
        await repository.commit(
            mutation(
                subject.scope,
                run_id,
                regenerated,
                technical_attempt=attempt(subject.scope, effect_claim_id="claim-regenerated"),
            )
        )
    stored = await repository.get_claim(subject.scope, "claim-1")
    assert stored is not None and stored.request_digest == effect_claim.request_digest


async def stale_run_version_is_refused(subject: OperationJournalSubject) -> None:
    repository = subject.repository
    run_id = await subject.admit("journal-stale")
    with pytest.raises(RunVersionConflict):
        await repository.commit(
            mutation(subject.scope, run_id, claim(subject.scope, run_id), version=2)
        )
    assert await repository.get_claim(subject.scope, "claim-1") is None
    with pytest.raises(RunControlNotFound):
        await repository.commit(
            mutation(
                subject.scope, "run-never-admitted", claim(subject.scope, "run-never-admitted")
            )
        )
    assert await repository.get_claim(subject.scope, "claim-1") is None


async def technical_attempt_replays_and_conflicts(subject: OperationJournalSubject) -> None:
    repository = subject.repository
    run_id = await subject.admit("journal-attempt")
    effect_claim = claim(subject.scope, run_id)
    await repository.commit(mutation(subject.scope, run_id, effect_claim))
    with_attempt = mutation(
        subject.scope, run_id, effect_claim, technical_attempt=attempt(subject.scope)
    )
    assert (await repository.commit(with_attempt)).status == "existing"
    assert (await repository.commit(with_attempt)).status == "existing"
    changed = mutation(
        subject.scope,
        run_id,
        effect_claim,
        technical_attempt=attempt(subject.scope, usage={"tokens.total": 9}),
    )
    with pytest.raises(IdempotencyConflict):
        await repository.commit(changed)


async def shadow_claim_is_denied(subject: OperationJournalSubject) -> None:
    repository = subject.repository
    run_id = await subject.admit("journal-shadow")
    result = await repository.commit(
        mutation(subject.scope, run_id, claim(subject.scope, run_id, claim_mode="shadow"))
    )
    assert result.status == "shadow_denied"
    assert result.claim is None
    assert await repository.get_claim(subject.scope, "claim-1") is None


async def scopes_are_isolated(subject: OperationJournalSubject) -> None:
    repository = subject.repository
    run_id = await subject.admit("journal-isolated")
    mine = claim(subject.scope, run_id)
    assert (await repository.commit(mutation(subject.scope, run_id, mine))).status == "acquired"
    other = subject.other_scope
    assert await repository.get_claim(other, "claim-1") is None
    # Another tenant cannot claim against this tenant's run.
    with pytest.raises(RunControlNotFound):
        await repository.commit(mutation(other, run_id, claim(other, run_id)))
    # The same claim identity and idempotency key in another tenant is a separate claim.
    other_run = await subject.admit("journal-isolated", scope=other)
    theirs = claim(other, other_run)
    assert (await repository.commit(mutation(other, other_run, theirs))).status == "acquired"
    assert _identity(await repository.get_claim(subject.scope, "claim-1")) == _identity(mine)
    assert _identity(await repository.get_claim(other, "claim-1")) == _identity(theirs)


SCENARIOS: tuple[Scenario, ...] = (
    claim_is_acquired_and_readable,
    claim_retry_is_idempotent,
    claim_conflicting_retry_is_refused,
    stale_run_version_is_refused,
    technical_attempt_replays_and_conflicts,
    shadow_claim_is_denied,
    scopes_are_isolated,
)

__all__ = ["SCENARIOS", "OperationJournalSubject", "Scenario"]
