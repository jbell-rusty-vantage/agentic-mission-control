"""Offline checks of observed lineage and stale verifier input refusal."""

import json

import pytest
from langchain_core.messages import HumanMessage, ToolMessage

from tests.fixtures.overnight_goal_model import GoalModel, GoalScript


def model():
    candidates = tuple(
        {
            "report": {"reportId": "report", "revision": revision},
            "assertions": [{"id": f"a{revision}"}],
            "supportSets": [{"id": f"s{revision}"}],
        }
        for revision in (1, 2)
    )
    script = GoalScript(candidates=candidates, feedback="Repair unsupported 9B to captured 7B.")
    return GoalModel(
        run_id="run",
        operation_id="operation",
        log=[],
        script=script,
        output_contract_ref="compiled-contract",
        obligation_refs=("compiled-obligation",),
    )


def context(role, iteration, feedback=""):
    return HumanMessage(
        content=f"{{'operation_role': '{role}', 'goal_iteration': {iteration}}} {feedback}"
    )


def test_successor_uses_actual_predecessor_receipt_and_leaves_fixture_unchanged():
    item = model()
    first = {"handle": "kh:test/report/one", "digest": "sha256:" + "1" * 64}
    item._reply(
        [
            context("executor", 1),
            ToolMessage(
                content=json.dumps({"ok": True, "result": {"affected": [first]}}),
                tool_call_id="register",
            ),
        ]
    )
    answer = item._reply([context("executor", 2, item.script.feedback)])
    candidate = answer.generations[0].message.tool_calls[0]["args"]["report"]
    assert candidate["report"]["supersedes"] == first
    assert "supersedes" not in item.script.candidates[1]["report"]


def test_verifier_refuses_stale_revision_before_read_or_acceptance():
    item = model()
    item.script.registered[2] = {"handle": "kh:test/report/two", "digest": "sha256:" + "2" * 64}
    stale = "kh:test/report/one#digest=sha256:" + "1" * 64
    with pytest.raises(AssertionError, match="stale or mismatched"):
        item._reply([context("verifier", 2), ToolMessage(content=stale, tool_call_id="index")])
    assert not item.script.reads


def test_current_root_context_ignores_previous_nested_role_and_iteration():
    from tests.fixtures.overnight_goal_model import goal_context

    continuation = {
        "goal_iteration": 2,
        "operation_role": "executor",
        "handoff": {"operation_role": "verifier", "goal_iteration": 1},
    }
    assert goal_context(str(continuation)) == ("executor", 2)


def test_full_feedback_can_arrive_in_separate_content_section():
    item = model()
    item.script.registered[1] = {"handle": "kh:test/report/one", "digest": "sha256:" + "1" * 64}
    continuation = {
        "operation_role": "executor",
        "goal_iteration": 2,
        "handoff": {"operation_role": "verifier", "goal_iteration": 1},
    }
    result = item._reply(
        [
            HumanMessage(content=str(continuation)),
            HumanMessage(content=item.script.feedback),
        ]
    )
    assert result.generations[0].message.tool_calls[0]["name"] == "report_register"
    assert item.script.feedback in item.script.contexts[-1]["received"]


def test_packet_preamble_placeholders_do_not_hide_actual_context():
    from tests.fixtures.overnight_goal_model import goal_context

    content = "References are run-relative: `{run_id}` stands for this run.\n" + str(
        {
            "goal_revision_id": "sha256:actual",
            "goal_iteration": 1,
            "operation_role": "executor",
            "operation_attempt": 1,
        }
    )
    assert goal_context(content) == ("executor", 1)


def test_failed_fixture_assertion_retains_actual_messages_and_reraises():
    item = model()
    with pytest.raises(AssertionError, match="actual goal context missing"):
        item._reply([HumanMessage(content="No continuation supplied.")])
    assert item.script.errors[0]["message"] == "actual goal context missing"
    assert item.script.errors[0]["received"][0]["content"] == "No continuation supplied."


def test_final_verifier_remains_repair_required_when_repair_is_disabled():
    item = model()
    item.script.accept_final = False
    current = {"handle": "kh:test/report/two", "digest": "sha256:" + "2" * 64}
    item.script.registered[2] = current
    result = item._reply(
        [
            context("verifier", 2),
            ToolMessage(
                content=current["handle"] + "#digest=" + current["digest"], tool_call_id="index"
            ),
            ToolMessage(content=json.dumps({"ok": True}), tool_call_id="read"),
        ]
    )
    observation = json.loads(result.generations[0].message.content)
    assert observation["decision"] == "repair_required"
    assert observation["accepted_obligation_refs"] == []
    assert observation["findings"] == [item.script.feedback]
