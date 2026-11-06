"""WI-01 compile proof: exact named promises in the pinned effective configuration.

A manifest's outputs compile into ``EffectiveRunConfiguration.output_promises``: one
``OutputObligation@2`` per declared output with its form, enforcement, distinct cardinality,
coverage, declared checks and pinned schema, plus a closed completion expression. Goals are
owned explicitly (never by the last stage), dependencies carry the exact bound producer output
and the authored join, and a nested Goal Loop keeps its own position.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from mission_control.application.knowledge.access import InvocationAccess
from mission_control.application.outputs.fulfillment import OutputFulfillmentService
from mission_control.application.outputs.submission_service import SubmissionService
from mission_control.domain.authoring.contracts import JoinKind
from mission_control.domain.authoring.stagegraph_builder import (
    StageGraphStageSpec,
    StageInputBindingSpec,
    build_stagegraph_v2,
)
from mission_control.domain.outputs.contracts import AllOf, Enforcement, OutputForm
from tests.fixtures.output_contracts import InMemoryOutputContractStore
from tests.unit.authoring.test_manifest_compile import minimal, reasons, scope, service, text
from tests.unit.knowledge.test_gateway import origin
from tests.unit.outputs.scenario import Stack, fulfillment, host_access
from tests.unit.outputs.scenario import text as text_candidate

pytestmark = pytest.mark.asyncio


def promised_manifest() -> dict:  # type: ignore[type-arg]
    document = minimal()
    synthesize = document["mission"]["program"]["nodes"][1]
    synthesize["outputs"] = [
        {
            "name": "claims",
            "schema": "claim_table@1",
            "coverage": {"subjects": ["nct-1", "nct-2"], "pointer": "/claims", "key": "study"},
        },
        {
            "name": "summary",
            "form": "text",
            "enforcement": "expected",
            "media_type": "text/markdown",
        },
        {
            "name": "patch",
            "form": "code_change",
            "enforcement": "optional",
            "repository": "github.com/overtonbell/mission-control",
            "requirements": [{"key": "tests", "validator": "mc.check.command@1"}],
        },
    ]
    return document


async def test_the_effective_configuration_pins_every_named_promise() -> None:
    compiler, _, _ = await service()
    result = await compiler.compile(text(promised_manifest()), scope())
    assert result.ok, result.report.blockers
    configuration = result.programs[0].configuration
    promises = configuration.output_promises
    assert promises is not None
    assert [item.key for item in promises.obligations] == [
        "collect.sources",
        "synthesize.claims",
        "synthesize.summary",
        "synthesize.patch",
    ]
    claims = promises.obligation("synthesize.claims")
    assert claims is not None and claims.owner_position == "synthesize"
    assert claims.form is OutputForm.STRUCTURED and claims.enforcement is Enforcement.REQUIRED
    assert claims.contract.coverage is not None
    assert claims.contract.coverage.subjects == ("nct-1", "nct-2")
    assert claims.contract.schema_pin is not None and claims.contract.schema_pin.ref == (
        "claim_table@1"
    )
    summary = promises.obligation("synthesize.summary")
    assert summary is not None and summary.enforcement is Enforcement.EXPECTED
    patch = promises.obligation("synthesize.patch")
    assert patch is not None and patch.form is OutputForm.CODE_CHANGE
    assert [item.key for item in patch.contract.requirements] == ["tests"]
    assert isinstance(promises.completion, AllOf)
    assert [leaf.obligation for leaf in promises.completion.items] == [  # type: ignore[union-attr]
        item.key for item in promises.obligations
    ]
    # The blueprint carries the same set, and the configuration digest covers it.
    assert configuration.selected_blueprint.output_promises == promises


def with_second_goal(evidence: str) -> dict:  # type: ignore[type-arg]
    document = minimal()
    document["mission"]["goals"].append(
        {
            "key": "published",
            "description": "Publish the claims",
            "criteria": [
                {
                    "key": "reviewed",
                    "description": "The owner reviewed the claims",
                    "evidence": [evidence],
                    "acceptance": {"human": "review_accept"},
                }
            ],
        }
    )
    return document


async def test_an_unowned_required_goal_refuses_instead_of_falling_to_the_last_stage() -> None:
    compiler, _, _ = await service()
    result = await compiler.compile(text(with_second_goal("claim_table@1")), scope())
    assert not result.ok
    assert ("/mission/goals/1", "unowned_goal") in reasons(result)


async def test_criterion_evidence_names_the_owning_stage() -> None:
    compiler, _, _ = await service()
    result = await compiler.compile(text(with_second_goal("sources")), scope())
    assert result.ok, result.report.blockers
    blueprint = result.programs[0].configuration.selected_blueprint
    owned = {
        (row.owner_stage_id, row.obligation_slot_id) for row in blueprint.completion_obligations
    }
    # The goal whose evidence cites collect's output is collect's, not the last stage's.
    assert owned == {("synthesize", "evidence_map"), ("collect", "published")}


async def test_a_removed_required_flag_is_refused_as_unknown() -> None:
    document = minimal()
    document["mission"]["program"]["nodes"][1]["outputs"][0]["required"] = True
    compiler, _, _ = await service()
    result = await compiler.compile(text(document), scope())
    assert not result.ok


def test_dependencies_carry_the_bound_output_and_the_authored_join() -> None:
    graph = build_stagegraph_v2(
        logical_id="t.bindings",
        title="bindings",
        description="bindings",
        stages=(
            StageGraphStageSpec("produce", output_slots=("draft", "notes")),
            StageGraphStageSpec("audit", output_slots=("verdict",)),
            StageGraphStageSpec(
                "review",
                depends_on=("produce", "audit"),
                bindings=(StageInputBindingSpec("produce", "notes", required=False),),
                join=JoinKind.ANY,
            ),
            StageGraphStageSpec("archive", depends_on=("produce",)),
        ),
    )
    edges = {
        (edge.consumer_stage_id, edge.producer_output_slot_id, edge.dependency_class.value)
        for edge in graph.dependencies
    }
    # Data binds the named slot; unbound predecessor edges wait on completion, not bytes.
    assert ("review", "notes", "optional") in edges
    assert ("review", "draft", "required") not in edges
    assert {("archive", "draft", "required"), ("archive", "notes", "required")} <= edges
    assert all(
        edge.ordering_only for edge in graph.dependencies if edge.consumer_stage_id == "archive"
    )
    assert not next(
        edge
        for edge in graph.dependencies
        if edge.consumer_stage_id == "review" and edge.producer_stage_id == "produce"
    ).ordering_only
    joins = {join.consumer_stage_id: join.kind for join in graph.joins}
    assert joins == {"review": JoinKind.ANY, "archive": JoinKind.ALL}


async def compiled_configuration():  # type: ignore[no-untyped-def]
    compiler, _, _ = await service()
    result = await compiler.compile(text(promised_manifest()), scope())
    assert result.ok, result.report.blockers
    configuration = result.programs[0].configuration
    assert configuration.output_promises is not None
    return configuration


async def test_the_compiled_configuration_registers_and_drives_fulfillment() -> None:
    """Gap (c): an admitted configuration's promises registered through the real service."""

    configuration = await compiled_configuration()
    promises = configuration.output_promises
    assert promises is not None
    # The compiled completion names the definition's criteria vocabulary.
    assert promises.criteria == ("evidence_map.coverage",)
    access = InvocationAccess(
        origin=origin(),
        subject="mission-control-runtime",
        invocation_id="inv-1",
        authenticated_at=datetime(2026, 10, 27, tzinfo=UTC),
    )
    store = InMemoryOutputContractStore()
    submissions = SubmissionService(store.submissions, contracts=store)
    outputs = OutputFulfillmentService(store, submissions)
    host = host_access(access.scope)
    registered = await outputs.register_promises(
        host, access.origin.run_id, promises, configuration_digest=configuration.digest
    )
    assert isinstance(registered, tuple)
    assert [item.key for item in registered] == [item.key for item in promises.obligations]
    assert await store.promise_set(access.scope, access.origin.run_id) == promises
    await outputs.pin_invocation(host, access)
    run = Stack(
        store, submissions, outputs, access, host, host_access(access.scope, role="assessor")
    )
    ack = await run.submit(
        "c-1", "synthesize.summary", text_candidate("summary", "# Summary"), position="synthesize"
    )
    await run.accept(ack, "synthesize.summary")
    result = await run.evaluate()
    assert fulfillment(result, "synthesize.summary").disposition == "fulfilled"
    assert result.completion == "waiting" and "synthesize.claims" in result.blocking


async def test_a_duplicate_output_name_is_a_manifest_issue() -> None:
    document = minimal()
    outputs = document["mission"]["program"]["nodes"][1]["outputs"]
    outputs.append(dict(outputs[0]))
    compiler, _, _ = await service()
    result = await compiler.compile(text(document), scope())
    assert ("/mission/program/nodes/1/outputs", "duplicate_output") in reasons(result)
