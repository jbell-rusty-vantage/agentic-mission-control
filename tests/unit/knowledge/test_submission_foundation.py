"""Foundation submission behavior through the real Deep Agents StructuredTool binding."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from mission_control.adapters.deep_agents.knowledge_tools import (
    CURRENT_INVOCATION,
    LEGACY_SUBMIT_CATALOG_DIGEST,
    knowledge_launch_bindings,
    knowledge_registry_tools,
    knowledge_tools,
)
from mission_control.application.outputs.fulfillment import OutputSetRef, PromoteOutput
from mission_control.domain.outputs.contracts import OutputForm
from tests.fixtures.output_contracts import InMemoryOutputContractStore
from tests.unit.knowledge.test_knowledge_tools import lane
from tests.unit.outputs.scenario import build_stack, obligation, schema

pytestmark = pytest.mark.asyncio


async def setup():
    h = lane()
    live = replace(h.live(), position="stage/draft")
    store = InMemoryOutputContractStore()
    stack = await build_stack(
        store,
        store.submissions,
        h.toolset.access(live),
        obligation(
            "draft.note",
            OutputForm.STRUCTURED,
            position="stage/draft",
            schema_pin=schema("note@1", {"type": "object", "required": ["finding"]}),
        ),
        obligation("review.private", OutputForm.TEXT, position="stage/review"),
        clock=h.clock,
    )
    toolset = replace(h.toolset, submissions=stack.submissions)
    tools = knowledge_tools(toolset)

    async def call(args, key="call-1", actor=live, tool=None):
        token = CURRENT_INVOCATION.set(actor)
        try:
            response = await (tool or tools["submit_output"]).ainvoke(
                {"name": "submit_output", "type": "tool_call", "id": key, "args": args}
            )
            return json.loads(response.content)
        finally:
            CURRENT_INVOCATION.reset(token)

    return h, live, store, stack, tools, call


def payload(value, **kwargs):
    return {"obligation": "draft.note", "items": [{"kind": "inline", "value": value}], **kwargs}


async def test_discovery_schema_repair_and_ack_does_not_fulfill():
    _, live, store, stack, _, call = await setup()
    view = await call({"action": "inspect"})
    obligations = view["result"]["obligations"]
    assert [item["obligation"]["key"] for item in obligations] == ["draft.note"]
    assert obligations[0]["obligation"]["contract"]["schema_pin"]["body"]["required"] == ["finding"]
    assert obligations[0]["latest_submission"] is None
    invalid = await call(payload({}))
    assert invalid["refusal"]["code"] == "SCHEMA_INVALID"
    assert invalid["refusal"]["field_pointer"]
    assert invalid["refusal"]["retry_state"] == "repairable"
    assert invalid["refusal"]["recovery_owner"] == "producer"
    good = await call(payload({"finding": "supported"}, mode="progressive"), "repair")
    assert good["ok"] and good["result"]["status"] == "accepted"
    assert good["result"]["meaning"] == "recorded_draft"
    assert "findings" in good["result"]
    assert len(store.outputs) == 1
    view = await call({"action": "inspect", "obligation": "draft.note"})
    current = view["result"]["obligations"][0]
    assert current["latest_submission"]["mode"] == "progressive"
    assert current["latest_submission"]["assessment_state"] == "pending"
    assert current["accepted_heads"] == []
    frontier = await stack.outputs.pin_frontier(stack.host, stack.run_id)
    evaluated = await stack.outputs.evaluate_frontier(
        stack.host, OutputSetRef(run_id=stack.run_id, set_id=frontier.set_id)
    )
    assert all(item.disposition == "unfulfilled" for item in evaluated.fulfillments)
    recorded = (await call({"action": "inspect"}))["result"]["obligations"][0][
        "recorded_fulfillment"
    ]
    assert recorded["disposition"] == "unfulfilled"
    assert recorded["output_set_id"] == frontier.set_id
    assert "assessment_refs" not in recorded
    # Discovery never grants or creates pins for a new invocation or leaks another position.
    other = replace(live, operation_id="stage/other")
    assert (await call({"action": "inspect"}, actor=other))["result"]["obligations"] == []
    assert (await call({"action": "inspect", "obligation": "review.private"}))["ok"] is False
    assert (await call({"action": "inspect"}, actor=replace(live, position=None)))["refusal"][
        "code"
    ] == "POSITION_UNBOUND"


async def test_replay_head_move_stale_head_and_finalization_fence():
    _, _live, store, stack, _, call = await setup()
    first = await call(payload({"finding": "one"}), "one")
    first_id = first["result"]["revisions"][0]["revision_id"]
    await stack.outputs.promote_output(
        stack.host,
        PromoteOutput(
            run_id=stack.run_id,
            revision_id=first_id,
            expected_head=None,
            generation=1,
        ),
    )
    update = payload({"finding": "two"}, expected_head=first_id)
    second = await call(update, "two")
    second_id = second["result"]["revisions"][0]["revision_id"]
    await stack.outputs.promote_output(
        stack.host,
        PromoteOutput(
            run_id=stack.run_id,
            revision_id=second_id,
            expected_head=first_id,
            generation=1,
        ),
    )
    assert (await call(update, "two")) == second
    changed = await call(payload({"finding": "changed"}, expected_head=first_id), "two")
    assert changed["refusal"]["code"] == "SUBMISSION_CONFLICT"
    stale = await call(update, "new")
    assert stale["refusal"]["code"] == "STALE_HEAD"
    assert stale["refusal"]["available_actions"] == ["inspect", "submit_output"]
    head = (await call({"action": "inspect"}))["result"]["obligations"][0]["accepted_heads"]
    assert head == [{"deliverable_id": "note", "revision_id": second_id}]
    await stack.evaluate()
    recorded = (await call({"action": "inspect"}))["result"]["obligations"][0][
        "recorded_fulfillment"
    ]
    assert recorded["disposition"] == "fulfilled"
    await stack.submissions.finalize(stack.access.identity(("draft.note",)))
    assert await call(update, "two") == second
    late = await call(payload({"finding": "late"}), "late")
    assert late["refusal"]["code"] == "INVOCATION_FINALIZED"
    assert late["refusal"]["recovery_owner"] == "host"
    assert len(store.outputs) == 2


async def test_model_cannot_supply_authority_and_legacy_schema_remains_exact():
    _, live, _, _, tools, call = await setup()
    for forbidden in ("derivation_refs", "origin", "tenant", "position"):
        result = await call(payload({"finding": "x"}, **{forbidden: "injected"}))
        assert result["refusal"]["code"] == "INVALID_ENVELOPE"
        assert forbidden in result["refusal"]["field_paths"]
    evaluator = await call(payload({"finding": "x"}), actor=replace(live, evaluator=True))
    assert evaluator["refusal"]["code"] == "ROLE_SEPARATION"
    wrong = await call(payload({"finding": "x"}), actor=replace(live, position="stage/review"))
    assert wrong["refusal"]["code"] == "POSITION_MISMATCH"
    bindings = knowledge_launch_bindings(
        {"tool.knowledge-submit-output": LEGACY_SUBMIT_CATALOG_DIGEST}, tools
    )
    component = bindings["tool.knowledge-submit-output"].tool
    assert component.ref.revision == 1
    legacy = knowledge_registry_tools(tools)[component.ref.digest]
    assert all(
        word not in legacy.description for word in ("inspect", "progressive", "expected_head")
    )
    assert (await call({"action": "inspect"}, tool=legacy))["refusal"]["code"] == "INVALID_ENVELOPE"
    assert (await call(payload({"finding": "legacy"}), tool=legacy))["ok"]


async def test_registered_receipt_is_the_submission_example_and_report_mixing_refuses():
    from tests.fixtures.knowledge_binding import model_report

    h = lane()
    live = replace(h.live(), position="stage/draft")
    store = InMemoryOutputContractStore()
    stack = await build_stack(
        store,
        store.submissions,
        h.toolset.access(live),
        obligation("draft.report", OutputForm.REFERENCE, position="stage/draft"),
        clock=h.clock,
    )
    tools = knowledge_tools(replace(h.toolset, submissions=stack.submissions))
    token = CURRENT_INVOCATION.set(live)
    try:
        message = await tools["report_register"].ainvoke(
            {
                "name": "report_register",
                "type": "tool_call",
                "id": "register",
                "args": {"report": model_report("foundation")},
            }
        )
        registered = json.loads(message.content)
        assert registered["ok"]
        report = registered["result"]["affected"][0]
        item = {"kind": "handle", "ref": report["handle"], "digest": report["digest"]}
        for call_id, items in (("submit", [item]), ("mixed", [item, item])):
            message = await tools["submit_output"].ainvoke(
                {
                    "name": "submit_output",
                    "type": "tool_call",
                    "id": call_id,
                    "args": {"obligation": "draft.report", "items": items},
                }
            )
            result = json.loads(message.content)
            if call_id == "submit":
                assert result["ok"] and result["result"]["meaning"] == "recorded_draft"
            else:
                assert result["refusal"]["code"] == "SCHEMA_UNSUPPORTED"
    finally:
        CURRENT_INVOCATION.reset(token)


async def test_same_call_id_in_distinct_attempts_is_not_cross_actor_replay():
    h, live, store, stack, _, call = await setup()
    args = payload({"finding": "same content"})
    original = await call(args, "same-call")
    other = replace(live, operation_attempt=2)
    other_access = h.toolset.access(other)
    await stack.outputs.pin_invocation(stack.host, other_access)
    isolated = (await call({"action": "inspect"}, actor=other))["result"]["obligations"][0]
    assert isolated["latest_submission"] is None
    second = await call(args, "same-call", actor=other)
    assert second["ok"] and second["result"]["submission_id"] != original["result"]["submission_id"]
    assert len(store.outputs) == 2


async def test_missing_submit_arguments_name_conditional_fields_for_repair():
    _, _, _, _, _, call = await setup()
    refused = await call({})
    assert refused["refusal"]["code"] == "INVALID_ENVELOPE"
    assert set(refused["refusal"]["field_paths"]) == {"action", "obligation", "items"}
    assert refused["refusal"]["available_actions"] == ["submit_output"]
