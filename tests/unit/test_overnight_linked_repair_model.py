"""A linked repair successor requires actual held bytes and complete pinned findings first."""

import json
from copy import deepcopy
from hashlib import sha256
from typing import Any

import pytest
from deepagents.backends.utils import format_content_with_line_numbers
from langchain_core.messages import ToolMessage

from mission_control.contracts.knowledge_protocol import RevisionSelection, SelectedReportRead
from mission_control.domain.authoring.canonical import canonical_json
from tests.fixtures.knowledge_binding import report_package
from tests.fixtures.overnight_linked_repair_model import (
    LinkedRepairConsumerModel,
    linked_repair_script,
)


def setup_case() -> tuple[LinkedRepairConsumerModel, list[ToolMessage], dict[str, Any]]:
    held = {
        "report": {"reportId": "r", "revision": 1},
        "assertions": [{"id": "a1"}],
        "supportSets": [{"id": "s1"}],
    }
    grounded = {
        "report": {
            "reportId": "r",
            "revision": 2,
            "structuredBody": {"text": "Model X has 7B parameters."},
        },
        "assertions": [{"id": "a2"}],
        "supportSets": [{"id": "s2"}],
    }
    feedback = "Full finding: " + "unsupported 9B; vendor states 7B. " * 3000
    script = linked_repair_script(held, grounded, feedback=feedback)
    script.source_run = "source"
    package = report_package("r1", "1", tenant="tenant", body=b"Model X has 9B parameters.\n")
    handle = f"kh:{package.report.binding}/report/{package.report.id}@{package.report.version}"
    digest = package.report.digest
    script.source.registered[1] = {"handle": handle, "digest": digest}
    linked = {
        "export_id": "export",
        "export_digest": "sha256:" + "a" * 64,
        "output_revision_id": "held-revision",
        "output_digest": digest,
        "source_run_id": "source",
    }
    payload = {
        "schema_version": "mc.linked-subject-findings.v1",
        "export_id": "export",
        "export_digest": linked["export_digest"],
        "source_run_id": "source",
        "revision_id": "held-revision",
        "content_digest": digest,
        "admission": "subject",
        "official_use": False,
        "goal_findings": [
            {
                "payload": {
                    "verification": {
                        "decision": "repair_required",
                        "findings": [feedback],
                        "executor_identity": {
                            "iteration": {"run_id": "source", "goal_iteration": 1}
                        },
                    }
                }
            }
        ],
        "assessments": [{"result": "review"}],
    }
    raw = canonical_json(payload)
    finding = {
        "member": "report/held-revision/findings",
        "admission": "subject",
        "purpose": "repair",
        "placement": "file",
        "read_with": "read_file",
        "path": "/inputs/exact-findings.json",
        "bytes": len(raw),
        "digest": "sha256:" + sha256(raw).hexdigest(),
        "linked_source": linked,
    }
    index = {
        "schema": "mc.transfer_inputs.v1",
        "inputs": [
            {
                "member": "report/held-revision/body",
                "admission": "subject",
                "purpose": "repair",
                "access_ref": handle + "#digest=" + digest,
            },
            finding,
        ],
    }
    selected = SelectedReportRead(
        report=package.report, exact=True, purpose="repair", selection=RevisionSelection()
    )
    read = {
        "ok": True,
        "result": {
            "content": {
                "manifest": package.answer(selected),
                "body": package.body.decode(),
                "ledger": package.ledger.decode(),
            }
        },
    }
    messages = [
        ToolMessage(content="1  " + json.dumps(index), tool_call_id="index"),
        ToolMessage(content=json.dumps(read), tool_call_id="read"),
        ToolMessage(
            content=format_content_with_line_numbers(raw.decode()), tool_call_id="findings"
        ),
    ]
    model = LinkedRepairConsumerModel(
        run_id="receiver",
        operation_id="consume",
        position="consume",
        script=script.consumer,
        repair=script,
        log=[],
    )
    return model, messages, grounded


def tool(result: Any) -> dict[str, Any]:
    return result.generations[0].message.tool_calls[0]


def test_real_read_order_full_findings_and_dynamic_successor_lineage() -> None:
    model, messages, grounded = setup_case()
    before = deepcopy(grounded)
    assert tool(model._consumer([]))["name"] == "read_file"
    assert tool(model._consumer(messages[:1]))["name"] == "knowledge_read"
    call = tool(model._consumer(messages[:2]))
    assert (
        call["name"] == "read_file" and call["args"]["file_path"] == "/inputs/exact-findings.json"
    )
    call = tool(model._consumer(messages))
    assert call["name"] == "report_register"
    assert call["args"]["report"]["report"]["supersedes"] == model.repair.source.registered[1]
    assert grounded == before and "supersedes" not in model.repair.grounded["report"]
    assert (
        len(
            model.repair.repair_observations[0]["findings"]["goal_findings"][0]["payload"][
                "verification"
            ]["findings"][0]
        )
        > 80000
    )
    receipt = ToolMessage(
        content=json.dumps(
            {
                "ok": True,
                "result": {
                    "affected": [
                        {
                            "handle": "kh:binding/report/actual-successor@v1",
                            "digest": "sha256:" + "b" * 64,
                        }
                    ]
                },
            }
        ),
        tool_call_id="registered",
    )
    submitted = tool(model._consumer([*messages, receipt]))
    assert submitted["args"]["obligation"] == "consume.report"
    assert submitted["args"]["items"][0]["ref"] == "kh:binding/report/actual-successor@v1"


@pytest.mark.parametrize(
    "tamper", ["body", "truncated_findings", "stale_index", "missing_feedback"]
)
def test_successor_registration_refuses_missing_or_stale_observed_evidence(tamper: str) -> None:
    model, messages, _ = setup_case()
    if tamper == "body":
        read = json.loads(str(messages[1].content))
        read["result"]["content"]["body"] = "Model X has 7B parameters.\n"
        messages[1] = ToolMessage(content=json.dumps(read), tool_call_id="read")
    elif tamper == "truncated_findings":
        messages[2] = ToolMessage(content=str(messages[2].content)[:100], tool_call_id="findings")
    elif tamper == "stale_index":
        model.repair.source.registered[1]["digest"] = "sha256:" + "f" * 64
    else:
        model.repair.source.feedback = "different full feedback never delivered"
    with pytest.raises(AssertionError):
        model._consumer(messages)
    assert not model.repair.registered_successor
    assert not any(row["tool"] == "report_register" for row in model.script.calls)
