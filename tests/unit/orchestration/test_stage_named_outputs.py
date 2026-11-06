"""Named stage settlement uses the current finalized attempt and normal host fulfillment."""

import pytest

from mission_control.application.programs.named_outputs import NamedStageOutputs
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import StageNode, StageOutputSlot
from mission_control.domain.outputs.contracts import (
    Cardinality,
    Enforcement,
    OutputForm,
    Requirement,
)
from mission_control.domain.programs.completion import OutputSchemaBinding, SchemaCriterion
from mission_control.domain.programs.contracts import StageCandidateIdentity, StageExecutionIdentity
from tests.fixtures.output_contracts import InMemoryOutputContractStore
from tests.unit.orchestration.test_stagegraph_v2 import operation_slot
from tests.unit.outputs.scenario import build_stack, obligation, schema, structured, text
from tests.unit.outputs.test_output_fulfillment import invocation


def identity(attempt=1, generation=1):
    return StageExecutionIdentity(
        invocation().origin.run_id,
        1,
        StageCandidateIdentity("draft", 0, "NO_MAPPED_INSTANCE", 0, 0, "execute"),
        attempt,
        generation,
    )


def stage():
    return StageNode(
        stage_id="draft",
        operation_slots=(operation_slot(),),
        output_slots=(
            StageOutputSlot(output_slot_id="summary", output_contract_ref="text"),
            StageOutputSlot(output_slot_id="optional", output_contract_ref="text", required=False),
        ),
    )


async def setup(*, cardinality=None):
    store = InMemoryOutputContractStore()
    current = identity()
    stack = await build_stack(
        store,
        store.submissions,
        invocation(operation_id=current.operation_id),
        obligation("draft.summary", OutputForm.TEXT, cardinality=cardinality or Cardinality()),
        obligation("draft.optional", OutputForm.TEXT, enforcement=Enforcement.OPTIONAL),
        obligation("later.summary", OutputForm.TEXT, position="later"),
    )
    return stack, NamedStageOutputs(store, stack.outputs), current


@pytest.mark.parametrize("failed", [False, True])
async def test_text_promotes_only_after_successful_current_finalization(failed):
    stack, bridge, current = await setup()
    ack = await stack.submit("submit", "draft.summary", text("note", "actual submitted text"))
    await stack.submissions.finalize(
        stack.access.identity(("draft.summary",)), attempt_failed=failed
    )
    result = await bridge.reconcile(stack.access.scope, current, stage(), {"output_refs": []})
    accepted = await stack.store.accepted_outputs(stack.access.scope, stack.run_id)
    if failed:
        assert result["output_refs"] == [] and not accepted
        recorded = await stack.store.latest_fulfillment(
            stack.access.scope, stack.run_id, "draft.summary", 1
        )
        assert recorded is not None and recorded[1].disposition == "unfulfilled"
    else:
        assert len(accepted) == 1
        assert result["output_bindings"]["summary"] == [
            f"output-revision:{ack.revisions[0].revision_id}#digest={ack.revisions[0].content_digest}"
        ]
        assert result["output_bindings"]["optional"] == []
        # Future stage's required absence does not veto this producer.
        assert result["named_output_fulfillment"]["set_id"]


@pytest.mark.parametrize("next_identity", [identity(2), identity(1, 2)])
async def test_prior_successful_head_cannot_supply_missing_current_attempt(next_identity):
    stack, bridge, current = await setup()
    await stack.submit("submit", "draft.summary", text("note", "prior attempt"))
    await stack.submissions.finalize(stack.access.identity(("draft.summary",)))
    prior = await bridge.reconcile(stack.access.scope, current, stage(), {"output_refs": []})
    assert prior["output_refs"]
    observed = await bridge.reconcile(
        stack.access.scope, next_identity, stage(), {"output_refs": []}
    )
    assert observed["output_refs"] == []
    assert observed["named_output_fulfillment"]["missing_current"] == ["draft.summary"]
    assert len(await stack.store.accepted_outputs(stack.access.scope, stack.run_id)) == 1


async def test_unfinalized_submission_is_never_promoted():
    stack, bridge, current = await setup()
    await stack.submit("submit", "draft.summary", text("note", "still running"))
    result = await bridge.reconcile(stack.access.scope, current, stage(), {"output_refs": []})
    assert not result["output_refs"]
    assert not await stack.store.accepted_outputs(stack.access.scope, stack.run_id)


async def test_prior_deliverable_cannot_complete_current_attempt_cardinality():
    stack, bridge, current = await setup(cardinality=Cardinality(min=2, max=2))
    await stack.submit("first", "draft.summary", text("a", "old a"), text("b", "old b"))
    await stack.submissions.finalize(stack.access.identity(("draft.summary",)))
    assert (await bridge.reconcile(stack.access.scope, current, stage(), {}))["output_refs"]
    second = await stack.start(invocation(2, operation_id=current.operation_id))
    ack = await second.submit("second", "draft.summary", text("a", "new a"))
    assert ack.status == "accepted"
    await second.submissions.finalize(second.access.identity(("draft.summary",)))
    result = await bridge.reconcile(second.access.scope, identity(2), stage(), {})
    assert result["output_bindings"]["summary"] == []


async def test_schema_validation_route_is_not_replaced_by_named_reference_projection():
    from mission_control.application.programs.completion_validation import validate_completion
    from tests.unit.orchestration.test_goal_schema_completion import multi_goal_request

    stack, bridge, current = await setup()
    schema_stage = stage().model_copy(
        update={
            "output_slots": multi_goal_request().completion_blueprint.output_slots,
        }
    )
    original = {"output_refs": []}
    assert await bridge.reconcile(stack.access.scope, current, schema_stage, original) is original
    validation = await validate_completion(
        None,
        request_scope=stack.access.scope,
        stage=multi_goal_request().completion_blueprint,
        interpreter=None,
        operation_result=original,
    )
    assert validation.status == "unsatisfied"
    assert validation.reason_codes


NAMED_SCHEMA = {
    "type": "object",
    "required": ["finding"],
    "properties": {"finding": {"type": "string"}},
    "additionalProperties": False,
}


async def schema_setup(*, form=OutputForm.STRUCTURED, requirements=(), optional=False):
    store, current = InMemoryOutputContractStore(), identity()
    promises = [
        obligation(
            "draft.summary",
            form,
            schema_pin=schema("finding@1", NAMED_SCHEMA),
            requirements=requirements,
        )
    ]
    if optional:
        promises.append(
            obligation("draft.optional", OutputForm.TEXT, enforcement=Enforcement.OPTIONAL)
        )
    stack = await build_stack(
        store, store.submissions, invocation(operation_id=current.operation_id), *promises
    )
    declared = [
        StageOutputSlot(
            output_slot_id="summary",
            output_contract_ref="finding@1",
            required=True,
            validation_schema=OutputSchemaBinding(
                schema_ref="finding@1",
                source_digest="sha256:" + "a" * 64,
                schema_digest=sha256_digest(NAMED_SCHEMA),
                json_schema=NAMED_SCHEMA,
            ),
        )
    ]
    if optional:
        declared.append(
            StageOutputSlot(output_slot_id="optional", output_contract_ref="text", required=False)
        )
    schema_stage = StageNode(
        stage_id="draft",
        operation_slots=(operation_slot(),),
        output_slots=tuple(declared),
        schema_criteria=(
            SchemaCriterion(
                criterion_key="finding-valid",
                obligation_ref="research",
                schema_ref="finding@1",
                output_slots=("summary",),
            ),
        ),
    )
    return stack, NamedStageOutputs(store, stack.outputs), current, schema_stage


@pytest.mark.parametrize("form", [OutputForm.STRUCTURED, OutputForm.CONTROL_RECORD])
async def test_finalized_named_value_validates_schema_before_promotion_with_optional_text_absent(
    form,
):
    stack, bridge, current, schema_stage = await schema_setup(form=form, optional=True)
    ack = await stack.submit(
        "real-submission",
        "draft.summary",
        structured(
            "note",
            {"finding": "Actual retained value"},
            schema_ref="finding@1",
            form=form,
        ),
    )
    assert ack.status == "accepted", ack.error
    assert not await stack.store.accepted_outputs(stack.access.scope, stack.run_id)
    await stack.submissions.finalize(stack.access.identity(("draft.summary", "draft.optional")))
    observed = await bridge.reconcile_with_validation(
        stack.access.scope,
        current,
        schema_stage,
        {
            "output_refs": [ack.revisions[0].revision_id],
            "output_bindings": {"summary": [ack.revisions[0].revision_id]},
        },
    )
    assert observed.validation.status == "satisfied"
    assert observed.validation.criteria[0].obligation_ref == "research"
    assert observed.result["output_bindings"]["optional"] == []
    assert observed.result["output_refs"] == [
        f"output-revision:{ack.revisions[0].revision_id}#digest={ack.revisions[0].content_digest}"
    ]
    assert observed.validation.checks[0].artifact_digest == ack.revisions[0].content_digest
    assert len(await stack.store.accepted_outputs(stack.access.scope, stack.run_id)) == 1


@pytest.mark.parametrize(
    "damage", ["digest", "candidate-digest", "form", "stage-schema", "schema-ref"]
)
async def test_invalid_named_schema_or_digest_never_promotes(damage):
    stack, bridge, current, schema_stage = await schema_setup()
    ack = await stack.submit(
        "submission",
        "draft.summary",
        structured(
            "note",
            {"finding": "Original value"},
            schema_ref="finding@1",
        ),
    )
    await stack.submissions.finalize(stack.access.identity(("draft.summary",)))
    row = await stack.store.output_revision(stack.access.scope, ack.revisions[0].revision_id)
    if damage == "digest":
        changed = row.model_copy(
            update={"candidate": {**row.candidate, "value": {"finding": "Changed"}}}
        )
        stack.store.outputs[(stack.access.scope, row.revision_id)] = changed
    elif damage == "schema-ref":
        changed = row.model_copy(
            update={"candidate": {**row.candidate, "schema_ref": "different@1"}}
        )
        stack.store.outputs[(stack.access.scope, row.revision_id)] = changed
    elif damage in {"candidate-digest", "form"}:
        field, value = (
            ("digest", "sha256:" + "f" * 64) if damage == "candidate-digest" else ("form", "text")
        )
        changed = row.model_copy(update={"candidate": {**row.candidate, field: value}})
        stack.store.outputs[(stack.access.scope, row.revision_id)] = changed
    else:
        stricter = {"type": "object", "required": ["different_field"]}
        slot = schema_stage.output_slots[0]
        binding = slot.validation_schema.model_copy(
            update={
                "json_schema": stricter,
                "schema_digest": sha256_digest(stricter),
            }
        )
        schema_stage = schema_stage.model_copy(
            update={"output_slots": (slot.model_copy(update={"validation_schema": binding}),)}
        )
    observed = await bridge.reconcile_with_validation(stack.access.scope, current, schema_stage, {})
    assert observed.validation.status == "unsatisfied"
    assert any(check.status == "unsatisfied" for check in observed.validation.checks)
    assert not await stack.store.accepted_outputs(stack.access.scope, stack.run_id)


async def test_named_schema_pass_cannot_override_independent_requirements():
    stack, bridge, current, schema_stage = await schema_setup(
        requirements=(Requirement(key="verified", validator="knowledge.report.assess@1"),)
    )
    ack = await stack.submit(
        "submission",
        "draft.summary",
        structured(
            "note",
            {"finding": "Shape valid but not independently judged"},
            schema_ref="finding@1",
        ),
    )
    assert ack.status == "accepted"
    await stack.submissions.finalize(stack.access.identity(("draft.summary",)))
    observed = await bridge.reconcile_with_validation(stack.access.scope, current, schema_stage, {})
    assert observed.result["output_refs"] == []
    assert observed.validation.status == "unsatisfied"
    assert not await stack.store.accepted_outputs(stack.access.scope, stack.run_id)


@pytest.mark.parametrize("new_identity", [identity(2), identity(1, 2)])
async def test_named_schema_never_reuses_prior_attempt_or_generation(new_identity):
    stack, bridge, current, schema_stage = await schema_setup()
    await stack.submit(
        "submission",
        "draft.summary",
        structured(
            "note",
            {"finding": "First attempt"},
            schema_ref="finding@1",
        ),
    )
    await stack.submissions.finalize(stack.access.identity(("draft.summary",)))
    assert (
        await bridge.reconcile_with_validation(stack.access.scope, current, schema_stage, {})
    ).validation.status == "satisfied"
    original = {"output_refs": []}
    observed = await bridge.reconcile_with_validation(
        stack.access.scope, new_identity, schema_stage, original
    )
    assert observed.result is original and observed.validation is None


@pytest.mark.parametrize("finalization", ["running", "failed"])
async def test_named_schema_draft_never_promotes_without_successful_finalization(finalization):
    stack, bridge, current, schema_stage = await schema_setup(optional=True)
    await stack.submit(
        "submission",
        "draft.summary",
        structured(
            "note",
            {"finding": "Only a draft"},
            schema_ref="finding@1",
        ),
    )
    if finalization == "failed":
        await stack.submissions.finalize(
            stack.access.identity(("draft.summary",)), attempt_failed=True
        )
    original = {"output_refs": []}
    observed = await bridge.reconcile_with_validation(
        stack.access.scope, current, schema_stage, original
    )
    assert observed.result is original and observed.validation is None
    assert not await stack.store.accepted_outputs(stack.access.scope, stack.run_id)
