"""Readable evidence for ordinary accepted same-app linked transfer; no runtime authority."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import UUID

from temporalio.service import RPCError, RPCStatusCode
from tests.fixtures.overnight_stagegraph_evidence import (
    export_stagegraph,
    observed_report_parts,
    output_export_metadata,
)

from mission_control.adapters.postgres.chains.store import PostgresChainReader
from mission_control.adapters.postgres.knowledge.output_contracts import PostgresOutputContractStore
from mission_control.contracts.identities import mission_root_id
from mission_control.domain.context.transfer import (
    LinkedExport,
    LinkedOutputRef,
    SealedTransferPlan,
)
from mission_control.domain.outputs.contracts import ExactOutput


def write_exact_report_part(path: Path, text: str, *, digest: str, byte_length: int) -> None:
    """Preserve the observed UTF8 receipt bytes, including LF, on every host platform."""
    raw = text.encode("utf-8")
    if len(raw) != byte_length or "sha256:" + hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("observed report part differs from its exact receipt")
    path.write_bytes(raw)
    if path.read_bytes() != raw:
        raise ValueError("exported report part differs from its observed bytes")


def verify_export_output(
    export: LinkedExport, selected: LinkedOutputRef, output: ExactOutput
) -> None:
    if (
        output.run_id,
        output.obligation_key,
        output.obligation_revision,
        output.revision_id,
        output.content_digest,
    ) != (
        export.source_run_id,
        selected.obligation_key,
        selected.obligation_revision,
        selected.revision_id,
        selected.content_digest,
    ):
        raise ValueError("released export differs from its exact scoped source revision")


def expected_never_started_root(
    projection: dict[str, Any],
    *,
    model_calls: list[dict[str, Any]],
    binding_count: int,
    output_count: int,
    provider_frame_count: int,
) -> bool:
    return (
        projection.get("phase") == "terminal"
        and projection.get("terminal_outcome") == "cancelled"
        and "execution_target" in projection
        and projection["execution_target"] is None
        and not model_calls
        and binding_count == 0
        and output_count == 0
        and provider_frame_count == 0
    )


def matching_receiver_output_reads(
    reads: list[dict[str, Any]], outputs: list[ExactOutput] | tuple[ExactOutput, ...], tenant: str
) -> list[dict[str, Any]]:
    """A received source becomes receiver output evidence only after exact authored adoption."""
    candidates = {
        (item.candidate.get("ref"), item.content_digest)
        for item in outputs
        if item.form == "reference"
    }
    matched = []
    for item in reads:
        answer = item.get("read") or {}
        report = (((answer.get("result") or {}).get("content") or {}).get("manifest") or {}).get(
            "report", {}
        )
        handle = f"kh:{report.get('binding')}/report/{report.get('id')}@{report.get('version')}"
        if (
            answer.get("ok")
            and report.get("tenant") == tenant
            and (handle, report.get("digest")) in candidates
        ):
            matched.append(item)
    return matched


def governed_cancel_applied(commands: dict[str, Any], scope: str, run_id: str) -> bool:
    if commands.get("status") != 200:
        return False
    for item in commands["body"].get("commands", []):
        command = item["command"]
        if (command["request_scope"], command["run_id"], command["kind"]) != (
            scope,
            run_id,
            "cancel",
        ):
            continue
        if (
            command["target"]["kind"] != "run_control"
            or command["target"]["root_workflow_id"] is not None
        ):
            continue
        states = {
            receipt["state"]
            for receipt in item["receipts"]
            if receipt["command_id"] == command["command_id"]
            and receipt["request_scope"] == scope
            and receipt["run_id"] == run_id
        }
        if {"accepted", "applied"} <= states:
            return True
    return False


def absence_readables(destination: Path, proof: dict[str, Any]) -> None:
    materialization = destination / "03-materialized"
    materialization.mkdir(parents=True, exist_ok=True)
    disposition = materialization / "observations.json"
    if not disposition.exists():
        disposition.write_text(
            json.dumps(
                {
                    "status": proof["status"],
                    "observations": [],
                    "reason": "No materialization; see scoped absence proof.",
                    "evidence": "../06-evidence/expected-absence.json",
                },
                indent=2,
            ),
            encoding="utf-8",
            newline="\n",
        )
    for folder in ("03-materialized", "05-outputs"):
        index = destination / folder / "INDEX.md"
        text = index.read_text(encoding="utf-8") if index.exists() else "# Expected absence\n"
        text = text.replace(
            "[Raw observed manifests/receipts](observations.json)",
            "[Explicit absence disposition](observations.json)",
        )
        text += (
            "\nNo provider/output evidence is invented for this verified pre-cognition absence. "
            "[Scoped absence proof](../06-evidence/expected-absence.json).\n"
        )
        index.write_text(text, encoding="utf-8", newline="\n")


EXPECTED_BLOCKED_GAPS = frozenset(
    {
        "Actual materialization manifests/files require fixture-supplied observed receipts.",
        "Output report body retrieval requires an authorized content retrieval binding.",
    }
)


def blocked_provider_absence(
    runtime: dict[str, Any],
    *,
    scope: str,
    run_id: str,
    model_calls: list[dict[str, Any]],
    output_count: int,
    settlements: list[dict[str, Any]],
    receipts: dict[str, list[dict[str, Any]]],
) -> dict[str, Any] | None:
    if model_calls or output_count or runtime["provider_frames"]:
        return None
    failures = [
        item["settlement"]
        for item in settlements
        if item.get("settlement")
        and item["settlement"].get("status") == "failed"
        and item["settlement"].get("failure_code") == "context_delivery_blocked"
        and "LINK_OUTPUT_REVOKED:" in (item["settlement"].get("failure_message") or "")
    ]
    if not failures:
        return None
    matches = []
    for raw in runtime["plans"]:
        plan = SealedTransferPlan.model_validate(raw)
        if (
            plan.receiver.scope != scope
            or plan.receiver.run_id != run_id
            or plan.boundary != "linked_mission"
        ):
            continue
        required = {item.member_key for item in plan.exact_sources if item.required}
        for receipt in receipts.get(plan.plan_id, []):
            if receipt["result"] != "refused" or receipt["plan_digest"] != plan.digest:
                continue
            denied = [
                item
                for item in receipt["delivered"]
                if item["member_key"] in required
                and item["access_ok"] is False
                and item.get("code") == "LINK_OUTPUT_REVOKED"
            ]
            typed = [
                item
                for item in receipt["findings"]
                if item["member_key"] in required
                and item["code"] == "LINK_OUTPUT_REVOKED"
                and not item["waiting"]
            ]
            if denied and typed:
                matches.append(
                    {
                        "plan_id": plan.plan_id,
                        "plan_digest": plan.digest,
                        "receipt": receipt,
                        "required_denied_members": denied,
                    }
                )
    return (
        None
        if not matches
        else {
            "status": "expected_blocked_before_provider",
            "run_id": run_id,
            "model_calls": 0,
            "output_revisions": 0,
            "provider_frames": 0,
            "typed_settlements": failures,
            "required_input_refusals": matches,
        }
    )


async def export_linked(
    stack: Any,
    scope: str,
    destination: Path,
    *,
    chain_id: UUID,
    runs: dict[str, str],
    script: Any,
    lane: Any,
    reviews: list[dict[str, Any]],
    relay_reports: list[Any],
    timeline: list[dict[str, Any]],
) -> list[str]:
    evidence = destination / "06-evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    gaps: list[str] = []
    store = PostgresOutputContractStore(stack.worker_pool)
    for name, run_id in runs.items():
        run_destination = destination / name
        run_destination.mkdir(parents=True, exist_ok=True)
        reads = (
            script.source.reads
            if name == "source"
            else matching_receiver_output_reads(
                script.consumer.reads,
                await store.finalized_outputs(scope, run_id),
                scope.rsplit("/", 1)[-1],
            )
        )
        run_gaps = await export_stagegraph(
            stack,
            scope,
            run_id,
            run_destination,
            observed_reads=reads,
            observed_evaluators=lane.startup_receipt["fixture_evaluators"]["calls"],
        )
        from mission_control.adapters.postgres.context.transfer_plans import (
            PostgresTransferPlanStore,
        )
        from mission_control.adapters.postgres.run_control import canonical as mc

        runtime = json.loads(
            (run_destination / "06-evidence/persisted-runtime.json").read_text(encoding="utf-8")
        )
        settlement_records = json.loads(
            (run_destination / "06-evidence/operation-settlements.json").read_text(encoding="utf-8")
        )
        plan_store = PostgresTransferPlanStore(stack.worker_pool)
        receipt_records = {
            raw["plan_id"]: [
                item.model_dump(mode="json")
                for item in await plan_store.receipts(scope, raw["plan_id"])
            ]
            for raw in runtime["plans"]
        }
        async with stack.worker_pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            output_count = await connection.fetchval(
                "SELECT count(*) FROM mission_control.output_revision WHERE "
                "installation_id=$1 AND application_id=$2 AND tenant_id=$3 AND run_id=$4::uuid",
                *args,
                run_id,
            )
        expected_absence = blocked_provider_absence(
            runtime,
            scope=scope,
            run_id=run_id,
            model_calls=[row for row in stack.model_log if row.get("run_id") == run_id],
            output_count=output_count,
            settlements=settlement_records,
            receipts=receipt_records,
        )
        if expected_absence is not None:
            classified = [gap for gap in run_gaps if gap in EXPECTED_BLOCKED_GAPS]
            expected_absence["original_collector_gaps"] = run_gaps
            expected_absence["expected_absences"] = classified
            (run_destination / "06-evidence/expected-absence.json").write_text(
                json.dumps(expected_absence, indent=2), encoding="utf-8", newline="\n"
            )
            run_gaps = [gap for gap in run_gaps if gap not in EXPECTED_BLOCKED_GAPS]
            for folder in ("03-materialized", "05-outputs"):
                with (run_destination / folder / "INDEX.md").open(
                    "a", encoding="utf-8", newline="\n"
                ) as index_file:
                    index_file.write(
                        "\nProvider/output absence is expected after an actual required-input "
                        "revocation refusal; zero model calls, output revisions and frames. "
                        "[Scoped receipt/settlement proof](../06-evidence/expected-absence.json).\n"
                    )
            absence_readables(run_destination, expected_absence)
        root_path = run_destination / "06-evidence/root-history.json"
        try:
            history = await stack.client.get_workflow_handle(
                mission_root_id(scope, run_id)
            ).fetch_history()
            root_path.write_text(history.to_json(), encoding="utf-8", newline="\n")
        except RPCError as error:
            from mission_control.bootstrap.technical_api import api

            projection = await api.state.run_control_service.get_run(scope, run_id)
            runtime = json.loads(
                (run_destination / "06-evidence/persisted-runtime.json").read_text(encoding="utf-8")
            )
            calls = [row for row in stack.model_log if row.get("run_id") == run_id]
            recorded_projection = projection.model_dump(mode="json")
            expected = error.status == RPCStatusCode.NOT_FOUND and expected_never_started_root(
                recorded_projection,
                model_calls=calls,
                binding_count=len(runtime["binding_documents"]),
                output_count=output_count,
                provider_frame_count=len(runtime["provider_frames"]),
            )
            commands = json.loads(
                (run_destination / "06-evidence/commands.0000.json").read_text(encoding="utf-8")
            )
            expected = expected and governed_cancel_applied(commands, scope, run_id)
            absence = {
                "status": "expected_not_started" if expected else "missing_root_history",
                "temporal_status": error.status.name,
                "run_id": run_id,
                "projection": recorded_projection,
                "model_calls": calls,
                "binding_count": len(runtime["binding_documents"]),
                "output_count": output_count,
                "provider_frame_count": len(runtime["provider_frames"]),
                "governed_cancel_commands": commands,
                "reason": "governed cancellation before launch"
                if expected
                else "unexplained absence",
            }
            root_path.write_text(json.dumps(absence, indent=2), encoding="utf-8", newline="\n")
            if expected:
                known = EXPECTED_BLOCKED_GAPS | {"outputs: HTTP 404"}
                absence["original_collector_gaps"] = run_gaps
                absence["expected_absences"] = [gap for gap in run_gaps if gap in known]
                (run_destination / "06-evidence/expected-absence.json").write_text(
                    json.dumps(absence, indent=2), encoding="utf-8", newline="\n"
                )
                run_gaps = [gap for gap in run_gaps if gap not in known]
                absence_readables(run_destination, absence)
            else:
                gaps.append(f"{name}: root history {error.status.name}")
        gaps.extend(f"{name}: {gap}" for gap in run_gaps)
    if "source" in runs and "consumer" in runs:
        from mission_control.adapters.postgres.chains.exports import PostgresLinkedExports

        authority = {"status": "currently_authorized", "retained_snapshots_only": False}
        try:
            exports = await PostgresLinkedExports(stack.worker_pool).released_for(
                scope, runs["consumer"], "consume"
            )
        except ValueError as error:
            from mission_control.adapters.postgres.run_control import canonical as mc
            from mission_control.bootstrap.technical_api import api

            # Diagnostic custody only: never feed retained exports back into a runtime resolver.
            async with stack.worker_pool.acquire() as connection, connection.transaction():
                args = await mc.begin(connection, scope)
                rows = await connection.fetch(
                    "SELECT payload,digest FROM mission_control.runtime_document WHERE "
                    "installation_id=$1 AND application_id=$2 AND tenant_id=$3 "
                    "AND contract='linked.export/1' AND payload->>'chain_id'=$4 "
                    "AND payload->>'receiver_run_id'=$5 "
                    "AND payload->>'receiver_position'='consume' "
                    "ORDER BY identity",
                    *args,
                    str(chain_id),
                    runs["consumer"],
                )
            retained = []
            for row in rows:
                export = LinkedExport.model_validate(mc.load(row["payload"]))
                if (
                    export.request_scope != scope
                    or export.chain_id != str(chain_id)
                    or (
                        export.receiver_run_id != runs["consumer"] or export.digest != row["digest"]
                    )
                ):
                    raise ValueError(
                        "retained linked export diagnostic identity/digest mismatch"
                    ) from error
                retained.append(export)
            exports = tuple(retained)
            projection = await api.state.run_control_service.get_run(scope, runs["consumer"])
            expected_cancel = (
                projection.phase == "terminal" and projection.terminal_outcome == "cancelled"
            )
            authority = {
                "status": "current_authority_refused",
                "reason": str(error),
                "retained_snapshots_only": True,
                "expected_terminal_cancellation": expected_cancel,
                "projection": projection.model_dump(mode="json"),
            }
            if not expected_cancel:
                gaps.append(f"consumer: current linked export authority refused: {error}")
        (evidence / "linked-export-authority.json").write_text(
            json.dumps(authority, indent=2), encoding="utf-8", newline="\n"
        )
        (evidence / "linked-exports.json").write_text(
            json.dumps(
                [
                    {"digest": export.digest, "export": export.model_dump(mode="json")}
                    for export in exports
                ],
                indent=2,
            ),
            encoding="utf-8",
            newline="\n",
        )
        # The receiving run delivers this source-owned revision. It is not a receiver output.
        source_outputs: list[ExactOutput] = []
        source_status = {}
        accepted_ids = {
            item.revision_id for item in await store.accepted_outputs(scope, runs["source"])
        }
        assessments = await store.output_assessments(scope, runs["source"])
        for export in exports:
            for selected in export.outputs:
                output = await store.output_revision(scope, selected.revision_id)
                if output is None:
                    gaps.append(f"linked source revision missing: {selected.revision_id}")
                    continue
                try:
                    verify_export_output(export, selected, output)
                except ValueError as error:
                    gaps.append(f"linked source revision mismatch: {selected.revision_id}: {error}")
                    continue
                source_status[output.revision_id] = {
                    **output_export_metadata(output, accepted_ids, assessments),
                    "purpose": export.purpose,
                    "admission": export.admission,
                    "export_id": export.export_id,
                    "producer": output.producer_origin_ref,
                    "source_run_id": output.run_id,
                    "implicit_receiver_fulfillment": False,
                }
                if output.revision_id not in {item.revision_id for item in source_outputs}:
                    source_outputs.append(output)
        (evidence / "linked-source-status-findings.json").write_text(
            json.dumps(source_status, indent=2), encoding="utf-8", newline="\n"
        )
        parts, read_gaps = observed_report_parts(
            matching_receiver_output_reads(
                script.consumer.reads, source_outputs, scope.rsplit("/", 1)[-1]
            ),
            source_outputs,
            scope.rsplit("/", 1)[-1],
        )
        gaps.extend(f"consumer linked read: {gap}" for gap in read_gaps)
        for index, part in enumerate(parts):
            text = part.pop("content")
            path = (
                destination / "consumer/03-materialized" / f"linked-read-{index}-{part['part']}.txt"
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            write_exact_report_part(
                path, text, digest=part["digest"], byte_length=part["byte_length"]
            )
            part.update(
                {
                    "path": str(path.relative_to(destination)),
                    **source_status[part["revision_id"]],
                    "delivery_status": (
                        "delivered_repair_subject"
                        if source_status[part["revision_id"]]["admission"] == "subject"
                        else "delivered_dependent_input"
                    ),
                    "owner_run_id": runs["source"],
                    "receiving_run_id": runs["consumer"],
                    "implicit_receiver_fulfillment": False,
                }
            )
        received_index = destination / "consumer/03-materialized/INDEX.md"
        with received_index.open("a", encoding="utf-8", newline="\n") as index_file:
            index_file.write("\n## Exact source-owned linked inputs\n\n")
            for part in parts:
                index_file.write(
                    f"- [{part['part']}]({Path(part['path']).name}): "
                    f"revision={part['revision_id']}, digest={part['digest']}, "
                    f"bytes={part['byte_length']}, admission={part['admission']}, "
                    f"purpose={part['purpose']}, current source status={part['status']}.\n"
                )
            index_file.write(
                "\n[Full source assessment/status/findings records](../../06-evidence/"
                "linked-source-status-findings.json). These are scoped source records; "
                "actual delivery of findings requires the sealed plan/backend read receipts. "
                "Receiving bytes never implicitly fulfills the receiver's obligations.\n"
            )
        (evidence / "linked-received-parts.json").write_text(
            json.dumps(parts, indent=2), encoding="utf-8", newline="\n"
        )
    chain = await PostgresChainReader(stack.worker_pool).inspect(scope, chain_id)
    (evidence / "chain-inspection.json").write_text(
        "null" if chain is None else chain.model_dump_json(indent=2), encoding="utf-8", newline="\n"
    )
    observed = {
        "runs": runs,
        "chain_id": str(chain_id),
        "source_contexts": script.source.contexts,
        "source_tool_calls": script.source.calls,
        "source_registration": script.source.registered,
        "source_verifier_reads": script.source.reads,
        "consumer_reads": script.consumer.reads,
        "consumer_tool_calls": script.consumer.calls,
        "summaries": script.summaries,
        "operator_reviews": reviews,
        "relay_reports": [asdict(report) for report in relay_reports],
        "timeline": timeline,
        "missing_evidence": gaps,
        "actual_provider_billed_cost_usd": 0,
        "cognition": "scripted",
        "qualification": "unrun",
    }
    (evidence / "observations.json").write_text(
        json.dumps(observed, indent=2, default=str), encoding="utf-8", newline="\n"
    )
    events: list[dict[str, Any]] = []
    for name in runs:
        path = destination / name / "04-workflow-transcript.jsonl"
        if path.is_file():
            events.extend(
                {**json.loads(line), "linked_mission": name}
                for line in path.read_text(encoding="utf-8").splitlines()
            )
    events.sort(key=lambda event: (event.get("at", ""), event.get("entry_seq", 0)))
    (destination / "04-combined-timeline.jsonl").write_text(
        "".join(json.dumps(event, default=str) + "\n" for event in events),
        encoding="utf-8",
        newline="\n",
    )
    (destination / "04-combined-timeline.md").write_text(
        "# Linked mission timeline\n\n"
        + "\n".join(
            f"- {event.get('at', '')} / {event['linked_mission']} / "
            f"{event.get('title', event.get('kind', ''))}"
            for event in events
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return gaps
