"""Exact received bytes use part digests, never aggregate report digests."""

import hashlib
import json
from types import SimpleNamespace

from mission_control.contracts.knowledge_protocol import RevisionSelection, SelectedReportRead
from tests.fixtures.knowledge_binding import report_package
from tests.fixtures.overnight_stagegraph_evidence import (
    frame_body_matches,
    observed_auditor_bodies,
    observed_report_parts,
    output_export_metadata,
)


def test_received_report_parts_check_part_digest_and_length():
    package = report_package("exact", "1", tenant="tenant-one")
    read = SelectedReportRead(
        report=package.report, exact=True, purpose="dependent_input", selection=RevisionSelection()
    )
    manifest = package.answer(read)
    output = SimpleNamespace(
        candidate={"ref": f"kh:{package.report.binding}/report/exact@research-report.v2"},
        content_digest=package.report.digest,
        revision_id="output-one",
        producer_origin_ref="producer",
        obligation_key="produce.report",
    )
    answer = {
        "ok": True,
        "result": {
            "content": {
                "manifest": manifest,
                "body": package.body.decode(),
                "ledger": package.ledger.decode(),
            }
        },
    }
    parts, gaps = observed_report_parts([{"read": answer}], [output], "tenant-one")
    assert not gaps and {part["part"] for part in parts} == {"body", "ledger"}
    assert parts[0]["digest"] == manifest["body"]["digest"] != parts[0]["report_digest"]
    answer["result"]["content"]["body"] = "wrong bytes"
    refused, gaps = observed_report_parts([{"read": answer}], [output], "tenant-one")
    assert not refused and any("digest mismatch" in gap for gap in gaps)
    assert frame_body_matches(package.body, manifest["body"]["digest"], len(package.body))
    assert not frame_body_matches(package.body, manifest["body"]["digest"], len(package.body) + 1)


def test_auditor_body_needs_same_registration_candidate_and_artifact_digest():
    text = "exact observed report\n"
    digest = "sha256:" + hashlib.sha256(text.encode()).hexdigest()
    output = SimpleNamespace(
        candidate={"ref": "kh:binding/report/current@research-report.v2"},
        content_digest="sha256:" + "a" * 64,
        revision_id="revision",
        producer_origin_ref="producer",
        obligation_key="produce.report",
    )
    affected = [
        {"handle": output.candidate["ref"], "digest": output.content_digest},
        {"handle": "kh:binding/artifact/body@artifact.v1", "digest": digest},
    ]
    raw = json.dumps(
        {
            "name": "report_register",
            "content": json.dumps({"ok": True, "result": {"affected": affected}}),
        }
    )
    frame = {
        "kind": "tool_call_completed",
        "frame_id": "frame",
        "body": raw,
        "body_bytes": len(raw.encode()),
        "body_digest": "sha256:" + hashlib.sha256(raw.encode()).hexdigest(),
    }
    calls = [{"role": "auditor", "body": "# Assertions\n# Report body\n" + text}]
    bodies = observed_auditor_bodies(calls, [frame], [output])
    assert len(bodies) == 1 and bodies[0]["content"] == text
    assert "receipt has no byte count" in bodies[0]["length_verification"]
    output.content_digest = "sha256:" + "b" * 64
    assert not observed_auditor_bodies(calls, [frame], [output])
    assert output_export_metadata(output, set(), [])["status"] == "recorded_draft"
    assert output_export_metadata(output, {"revision"}, [])["status"] == "accepted"


def test_historical_verifier_reads_keep_both_revisions_and_actual_acceptance_status():
    outputs, reads = [], []
    for name, revision in (("prior", "1"), ("current", "2")):
        package = report_package(name, revision, tenant="tenant-one")
        selection = SelectedReportRead(
            report=package.report,
            exact=True,
            purpose="dependent_input",
            selection=RevisionSelection(),
        )
        outputs.append(
            SimpleNamespace(
                candidate={"ref": f"kh:{package.report.binding}/report/{name}@research-report.v2"},
                content_digest=package.report.digest,
                revision_id=name,
                producer_origin_ref="executor",
                obligation_key="root.report",
            )
        )
        reads.append(
            {
                "iteration": int(revision),
                "read_results": [
                    {
                        "ok": True,
                        "result": {
                            "content": {
                                "manifest": package.answer(selection),
                                "body": package.body.decode(),
                                "ledger": package.ledger.decode(),
                            }
                        },
                    }
                ],
            }
        )
    parts, gaps = observed_report_parts(reads, outputs, "tenant-one")
    assert not gaps
    assert {part["revision_id"] for part in parts} == {"prior", "current"}
    assessment = SimpleNamespace(
        subject_kind="output_revision",
        subject_id="prior",
        subject_digest=outputs[0].content_digest,
        model_dump=lambda **_: {"result": "fail", "subject_id": "prior"},
    )
    by_revision = {output.revision_id: output for output in outputs}
    for part in parts:
        part.update(
            output_export_metadata(by_revision[part["revision_id"]], {"current"}, [assessment])
        )
    historical = [part for part in parts if part["revision_id"] == "prior"]
    assert all(part["status"] == "recorded_draft" for part in historical)
    assert all(part["assessment_results"] == ["fail"] for part in historical)
    assert all(part["status"] == "accepted" for part in parts if part["revision_id"] == "current")


def test_retained_accepted_head_is_not_presented_as_currently_usable_after_demotion() -> None:
    from mission_control.domain.outputs.contracts import Assessment, ExactOutput

    digest = "sha256:" + "a" * 64
    output = ExactOutput(
        revision_id="revision",
        run_id="run",
        obligation_key="root.report",
        obligation_revision=1,
        deliverable_id="report",
        revision=1,
        form="reference",
        content_digest=digest,
        candidate={},
        producer_origin_ref="source",
    )
    passed = Assessment(
        assessment_id="pass",
        subject_kind="output_revision",
        subject_id="revision",
        subject_digest=digest,
        requirement_results={"assessed": "pass"},
        result="pass",
        assessor_origin_ref="ks:decision",
        method_pin="knowledge.report.assess@1",
        policy_pin="policy",
        evidence_refs=("ks-use-decision:decision@" + digest,),
    )
    review = passed.model_copy(
        update={
            "assessment_id": "review",
            "result": "review",
            "requirement_results": {"assessed": "review"},
            "supersedes": "pass",
        }
    )
    normal = output_export_metadata(output, {"revision"}, [passed])
    assert normal["status"] == "accepted" and not normal["current_use_demoted"]
    demoted = output_export_metadata(output, {"revision"}, [passed, review])
    assert demoted["status"] == "accepted_head_demoted"
    assert demoted["historical_accepted_head"] and demoted["current_use_demoted"]
    assert demoted["assessment_results"] == ["pass", "review"]
    assert output_export_metadata(output, set(), [review])["status"] == "recorded_draft"
