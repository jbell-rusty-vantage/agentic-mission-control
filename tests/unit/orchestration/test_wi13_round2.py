"""OVE-176 / WI-13 round 2: the explicit adoption act, the production launcher, the child-run
definition view, governed child controls, and the settlement fixes (unstarted child closed,
adoption into the parent, redelivery from the recorded receipt)."""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from mission_control.application.authoring.manifest_submit import budget_envelope
from mission_control.application.execution.boundary_interventions import (
    BoundaryInterventionService,
)
from mission_control.application.knowledge.access import InvocationAccess
from mission_control.application.outputs.adoption import (
    AdoptionSource,
    OutputAdoptionService,
    exact_ref,
)
from mission_control.application.programs.nested_bodies import (
    InMemoryNestedActivationStore,
    NestedActivationRecord,
    NestedAdoptionRefused,
    NestedLaunchRefused,
    NestedProgramService,
)
from mission_control.application.programs.nested_launch import (
    ManifestNestedRunLauncher,
    NestedRunDefinitions,
    RunControlNestedControls,
    StoreNestedOutputs,
    contained_envelope,
    host_position,
)
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import (
    DefinitionKind,
    ExactDefinitionRef,
    StageGraphBlueprint,
)
from mission_control.domain.authoring.manifest_lowering import lower_mission
from mission_control.domain.authoring.nested_lowering import nested_definition_at
from mission_control.domain.knowledge.lineage import ActorKind, ProvenanceRole
from mission_control.domain.knowledge.origin import InvocationOrigin
from mission_control.domain.outputs.contracts import (
    CandidateRef,
    ExactOutput,
    OutputForm,
    SubmissionAck,
    SubmittedRevision,
)
from mission_control.domain.policies.contracts import (
    BudgetApplicability,
    BudgetDimensionLimit,
    BudgetEnvelope,
    RunPhase,
    StartAction,
)
from mission_control.domain.programs.contracts import StageGraphRunInput
from mission_control.domain.programs.nested import (
    NestedActivationRequest,
    NestedControlRequest,
    NestedSettlementRequest,
)
from tests.unit.authoring.test_wi13_nested_authoring import definition, document
from tests.unit.orchestration.test_wi13_nested_runtime import (
    body,
    parent_with_reservation,
)
from tests.unit.run_control.test_run_control import command, request, service

NOW = datetime(2026, 10, 29, tzinfo=UTC)
SCOPE = "mc/5e8f2a52-7c0e-4f55-9a4e-2f2a3b1c0d11/ai-engineer/7a7d7b1e-1c2d-4e3f-8a9b-0c1d2e3f4a5b"
DIGEST = "sha256:" + "d" * 64


# --------------------------------------------------------------------------- adoption act


def output(revision: str, digest: str = DIGEST, run: str = "child-run") -> ExactOutput:
    candidate = CandidateRef(
        deliverable_id="report", form=OutputForm.TEXT, kind="inline", digest=digest, value="x"
    )
    return ExactOutput(
        revision_id=revision,
        run_id=run,
        obligation_key="draft.report",
        obligation_revision=1,
        deliverable_id="report",
        revision=1,
        form=OutputForm.TEXT,
        content_digest=digest,
        candidate=candidate.document(),
        producer_origin_ref="mc-inv:child",
    )


class Accepted:
    def __init__(self, *items: ExactOutput) -> None:
        self.items = items

    async def accepted_outputs(self, scope: str, run_id: str) -> tuple[ExactOutput, ...]:
        return tuple(item for item in self.items if item.run_id == run_id)

    async def promise_set(self, scope: str, run_id: str) -> object | None:
        return object() if self.items else None


class Submissions:
    def __init__(self, refuse: bool = False) -> None:
        self.calls: list[tuple[Any, str | None]] = []
        self.refuse = refuse

    async def submit_output(self, access: Any, request: Any, *, position: str | None, **_: Any):
        self.calls.append((request, position))
        if self.refuse:
            from mission_control.domain.outputs.contracts import OutputError, OutputErrorCode

            return SubmissionAck(
                status="refused",
                error=OutputError(code=OutputErrorCode.POSITION_MISMATCH, safe_message="no"),
            )
        return SubmissionAck(
            submission_id="s1",
            status="accepted",
            revisions=(
                SubmittedRevision(
                    revision_id="parent-r1",
                    deliverable_id="report",
                    revision=1,
                    content_digest=request.items[0].digest,
                ),
            ),
        )


class Lineage:
    def __init__(self) -> None:
        self.entries: list[Any] = []

    async def record(self, scope: str, entries: Any, *, actor_ref: str, at: datetime) -> int:
        self.entries.extend(entries)
        return len(entries)


def access() -> InvocationAccess:
    origin = InvocationOrigin(
        issuer="mission-control",
        installation_id="5e8f2a52-7c0e-4f55-9a4e-2f2a3b1c0d11",
        application_id="ai-engineer",
        tenant_id="7a7d7b1e-1c2d-4e3f-8a9b-0c1d2e3f4a5b",
        mission_id="parent-run",
        run_id="parent-run",
        activation_id="5e8f2a52-7c0e-4f55-9a4e-2f2a3b1c0d12",
        operation_id="parent-run:operation:stage:research",
        attempt=1,
        generation=1,
        lane="nested_body",
    )
    return InvocationAccess(
        origin=origin, subject="mc", invocation_id="inv-1", authenticated_at=NOW
    )


@pytest.mark.asyncio
async def test_adoption_submits_the_exact_accepted_revision_with_adopter_lineage() -> None:
    submissions, lineage = Submissions(), Lineage()
    service_ = OutputAdoptionService(
        outputs=Accepted(output("r1")), submissions=submissions, lineage=lineage
    )
    result = await service_.adopt(
        access(),
        position="research",
        target_obligation="research.report",
        sources=(AdoptionSource.parse("child-run", f"output:r1@{DIGEST}"),),
        act="nested_export",
        at=NOW,
    )
    assert result.adopted and result.revisions == (f"output:parent-r1@{DIGEST}",)
    ((submitted, position),) = submissions.calls
    assert position == "research" and submitted.obligation_key == "research.report"
    assert submitted.items[0].digest == DIGEST and submitted.mode == "final"
    assert submitted.derivation_refs == (f"output:r1@{DIGEST}",)
    (entry,) = lineage.entries
    assert entry.fact.role is ProvenanceRole.ADOPTER
    assert entry.fact.actor_kind is ActorKind.OBLIGATION
    assert entry.fact.actor_ref == "parent-run:research.report"
    assert entry.fact.fact["act"] == "adoption"  # never a producer fact
    await service_.adopt(
        access(),
        position="research",
        target_obligation="research.report",
        sources=(AdoptionSource.parse("child-run", f"output:r1@{DIGEST}"),),
        act="nested_export",
        at=NOW,
    )
    assert submissions.calls[1][0].submission_key == submitted.submission_key  # idempotent key


@pytest.mark.asyncio
async def test_adoption_refuses_a_non_accepted_or_other_digest_source() -> None:
    submissions = Submissions()
    service_ = OutputAdoptionService(outputs=Accepted(output("r1")), submissions=submissions)
    for ref in ("output:r2@" + DIGEST, "output:r1@sha256:" + "e" * 64):
        result = await service_.adopt(
            access(),
            position="research",
            target_obligation="research.report",
            sources=(AdoptionSource.parse("child-run", ref),),
            act="nested_export",
            at=NOW,
        )
        assert (result.adopted, result.code) == (False, "adoption_source_not_accepted")
    assert submissions.calls == []  # nothing is submitted for a refused source
    refusing = OutputAdoptionService(
        outputs=Accepted(output("r1")), submissions=Submissions(refuse=True)
    )
    refused = await refusing.adopt(
        access(),
        position="other",
        target_obligation="research.report",
        sources=(AdoptionSource.parse("child-run", f"output:r1@{DIGEST}"),),
        act="nested_export",
        at=NOW,
    )
    assert refused.code == "adoption_refused:POSITION_MISMATCH"
    with pytest.raises(ValueError):
        AdoptionSource.parse("child-run", "artifact:x")


@pytest.mark.asyncio
async def test_store_outputs_read_exact_accepted_heads_or_none_without_promises() -> None:
    assert await StoreNestedOutputs(Accepted()).accepted(SCOPE, "child-run") is None
    found = await StoreNestedOutputs(Accepted(output("r1"))).accepted(SCOPE, "child-run")
    assert found == {"draft.report": (exact_ref(output("r1")),)}


# --------------------------------------------------------------------------- settlement fixes


class Adoption:
    def __init__(self, refuse: str = "") -> None:
        self.calls: list[Any] = []
        self.refuse = refuse

    async def adopt(self, request: Any, projection: Any) -> tuple[str, ...]:
        self.calls.append((request, projection))
        if self.refuse:
            raise NestedAdoptionRefused(self.refuse, "refused")
        return ("output:parent-r1@" + DIGEST,)


def adopting_body() -> Any:
    original = body()
    return original.model_copy(
        update={
            "exports": tuple(
                item.model_copy(update={"adopt_into": f"research.{item.output}"})
                for item in original.exports
            )
        }
    )


async def child_with_record(control: Any, store: Any, parent: str, nested_body: Any) -> str:
    admitted = await control.admit(request(request_id="child-run"))
    child = admitted.run_id
    assert child
    await store.record(
        NestedActivationRecord(
            request_scope="tenant-1",
            parent_run_id=parent,
            host_id="research",
            semantic_attempt_id="attempt-1",
            position="research",
            family="StageGraph",
            depth=1,
            child_run_id=child,
            budget_ceiling={"tokens.total": 40},
            body_digest=sha256_digest(nested_body),
            activated_at=NOW,
        )
    )
    return child


def settlement(parent: str, child: str, nested_body: Any, **changes: Any) -> Any:
    base = NestedSettlementRequest(
        request_scope="tenant-1",
        parent_run_id=parent,
        host_id="research",
        semantic_attempt_id="attempt-1",
        parent_reservation_id="unit-1",
        body=nested_body,
        child_run_id=child,
        end="returned",
        family_result={"completion_proposal": {"required_obligations_accepted": True}},
        occurred_at=NOW,
        operation_id="op-1",
    )
    return replace(base, **changes)


class Outputs:
    async def accepted(self, scope: str, run_id: str) -> dict[str, tuple[str, ...]]:
        return {"inner.report": (f"output:r@{DIGEST}",), "notes.note": (f"output:n@{DIGEST}",)}


@pytest.mark.asyncio
async def test_an_accepted_composite_adopts_its_exports_into_the_parent() -> None:
    control, _ = service()
    parent = await parent_with_reservation(control)
    store = InMemoryNestedActivationStore()
    nested_body = adopting_body()
    child = await child_with_record(control, store, parent, nested_body)
    adoption = Adoption()
    nested = NestedProgramService(
        run_control=control,
        launcher=None,
        outputs=Outputs(),
        controls=None,
        activations=store,
        adoption=adoption,
    )
    settled = await nested.settle(settlement(parent, child, nested_body))
    assert settled.projection.composite_accepted
    assert settled.projection.adopted == ("output:parent-r1@" + DIGEST,)
    assert settled.projection.receipt()["adopted"] == ["output:parent-r1@" + DIGEST]
    # Redelivered after the reservation was settled: the recorded receipt, adopted once.
    again = await nested.settle(settlement(parent, child, nested_body))
    assert again.projection.receipt() == settled.projection.receipt()
    assert len(adoption.calls) == 1


@pytest.mark.asyncio
async def test_a_refused_adoption_leaves_the_composite_not_accepted() -> None:
    control, _ = service()
    parent = await parent_with_reservation(control)
    store = InMemoryNestedActivationStore()
    nested_body = adopting_body()
    child = await child_with_record(control, store, parent, nested_body)
    nested = NestedProgramService(
        run_control=control,
        launcher=None,
        outputs=Outputs(),
        controls=None,
        activations=store,
        adoption=Adoption(refuse="adoption_refused:POSITION_MISMATCH"),
    )
    settled = await nested.settle(settlement(parent, child, nested_body))
    assert not settled.projection.composite_accepted
    assert settled.projection.output_refs == ()
    assert settled.projection.cause == "adoption_refused:adoption_refused:POSITION_MISMATCH"


@pytest.mark.asyncio
async def test_a_child_cancelled_before_it_started_is_closed_and_settled() -> None:
    control, _ = service()
    parent = await parent_with_reservation(control)
    store = InMemoryNestedActivationStore()
    child = await child_with_record(control, store, parent, body())
    nested = NestedProgramService(
        run_control=control, launcher=None, outputs=None, controls=None, activations=store
    )
    settled = await nested.settle(
        settlement(
            parent,
            child,
            body(),
            end="cancelled",
            family_result=None,
            cause="cancelled",
            child_started=False,
        )
    )
    assert settled.projection.outcome == "cancelled"
    closed = await control.get_run("tenant-1", child)
    assert closed.phase in {RunPhase.CANCELLING, RunPhase.TERMINAL}
    (record,) = await store.for_parent("tenant-1", parent)
    assert record.receipt is not None  # the activation never stays unsettled
    budget = await control.get_budget("tenant-1", parent)
    assert budget.reservations.get("unit-1", {}).get("tokens.total", 0) == 0


# --------------------------------------------------------------------------- governed controls


@pytest.mark.asyncio
async def test_child_controls_go_through_the_child_run_control() -> None:
    control, _ = service()
    admitted = await control.admit(request(request_id="child-run"))
    child = admitted.run_id
    assert child
    await control.execute(command(child, 1, "start", StartAction()))
    controls = RunControlNestedControls(BoundaryInterventionService(control), control)

    def propagated(kind: str, ref: str) -> NestedControlRequest:
        return NestedControlRequest(
            request_scope="tenant-1",
            parent_run_id="parent",
            host_id="research",
            child_run_id=child,
            kind=kind,  # type: ignore[arg-type]
            command_ref=ref,
            reason=f"parent {kind}",
            occurred_at=NOW,
        )

    assert (await controls.command(propagated("pause", "pause-1"))).delivered
    assert (await controls.command(propagated("resume", "pause-1"))).delivered
    cancelled = await controls.command(propagated("cancel", "cancel-1"))
    assert cancelled.delivered
    assert (await control.get_run("tenant-1", child)).phase in {
        RunPhase.CANCELLING,
        RunPhase.TERMINAL,
    }


# --------------------------------------------------------------------------- launcher


def graph_in_goal() -> Any:
    resolved = definition(document("ai-engineer.graph-in-goal.mission.yml"))
    return resolved, lower_mission(resolved).blueprint.nested_bodies[0]


class Definitions:
    def __init__(self, resolved: Any) -> None:
        self.resolved = resolved

    async def run_subscriptions(self, scope: str, run_key: str) -> Any:
        return {"definition": self.resolved.model_dump(mode="json"), "mission_id": "m"}


class Runs:
    def __init__(self) -> None:
        self.verified: list[Any] = []

    async def get_run(self, scope: str, run_id: str) -> Any:
        return SimpleNamespace(
            effective_configuration_digest=DIGEST,
            workflow_type_ref=SimpleNamespace(digest=DIGEST),
            phase=RunPhase.ACTIVE,
        )

    async def verify_admission(self, run_request: Any) -> Any:
        self.verified.append(run_request)
        return "verified"


class Configurations:
    async def retrieve_for_admission(self, digest: str) -> Any:
        return SimpleNamespace(runtime_profile=SimpleNamespace(operation_binding_refs=frozenset()))


class Programs:
    def __init__(self) -> None:
        self.lowered: list[Any] = []

    async def compile(self, lowered: Any, **_: Any) -> Any:
        self.lowered.append(lowered)
        configuration = SimpleNamespace(
            digest=DIGEST,
            input_manifest=lowered.input_manifest,
            effective_authority=SimpleNamespace(
                budgets=SimpleNamespace(dimensions={"tokens.total": 500000, "goal.iterations": 2}),
                max_concurrency=1,
            ),
        )
        return configuration, ExactDefinitionRef(
            kind=DefinitionKind.WORKFLOW_TYPE,
            logical_id="nested.workflow",
            revision=1,
            digest=DIGEST,
        )


ADMITTED: list[str] = []


class Admissions:
    """Idempotent per request id, as the PostgreSQL admission is (receipt + advisory lock)."""

    async def admit(self, scope: str, parent: str, run_request: Any, verified: Any) -> str:
        ADMITTED.append(run_request.request_id)
        return "child-run"


class Author:
    def __init__(self, store: Any) -> None:
        self.store = store

    async def family_input(self, *, request_scope: str, run_id: str, family: Any, **_: Any):
        # The lineage is recorded before the launch input is authored (the definition view).
        assert await self.store.by_child(request_scope, run_id) is not None
        graph = Programs.graph
        return asdict(
            StageGraphRunInput(
                run_id=run_id,
                request_scope=request_scope,
                effective_configuration_digest=DIGEST,
                workflow_type_digest=DIGEST,
                blueprint_digest=sha256_digest(graph),
                blueprint=graph.model_dump(mode="json"),
                semantic_input_binding_ref=f"semantic-input:manifest:{run_id}",
            )
        )


REGISTERED: list[tuple[str, str]] = []


def launcher(resolved: Any, store: Any, runs: Any) -> ManifestNestedRunLauncher:
    async def schemas(_: Any) -> dict[str, Any]:
        return {}

    async def register(scope: str, run_id: str, digest: str, promises: Any) -> None:
        REGISTERED.append((run_id, promises.obligations[0].owner_position))

    return ManifestNestedRunLauncher(
        run_control=runs,
        definitions=Definitions(resolved),
        configurations=Configurations(),
        output_schemas=schemas,
        programs=Programs(),
        admissions=Admissions(),
        activations=store,
        launch_inputs=Author(store),
        promises=register,
        family_task_queues={"StageGraph": "q-stagegraph", "GoalDirected": "q-goal"},
    )


def activation(nested_body: Any, **changes: Any) -> NestedActivationRequest:
    base = NestedActivationRequest(
        request_scope=SCOPE,
        parent_run_id="parent-run",
        parent_family="GoalDirected",
        host_id="executor",
        semantic_attempt_id="attempt-1",
        parent_reservation_id="unit-1",
        parent_reservation={"goal.iterations": 1, "tokens.total": 40000},
        body=nested_body,
        parent_execution_epoch=1,
        child_task_queue="q-goal",
        occurred_at=NOW,
    )
    return replace(base, **changes)


@pytest.mark.asyncio
async def test_the_launcher_admits_a_sealed_contained_child_and_returns_its_root() -> None:
    resolved, nested_body = graph_in_goal()
    store, runs = InMemoryNestedActivationStore(), Runs()
    nested_def = nested_definition_at(resolved, nested_body.position)
    graph = lower_mission(nested_def, position=nested_body.position, depth=1).blueprint
    assert isinstance(graph, StageGraphBlueprint)
    Programs.graph = graph  # type: ignore[attr-defined]
    launched = await launcher(resolved, store, runs).launch(activation(nested_body))
    root = launched.child_root
    assert (root.run_id, root.family, root.family_task_queue) == (
        "child-run",
        "StageGraph",
        "q-stagegraph",
    )
    assert root.parent_run_id == "parent-run" and root.workflow_id.endswith("/run/child-run")
    assert launched.budget_ceiling == {"tokens.total": 40000, "goal.iterations": 2}
    (run_request,) = runs.verified
    caps = {limit.dimension: limit.hard_cap for limit in run_request.budget_envelope.dimensions}
    assert caps["tokens.total"] == 40000  # never above the unit's reservation
    assert run_request.idempotency_issuer == "mc.nested-body"
    assert any(ref.startswith("manifest:sha256:") for ref in run_request.admission_evidence_refs)
    (record,) = await store.for_parent(SCOPE, "parent-run")
    assert (record.child_run_id, record.position, record.depth) == ("child-run", "refine/pass", 1)
    # The body's promises register for the child run with their absolute nested positions.
    assert REGISTERED[-1][0] == "child-run" and REGISTERED[-1][1].startswith("refine/pass/")


@pytest.mark.asyncio
async def test_the_launcher_refuses_a_drifted_body_or_a_mismatched_lineage() -> None:
    resolved, nested_body = graph_in_goal()
    tampered = nested_body.model_copy(update={"definition_digest": "sha256:" + "0" * 64})
    with pytest.raises(NestedLaunchRefused) as drifted:
        await launcher(resolved, InMemoryNestedActivationStore(), Runs()).launch(
            activation(tampered)
        )
    assert drifted.value.code == "nested_body_digest_mismatch"
    lowered = nested_body.model_copy(update={"blueprint_digest": "sha256:" + "0" * 64})
    with pytest.raises(NestedLaunchRefused) as relowered:
        await launcher(resolved, InMemoryNestedActivationStore(), Runs()).launch(
            activation(lowered)
        )
    assert relowered.value.code == "nested_body_digest_mismatch"
    # S3: the parent is itself a depth-1 child, so this body would run at depth 2, not 1.
    store = InMemoryNestedActivationStore()
    await store.record(
        NestedActivationRecord(
            request_scope=SCOPE,
            parent_run_id="grandparent",
            host_id="x",
            semantic_attempt_id="a",
            position="x",
            family="GoalDirected",
            depth=1,
            child_run_id="parent-run",
            budget_ceiling={},
            body_digest=DIGEST,
            activated_at=NOW,
        )
    )
    with pytest.raises(NestedLaunchRefused) as lineage:
        await launcher(resolved, store, Runs()).launch(activation(nested_body))
    assert lineage.value.code == "nested_depth_lineage_mismatch"


@pytest.mark.asyncio
async def test_the_launch_author_reads_a_child_run_as_its_derived_body() -> None:
    resolved, nested_body = graph_in_goal()
    store = InMemoryNestedActivationStore()
    view = NestedRunDefinitions(Definitions(resolved), store)
    assert (await view.run_subscriptions(SCOPE, "child-run"))["definition"][
        "mission_key"
    ] == resolved.mission_key
    await store.record(
        NestedActivationRecord(
            request_scope=SCOPE,
            parent_run_id="parent-run",
            host_id="executor",
            semantic_attempt_id="a",
            position=nested_body.position,
            family="StageGraph",
            depth=1,
            child_run_id="child-run",
            budget_ceiling={},
            body_digest=DIGEST,
            activated_at=NOW,
        )
    )
    seen = (await view.run_subscriptions(SCOPE, "child-run"))["definition"]
    assert seen["program"]["key"] == "pass"
    assert sha256_digest(seen) and seen["mission_key"].endswith(".pass")


def test_containment_caps_bounded_and_reserved_spend_and_keeps_counters() -> None:
    envelope = BudgetEnvelope(
        dimensions=(
            BudgetDimensionLimit(
                dimension="tokens.total", applicability=BudgetApplicability.BOUNDED, hard_cap=9
            ),
            BudgetDimensionLimit(
                dimension="time.elapsed_ms", applicability=BudgetApplicability.UNBOUNDED
            ),
            BudgetDimensionLimit(
                dimension="goal.iterations", applicability=BudgetApplicability.BOUNDED, hard_cap=3
            ),
        )
    )
    capped = {
        item.dimension: (item.applicability.value, item.hard_cap)
        for item in contained_envelope(envelope, {"tokens.total": 5}).dimensions
    }
    assert capped == {
        "tokens.total": ("bounded", 5),
        "time.elapsed_ms": ("unbounded", None),
        "goal.iterations": ("bounded", 3),
    }
    assert budget_envelope  # the compiled envelope is the base contained_envelope narrows


def test_adoption_targets_the_composite_or_the_hosting_loop_position() -> None:
    stage = settlement("p", "c", body())
    assert host_position(stage) == "research"
    _, nested_body = graph_in_goal()
    assert host_position(settlement("p", "c", nested_body)) == "refine"
    (export,) = nested_body.exports
    assert export.adopt_into == "refine.report"


@pytest.mark.asyncio
async def test_a_retried_activation_returns_the_same_child_for_the_same_unit_attempt() -> None:
    """S-A: a redelivered activate (same unit attempt) re-presents the same request id, gets the
    same child run and one activation record; the workflow starts the child once by its id."""

    resolved, nested_body = graph_in_goal()
    nested_def = nested_definition_at(resolved, nested_body.position)
    Programs.graph = lower_mission(nested_def, position=nested_body.position, depth=1).blueprint  # type: ignore[attr-defined]
    store, runs = InMemoryNestedActivationStore(), Runs()
    nested = NestedProgramService(
        run_control=runs,  # type: ignore[arg-type]
        launcher=launcher(resolved, store, runs),
        outputs=None,
        controls=None,
        activations=store,
    )
    ADMITTED.clear()
    first = await nested.activate(activation(nested_body))
    again = await nested.activate(activation(nested_body))
    assert first.activated and again.activated
    assert first.child_run_id == again.child_run_id == "child-run"
    assert first.child_workflow_id == again.child_workflow_id
    assert len(set(ADMITTED)) == 1  # one admission identity, however often it is presented
    assert len(await store.for_parent(SCOPE, "parent-run")) == 1
    other = await nested.activate(activation(nested_body, semantic_attempt_id="attempt-2"))
    assert len(set(ADMITTED)) == 2 and other.activated  # a new attempt is a new request


class LeakToolset:
    def __init__(self) -> None:
        self.begun: list[Any] = []
        self.settled: list[Any] = []

    async def begin(self, live: Any) -> Any:
        self.begun.append(live)
        return live

    def access(self, live: Any) -> Any:
        return access()

    async def settle_saved(self, live: Any) -> Any:
        self.settled.append(live)
        return None, ()


@pytest.mark.asyncio
async def test_a_refused_adoption_still_settles_the_begun_invocation() -> None:
    """N-B: the hosting unit's invocation never stays open when an adoption refuses."""

    from mission_control.application.programs.nested_launch import ToolsetNestedAdoption
    from mission_control.domain.programs.nested import ChildTerminal, project_exports

    toolset = LeakToolset()
    refusing = OutputAdoptionService(
        outputs=Accepted(output("r1")), submissions=Submissions(refuse=True)
    )
    adapter = ToolsetNestedAdoption(toolset, refusing)  # type: ignore[arg-type]
    nested_body = adopting_body()
    projection = project_exports(
        nested_body,
        "child-run",
        ChildTerminal("accepted"),
        {"inner.report": (f"output:r1@{DIGEST}",), "notes.note": (f"output:r1@{DIGEST}",)},
    )
    with pytest.raises(NestedAdoptionRefused):
        await adapter.adopt(settlement("p", "child-run", nested_body), projection)
    assert len(toolset.begun) == 1 and toolset.settled == toolset.begun
