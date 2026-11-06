"""Bounded linked cognition follows actual contexts and sealed input identities."""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import HumanMessage, ToolMessage

from tests.fixtures.overnight_linked_model import (
    LinkedConsumerModel,
    linked_components,
    linked_script,
)
from tests.fixtures.rrm009_production_stack import technical_binding


def script():
    return linked_script(
        {
            "report": {"reportId": "fixture", "revision": 2},
            "assertions": [{"id": "fixture-assertion"}],
            "supportSets": [{"id": "fixture-support"}],
        }
    )


def test_actual_source_lane_binding_starts_one_grounded_candidate():
    state = script()
    technical = technical_binding()
    state.source_run = technical.binding.run_id
    state.source.output_contract_ref = "compiled-source-contract"
    state.source.obligation_refs = ("compiled-source-obligation",)
    bound = technical.binding.model_copy(update={"operation_id": "goal-iteration/1/executor"})
    components = linked_components(technical, state, [])
    model = components.model_factories[bound.model.ref.digest](bound, {})
    reply = model.invoke(
        [HumanMessage(content=str({"operation_role": "executor", "goal_iteration": 1}))]
    )
    assert reply.tool_calls[0]["name"] == "report_register"
    candidate = reply.tool_calls[0]["args"]["report"]
    assert candidate["report"]["revision"] == 1 and candidate["report"]["supersedes"] is None
    answer = model._answer({"decision": "repair_required", "accepted_obligation_refs": []})
    assert json.loads(answer.generations[0].message.content)["decision"] == "accepted"


def test_consumer_reads_selected_exact_handle_and_refuses_different_source():
    state = script()
    exact = {
        "handle": "kh:binding/report/source-r1@research-report.v2",
        "digest": "sha256:" + "a" * 64,
    }
    state.source.registered[1] = exact
    model = LinkedConsumerModel(
        run_id="consumer",
        operation_id="consumer-operation",
        position="consume",
        script=state.consumer,
        linked=state,
        log=[],
    )
    messages = [HumanMessage(content="Use the sealed linked input.")]
    messages.append(
        ToolMessage(content=exact["handle"] + "#digest=" + exact["digest"], tool_call_id="index")
    )
    result = model._reply(messages)
    assert result.generations[0].message.tool_calls[0]["args"] == exact
    messages[-1] = ToolMessage(
        content=exact["handle"] + "#digest=sha256:" + "b" * 64, tool_call_id="index"
    )
    with pytest.raises(AssertionError, match="linked sealed index differs"):
        model._reply(messages)
