"""WI-22 / OVE-183: an admitted reaction activation becomes an ordinary operation request.

The production materializer binds the run's admitted template to the activation (identity
``reaction-<activation>``, runtime unit, reservation and control revision, the bounded event as
an admitted-input segment, the reaction's operation time) and refuses a template that exceeds the
reaction's grants or is unavailable. The run-control budget port reserves once per activation.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from mission_control.application.reactions.operations import (
    BUDGET_KEY,
    REACTION_ISSUER,
    AdmittedReactionOperations,
    RunControlReactionBudget,
)
from mission_control.application.reactions.service import (
    ReactionDispatchReceipt,
    ReactionDispatchRefused,
)
from mission_control.domain.execution.contracts import (
    OperationExecutionRequest,
    OperationWorkflowRequest,
)
from mission_control.domain.execution.data_class import DataClassPolicy
from mission_control.domain.reactions.contracts import ReactionActivation
from tests.unit.operations.test_operation_execution import operation_request
from tests.unit.reactions.test_reaction_planning import (
    AT,
    RUN,
    SCOPE,
    bind,
    declaration,
    plan,
    transition,
)
from tests.unit.run_control.test_run_control import command, request, service


class Templates:
    def __init__(self, template: OperationExecutionRequest | None) -> None:
        self.template = template
        self.calls: list[dict[str, object]] = []

    async def get_template(self, **kwargs: object) -> OperationExecutionRequest:
        self.calls.append(kwargs)
        if self.template is None:
            raise LookupError("no admitted template named reviewer")
        return self.template


class Budget:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, int]]] = []

    async def reserve(
        self, scope: str, run_id: str, *, reservation_id: str, amounts: dict[str, int]
    ) -> int:
        self.calls.append((reservation_id, amounts))
        return 7

    async def release(
        self, scope: str, run_id: str, *, reservation_id: str, amounts: dict[str, int]
    ) -> None:
        self.calls.append((f"release:{reservation_id}", amounts))


class Starter:
    def __init__(self) -> None:
        self.started: list[OperationWorkflowRequest] = []

    async def start(
        self, scope: str, run_id: str, request: OperationWorkflowRequest
    ) -> ReactionDispatchReceipt:
        self.started.append(request)
        return ReactionDispatchReceipt(workflow_id=f"wf:{request.semantic_attempt_id}")


GRANTED = {"mcp_servers": ["fixture-mcp"]}


def activation(grants: dict[str, object] | None = None) -> tuple[ReactionActivation, object]:
    binding = bind(declaration(grants=grants if grants is not None else GRANTED))
    planned = plan(binding, transition("f-9"))
    assert planned is not None
    return planned, binding


@pytest.mark.asyncio
async def test_an_activation_is_bound_as_an_ordinary_operation() -> None:
    planned, binding = activation()
    templates, budget, starter = Templates(operation_request()), Budget(), Starter()
    operations = AdmittedReactionOperations(templates=templates, budget=budget, starter=starter)
    receipt = await operations.dispatch(SCOPE, planned, binding, transition("f-9"))  # type: ignore[arg-type]
    [started] = starter.started
    operation = started.operation
    assert receipt.workflow_id == f"wf:{started.semantic_attempt_id}"
    assert operation.identity.run_id == RUN
    assert operation.identity.operation_id == planned.operation_id
    assert started.semantic_attempt_id == operation.identity.semantic_key
    assert operation.runtime_unit is not None
    assert operation.runtime_unit.location.stage_id == "reaction.review-on-fulfillment"  # type: ignore[union-attr]
    assert operation.request_scope == SCOPE
    assert budget.calls == [(f"reaction:{planned.activation_id}", {BUDGET_KEY: 100})]
    assert operation.budget_reservation_id == f"reaction:{planned.activation_id}"
    assert operation.budget_limits == {BUDGET_KEY: 100}
    assert operation.run_control_revision == 7
    assert operation.idempotency_key == f"reaction:{planned.activation_id}"
    assert operation.requested_at == planned.admitted_at
    assert started.timeout_seconds == 120
    event = json.loads(operation.prompt_segments[-1].content)
    assert operation.prompt_segments[-1].trust_class == "admitted_input"
    assert event["event"] == {
        "kind": "fulfillment.decided",
        "version": 1,
        "source_ref": "f-9",
        "facts": {"obligation_key": "report", "disposition": "unfulfilled"},
    }
    assert event["outputs"] == ["report.repaired"]
    assert templates.calls[0]["template"] == "reviewer"
    assert planned.admitted_at == AT + timedelta(seconds=1)


@pytest.mark.asyncio
async def test_a_template_above_the_reaction_grants_or_missing_refuses() -> None:
    planned, binding = activation(grants={})
    budget, starter = Budget(), Starter()
    operations = AdmittedReactionOperations(
        templates=Templates(operation_request()), budget=budget, starter=starter
    )
    with pytest.raises(ReactionDispatchRefused) as refused:
        await operations.dispatch(SCOPE, planned, binding, transition("f-9"))  # type: ignore[arg-type]
    assert refused.value.code == "GRANT_EXCEEDED"
    planned, binding = activation()
    missing = AdmittedReactionOperations(templates=Templates(None), budget=budget, starter=starter)
    with pytest.raises(ReactionDispatchRefused) as refused:
        await missing.dispatch(SCOPE, planned, binding, transition("f-9"))  # type: ignore[arg-type]
    assert refused.value.code == "TEMPLATE_UNAVAILABLE"
    assert budget.calls == [] and starter.started == []


@pytest.mark.asyncio
async def test_run_control_reserves_once_per_activation() -> None:
    run_service, _ = service()
    admitted = await run_service.admit(request())
    assert admitted.run_id is not None
    budget = RunControlReactionBudget(run_service)
    first = await budget.reserve(
        "tenant-1", admitted.run_id, reservation_id="reaction:a", amounts={BUDGET_KEY: 5}
    )
    again = await budget.reserve(
        "tenant-1", admitted.run_id, reservation_id="reaction:a", amounts={BUDGET_KEY: 5}
    )
    assert first == again
    state = await run_service.get_budget("tenant-1", admitted.run_id)
    assert "reaction:a" in json.dumps(state.model_dump(mode="json"))


@pytest.mark.asyncio
async def test_a_run_whose_version_moves_between_read_and_execute_still_reserves_once() -> None:
    """B2: a concurrent command makes the first attempt stale; the next attempt reads the new
    version and reserves; a redelivery replays the accepted attempt instead of reserving again."""

    from mission_control.domain.policies.contracts import ReserveBudgetAction

    run_service, _ = service()
    admitted = await run_service.admit(request())
    assert admitted.run_id is not None
    run_id: str = admitted.run_id

    class Busy:
        """Run control where another command lands between the read and the first execute."""

        def __init__(self) -> None:
            self.bumped = False

        async def get_run(self, scope: str, run: str):  # type: ignore[no-untyped-def]
            return await run_service.get_run(scope, run)

        async def get_command_result(self, *args: str):  # type: ignore[no-untyped-def]
            return await run_service.get_command_result(*args)

        async def execute(self, cmd):  # type: ignore[no-untyped-def]
            if not self.bumped:
                self.bumped = True
                current = await run_service.get_run("tenant-1", run_id)
                other = command(
                    run_id,
                    current.version,
                    "concurrent",
                    ReserveBudgetAction(reservation_id="other", amounts={BUDGET_KEY: 1}),
                )
                assert (await run_service.execute(other)).status == "accepted"
            return await run_service.execute(cmd)

    busy = Busy()
    budget = RunControlReactionBudget(busy)
    revision = await budget.reserve(
        "tenant-1", run_id, reservation_id="reaction:a", amounts={BUDGET_KEY: 5}
    )
    first = await run_service.get_command_result(
        "tenant-1", run_id, REACTION_ISSUER, "reserve:reaction:a:0"
    )
    second = await run_service.get_command_result(
        "tenant-1", run_id, REACTION_ISSUER, "reserve:reaction:a:1"
    )
    assert first is not None and first.status == "stale"
    assert second is not None and second.status == "accepted"
    assert revision == second.resulting_run_version
    again = await budget.reserve(
        "tenant-1", run_id, reservation_id="reaction:a", amounts={BUDGET_KEY: 5}
    )
    assert again == revision
    assert (
        await run_service.get_command_result(
            "tenant-1", run_id, REACTION_ISSUER, "reserve:reaction:a:2"
        )
        is None
    ), "the redelivery reserved nothing new"
    state = await run_service.get_budget("tenant-1", run_id)
    assert state.reservations["reaction:a"] == {BUDGET_KEY: 5}


@pytest.mark.asyncio
async def test_a_refusal_after_the_reservation_releases_it() -> None:
    """S1: a cancelled activation never keeps spend reserved in run control."""

    run_service, _ = service()
    admitted = await run_service.admit(request())
    assert admitted.run_id is not None
    planned, binding = activation()
    planned = planned.model_copy(update={"run_id": admitted.run_id, "reserved_tokens": 5})

    class Conflicting:
        async def create_binding(self, binding, *, request_scope):  # type: ignore[no-untyped-def]
            return binding.model_copy(update={"request_fingerprint": "sha256:" + "f" * 64})

        async def get_binding_by_id(self, binding_id, *, request_scope):  # type: ignore[no-untyped-def]
            return None

    operations = AdmittedReactionOperations(
        templates=Templates(operation_request()),
        budget=RunControlReactionBudget(run_service),
        starter=Starter(),
        operation_bindings=Conflicting(),
    )
    before = await run_service.get_budget("tenant-1", admitted.run_id)
    with pytest.raises(ReactionDispatchRefused) as refused:
        await operations.dispatch("tenant-1", planned, binding, transition("f-9"))  # type: ignore[arg-type]
    assert refused.value.code == "BINDING_CONFLICT"
    state = await run_service.get_budget("tenant-1", admitted.run_id)
    reservation = f"reaction:{planned.activation_id}"
    assert reservation not in state.reservations, "the reservation was released"
    assert state.reserved == before.reserved, "nothing stays reserved"
    assert state.consumed.get(BUDGET_KEY, 0) == before.consumed.get(BUDGET_KEY, 0), "no usage"


@pytest.mark.asyncio
async def test_a_lane_that_does_not_admit_the_run_data_class_refuses_before_reserving() -> None:
    planned, _binding = activation()
    strict = DataClassPolicy(
        admitted={**DataClassPolicy().admitted, "deep_agents": frozenset({"public"})}
    )
    for data_class, code in (
        ("confidential", "DATA_CLASS_NOT_ADMITTED"),
        (None, "DATA_CLASS_UNDECLARED"),
    ):
        binding = bind(declaration(grants=GRANTED)).model_copy(update={"data_class": data_class})
        budget = Budget()
        operations = AdmittedReactionOperations(
            templates=Templates(operation_request()),
            budget=budget,
            starter=Starter(),
            data_classes=strict,
        )
        with pytest.raises(ReactionDispatchRefused) as refused:
            await operations.dispatch(SCOPE, planned, binding, transition("f-9"))
        assert refused.value.code == code
        assert budget.calls == []
