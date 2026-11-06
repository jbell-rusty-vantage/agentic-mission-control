from __future__ import annotations

import hashlib
import json
from contextlib import asynccontextmanager
from dataclasses import asdict
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from tests.fixtures.checkpoint_recovery import stage_recovery_unit
from tests.unit.claude.fixtures import claude_operation
from tests.unit.recovery.test_closed_workflow import setup_recovery
from tests.unit.recovery.test_closed_workflow_postgres_metadata import record
from tests.unit.run_control.test_run_control import NOW

from mission_control.adapters.postgres.closed_workflow import PostgresClosedWorkflowAuthority
from mission_control.adapters.storage.artifact_payloads import InMemoryArtifactPayloadStore
from mission_control.application.execution.operations.journaled_operation_execution import (
    output_payload,
)
from mission_control.application.execution.operations.operation_execution import (
    bind_operation_execution_request,
    settlement_result_manifest,
)
from mission_control.application.frames.sink import harness_execution_id
from mission_control.contracts.contracts import MissionControlRejected
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.execution.contracts import (
    OperationExecutionBinding,
    OperationSettlement,
    RuntimeUsage,
)
from mission_control.domain.execution.journal import OperationJournalSettlement
from mission_control.domain.execution.lane_turns import ClosingFacts
from mission_control.domain.execution.lanes import UsageReport
from mission_control.domain.policies.contracts import (
    BudgetApplicability,
    BudgetDimensionLimit,
    BudgetState,
    UsageRecord,
)
from mission_control.domain.programs.contracts import (
    ExecutionIdentity,
    ProducerLiability,
    ResultDecision,
    StageCandidateIdentity,
    StageGraphAcceptedProjection,
    StageGraphDecisionMutation,
    StageInstanceProjection,
)


class Connection:
    def __init__(self, rows, head, settlement, binding, run):
        self.rows, self.head, self.settlement, self.binding, self.run = (
            rows,
            head,
            settlement,
            binding,
            run,
        )
        self.readonly = False
        self.statements = []

    @asynccontextmanager
    async def transaction(self, **kwargs):
        self.readonly = kwargs == {"isolation": "repeatable_read", "readonly": True}
        yield

    async def execute(self, sql, *_args):
        self.statements.append(sql)
        assert "set_config" in sql or "SET LOCAL" in sql or "set_request_scope" in sql

    async def fetchrow(self, sql, *_args):
        self.statements.append(sql)
        if "mission_run" in sql:
            return {"version": self.run.version, "run_id": uuid4()}
        if "runtime_document" in sql:
            return self.binding
        raise AssertionError("unexpected SQL")

    async def fetchval(self, sql, *_args):
        self.statements.append(sql)
        if "family_admission_head" in sql:
            return self.head.model_dump(mode="json")
        if "operation_settlement" in sql:
            return self.settlement.model_dump(mode="json")
        raise AssertionError("unexpected SQL")

    async def fetch(self, sql, *_args):
        self.statements.append(sql)
        return next(
            value
            for table, value in self.rows.items()
            if "mission_control." + table + " " in " ".join(sql.split())
        )


class Pool:
    def __init__(self, connection):
        self.connection = connection

    @asynccontextmanager
    async def acquire(self):
        yield self.connection


async def scenario(monkeypatch):
    _, controls, _, _, _, _, run_id = await setup_recovery()
    scope = f"mc/{uuid4()}/app/{uuid4()}"
    run = (await controls.get_run("tenant-1", run_id)).model_copy(update={"request_scope": scope})
    unit = stage_recovery_unit(run_id, request_scope=scope)
    op = claude_operation()
    op = op.model_copy(
        update={
            "request_scope": scope,
            "runtime_unit": unit,
            "identity": op.identity.model_copy(
                update={
                    "run_id": run_id,
                    "operation_id": unit.semantic_operation_id,
                    "operation_attempt": unit.semantic_attempt,
                }
            ),
            "effective_configuration_digest": run.effective_configuration_digest,
        }
    )
    binding = bind_operation_execution_request(op)
    heid = harness_execution_id(
        request_scope=scope,
        run_key=run_id,
        activation_key=unit.unit_key,
        attempt_no=1,
        lane="claude_agent_sdk",
    )
    sid, tid = uuid4(), uuid4()
    dispatch = record()
    request_ref = "operation-request:" + sha256_digest(binding.semantic_attempt_key)[7:]
    family = StageGraphAcceptedProjection(
        ExecutionIdentity(run_id),
        1,
        3,
        stages={
            "probe": StageInstanceProjection(
                StageCandidateIdentity("draft", 0, "NO_MAPPED_INSTANCE", 0, 0, "default"),
                status="completed",
                semantic_attempt=1,
                admitted_operation_request_ref=request_ref,
            )
        },
        producer_liabilities={
            binding.semantic_attempt_key: ProducerLiability(
                binding.semantic_attempt_key,
                "reservation",
                child_closed_or_quiesced=True,
                reservations_and_usage_settled=True,
                effects_settled=True,
                cancellation_reconciled=True,
                result_decision=ResultDecision.ADMIT,
            )
        },
    )
    head = StageGraphDecisionMutation(
        mutation_id="decision-1",
        request_scope=scope,
        run_id=run_id,
        expected_family_version=0,
        exact_operation_request_ref=request_ref,
        decided_at=NOW,
        decision_kind="result_decided",
        prior_projection_digest="sha256:" + "a" * 64,
        next_projection_digest=family.digest,
        decision_payload={"projection": asdict(family)},
    )
    settlement = OperationJournalSettlement.create(
        settlement_id="settlement",
        request_scope=scope,
        effect_claim_id="claim",
        settlement_revision=1,
        status="completed",
        settled_at=NOW,
        usage={"tokens.total": 112976},
        released_usage={},
        pending_external_usage={},
        detail={},
    )
    rows = {
        "command": [{"command_id": uuid4(), "lifecycle": "rejected"}],
        "operation_claim": [
            {
                "claim_key": "claim",
                "status": "settled",
                "semantic_binding_key": binding.binding_id,
                "semantic_attempt_key": binding.semantic_attempt_key,
            }
        ],
        "harness_execution": [
            {
                "harness_execution_id": heid,
                "native_session_ref": "actual-native",
                "native_turn_ref": "actual-turn",
                "generation": 1,
                "lifecycle": "ended",
                "usage_disposition": "estimated",
                "native_identity": {
                    "native_session_ref": "actual-native",
                    "mc_dispatch": {dispatch.key: dispatch.model_dump(mode="json")},
                },
            }
        ],
        "agent_session": [
            {
                "session_id": sid,
                "harness_execution_id": heid,
                "native_session_ref": "actual-native",
                "state": "closed",
                "ended_at": NOW,
            }
        ],
        "session_turn": [
            {
                "turn_id": tid,
                "native_turn_ref": "actual-turn",
                "session_id": sid,
                "execution_generation": 1,
                "execution_outcome": "succeeded",
                "ended_frame_id": uuid4(),
            }
        ],
    }
    payload = binding.model_dump(mode="json")
    connection = Connection(
        rows, head, settlement, {"payload": payload, "digest": sha256_digest(payload)}, run
    )
    from mission_control.adapters.postgres.closed_workflow import mc

    monkeypatch.setattr(mc, "begin", AsyncMock(return_value=(uuid4(), "app", uuid4())))
    return PostgresClosedWorkflowAuthority(Pool(connection)), connection, run


@pytest.mark.asyncio
async def test_exact_journal_harness_session_turn_join_and_readonly_metadata(monkeypatch):
    reader, connection, run = await scenario(monkeypatch)
    first = await reader._read(run)
    second = await reader.read(run)
    assert first == second
    assert connection.readonly
    assert first.family.producer_liabilities
    assert first.fingerprint.startswith("sha256:")
    assert all(sql.lstrip().startswith("SELECT") for sql in connection.statements)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "extra_harness",
        "missing_harness",
        "foreign_session",
        "missing_turn",
        "pending_command",
        "active_claim",
        "bad_binding_digest",
        "unknown_dispatch",
        "wrong_admitted_ref",
        "dangling_current_turn",
        "json_only_native_identity",
        "unknown_turn",
    ],
)
async def test_refuses_unjoined_or_unresolved_producer_evidence(monkeypatch, case):
    reader, c, run = await scenario(monkeypatch)
    if case == "extra_harness":
        c.rows["harness_execution"].append(
            {**c.rows["harness_execution"][0], "harness_execution_id": uuid4()}
        )
    if case == "missing_harness":
        c.rows["harness_execution"] = []
    if case == "foreign_session":
        c.rows["agent_session"][0]["harness_execution_id"] = uuid4()
    if case == "missing_turn":
        c.rows["session_turn"] = []
    if case == "pending_command":
        c.rows["command"][0]["lifecycle"] = "delivered"
    if case == "active_claim":
        c.rows["operation_claim"][0]["status"] = "claimed"
    if case == "bad_binding_digest":
        c.binding["digest"] = "sha256:" + "0" * 64
    if case == "unknown_dispatch":
        c.rows["harness_execution"][0]["native_identity"]["mc_dispatch"] = []
    if case == "unknown_turn":
        c.rows["session_turn"][0]["execution_outcome"] = "unknown"
    if case == "dangling_current_turn":
        c.rows["harness_execution"][0]["native_turn_ref"] = "not-retained"
    if case == "json_only_native_identity":
        c.rows["harness_execution"][0]["native_session_ref"] = None
    if case == "wrong_admitted_ref":
        from pydantic import TypeAdapter

        payload = c.head.decision_payload["projection"]
        payload["stages"]["probe"]["admitted_operation_request_ref"] = "operation-request:wrong"
        family = TypeAdapter(StageGraphAcceptedProjection).validate_python(payload)
        c.head = c.head.model_copy(update={"next_projection_digest": family.digest})
    with pytest.raises(MissionControlRejected):
        await reader.read(run)


async def unknown_cost_scenario(monkeypatch, mutation=None):
    _reader, c, run = await scenario(monkeypatch)
    c.rows["harness_execution"][0]["usage_disposition"] = "unknown"
    binding = OperationExecutionBinding.model_validate(c.binding["payload"])
    # Only slot/attempt reservation, with a separately admitted run token dimension.
    binding = binding.model_copy(
        update={"budget_limits": {"operation.attempts": 1, "concurrency.slots": 1}}
    )
    if mutation == "admitted_currency":
        binding = binding.model_copy(
            update={"budget_limits": {**binding.budget_limits, "currency.estimated_micros": 100}}
        )
    binding_payload = binding.model_dump(mode="json")
    c.binding = {"payload": binding_payload, "digest": sha256_digest(binding_payload)}
    facts = ClosingFacts(
        native_status="finished",
        cost_disposition="unknown",
        usage=UsageReport(disposition="estimated", total_tokens=112976),
    )
    if mutation == "unknown_tokens":
        facts = facts.model_copy(update={"usage": UsageReport(disposition="unknown")})
    settlement = OperationSettlement(
        settlement_id=c.settlement.settlement_id,
        binding_id=binding.binding_id,
        status="completed",
        output_text="",
        usage=RuntimeUsage(amounts={"tokens.total": 112976}),
        provider_run_id="actual-turn",
        event_payloads=({"lane_closing_facts": facts.model_dump(mode="json")},),
        settled_at=NOW,
    )
    if mutation == "native_turn":
        settlement = settlement.model_copy(update={"provider_run_id": "foreign"})
    if mutation == "binding":
        settlement = settlement.model_copy(update={"binding_id": "foreign"})
    store = InMemoryArtifactPayloadStore()
    content = output_payload(settlement)
    if mutation == "missing_facts":
        content = json.dumps({"event_payloads": []}).encode()
    address = await store.stage(
        artifact_id="output",
        content=content,
        content_digest="sha256:" + hashlib.sha256(content).hexdigest(),
        media_type="application/json",
    )
    settlement = settlement.model_copy(
        update={
            "output_payload_ref": address.object_ref,
            "output_payload_digest": address.content_digest,
            "output_payload_size_bytes": address.size_bytes,
        }
    )
    manifest = settlement_result_manifest(settlement)
    address = await store.stage(
        artifact_id="manifest",
        content=manifest,
        content_digest="sha256:" + hashlib.sha256(manifest).hexdigest(),
        media_type="application/json",
    )
    c.settlement = c.settlement.model_copy(
        update={
            "result_manifest_ref": address.object_ref,
            "result_manifest_digest": address.content_digest,
            "result_manifest_size_bytes": address.size_bytes,
        }
    )
    if mutation == "payload_digest":
        store.payloads[address.object_ref] = b"corrupt"
    if mutation == "coverage":
        c.settlement = c.settlement.model_copy(update={"usage": {"tokens.total": 1}})
    c.settlement = OperationJournalSettlement.create(**c.settlement.model_dump(mode="python"))
    budget = BudgetState(
        account_id="account",
        run_id=run.run_id,
        limits=(
            BudgetDimensionLimit(
                dimension="tokens.total", applicability=BudgetApplicability.BOUNDED, hard_cap=200000
            ),
        ),
        usage_records={
            c.settlement.settlement_id: UsageRecord(
                usage_id=c.settlement.settlement_id,
                reservation_id=binding.budget_reservation_id,
                authority_ref=binding.binding_id,
                actual_amounts={"tokens.total": 112976},
            )
        },
    )
    if mutation == "pending_currency":
        budget = budget.model_copy(
            update={"pending_settlement": {"currency.estimated_micros": 100}}
        )
    if mutation == "unbounded_currency":
        budget = budget.model_copy(
            update={
                "limits": (
                    *budget.limits,
                    BudgetDimensionLimit(
                        dimension="currency.estimated_micros",
                        applicability=BudgetApplicability.UNBOUNDED,
                    ),
                )
            }
        )
    if mutation == "missing_budget_usage":
        budget = budget.model_copy(update={"usage_records": {}})
    from mission_control.adapters.postgres.closed_workflow import mc

    monkeypatch.setattr(mc, "budget_state", AsyncMock(return_value=budget))
    return (
        PostgresClosedWorkflowAuthority(
            Pool(c), results=None if mutation == "missing_reader" else store
        ),
        c,
        run,
    )


async def test_unknown_cost_with_digest_bound_known_tokens_and_no_currency_is_eligible(monkeypatch):
    reader, c, run = await unknown_cost_scenario(monkeypatch)
    first = await reader.read(run)
    assert first == await reader.read(run)
    assert c.rows["harness_execution"][0]["usage_disposition"] == "unknown"
    assert c.readonly and all(sql.lstrip().startswith("SELECT") for sql in c.statements)


async def test_declared_unbounded_currency_without_reservation_does_not_invent_debt(monkeypatch):
    reader, _, run = await unknown_cost_scenario(monkeypatch, "unbounded_currency")
    await reader.read(run)


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_tokens",
        "native_turn",
        "binding",
        "missing_facts",
        "payload_digest",
        "coverage",
        "pending_currency",
        "admitted_currency",
        "missing_reader",
        "missing_budget_usage",
    ],
)
async def test_unknown_cost_exception_refuses_missing_or_mismatched_authority(
    monkeypatch, mutation
):
    reader, _, run = await unknown_cost_scenario(monkeypatch, mutation)
    with pytest.raises(MissionControlRejected):
        await reader.read(run)
