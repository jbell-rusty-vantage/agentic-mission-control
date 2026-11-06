"""Trusted capture pins and exact immutable workflow/context readers, no external calls."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from temporalio.client import WorkflowExecutionStatus
from tests.fixtures.lane_turns import cursor_operation
from tests.unit.recovery.test_closed_workflow_postgres_authority import scenario
from tests.unit.recovery.test_closed_workflow_temporal import Client, Handle, history
from tests.unit.recovery.test_terminal_evidence_capture import IDENTITY, captured
from tests.unit.run_control.test_run_control import command

from mission_control.adapters.postgres import terminal_adoption_context as context_module
from mission_control.adapters.storage.artifact_payloads import InMemoryArtifactPayloadStore
from mission_control.adapters.storage.terminal_capture import (
    ApprovedTerminalCapture,
    ApprovedTerminalCaptureReader,
)
from mission_control.adapters.temporal.terminal_adoption_inputs import (
    TemporalTerminalInputReader,
    TerminalWorkflowInputs,
)
from mission_control.application.execution.harness.dispatch import SessionOwner
from mission_control.application.execution.harness.lane_turns import LaneExecutionIdentity
from mission_control.application.execution.operations.operation_execution import (
    bind_operation_execution_request,
)
from mission_control.application.recovery.terminal_lane_adoption import (
    AdoptionIdentity,
    AdoptionInspectionRefused,
)
from mission_control.contracts.contracts import MissionControlRejected
from mission_control.contracts.identities import mission_operation_id
from mission_control.domain.authoring.canonical import contract_fingerprint, sha256_digest
from mission_control.domain.authoring.stagegraph_builder import (
    StageGraphStageSpec,
    build_stagegraph_v2,
)
from mission_control.domain.execution.contracts import (
    OperationAttemptIdentity,
    OperationWorkflowRequest,
)
from mission_control.domain.policies.boundary_commands import (
    boundary_command_record,
    boundary_target_for,
)
from mission_control.domain.policies.contracts import (
    BoundaryCommandReceipt,
    BoundaryCommandStatus,
    CancelAction,
    ReceiptState,
)
from mission_control.domain.programs.contracts import StageGraphRunInput


async def test_capture_origin_requires_server_pin_and_exact_bytes():
    content, digest = captured()
    store = InMemoryArtifactPayloadStore()
    from mission_control.application.recovery.terminal_evidence_capture import capture_digest

    manifest = await store.stage(
        artifact_id="manifest",
        content=content.manifest,
        content_digest=digest,
        media_type="application/json",
    )
    result = await store.stage(
        artifact_id="response",
        content=content.result,
        content_digest=capture_digest(content.result),
        media_type="text/plain",
    )
    reader = ApprovedTerminalCaptureReader(
        store, {"approved": ApprovedTerminalCapture(IDENTITY, manifest, result)}
    )
    assert await reader.load_verified(IDENTITY, "approved") == content
    with pytest.raises(AdoptionInspectionRefused):
        await reader.load_verified(IDENTITY, "arbitrary/path")
    with pytest.raises(AdoptionInspectionRefused):
        await reader.load_verified(replace(IDENTITY, generation=2), "approved")


@pytest.mark.parametrize("change", [None, "counter", "source", "boolean_total"])
async def test_r1_bridge_requires_exact_private_manifest_and_separate_native_attestation(change):
    import json

    from mission_control.adapters.storage.terminal_capture import (
        ApprovedR1Capture,
        ApprovedR1CaptureReader,
    )
    from mission_control.application.recovery.terminal_evidence_capture import (
        capture_digest,
        validate_capture,
    )

    retained, _ = captured()
    body = json.loads(retained.manifest)
    sources = dict.fromkeys(("index.db", "index.db-wal", "index.db-shm"), "a" * 64)
    old = {
        "schema": "mc.r1.private-local-custody.v1",
        "public_run": IDENTITY.public_run_key,
        "internal_run": IDENTITY.internal_run_id,
        "native_agent": IDENTITY.native_session_ref,
        "native_run": IDENTITY.native_turn_ref,
        "native_status": "FINISHED",
        "total_tokens": 926070,
        "result_bytes": len(retained.result),
        "result_sha256": capture_digest(retained.result)[7:],
        "source_sha256": sources,
        "original_sqlite_opened": False,
        "private_local_only": True,
        "runtime_artifact_registered": False,
        "settlement_proven": False,
    }
    if change == "boolean_total":
        old["total_tokens"] = True
        body["usage"]["totalTokens"] = 1
    raw = json.dumps(old).encode()
    store = InMemoryArtifactPayloadStore()
    manifest = await store.stage(
        artifact_id="r1",
        content=raw,
        content_digest=capture_digest(raw),
        media_type="application/json",
    )
    result = await store.stage(
        artifact_id="r1-result",
        content=retained.result,
        content_digest=capture_digest(retained.result),
        media_type="text/plain",
    )
    pin = ApprovedR1Capture(
        IDENTITY,
        manifest,
        result,
        body["usage"],
        sources,
        body["source_evidence_digest"],
        datetime.fromisoformat(body["observed_at"]),
        datetime.fromisoformat(body["native_finished_at"]),
    )
    if change == "counter":
        pin = replace(pin, native_usage={**pin.native_usage, "totalTokens": 1})
    if change == "source":
        pin = replace(pin, source_sha256={**sources, "index.db": "b" * 64})
    reader = ApprovedR1CaptureReader(store, {"reviewed-r1": pin})
    if change:
        with pytest.raises(AdoptionInspectionRefused):
            await reader.load_verified(IDENTITY, "reviewed-r1")
    else:
        first = await reader.load_verified(IDENTITY, "reviewed-r1")
        assert first == await reader.load_verified(IDENTITY, "reviewed-r1")
        normalized = validate_capture(first, IDENTITY, capture_digest(first.manifest))
        assert normalized.usage.total_tokens == 926070 and normalized.usage.cost_micros_usd is None
        assert normalized.result == retained.result and len(store.payloads) == 2


async def context_scenario(monkeypatch):
    _, old, run = await scenario(monkeypatch)
    prior = old.binding["payload"]
    operation = cursor_operation().model_copy(
        update={
            "request_scope": run.request_scope,
            "runtime_unit": context_module.OperationExecutionBinding.model_validate(
                prior
            ).runtime_unit,
            "identity": OperationAttemptIdentity(
                run_id=run.run_id,
                operation_id=prior["operation_id"],
                operation_attempt=prior["operation_attempt"],
            ),
            "effective_configuration_digest": run.effective_configuration_digest,
        }
    )
    binding = bind_operation_execution_request(operation)
    native = old.rows["harness_execution"][0]["native_identity"]
    create = next(iter(native["mc_dispatch"].values()))
    send = context_module.DispatchRecord.model_validate(create).model_copy(
        update={"kind": "send", "native_ref": "actual-turn"}
    )
    native["mc_dispatch"][send.key] = send.model_dump(mode="json")
    native["mc_session_owner"] = SessionOwner(
        owner_ref="prior",
        epoch=1,
        generation=1,
        lease_expires_at=datetime.now(UTC) - timedelta(minutes=1),
        claimed_at=datetime.now(UTC) - timedelta(minutes=2),
    ).model_dump(mode="json")
    hid = LaneExecutionIdentity.of(operation, "cursor_local", 1).harness_execution_id
    identity = AdoptionIdentity(
        run.request_scope, run.run_id, str(uuid4()), str(hid), 1, "actual-native", "actual-turn"
    )
    old.head = old.head.model_copy(update={"decision_kind": "operation_admitted"})
    first = boundary_command_record(
        # Trusted fixture command, with the same scope/run as the fake restricted database.
        command(run.run_id, run.version, "cancel", CancelAction()).model_copy(
            update={"request_scope": run.request_scope}
        ),
        target=boundary_target_for(run, CancelAction()),
        target_sequence=1,
        accepted_run_version=run.version,
    )
    receipt = BoundaryCommandReceipt(
        command_id=first.command_id,
        idempotency_issuer=first.idempotency_issuer,
        run_id=run.run_id,
        request_scope=run.request_scope,
        ordinal=1,
        state=ReceiptState.ACCEPTED,
        recorded_by="run_control",
        recorded_at=datetime.now(UTC),
    )
    cancel = BoundaryCommandStatus(command=first, receipts=(receipt,))
    monkeypatch.setattr(context_module, "_boundary_command", AsyncMock(return_value=cancel))
    monkeypatch.setattr(
        context_module.mc,
        "budget_state",
        AsyncMock(return_value=SimpleNamespace(reservations={}, pending_settlement={})),
    )
    graph = build_stagegraph_v2(
        logical_id="test.recovery.blueprint",
        title="Recovery blueprint",
        description="Use the same typed canonical digest as admitted launch input",
        stages=(StageGraphStageSpec("probe"),),
    )
    # JSON includes additive defaults that canonical model hashing omits.
    assert sha256_digest(graph.model_dump(mode="json")) != sha256_digest(graph)
    family = StageGraphRunInput(
        run_id=run.run_id,
        request_scope=run.request_scope,
        effective_configuration_digest=run.effective_configuration_digest,
        workflow_type_digest=run.workflow_type_ref.digest,
        blueprint_digest=sha256_digest(graph),
        blueprint=graph.model_dump(mode="json"),
    )

    class Connection(type(old)):
        async def fetchrow(self, query, *args):
            if "mission_run" in query:
                return {
                    "run_id": uuid4()
                    if self.bad_run
                    else __import__("uuid").UUID(identity.internal_run_id),
                    "version": run.version,
                    "projection": run.model_dump(mode="json"),
                }
            if "runtime_document" in query:
                payload = binding.model_dump(mode="json")
                return {"payload": payload, "digest": sha256_digest(payload)}
            if "harness_execution h" in query:
                return {
                    "generation": 1,
                    "native_session_ref": "actual-native",
                    "native_turn_ref": "actual-turn",
                    "lane_profile": "cursor_local",
                    "native_identity": native,
                    "lifecycle": "live",
                    "version": 7,
                    "activation_id": uuid4(),
                    "attempt_no": 1,
                }
            raise AssertionError(query)

        async def fetch(self, query, *args):
            if "operation_claim" in query:
                return [{"claim_key": "claim", "status": "claimed"}]
            if "family_admission_journal" in query:
                return [
                    {
                        "mutation": old.head.model_dump(mode="json"),
                        "mutation_fingerprint": contract_fingerprint(
                            old.head, exclude={"decided_at"}
                        ),
                    }
                ]
            raise AssertionError(query)

    connection = Connection(old.rows, old.head, old.settlement, old.binding, run)
    connection.bad_run = False
    from tests.unit.recovery.test_closed_workflow_postgres_authority import Pool

    inputs = TerminalWorkflowInputs(
        OperationWorkflowRequest(
            semantic_attempt_id=operation.identity.semantic_key,
            operation_kind="bound_operation",
            operation=operation,
        ),
        family,
        "op-exact",
        "family-exact",
    )
    reader = context_module.PostgresTerminalAdoptionContextReader(
        Pool(connection),
        identity=identity,
        inputs=inputs,
        cancel_issuer=first.idempotency_issuer,
        cancel_command_id=first.command_id,
    )
    return reader, identity, old.head.next_projection_digest, run, connection, inputs


async def test_readonly_context_joins_exact_inputs_historical_family_and_current_authority(
    monkeypatch,
):
    reader, identity, digest, _, connection, _ = await context_scenario(monkeypatch)
    context = await reader.read(identity, digest)
    assert context.authority.admitted_currency_micros == 0
    assert context.family.projection.digest == digest and connection.readonly
    connection.bad_run = True
    with pytest.raises(AdoptionInspectionRefused):
        await reader.read(identity, digest)


async def test_pinned_workflow_inputs_use_real_typed_validation(monkeypatch):
    _, _identity, _, run, _, inputs = await context_scenario(monkeypatch)
    opid = mission_operation_id(run.request_scope, run.run_id, inputs.operation.semantic_attempt_id)
    events = history()
    events[0].workflow_execution_started_event_attributes.workflow_type.name = "mc.operation.v1"
    handles = {
        (opid, "op-exact"): Handle(opid, "op-exact", events, WorkflowExecutionStatus.FAILED),
        ("family", "family-exact"): Handle(
            "family", "family-exact", history(), WorkflowExecutionStatus.FAILED
        ),
    }
    client = Client(handles, {opid: "op-exact", "family": "family-exact"})

    async def decode(payloads, hints):
        return [inputs.operation if hints == [OperationWorkflowRequest] else inputs.family]

    client.data_converter.decode.side_effect = decode
    reader = TemporalTerminalInputReader(client)
    observed = await reader.read(
        run,
        semantic_attempt_key=inputs.operation.semantic_attempt_id,
        operation_temporal_run_id="op-exact",
        family_temporal_run_id="family-exact",
    )
    assert observed == inputs
    handles[(opid, "op-exact")].status = WorkflowExecutionStatus.RUNNING
    with pytest.raises(MissionControlRejected, match="active"):
        await reader.read(
            run,
            semantic_attempt_key=inputs.operation.semantic_attempt_id,
            operation_temporal_run_id="op-exact",
            family_temporal_run_id="family-exact",
        )
