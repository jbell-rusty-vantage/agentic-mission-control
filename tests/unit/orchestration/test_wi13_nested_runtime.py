"""OVE-176 / WI-13: nested activation identity, budget containment, exact export, terminal
reflection and control propagation (domain rules and the application service)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from mission_control.application.programs.nested_bodies import (
    InMemoryNestedActivationStore,
    NestedActivationConflict,
    NestedActivationRecord,
    NestedLaunch,
    NestedLaunchRefused,
    NestedProgramService,
)
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.nested_bodies import NestedBody, NestedExport
from mission_control.domain.policies.contracts import (
    CancelAction,
    CommandStatus,
    RecordUsageAction,
    ReserveBudgetAction,
    StartAction,
)
from mission_control.domain.programs.contracts import BellLabsRunInput
from mission_control.domain.programs.nested import (
    ChildTerminal,
    NestedActivationRequest,
    NestedControlReceipt,
    NestedControlRequest,
    NestedSettlementRequest,
    capped_usage,
    child_terminal,
    contained_ceiling,
    executor_result,
    nested_request_id,
    project_exports,
    stage_result,
    uncontained,
)
from tests.unit.run_control.test_run_control import command, request, service

NOW = datetime(2026, 10, 29, tzinfo=UTC)
DIGEST = "sha256:" + "a" * 64
SCOPE = "tenant-1"


def body(*, depth: int = 1, timing: str = "final", required: bool = True) -> NestedBody:
    return NestedBody(
        host_id="research",
        node_key="research",
        position="research",
        behavior="stage_graph",
        family="StageGraph",
        depth=depth,
        max_depth=2,
        definition_digest=DIGEST,
        blueprint_digest=DIGEST,
        exports=(
            NestedExport(output="report", source="inner.report"),
            NestedExport(output="note", source="notes.note", timing=timing, required=required),
        ),
    )


# --------------------------------------------------------------------------- domain rules


def test_the_child_request_is_deterministic_per_unit_attempt() -> None:
    first = nested_request_id("run-1", "research", "attempt-1")
    assert first == nested_request_id("run-1", "research", "attempt-1")
    assert first != nested_request_id("run-1", "research", "attempt-2")  # a revisit or retry
    assert first != nested_request_id("run-1", "other", "attempt-1")
    assert first.startswith("nested:") and len(first) <= 64


def test_a_child_never_spends_more_than_the_parent_reserved() -> None:
    # S4: an unreserved spend dimension is capped at zero; governor counters stay the child's.
    assert contained_ceiling(
        {"tokens.total": 40, "operation.attempts": 1},
        {"tokens.total": 100, "time.elapsed_ms": 9, "goal.iterations": 3},
    ) == {"tokens.total": 40, "time.elapsed_ms": 0, "goal.iterations": 3}
    assert contained_ceiling({"tokens.total": 40}, {"tokens.total": 10}) == {"tokens.total": 10}
    assert contained_ceiling({"tool.calls.total": 3}, {}) == {"tool.calls.total": 3}
    with pytest.raises(ValueError):
        contained_ceiling({"tokens.total": -1}, {})
    assert uncontained({"tokens.total": 40}, {"tokens.total": 40, "goal.iterations": 9}) == ()
    assert uncontained({"tokens.total": 40}, {"tokens.total": 41, "time.elapsed_ms": 1}) == (
        "time.elapsed_ms",
        "tokens.total",
    )
    # S5: the charged spend is the consumed spend within the admitted ceiling, everywhere.
    assert capped_usage({"tokens.total": 50, "goal.iterations": 2}, {"tokens.total": 40}) == {
        "tokens.total": 40
    }


def test_child_terminal_reflects_each_family_and_root_end() -> None:
    accepted = child_terminal(
        "StageGraph",
        "returned",
        {
            "completion_proposal": {"required_obligations_accepted": True},
            "output_refs": {"inner": ["artifact:inner"], "draft": ["artifact:draft"]},
        },
    )
    assert accepted.outcome == "accepted"
    assert accepted.family_refs["inner"] == ("artifact:inner",)
    failed = child_terminal(
        "StageGraph", "returned", {"completion_proposal": {"failed": True}, "output_refs": {}}
    )
    assert failed.outcome == "not_accepted"
    capped = child_terminal(
        "StageGraph",
        "returned",
        {"completion_proposal": {"failed": True, "unmet_reasons": ["revisit_cap"]}},
    )
    assert (capped.outcome, capped.cause) == ("governor_exhausted", "revisit_cap")
    assert child_terminal("StageGraph", "cancelled", None).outcome == "cancelled"
    assert child_terminal("GoalDirected", "timed_out", None).outcome == "governor_exhausted"
    assert child_terminal("GoalDirected", "failed", None, cause="boom").cause == "boom"
    complete = child_terminal(
        "GoalDirected",
        "returned",
        {"terminalization_proposal": {"proposed_outcome": "complete", "output_refs": ["r"]}},
    )
    assert (complete.outcome, complete.family_refs) == ("accepted", {"*": ("r",)})
    iteration_cap = child_terminal(
        "GoalDirected",
        "returned",
        {
            "terminalization_proposal": {"proposed_outcome": "partial_or_fail", "output_refs": []},
            "convergence_proposal": {"reason": "iteration_limit"},
        },
    )
    assert iteration_cap.outcome == "governor_exhausted"
    assert child_terminal("GoalDirected", "returned", {"status": "cancelled"}).outcome == (
        "cancelled"
    )


def test_only_declared_accepted_exports_cross_and_accept_the_composite() -> None:
    terminal = ChildTerminal("accepted")
    accepted = {
        "inner.report": ("output:r1@sha256:1",),
        "notes.note": ("output:n1@sha256:2",),
        "draft.internal": ("output:d1@sha256:3",),  # internal: never exported
    }
    projection = project_exports(body(), "child-1", terminal, accepted, actual_usage={"t": 3})
    assert projection.composite_accepted
    assert projection.output_refs == ("output:r1@sha256:1", "output:n1@sha256:2")
    assert "output:d1@sha256:3" not in projection.output_refs
    disposition, payload = stage_result(projection, accepted_obligation_refs=("goal",))
    assert disposition == "completed"
    assert payload["output_refs"] == list(projection.output_refs)
    assert payload["obligation_refs"] == ["goal"]
    receipt = payload["nested"]
    assert receipt["receipt_digest"] == sha256_digest(
        {key: value for key, value in receipt.items() if key != "receipt_digest"}
    )


def test_a_missing_required_export_never_accepts_the_composite() -> None:
    projection = project_exports(
        body(), "child-1", ChildTerminal("accepted"), {"inner.report": ("r",)}
    )
    assert not projection.composite_accepted
    assert projection.missing_required == ("note",)
    assert projection.output_refs == ()
    assert stage_result(projection)[0] == "failed"


def test_an_early_export_leaves_an_incomplete_composite_without_accepting_it() -> None:
    projection = project_exports(
        body(timing="early"),
        "child-1",
        ChildTerminal("governor_exhausted", "iteration_limit"),
        {"notes.note": ("output:n1@sha256:2",), "inner.report": ()},
    )
    assert not projection.composite_accepted
    assert projection.outcome == "governor_exhausted"
    assert [item.output for item in projection.early_exports] == ["note"]
    disposition, payload = stage_result(projection)
    assert disposition == "failed"
    assert "output_refs" not in payload  # never a parent output
    assert payload["nested"]["early_exports"][0]["refs"] == ["output:n1@sha256:2"]


def test_a_final_export_never_leaves_an_incomplete_composite() -> None:
    projection = project_exports(
        body(), "child-1", ChildTerminal("not_accepted"), {"notes.note": ("n",)}
    )
    assert projection.early_exports == ()


def test_the_family_result_is_the_export_basis_only_without_named_promises() -> None:
    terminal = ChildTerminal("accepted", family_refs={"inner": ("a",), "notes": ("b",)})
    assert project_exports(body(), "c", terminal, None).output_refs == ("a", "b")
    assert not project_exports(body(), "c", terminal, {}).composite_accepted


def test_cancellation_and_executor_dispositions() -> None:
    cancelled = project_exports(body(), "c", ChildTerminal("cancelled"), {})
    assert stage_result(cancelled)[0] == "cancelled"
    assert executor_result(cancelled)[0] == "cancelled"
    failed = project_exports(body(), "c", ChildTerminal("execution_failed"), {})
    assert executor_result(failed)[0] == "failed"
    # A governed non-acceptance completes the executor: the loop's policy decides next.
    rejected = project_exports(body(), "c", ChildTerminal("not_accepted"), {})
    assert executor_result(rejected) == ("completed", {"nested": rejected.receipt()})


def test_only_cancel_pause_and_resume_propagate() -> None:
    with pytest.raises(ValueError):
        NestedControlRequest(
            request_scope=SCOPE,
            parent_run_id="p",
            host_id="h",
            child_run_id="c",
            kind="satisfy_wait",  # type: ignore[arg-type]
            command_ref="x",
            reason="r",
            occurred_at=NOW,
        )


def test_a_nested_body_is_bounded_and_its_family_matches_its_behavior() -> None:
    with pytest.raises(ValueError):
        body(depth=3)
    with pytest.raises(ValueError):
        NestedBody.model_validate({**body().model_dump(), "family": "GoalDirected"})


# --------------------------------------------------------------------------- application


class Launcher:
    def __init__(self, ceiling: dict[str, int] | None = None, refuse: str = "") -> None:
        self.calls: list[NestedActivationRequest] = []
        self._ceiling = ceiling
        self._refuse = refuse

    async def launch(self, request: NestedActivationRequest) -> NestedLaunch:
        self.calls.append(request)
        if self._refuse:
            raise NestedLaunchRefused(self._refuse, "refused by the fixture")
        child = f"child-{request.request_id[-8:]}"
        root = BellLabsRunInput(
            schema_version="belllabs.temporal-root.v1",
            run_id=child,
            request_scope=request.request_scope,
            effective_configuration_digest=DIGEST,
            workflow_type_digest=DIGEST,
            family="StageGraph",
            family_input={},
            family_task_queue="queue",
            parent_run_id=request.parent_run_id,
        )
        ceiling = (
            self._ceiling
            if self._ceiling is not None
            else contained_ceiling(request.parent_reservation, {"tokens.total": 100})
        )
        return NestedLaunch(child_run_id=child, child_root=root, budget_ceiling=ceiling)


class Outputs:
    def __init__(self, accepted: dict[str, tuple[str, ...]] | None) -> None:
        self._accepted = accepted

    async def accepted(self, scope: str, run_id: str) -> dict[str, tuple[str, ...]] | None:
        return self._accepted


class Controls:
    def __init__(self) -> None:
        self.requests: list[NestedControlRequest] = []

    async def command(self, request: NestedControlRequest) -> NestedControlReceipt:
        self.requests.append(request)
        return NestedControlReceipt(True, status="delivered")


async def parent_with_reservation(control: Any, amount: int = 40) -> str:
    admitted = await control.admit(request())
    run_id = admitted.run_id
    assert run_id
    await control.execute(command(run_id, 1, "start", StartAction()))
    reserved = await control.execute(
        command(
            run_id,
            2,
            "reserve-unit",
            ReserveBudgetAction(reservation_id="unit-1", amounts={"tokens.total": amount}),
        )
    )
    assert reserved.status == CommandStatus.ACCEPTED
    return run_id


def activation(parent: str, **changes: Any) -> NestedActivationRequest:
    base = NestedActivationRequest(
        request_scope=SCOPE,
        parent_run_id=parent,
        parent_family="StageGraph",
        host_id="research",
        semantic_attempt_id="attempt-1",
        parent_reservation_id="unit-1",
        parent_reservation={"tokens.total": 40},
        body=body(),
        parent_execution_epoch=1,
        child_task_queue="queue",
        occurred_at=NOW,
    )
    return replace(base, **changes)


@pytest.mark.asyncio
async def test_activation_is_contained_recorded_and_idempotent() -> None:
    control, _ = service()
    parent = await parent_with_reservation(control)
    launcher = Launcher()
    store = InMemoryNestedActivationStore()
    nested = NestedProgramService(
        run_control=control, launcher=launcher, outputs=None, controls=None, activations=store
    )
    first = await nested.activate(activation(parent))
    again = await nested.activate(activation(parent))
    assert first.activated and again.activated
    assert first.child_run_id == again.child_run_id
    assert first.budget_ceiling == {"tokens.total": 40}
    assert first.child_root is not None and first.child_root.parent_run_id == parent
    (record,) = await store.for_parent(SCOPE, parent)
    assert (record.position, record.family, record.depth) == ("research", "StageGraph", 1)
    other = await nested.activate(activation(parent, semantic_attempt_id="attempt-2"))
    assert other.child_run_id != first.child_run_id  # a revisit activates a new child


@pytest.mark.asyncio
async def test_activation_refuses_typed_and_starts_nothing() -> None:
    control, _ = service()
    parent = await parent_with_reservation(control)
    store = InMemoryNestedActivationStore()

    def nested(launcher: Any) -> NestedProgramService:
        return NestedProgramService(
            run_control=control, launcher=launcher, outputs=None, controls=None, activations=store
        )

    unwired = await nested(None).activate(activation(parent))
    assert (unwired.activated, unwired.reason_code) == (False, "nested_execution_unavailable")
    refused = await nested(Launcher(refuse="nested_body_digest_mismatch")).activate(
        activation(parent)
    )
    assert refused.reason_code == "nested_body_digest_mismatch"
    uncontained = await nested(Launcher(ceiling={"tokens.total": 41})).activate(activation(parent))
    assert uncontained.reason_code == "nested_budget_uncontained"
    mismatch = await nested(Launcher()).activate(activation(parent, host_id="other"))
    assert mismatch.reason_code == "nested_host_mismatch"
    assert await store.for_parent(SCOPE, parent) == ()
    await control.execute(command(parent, 3, "cancel", CancelAction()))
    cancelling = await nested(Launcher()).activate(activation(parent))
    assert cancelling.reason_code == "parent_not_running"


@pytest.mark.asyncio
async def test_settlement_exports_exactly_and_settles_the_unit_on_child_usage() -> None:
    control, _ = service()
    parent = await parent_with_reservation(control)
    child_admitted = await control.admit(request(request_id="child-run"))
    child = child_admitted.run_id
    assert child
    await control.execute(command(child, 1, "start", StartAction()))
    used = await control.execute(
        command(
            child,
            2,
            "child-usage",
            RecordUsageAction(
                usage_id="u", actual_amounts={"tokens.total": 25}, reservation_id="baseline"
            ),
        )
    )
    assert used.status == CommandStatus.ACCEPTED, used.reason_code
    store = InMemoryNestedActivationStore()
    await store.record(
        NestedActivationRecord(
            request_scope=SCOPE,
            parent_run_id=parent,
            host_id="research",
            semantic_attempt_id="attempt-1",
            position="research",
            family="StageGraph",
            depth=1,
            child_run_id=child,
            budget_ceiling={"tokens.total": 40},
            body_digest=sha256_digest(body()),
            activated_at=NOW,
        )
    )
    nested = NestedProgramService(
        run_control=control,
        launcher=Launcher(),
        outputs=Outputs({"inner.report": ("output:r@d",), "notes.note": ("output:n@d",)}),
        controls=None,
        activations=store,
    )
    settle = NestedSettlementRequest(
        request_scope=SCOPE,
        parent_run_id=parent,
        host_id="research",
        semantic_attempt_id="attempt-1",
        parent_reservation_id="unit-1",
        body=body(),
        child_run_id=child,
        end="returned",
        family_result={"completion_proposal": {"required_obligations_accepted": True}},
        occurred_at=NOW,
    )
    settled = await nested.settle(settle)
    assert settled.projection.composite_accepted
    assert settled.projection.output_refs == ("output:r@d", "output:n@d")
    assert settled.projection.actual_usage == {"tokens.total": 25}
    budget = await control.get_budget(SCOPE, parent)
    assert budget.reservations.get("unit-1", {}).get("tokens.total", 0) == 0
    assert budget.consumed.get("tokens.total") == 25
    (record,) = await store.for_parent(SCOPE, parent)
    assert record.receipt is not None
    assert record.receipt["receipt_digest"] == settled.projection.receipt()["receipt_digest"]
    # Redelivered: nothing is settled twice, the receipt is the same.
    again = await nested.settle(settle)
    assert again.projection == settled.projection


@pytest.mark.asyncio
async def test_a_refused_activation_releases_the_unit_reservation() -> None:
    control, _ = service()
    parent = await parent_with_reservation(control)
    nested = NestedProgramService(
        run_control=control,
        launcher=None,
        outputs=None,
        controls=None,
        activations=InMemoryNestedActivationStore(),
    )
    settled = await nested.settle(
        NestedSettlementRequest(
            request_scope=SCOPE,
            parent_run_id=parent,
            host_id="research",
            semantic_attempt_id="attempt-1",
            parent_reservation_id="unit-1",
            body=body(),
            child_run_id="",
            end="failed",
            family_result=None,
            occurred_at=NOW,
            cause="nested_execution_unavailable",
        )
    )
    assert settled.projection.outcome == "execution_failed"
    assert settled.projection.cause == "nested_execution_unavailable"
    budget = await control.get_budget(SCOPE, parent)
    assert budget.reservations.get("unit-1", {}).get("tokens.total", 0) == 0
    assert budget.consumed.get("tokens.total", 0) == 0


@pytest.mark.asyncio
async def test_controls_reach_a_running_child_through_its_own_run_control() -> None:
    control, _ = service()
    child_admitted = await control.admit(request(request_id="child-run"))
    child = child_admitted.run_id
    assert child
    await control.execute(command(child, 1, "start", StartAction()))
    controls = Controls()
    nested = NestedProgramService(
        run_control=control,
        launcher=None,
        outputs=None,
        controls=controls,
        activations=InMemoryNestedActivationStore(),
    )
    propagated = NestedControlRequest(
        request_scope=SCOPE,
        parent_run_id="parent",
        host_id="research",
        child_run_id=child,
        kind="cancel",
        command_ref="cmd-1",
        reason="parent cancelled",
        occurred_at=NOW,
    )
    assert (await nested.propagate(propagated)).delivered
    assert [item.kind for item in controls.requests] == ["cancel"]
    await control.execute(command(child, 2, "cancel", CancelAction()))
    assert (await nested.propagate(propagated)).status == "already_cancelling"
    unwired = NestedProgramService(
        run_control=control,
        launcher=None,
        outputs=None,
        controls=None,
        activations=InMemoryNestedActivationStore(),
    )
    assert (await unwired.propagate(propagated)).reason_code == "nested_controls_unavailable"


@pytest.mark.asyncio
async def test_the_activation_store_is_write_once() -> None:
    store = InMemoryNestedActivationStore()
    record = NestedActivationRecord(
        request_scope=SCOPE,
        parent_run_id="p",
        host_id="h",
        semantic_attempt_id="a",
        position="h",
        family="StageGraph",
        depth=1,
        child_run_id="c1",
        budget_ceiling={},
        body_digest=DIGEST,
        activated_at=NOW,
    )
    await store.record(record)
    with pytest.raises(NestedActivationConflict):
        await store.record(replace(record, child_run_id="c2"))
    await store.settle(SCOPE, "c1", {"receipt_digest": "x"}, NOW)
    with pytest.raises(NestedActivationConflict):
        await store.settle(SCOPE, "c1", {"receipt_digest": "y"}, NOW)
