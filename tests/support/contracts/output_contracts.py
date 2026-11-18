"""Output contract store contract: `InMemoryOutputContractStore` versus PostgreSQL (release 1.7.0).

The scenarios wire the real submission and fulfillment services over the store under test
(`tests.unit.outputs.scenario.build_stack`) and call the store directly, asserting what a caller
observes: promises registered once per run, submission keys that replay or refuse, accepted
heads that move only by compare-and-set, successors that wait for their boundary while pins
hold, pinned sets, assessments and association steps recorded once, and scoping by tenant.

Runners: `tests/unit/outputs/test_output_contract_store_contract.py` (in memory) and
`tests/integration/postgres/test_output_contract_store_contract_postgres.py` (PostgreSQL).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import pytest

from mission_control.application.knowledge.access import InvocationAccess
from mission_control.application.outputs.fulfillment import AuthorAccess, PromoteOutput
from mission_control.application.ports.outputs import (
    OlderRevision,
    OutputContractStore,
    PromisesConflict,
    StaleGeneration,
    StaleHead,
)
from mission_control.domain.outputs.contracts import (
    Cardinality,
    OutputForm,
    OutputObligation,
    Requirement,
)
from mission_control.domain.outputs.successors import ContractRevisionProposal, RegisteredCandidate
from tests.support.integration.postgres.output_contracts_postgres import AT
from tests.support.knowledge.gateway import origin
from tests.unit.outputs.scenario import (
    REPO,
    Stack,
    build_stack,
    code_change,
    obligation,
    promises,
    text,
)

ACTOR = "host:test"


@dataclass
class OutputContractSubject:
    """The output contract store under test, its submission store and two tenant scopes."""

    store: OutputContractStore
    submissions: Any
    scope: str
    other_scope: str

    def access(self, *, scope: str | None = None, attempt: int = 1) -> InvocationAccess:
        _mc, installation, application, tenant = (scope or self.scope).split("/")
        return InvocationAccess(
            origin=origin(
                attempt,
                installation_id=installation,
                application_id=application,
                tenant_id=tenant,
            ),
            subject="mission-control-runtime",
            invocation_id=f"inv-{attempt:04d}",
            authenticated_at=AT,
        )

    async def stack(self, *items: OutputObligation, scope: str | None = None) -> Stack:
        return await build_stack(self.store, self.submissions, self.access(scope=scope), *items)


Scenario = Callable[[OutputContractSubject], Awaitable[None]]


def report() -> OutputObligation:
    return obligation("draft.report", OutputForm.TEXT)


async def promises_register_once_per_run(subject: OutputContractSubject) -> None:
    store = subject.store
    second, first = obligation("draft.second", OutputForm.TEXT), report()
    stack = await subject.stack(second, first)
    scope, run_id = stack.host.scope, stack.run_id
    registered = promises(second, first)
    assert [
        (item.key, item.revision) for item in await store.active_obligations(scope, run_id)
    ] == [
        ("draft.second", 1),
        ("draft.report", 1),
    ]
    stored = await store.promise_set(scope, run_id)
    assert stored is not None and stored.digest == registered.digest
    again = await store.register_promises(
        scope, run_id, registered, configuration_digest=None, actor_ref=ACTOR, at=AT
    )
    assert [item.key for item in again] == ["draft.second", "draft.report"]
    with pytest.raises(PromisesConflict):
        await store.register_promises(
            scope, run_id, promises(first), configuration_digest=None, actor_ref=ACTOR, at=AT
        )
    assert await store.obligation_revision(scope, run_id, "draft.report", 1) == first
    assert await store.obligation_revision(scope, run_id, "draft.report", 2) is None
    assert await store.invocation_pins(scope, stack.access.invocation_ref) == {
        "draft.second": 1,
        "draft.report": 1,
    }


async def submission_keys_replay_or_refuse(subject: OutputContractSubject) -> None:
    store = subject.store
    stack = await subject.stack(report())
    first = await stack.submit("call-1", "draft.report", text("report", "v1"))
    assert first.status == "accepted", first.error
    replay = await stack.submit("call-1", "draft.report", text("report", "v1"))
    assert replay.submission_id == first.submission_id and replay.revisions == first.revisions
    changed = await stack.submit("call-1", "draft.report", text("report", "v2"))
    assert changed.error is not None and changed.error.code == "SUBMISSION_CONFLICT"
    second = await stack.submit("call-2", "draft.report", text("report", "v2"))
    assert [item.revision for item in second.revisions] == [2]
    stored = await store.output_revision(stack.host.scope, first.revisions[0].revision_id)
    assert stored is not None
    assert (stored.deliverable_id, stored.revision, stored.obligation_revision) == ("report", 1, 1)
    assert stored.content_digest == first.revisions[0].content_digest
    # A finalized invocation still replays a key it recorded, and refuses a new one.
    await stack.submissions.finalize(stack.access.identity(("draft.report",)))
    assert (
        await stack.submit("call-2", "draft.report", text("report", "v2"))
    ).submission_id == second.submission_id
    closed = await stack.submit("call-3", "draft.report", text("report", "v3"))
    assert closed.status != "accepted" and closed.error is not None


async def accepted_heads_move_by_compare_and_set(subject: OutputContractSubject) -> None:
    store = subject.store
    stack = await subject.stack(report())
    scope, run_id = stack.host.scope, stack.run_id
    first = await stack.submit("call-1", "draft.report", text("report", "v1"))
    second = await stack.submit("call-2", "draft.report", text("report", "v2"))
    older = await store.output_revision(scope, first.revisions[0].revision_id)
    newer = await store.output_revision(scope, second.revisions[0].revision_id)
    assert older is not None and newer is not None
    assert await store.accepted_head(scope, run_id, "draft.report", "report") is None
    head = await store.promote(
        scope, run_id, older, expected_head=None, generation=2, actor_ref=ACTOR, at=AT
    )
    assert (head.revision_id, head.version, head.generation) == (older.revision_id, 1, 2)
    assert await store.accepted_head(scope, run_id, "draft.report", "report") == head
    with pytest.raises(StaleHead):
        await store.promote(
            scope, run_id, newer, expected_head=None, generation=2, actor_ref=ACTOR, at=AT
        )
    with pytest.raises(StaleGeneration):
        await store.promote(
            scope,
            run_id,
            newer,
            expected_head=older.revision_id,
            generation=1,
            actor_ref=ACTOR,
            at=AT,
        )
    moved = await store.promote(
        scope, run_id, newer, expected_head=older.revision_id, generation=2, actor_ref=ACTOR, at=AT
    )
    assert (moved.revision_id, moved.version) == (newer.revision_id, 2)
    with pytest.raises(OlderRevision):
        await store.promote(
            scope,
            run_id,
            older,
            expected_head=newer.revision_id,
            generation=2,
            actor_ref=ACTOR,
            at=AT,
        )
    assert [item.revision_id for item in await store.accepted_outputs(scope, run_id)] == [
        newer.revision_id
    ]
    # A draft submission never moves the accepted head.
    await stack.submit("call-3", "draft.report", text("report", "v3"))
    assert await store.accepted_head(scope, run_id, "draft.report", "report") == moved
    # Through the service, a stale expected head is a refusal, not an exception.
    refused = await stack.outputs.promote_output(
        stack.host,
        PromoteOutput(run_id=run_id, revision_id=older.revision_id, generation=2),
    )
    assert refused.status == "refused"


async def a_successor_waits_for_its_boundary(subject: OutputContractSubject) -> None:
    store = subject.store
    prior = obligation("draft.report", OutputForm.TEXT, cardinality=Cardinality(min=1, max=2))
    stack = await subject.stack(prior)
    scope, run_id = stack.host.scope, stack.run_id
    author = AuthorAccess(
        scope=scope,
        actor_id="owner",
        role="author",
        delegation_refs=frozenset({"delegation:owner"}),
    )
    tighter = prior.model_copy(update={"revision": 2, "cardinality": Cardinality(min=2, max=2)})
    proposal = ContractRevisionProposal(
        run_id=run_id,
        obligation_key="draft.report",
        expected_prior_revision=1,
        successor=tighter,
        actor_id="owner",
        actor_role="author",
        reason="two reports",
        delegation_ref="delegation:owner",
        boundary="between_iterations",
        boundary_ref="iteration:2",
    )
    assert (await stack.outputs.activate_contract_successor(author, proposal)).status == "pending"
    assert (await stack.outputs.activate_contract_successor(author, proposal)).status == "refused"
    assert [item.revision for item in await store.active_obligations(scope, run_id)] == [1]
    assert await store.obligation_revision(scope, run_id, "draft.report", 2) == tighter
    elsewhere = await store.activate_pending(
        scope, run_id, boundary="at_stage_exit", boundary_ref="stage:1", actor_ref=ACTOR, at=AT
    )
    assert elsewhere == ()
    activated = await stack.outputs.activate_at_boundary(
        stack.host, run_id, boundary="between_iterations", boundary_ref="iteration:2"
    )
    assert [item.revision for item in activated] == [2]
    assert [item.revision for item in await store.active_obligations(scope, run_id)] == [2]
    # The in-flight invocation keeps the revision it pinned; a new attempt pins the successor.
    assert await store.invocation_pins(scope, stack.access.invocation_ref) == {"draft.report": 1}
    late = await stack.submit("call-1", "draft.report", text("report", "v1"))
    stored = await store.output_revision(scope, late.revisions[0].revision_id)
    assert stored is not None and stored.obligation_revision == 1
    after = await stack.start(subject.access(attempt=2))
    fresh = await after.submit("call-1", "draft.report", text("report2", "x"))
    fresh_stored = await store.output_revision(scope, fresh.revisions[0].revision_id)
    assert fresh_stored is not None and fresh_stored.obligation_revision == 2


async def pinned_sets_are_reused_until_membership_changes(subject: OutputContractSubject) -> None:
    store = subject.store
    stack = await subject.stack(report())
    scope, run_id = stack.host.scope, stack.run_id
    empty = await store.pin_set(scope, run_id, actor_ref=ACTOR, at=AT)
    assert empty.members == () and empty.revision == 1
    assert (await store.pin_set(scope, run_id, actor_ref=ACTOR, at=AT)).set_id == empty.set_id
    await stack.accept(
        await stack.submit("call-1", "draft.report", text("report", "v1")), "draft.report"
    )
    grown = await store.pin_set(scope, run_id, actor_ref=ACTOR, at=AT)
    assert grown.set_id != empty.set_id
    assert (grown.revision, grown.prior_set_id) == (2, empty.set_id)
    assert [item.deliverable_id for item in grown.members] == ["report"]
    assert await store.output_set(scope, grown.set_id) == grown
    assert await store.output_set(subject.other_scope, grown.set_id) is None


async def assessments_are_recorded_once(subject: OutputContractSubject) -> None:
    store = subject.store
    patch = obligation(
        "draft.patch",
        OutputForm.CODE_CHANGE,
        repository=REPO,
        requirements=(Requirement(key="tests", validator="mc.check.command@1"),),
    )
    stack = await subject.stack(patch)
    ack = await stack.submit("p1", "draft.patch", code_change())
    revision = ack.revisions[0]
    first = await stack.judge(revision.revision_id, revision.content_digest, tests="pass")
    again = await stack.judge(revision.revision_id, revision.content_digest, tests="pass")
    assert (first.status, again.status) == ("recorded", "recorded")
    stored = await store.output_assessments(stack.host.scope, stack.run_id)
    assert [(item.subject_id, item.subject_digest) for item in stored] == [
        (revision.revision_id, revision.content_digest)
    ]
    assert await store.output_assessments(subject.other_scope, stack.run_id) == ()


async def association_steps_are_taken_once(subject: OutputContractSubject) -> None:
    store = subject.store
    stack = await subject.stack(report())
    one = (RegisteredCandidate(candidate=text("report", "registered"), source="registered_output"),)
    actions = [
        (
            await stack.outputs.resolve_missing_submission(
                stack.host, stack.access, "draft.report", one, position="draft"
            )
        ).action
        for _ in range(3)
    ]
    assert actions == ["remind", "associate", "not_missing"]
    invocation = stack.access.invocation_ref
    scope, run_id = stack.host.scope, stack.run_id
    assert await store.association_steps(scope, invocation, "draft.report") == frozenset(
        {"reminder", "auto_associated"}
    )
    assert not await store.record_association_step(
        scope, run_id, invocation, "draft.report", "reminder", {}, actor_ref=ACTOR, at=AT
    )
    assert await store.association_steps(subject.other_scope, invocation, "draft.report") == (
        frozenset()
    )


async def scopes_are_isolated(subject: OutputContractSubject) -> None:
    store = subject.store
    stack = await subject.stack(report())
    scope, run_id, other = stack.host.scope, stack.run_id, subject.other_scope
    ack = await stack.submit("call-1", "draft.report", text("report", "v1"))
    await stack.accept(ack, "draft.report")
    revision_id = ack.revisions[0].revision_id
    assert await store.promise_set(other, run_id) is None
    assert await store.active_obligations(other, run_id) == ()
    assert await store.output_revision(other, revision_id) is None
    assert await store.accepted_head(other, run_id, "draft.report", "report") is None
    assert await store.accepted_outputs(other, run_id) == ()
    assert await store.finalized_outputs(other, run_id) == ()
    assert await store.invocation_pins(other, stack.access.invocation_ref) == {}
    # The same run identity in another tenant registers its own promises and submissions.
    theirs = await subject.stack(obligation("draft.other", OutputForm.TEXT), scope=other)
    assert [item.key for item in await store.active_obligations(other, run_id)] == ["draft.other"]
    their_ack = await theirs.submit("call-1", "draft.other", text("other", "v1"))
    assert their_ack.status == "accepted", their_ack.error
    assert [item.key for item in await store.active_obligations(scope, run_id)] == ["draft.report"]
    head = await store.accepted_head(scope, run_id, "draft.report", "report")
    assert head is not None and head.revision_id == revision_id


SCENARIOS: tuple[Scenario, ...] = (
    promises_register_once_per_run,
    submission_keys_replay_or_refuse,
    accepted_heads_move_by_compare_and_set,
    a_successor_waits_for_its_boundary,
    pinned_sets_are_reused_until_membership_changes,
    assessments_are_recorded_once,
    association_steps_are_taken_once,
    scopes_are_isolated,
)

__all__ = ["SCENARIOS", "OutputContractSubject", "Scenario"]
