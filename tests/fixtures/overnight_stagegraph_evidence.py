"""Observe persisted exact outputs/plans and export failures before fixture teardown."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from scripts.overnight_evidence import export_run, observe_mission_event, redact
from tests.fixtures.overnight_read_api import overnight_read_api

from mission_control.adapters.operations.runtime_ports import FilesystemArtifactPayloadStore
from mission_control.adapters.postgres.context.transfer_plans import PostgresTransferPlanStore
from mission_control.adapters.postgres.knowledge.output_contracts import PostgresOutputContractStore
from mission_control.adapters.postgres.run_control import canonical as mc
from mission_control.application.artifacts.artifact_promotion import ArtifactPayloadAddress
from mission_control.application.outputs.submission_service import SelectedItem, report_ref
from mission_control.bootstrap.technical_api import api
from mission_control.contracts.knowledge_protocol import ResearchReportPackage
from mission_control.domain.context.transfer import SealedTransferPlan
from mission_control.domain.execution.contracts import OperationSettlement


async def verify_exact_stagegraph(stack: Any, scope: str, run_id: str, reads: list[Any]) -> None:
    store = PostgresOutputContractStore(stack.worker_pool)
    outputs = await store.accepted_outputs(scope, run_id)
    report = next(output for output in outputs if output.obligation_key == "produce.report")
    expected = f"{report.candidate['ref']}#digest={report.content_digest}"
    exact_report = report_ref(
        SelectedItem(kind="handle", ref=str(report.candidate["ref"]), digest=report.content_digest),
        tenant=scope.rsplit("/", 1)[-1],
    )
    assert exact_report is not None
    observed_reads = [item["read"] for item in reads if "read" in item]
    assert observed_reads
    for observed in observed_reads:
        assert observed["result"]["content"]["manifest"]["report"] == exact_report.model_dump(
            mode="json"
        )
    indexes = [item["index"] for item in reads if "index" in item]
    assert indexes and all(expected in index for index in indexes)
    async with stack.worker_pool.acquire() as connection, connection.transaction():
        args = await mc.begin(connection, scope)
        rows = await connection.fetch(
            "SELECT plan FROM mission_control.transfer_plan WHERE "
            "installation_id=$1 AND application_id=$2 AND tenant_id=$3 "
            "AND run_id=$4::uuid AND receiver_position='consume'",
            *args,
            run_id,
        )
    assert len(rows) == 1
    plan = SealedTransferPlan.model_validate(mc.load(rows[0]["plan"]))
    manifests = [member for member in plan.exact_sources if member.part == "manifest"]
    assert len(manifests) == 1 and manifests[0].access_ref == expected
    assert manifests[0].admission == "accepted"
    receipts = await PostgresTransferPlanStore(stack.worker_pool).receipts(scope, plan.plan_id)
    assert receipts and all(receipt.result == "ready" for receipt in receipts)
    decisions = {}
    for obligation in await store.active_obligations(scope, run_id):
        decision = await store.latest_fulfillment(
            scope, run_id, obligation.key, obligation.revision
        )
        assert decision is not None, obligation.key
        decisions[obligation.key] = decision[1]
    for key in ("produce.report", "produce.progress_note", "consume.comparison"):
        assert decisions[key].disposition == "fulfilled", decisions[key]
    assert decisions["produce.caveats"].enforcement.value == "optional"
    assert not decisions["produce.caveats"].submitted


def observed_report_parts(
    reads: list[dict[str, Any]], outputs: Any, tenant: str
) -> tuple[list[dict[str, Any]], list[str]]:
    """Keep aggregate report identity distinct from the exact bytes of each package part."""
    parts: list[dict[str, Any]] = []
    gaps: list[str] = []
    for index, item in enumerate(reads):
        answers = [item["read"]] if "read" in item else item.get("read_results", [])
        for answer in answers:
            try:
                assert answer.get("ok"), "read was refused"
                content = answer["result"]["content"]
                package = ResearchReportPackage.model_validate(content["manifest"])
                matches = [
                    output
                    for output in outputs
                    if output.candidate.get("ref")
                    and report_ref(
                        SelectedItem(
                            kind="handle",
                            ref=str(output.candidate.get("ref", "")),
                            digest=output.content_digest,
                        ),
                        tenant=tenant,
                    )
                    == package.report
                ]
                assert len(matches) == 1, "read does not match one exact finalized output revision"
                output = matches[0]
                for name in ("body", "ledger"):
                    descriptor = getattr(package, name)
                    assert descriptor is not None, "member-only read has no exact body/ledger"
                    text = content[name]
                    assert isinstance(text, str), "read part is not UTF-8 text"
                    data = text.encode("utf-8")
                    digest = "sha256:" + hashlib.sha256(data).hexdigest()
                    assert digest == descriptor.digest, f"{name} digest mismatch"
                    assert len(data) == descriptor.bytes, f"{name} byte length mismatch"
                    parts.append(
                        {
                            "content": text,
                            "digest": descriptor.digest,
                            "byte_length": descriptor.bytes,
                            "part": name,
                            "report_digest": output.content_digest,
                            "report_ref": output.candidate["ref"],
                            "revision_id": output.revision_id,
                            "producer": output.producer_origin_ref,
                            "slot": output.obligation_key,
                            "status": "recorded_draft",
                            "source": "observed knowledge_read result.content",
                            "read_index": index,
                            "manifest": package.model_dump(mode="json", by_alias=True),
                        }
                    )
            except (AssertionError, KeyError, TypeError, ValueError) as error:
                gaps.append(f"observed read {index}: {type(error).__name__}: {error}")
    return parts, gaps


def observed_auditor_bodies(
    calls: list[dict[str, Any]], frames: list[dict[str, Any]], outputs: Any
) -> list[dict[str, Any]]:
    """Recover bytes actually sent to an auditor, joined to the host registration receipt.

    The matched artifact digest proves this is the registered body, rather than a render
    of producer input. The aggregate report digest is independently matched in that receipt.
    """
    receipts = []
    for frame in frames:
        if frame.get("kind") != "tool_call_completed":
            continue
        text = frame.get("body", "")
        if not isinstance(text, str) or not frame_body_matches(
            text.encode(), frame.get("body_digest", ""), frame.get("body_bytes", -1)
        ):
            continue
        try:
            message = json.loads(text)
            answer = json.loads(message["content"])
            if message.get("name") == "report_register" and answer.get("ok"):
                receipts.append((frame["frame_id"], answer["result"]["affected"]))
        except (ValueError, KeyError, TypeError):
            continue
    bodies: list[dict[str, Any]] = []
    for index, call in enumerate(calls):
        if call.get("role") != "auditor" or "\n# Report body\n" not in call.get("body", ""):
            continue
        text = call["body"].split("\n# Report body\n", 1)[1]
        data = text.encode("utf-8")
        digest = "sha256:" + hashlib.sha256(data).hexdigest()
        for output in outputs:
            for frame_id, affected in receipts:
                if not any(
                    row.get("handle") == output.candidate.get("ref")
                    and row.get("digest") == output.content_digest
                    for row in affected
                ):
                    continue
                artifacts = [
                    row
                    for row in affected
                    if "/artifact/" in row.get("handle", "") and row.get("digest") == digest
                ]
                if not artifacts:
                    continue
                bodies.append(
                    {
                        "content": text,
                        "digest": digest,
                        "byte_length": len(data),
                        "part": "body",
                        "report_digest": output.content_digest,
                        "report_ref": output.candidate["ref"],
                        "revision_id": output.revision_id,
                        "producer": output.producer_origin_ref,
                        "slot": output.obligation_key,
                        "status": "recorded_draft",
                        "source": "observed auditor input matched to report_register receipt",
                        "auditor_call_index": index,
                        "registration_frame_id": frame_id,
                        "body_artifact": artifacts[0],
                        "length_verification": "measured UTF-8 bytes; receipt has no byte count",
                    }
                )
    return bodies


async def export_stagegraph(
    stack: Any,
    scope: str,
    run_id: str,
    destination: Path,
    *,
    observed_reads: list[dict[str, Any]] | None = None,
    observed_evaluators: list[dict[str, Any]] | None = None,
    observed_billing: dict[str, Any] | None = None,
) -> list[str]:
    (destination / "03-materialized").mkdir(parents=True, exist_ok=True)
    projection = await api.state.run_control_service.get_run(scope, run_id)
    configuration = await stack.control_plane.retrieve_for_admission(
        projection.effective_configuration_digest
    )
    bodies = []
    materializations = []
    async with stack.worker_pool.acquire() as connection, connection.transaction():
        args = await mc.begin(connection, scope)
        bindings = await connection.fetch(
            "SELECT payload FROM mission_control.runtime_document WHERE "
            "installation_id=$1 AND application_id=$2 AND tenant_id=$3 "
            "AND contract='operation.binding/1' AND payload->>'run_id'=$4",
            *args,
            run_id,
        )
        database_run_id = await connection.fetchval(
            "SELECT run_id FROM mission_control.mission_run WHERE "
            "installation_id=$1 AND application_id=$2 AND tenant_id=$3 AND run_key=$4",
            *args,
            run_id,
        )
        frames = await connection.fetch(
            "SELECT frame_id::text, kind, arrival_ordinal, observed_at, body_digest, body_bytes, "
            "body_excerpt, body_artifact_ref, lifecycle_body "
            "FROM mission_control.provider_frame WHERE "
            "installation_id=$1 AND application_id=$2 AND tenant_id=$3 AND run_id=$4::uuid "
            "ORDER BY observed_at, arrival_ordinal, frame_id",
            *args,
            database_run_id,
        )
        events = await connection.fetch(
            "SELECT seq, event_id::text, event_type, recorded_at, payload "
            "FROM mission_control.mission_event WHERE "
            "installation_id=$1 AND application_id=$2 AND tenant_id=$3 AND run_id=$4::uuid "
            "ORDER BY seq",
            *args,
            database_run_id,
        )
        plans = await connection.fetch(
            "SELECT plan FROM mission_control.transfer_plan WHERE "
            "installation_id=$1 AND application_id=$2 AND tenant_id=$3 AND run_id=$4::uuid",
            *args,
            run_id,
        )
    event_documents = [observe_mission_event(run_id, dict(row)) for row in events]
    frame_documents = []
    for frame in frames:
        row = dict(frame)
        raw = bytes(row.pop("body_excerpt"))
        row["body"] = raw.decode("utf-8", errors="replace")
        row["complete_body"] = frame_body_matches(raw, row["body_digest"], row["body_bytes"])
        frame_documents.append(row)
        if row["kind"] == "environment_materialized" and row["complete_body"]:
            materializations.append(
                {
                    "source": "mission_control.provider_frame",
                    "run_id": run_id,
                    "frame_id": row["frame_id"],
                    "manifest": json.loads(row["body"]),
                }
            )
    evidence = destination / "06-evidence"
    await asyncio.to_thread(evidence.mkdir, parents=True, exist_ok=True)
    settlements = []
    observed_ids = []
    for row in bindings:
        observed_binding = mc.load(row["payload"])
        assert observed_binding["request_scope"] == scope
        assert observed_binding["run_id"] == run_id
        observed_ids.append(observed_binding["binding_id"])
    async with stack.worker_pool.acquire() as connection, connection.transaction():
        args = await mc.begin(connection, scope)
        journal_rows = await connection.fetch(
            "SELECT DISTINCT ON (s.claim_key) c.semantic_binding_key, s.result_manifest_ref, "
            "s.result_manifest_digest, s.result_manifest_size_bytes "
            "FROM mission_control.operation_settlement s "
            "JOIN mission_control.operation_claim c ON "
            "(c.installation_id,c.application_id,c.tenant_id,c.claim_key) = "
            "(s.installation_id,s.application_id,s.tenant_id,s.claim_key) "
            "WHERE c.installation_id=$1 AND c.application_id=$2 AND c.tenant_id=$3 "
            "AND c.run_key=$4 AND c.semantic_binding_key=ANY($5::text[]) "
            "ORDER BY s.claim_key,s.settlement_revision DESC",
            *args,
            run_id,
            observed_ids,
        )
    payloads = FilesystemArtifactPayloadStore(stack.payload_root)
    for row in journal_rows:
        address = ArtifactPayloadAddress(
            object_ref=row["result_manifest_ref"],
            content_digest=row["result_manifest_digest"],
            size_bytes=row["result_manifest_size_bytes"],
        )
        manifest = await payloads.retrieve(address)
        settlement = OperationSettlement.model_validate(json.loads(manifest))
        assert settlement.binding_id == row["semantic_binding_key"]
        settlements.append(
            {
                "binding_id": settlement.binding_id,
                "source": "scoped operation_settlement with digest-verified result manifest",
                "result_manifest_address": address.model_dump(mode="json"),
                "status": "recorded",
                "settlement": settlement.model_dump(
                    mode="json",
                    include={
                        "settlement_id",
                        "binding_id",
                        "status",
                        "failure_code",
                        "failure_message",
                        "output_refs",
                        "output_payload_ref",
                        "output_payload_digest",
                        "output_payload_size_bytes",
                        "result_checkpoint",
                        "settled_at",
                    },
                ),
            }
        )
    (evidence / "operation-settlements.json").write_text(
        json.dumps(redact(settlements), indent=2, default=str), encoding="utf-8"
    )
    (evidence / "persisted-runtime.json").write_text(
        json.dumps(
            {
                "binding_documents": [mc.load(row["payload"]) for row in bindings],
                "plans": [mc.load(row["plan"]) for row in plans],
                "provider_frames": frame_documents,
                "mission_events": event_documents,
                "billing": observed_billing
                if observed_billing is not None
                else {
                    "actual_provider_cost_usd": 0,
                    "persisted_usage": "synthetic scripted fixture accounting; retained unchanged",
                },
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    store = PostgresOutputContractStore(stack.worker_pool)
    accepted = await store.accepted_outputs(scope, run_id)
    finalized = await store.finalized_outputs(scope, run_id)
    assessments = await store.output_assessments(scope, run_id)
    accepted_ids = {output.revision_id for output in accepted}
    report_parts, read_gaps = observed_report_parts(
        observed_reads or [], finalized, scope.rsplit("/", 1)[-1]
    )
    observed_body_keys = {(part["revision_id"], part["part"]) for part in report_parts}
    report_parts.extend(
        part
        for part in observed_auditor_bodies(observed_evaluators or [], frame_documents, finalized)
        if (part["revision_id"], part["part"]) not in observed_body_keys
    )
    by_revision = {output.revision_id: output for output in finalized}
    for part in report_parts:
        part.update(
            output_export_metadata(by_revision[part["revision_id"]], accepted_ids, assessments)
        )
    bodies.extend(report_parts)
    for output in finalized:
        text = output.candidate.get("text")
        if text is None and output.candidate.get("value") is not None:
            text = json.dumps(output.candidate["value"], indent=2, ensure_ascii=False)
        if isinstance(text, str):
            bodies.append(
                {
                    "content": text,
                    "digest": "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    "output_content_digest": output.content_digest,
                    "revision_id": output.revision_id,
                    "producer": output.producer_origin_ref,
                    "slot": output.obligation_key,
                    **output_export_metadata(output, accepted_ids, assessments),
                    "source": "PostgresOutputContractStore.finalized_outputs",
                }
            )
    loop = asyncio.get_running_loop()

    def request(request: httpx.Request) -> httpx.Response:
        response = asyncio.run_coroutine_threadsafe(
            public_http.request(request.method, str(request.url)), loop
        ).result(timeout=30)
        return httpx.Response(
            response.status_code,
            content=response.content,
            headers=response.headers,
            request=request,
        )

    def export() -> list[str]:
        with httpx.Client(
            transport=httpx.MockTransport(request),
            base_url=f"http://mission-control/v1/applications/{stack.database.application_id}/",
        ) as client:
            return export_run(
                client,
                run_id,
                destination,
                observed_config={
                    "source": "ControlPlaneService.retrieve_for_admission",
                    "run_id": run_id,
                    "configuration": configuration.model_dump(mode="json"),
                },
                output_bodies=bodies,
                materializations=materializations,
                observed_frames=frame_documents,
                observed_events=event_documents,
            )

    materialization_reads: list[dict[str, Any]] = []
    materialization_gaps: list[str] = []
    async with overnight_read_api(stack) as public_http:
        frame_readbacks = await recover_tool_call_frame_bodies(frame_documents, public_http, run_id)
        (evidence / "provider-frame-body-readbacks.json").write_text(
            json.dumps(frame_readbacks, indent=2), encoding="utf-8"
        )
        for index, row in enumerate(frame_documents):
            if row["kind"] != "environment_materialized" or row["complete_body"]:
                continue
            ref = row.get("body_artifact_ref")
            readback = {
                "frame_id": row["frame_id"],
                "ref": ref,
                "expected_digest": row["body_digest"],
                "expected_bytes": row["body_bytes"],
            }
            if not ref:
                materialization_gaps.append(f"materialization frame {index}: missing full-body ref")
                materialization_reads.append({**readback, "status": "missing_ref"})
                continue
            path = f"runs/{run_id}/artifacts/" + quote(ref, safe="")
            response = await public_http.get(path)
            readback["status"] = response.status_code
            if response.status_code != 200 or not frame_body_matches(
                response.content, row["body_digest"], row["body_bytes"]
            ):
                materialization_reads.append({**readback, "verified": False})
                materialization_gaps.append(
                    f"materialization frame {index}: body unavailable or digest/size mismatch"
                )
                continue
            filename = f"03-materialized/frame-body-{index:04d}.json"
            (destination / filename).write_bytes(response.content)
            materialization_reads.append({**readback, "verified": True, "file": filename})
            try:
                receipt = json.loads(response.content)
            except (ValueError, UnicodeDecodeError):
                materialization_gaps.append(
                    f"materialization frame {index}: body is not readable JSON"
                )
                continue
            materializations.append(
                {
                    "source": "run-scoped artifact body reader",
                    "run_id": run_id,
                    "frame_id": row["frame_id"],
                    "body_ref": ref,
                    "body_digest": row["body_digest"],
                    "body_bytes": row["body_bytes"],
                    "receipt": receipt,
                }
            )
        gaps = await asyncio.to_thread(export)
    from tests.fixtures.overnight_config_readable import render_configuration

    render_configuration(
        destination,
        configuration.model_dump(mode="json"),
        [mc.load(row["payload"]) for row in bindings],
        materializations,
    )
    (destination / "06-evidence/materialization-body-readbacks.json").write_text(
        json.dumps(materialization_reads, indent=2, default=str), encoding="utf-8"
    )
    with (destination / "03-materialized/INDEX.md").open("a", encoding="utf-8") as stream:
        stream.write(
            "\n[Full-body read statuses](../06-evidence/materialization-body-readbacks.json)\n"
        )
        for readback in materialization_reads:
            if readback.get("file"):
                stream.write(
                    f"\n- [Verified actual materialization body]({Path(readback['file']).name}) "
                    f"digest={readback['expected_digest']}, bytes={readback['expected_bytes']}\n"
                )
        for gap in materialization_gaps:
            stream.write(f"\n- Missing evidence: {gap}\n")
    with (destination / "05-outputs/INDEX.md").open("a", encoding="utf-8") as stream:
        stream.write("\n## Exact report parts from observed knowledge_read\n\n")
        for index, part in enumerate(report_parts):
            stream.write(
                f"- [{part['part']}](body-{index:04d}.txt): "
                f"slot={part['slot']}, revision={part['revision_id']}, "
                f"part digest={part['digest']}, bytes={part['byte_length']}; "
                f"aggregate report digest={part['report_digest']}.\n"
            )
        for gap in read_gaps:
            stream.write(f"- Missing evidence: {gap}\n")
    return [*gaps, *read_gaps, *materialization_gaps]


def frame_body_matches(data: bytes, digest: str, size: int) -> bool:
    return len(data) == size and "sha256:" + hashlib.sha256(data).hexdigest() == digest


async def recover_tool_call_frame_bodies(
    frames: list[dict[str, Any]], client: httpx.AsyncClient, run_id: str
) -> list[dict[str, Any]]:
    """Recover excerpted tool calls only when their original bytes are reproducible.

    Deep Agents retains full assistant messages, but the capture policy can retain
    only an 8 KiB prefix of the derived tool_call_started frame. The message's
    tool_calls contain the original arguments. Both the message bytes and the
    reconstructed frame must independently match their persisted digest and size.
    Existing excerpts stay untouched on any failed check.
    """
    targets = [
        row
        for row in frames
        if row["kind"] == "tool_call_started"
        and not frame_body_matches(
            row["body"].encode("utf-8"), row["body_digest"], row["body_bytes"]
        )
    ]
    if not targets:
        return []
    readbacks: list[dict[str, Any]] = []
    for source in frames:
        if source["kind"] != "message":
            continue
        raw = source["body"].encode("utf-8")
        ref = source.get("body_artifact_ref")
        if not frame_body_matches(raw, source["body_digest"], source["body_bytes"]):
            if not ref:
                continue
            try:
                response = await client.get(f"runs/{run_id}/artifacts/" + quote(ref, safe=""))
            except httpx.RequestError as exc:
                readbacks.append(
                    {
                        "source_frame_id": source["frame_id"],
                        "source_ref": ref,
                        "verified": False,
                        "error": type(exc).__name__,
                    }
                )
                continue
            readback = {
                "source_frame_id": source["frame_id"],
                "source_ref": ref,
                "expected_digest": source["body_digest"],
                "expected_bytes": source["body_bytes"],
                "http_status": response.status_code,
                "verified": response.status_code == 200
                and frame_body_matches(
                    response.content, source["body_digest"], source["body_bytes"]
                ),
            }
            readbacks.append(readback)
            if not readback["verified"]:
                continue
            raw = response.content
        try:
            message = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            continue
        if not isinstance(message, dict) or message.get("type") != "ai":
            continue
        calls = message.get("tool_calls")
        if not isinstance(calls, list):
            continue
        for call in calls:
            if not isinstance(call, dict) or not call.get("id") or not message.get("id"):
                continue
            # Match the producer's argument digest and frame-body serialization.
            args_bytes = json.dumps(
                call.get("args"), sort_keys=True, separators=(",", ":"), default=str
            ).encode("utf-8")
            body = json.dumps(
                {
                    "tool_call_id": call["id"],
                    "name": call.get("name"),
                    "args": call.get("args"),
                    "args_digest": "sha256:" + hashlib.sha256(args_bytes).hexdigest(),
                    "message_id": message["id"],
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                default=str,
            )
            for target in targets:
                if not frame_body_matches(
                    body.encode("utf-8"), target["body_digest"], target["body_bytes"]
                ):
                    continue
                provenance = {
                    "source": (
                        "digest-exact Deep Agents tool frame reconstructed "
                        "from verified assistant message"
                    ),
                    "frame_id": target["frame_id"],
                    "digest": target["body_digest"],
                    "bytes": target["body_bytes"],
                    "source_frame_id": source["frame_id"],
                    "source_ref": ref,
                    "source_digest": source["body_digest"],
                    "source_bytes": source["body_bytes"],
                    "tool_call_id": call["id"],
                    "message_id": message["id"],
                    "verified": True,
                }
                target.update(body=body, complete_body=True, body_recovery=provenance)
                readbacks.append(provenance)
    return readbacks


def output_export_metadata(output: Any, accepted_ids: set[str], assessments: Any) -> dict[str, Any]:
    from mission_control.domain.knowledge.judgment import head_demoted

    retained_head = output.revision_id in accepted_ids
    demoted = retained_head and head_demoted(assessments, output.revision_id, output.content_digest)
    exact = [
        assessment.model_dump(mode="json")
        for assessment in assessments
        if assessment.subject_kind == "output_revision"
        and assessment.subject_id == output.revision_id
        and assessment.subject_digest == output.content_digest
    ]
    return {
        "status": "accepted_head_demoted"
        if demoted
        else ("accepted" if retained_head else "recorded_draft"),
        "historical_accepted_head": retained_head,
        "current_use_demoted": demoted,
        "assessment_metadata": exact,
        "assessment_results": [assessment["result"] for assessment in exact],
        "status_basis": (
            "retained accepted head; current use demoted by standing trusted assessment"
            if demoted
            else "current accepted output head"
            if retained_head
            else "finalized output revision; no current accepted head"
        ),
    }
