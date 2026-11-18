"""WI-01 compile proof: exact named promises in the pinned effective configuration.

A manifest's outputs compile into ``EffectiveRunConfiguration.output_promises``: one
``OutputObligation@2`` per declared output with its form, enforcement, distinct cardinality,
coverage, declared checks and pinned schema, plus a closed completion expression. Goals are
owned explicitly (never by the last stage), dependencies carry the exact bound producer output
and the authored join, and a nested Goal Loop keeps its own position.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mission_control.adapters.outputs.memory import InMemoryOutputContractStore
from mission_control.application.chains.service import ManifestStructureService
from mission_control.application.knowledge.access import InvocationAccess
from mission_control.application.outputs.fulfillment import OutputFulfillmentService
from mission_control.application.outputs.submission_service import SubmissionService
from mission_control.domain.authoring.contracts import JoinKind
from mission_control.domain.authoring.manifest_lowering import output_promises
from mission_control.domain.authoring.manifest_v2 import parse_manifest_yaml_versioned
from mission_control.domain.authoring.mission_definition import manifest_to_definition
from mission_control.domain.authoring.stagegraph_builder import (
    StageGraphStageSpec,
    StageInputBindingSpec,
    build_stagegraph_v2,
)
from mission_control.domain.outputs.contracts import (
    AllOf,
    Enforcement,
    EvaluationScope,
    OutputForm,
)
from tests.support.knowledge.gateway import origin
from tests.support.manifests.compile import minimal, reasons, scope, service, text
from tests.support.unit.authoring.output_promises_compile import (
    compiled_configuration,
    promised_manifest,
)
from tests.unit.outputs.scenario import Stack, fulfillment, host_access
from tests.unit.outputs.scenario import text as text_candidate

pytestmark = pytest.mark.asyncio


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


REPORT_COLLECTIONS = Path(__file__).resolve().parents[2] / "fixtures/manifests/sprint-oc-w3"
REPORT_PACK = {
    "reports": [
        {"reportId": f"w3-{name}", "task": {}, "fragments": [{"id": f"frag-{name}"}]}
        for name in ("a", "b", "c")
    ]
}


@pytest.mark.parametrize(
    "name", ["ai-engineer.report-collection.mission.yml", "biotech.report-collection.mission.yml"]
)
async def test_a_report_collection_lowers_to_a_goal_scoped_collection_promise(name: str) -> None:
    """Each app's report-collection manifest (frozen pack and producer profile substituted as
    the driver does) lowers to a goal-scoped required ``reports`` promise of exactly three
    report references, judged per exact revision, plus an iteration-scoped progress note,
    under a Goal Loop with at least three iterations (WI-07 / OVE-170)."""

    manifest_text = (
        (REPORT_COLLECTIONS / name)
        .read_text(encoding="utf-8")
        .replace("__PACK__", json.dumps(REPORT_PACK))
        .replace("__PRODUCER__", "producer.default")
    )
    report = ManifestStructureService().compile(manifest_text)
    assert report.ok, report.blockers
    manifest, _document = parse_manifest_yaml_versioned(manifest_text)
    ((pointer, block),) = tuple(manifest.mission_blocks())
    definition = manifest_to_definition(block, pointer=pointer, digest=report.manifest_digest)
    promises = output_promises(definition)
    assert promises is not None
    reports = promises.obligation("root.reports")
    note = promises.obligation("root.progress_note")
    assert reports is not None and note is not None
    assert reports.contract.form is OutputForm.REFERENCE
    assert reports.enforcement is Enforcement.REQUIRED
    assert reports.evaluation_scope is EvaluationScope.GOAL
    assert (reports.cardinality.min, reports.cardinality.max) == (3, 3)
    assert [item.validator for item in reports.contract.requirements] == [
        "knowledge.report.assess@1"
    ]
    assert note.evaluation_scope is EvaluationScope.ITERATION
    assert block.environment.governors.iterations >= 3  # type: ignore[union-attr]
