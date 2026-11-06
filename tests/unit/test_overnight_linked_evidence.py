"""Exact linked-report receipt bytes survive Windows text newline defaults."""

from hashlib import sha256
from pathlib import Path

import pytest

from mission_control.domain.context.transfer import LinkedExport, LinkedOutputRef
from mission_control.domain.outputs.contracts import ExactOutput
from tests.fixtures.overnight_linked_evidence import (
    blocked_provider_absence,
    expected_never_started_root,
    governed_cancel_applied,
    matching_receiver_output_reads,
    verify_export_output,
    write_exact_report_part,
)


def test_observed_unicode_lf_part_preserves_exact_utf8_receipt(tmp_path: Path) -> None:
    text = "## Exact report\n\nUnicode: café — 7B\n"
    raw = text.encode("utf-8")
    destination = tmp_path / "body.txt"
    write_exact_report_part(
        destination, text, digest="sha256:" + sha256(raw).hexdigest(), byte_length=len(raw)
    )
    assert destination.read_bytes() == raw
    assert b"\r\n" not in destination.read_bytes()


def test_mismatched_receipt_never_exports_claimed_exact_part(tmp_path: Path) -> None:
    destination = tmp_path / "body.txt"
    with pytest.raises(ValueError, match="exact receipt"):
        write_exact_report_part(destination, "actual\n", digest="sha256:" + "a" * 64, byte_length=7)
    assert not destination.exists()


@pytest.mark.parametrize(
    "change",
    [
        {"terminal_outcome": "completed"},
        {"phase": "pending"},
        {"execution_target": {"family": "StageGraph"}},
    ],
)
def test_unexplained_missing_root_is_not_expected_cancellation(change: dict) -> None:
    projection = {"phase": "terminal", "terminal_outcome": "cancelled", "execution_target": None}
    assert expected_never_started_root(
        projection, model_calls=[], binding_count=0, output_count=0, provider_frame_count=0
    )
    assert not expected_never_started_root(
        {**projection, **change},
        model_calls=[],
        binding_count=0,
        output_count=0,
        provider_frame_count=0,
    )
    assert not expected_never_started_root(
        projection,
        model_calls=[{"run_id": "r"}],
        binding_count=0,
        output_count=0,
        provider_frame_count=0,
    )
    assert not expected_never_started_root(
        projection, model_calls=[], binding_count=1, output_count=0, provider_frame_count=0
    )


@pytest.mark.parametrize(
    "tamper", [None, "run_id", "content_digest", "obligation_key", "revision_id"]
)
def test_exact_held_export_does_not_depend_on_accepted_head(tamper: str | None) -> None:
    digest = "sha256:" + "a" * 64
    selected = LinkedOutputRef(
        obligation_key="root.report",
        obligation_revision=1,
        owner_position="root",
        revision_id="held",
        content_digest=digest,
    )
    export = LinkedExport(
        export_id="e",
        request_scope="scope",
        chain_id="c",
        link_id="l",
        release_event_ref="release",
        caller_ref="chain:c",
        source_mission_id="source-mission",
        source_run_id="source",
        receiver_mission_id="receiver-mission",
        receiver_run_id="receiver",
        receiver_position="consume",
        input_name="report",
        purpose="repair",
        admission="subject",
        release_gate="execution_complete",
        gate_ref="gate",
        outputs=(selected,),
    )
    output = ExactOutput(
        revision_id="held",
        run_id="source",
        obligation_key="root.report",
        obligation_revision=1,
        deliverable_id="report",
        revision=1,
        form="reference",
        content_digest=digest,
        candidate={"ref": "kh:binding/report/r@v1", "digest": digest},
        producer_origin_ref="original-producer",
    )
    if tamper is None:
        verify_export_output(export, selected, output)
    else:
        value = "sha256:" + "b" * 64 if tamper == "content_digest" else "different"
        with pytest.raises(ValueError, match="exact scoped source"):
            verify_export_output(export, selected, output.model_copy(update={tamper: value}))


def test_only_exact_adopted_receiver_output_gets_received_report_body_evidence() -> None:
    from mission_control.contracts.knowledge_protocol import RevisionSelection, SelectedReportRead
    from tests.fixtures.knowledge_binding import report_package

    package = report_package("source-owned", "1", tenant="tenant")
    selected = SelectedReportRead(
        report=package.report, exact=True, purpose="dependent_input", selection=RevisionSelection()
    )
    answer = {
        "read": {
            "ok": True,
            "result": {
                "content": {
                    "manifest": package.answer(selected),
                    "body": package.body.decode(),
                    "ledger": package.ledger.decode(),
                }
            },
        }
    }
    handle = f"kh:{package.report.binding}/report/source-owned@research-report.v2"
    adopted = ExactOutput(
        revision_id="adopted",
        run_id="receiver",
        obligation_key="consume.adopted_report",
        obligation_revision=1,
        deliverable_id="adopted_report",
        revision=1,
        form="reference",
        content_digest=package.report.digest,
        candidate={"ref": handle, "digest": package.report.digest},
        producer_origin_ref="original-source-producer",
    )
    assert matching_receiver_output_reads([answer], [], "tenant") == []
    assert matching_receiver_output_reads([answer], [adopted], "tenant") == [answer]
    assert matching_receiver_output_reads([answer], [adopted], "other") == []
    assert (
        matching_receiver_output_reads(
            [answer],
            [adopted.model_copy(update={"content_digest": "sha256:" + "b" * 64})],
            "tenant",
        )
        == []
    )


@pytest.mark.parametrize(
    "tamper", [None, "ready", "wrong_digest", "model", "output", "frame", "settlement"]
)
def test_only_actual_required_revocation_refusal_explains_absent_provider(
    tamper: str | None,
) -> None:
    from mission_control.domain.context.transfer import Boundary
    from tests.unit.context.test_transfer_plan import report_input, report_members, seal, selection

    plan = seal(selection(report_input(), boundary=Boundary.LINKED_MISSION), report_members())
    member = plan.exact_sources[0].member_key
    runtime = {
        "provider_frames": [],
        "plans": [plan.model_dump(mode="json")],
        "binding_documents": [{"binding_id": "prepared-only"}],
    }
    receipt = {
        "result": "refused",
        "plan_digest": plan.digest,
        "delivered": [{"member_key": member, "access_ok": False, "code": "LINK_OUTPUT_REVOKED"}],
        "findings": [{"member_key": member, "code": "LINK_OUTPUT_REVOKED", "waiting": False}],
    }
    settlements = [
        {
            "settlement": {
                "status": "failed",
                "failure_code": "context_delivery_blocked",
                "failure_message": "context_delivery_blocked: LINK_OUTPUT_REVOKED:" + member,
            }
        }
    ]
    calls, count = [], 0
    if tamper == "ready":
        receipt["result"] = "ready"
    elif tamper == "wrong_digest":
        receipt["plan_digest"] = "sha256:" + "f" * 64
    elif tamper == "model":
        calls = [{"run_id": plan.receiver.run_id}]
    elif tamper == "output":
        count = 1
    elif tamper == "frame":
        runtime["provider_frames"] = [{"kind": "environment_materialized"}]
    elif tamper == "settlement":
        settlements[0]["settlement"]["failure_code"] = "runtime_failed"
    actual = blocked_provider_absence(
        runtime,
        scope=plan.receiver.scope,
        run_id=plan.receiver.run_id,
        model_calls=calls,
        output_count=count,
        settlements=settlements,
        receipts={plan.plan_id: [receipt]},
    )
    assert (actual is not None) == (tamper is None)


def test_never_started_absence_requires_scoped_cancel_accepted_and_applied() -> None:
    command = {
        "command_id": "cancel",
        "kind": "cancel",
        "request_scope": "scope",
        "run_id": "r",
        "target": {"kind": "run_control", "root_workflow_id": None},
    }
    receipts = [
        {"command_id": "cancel", "request_scope": "scope", "run_id": "r", "state": state}
        for state in ("accepted", "applied")
    ]
    document = {"status": 200, "body": {"commands": [{"command": command, "receipts": receipts}]}}
    assert governed_cancel_applied(document, "scope", "r")
    assert not governed_cancel_applied(document, "other", "r")
    assert not governed_cancel_applied({"status": 404}, "scope", "r")
    receipts.pop()
    assert not governed_cancel_applied(document, "scope", "r")
