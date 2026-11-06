"""Scoped read-only family/producer proof for closed-workflow cancellation recovery."""

from __future__ import annotations

import hashlib
import json

import asyncpg
from pydantic import TypeAdapter
from pydantic_core import to_jsonable_python

from mission_control.adapters.postgres.run_control import canonical as mc
from mission_control.application.artifacts.artifact_promotion import (
    ArtifactPayloadAddress,
)
from mission_control.application.execution.harness.dispatch import DispatchRecord
from mission_control.application.execution.operations.operation_execution import lane_usage_amounts
from mission_control.application.frames.artifact_bodies import ArtifactPayloadReader
from mission_control.application.frames.sink import harness_execution_id
from mission_control.application.recovery.closed_workflow import ProducerAuthority
from mission_control.contracts.contracts import MissionControlRejected
from mission_control.contracts.identities import mission_operation_id
from mission_control.domain.authoring.canonical import contract_fingerprint, sha256_digest
from mission_control.domain.execution.contracts import (
    OperationExecutionBinding,
    OperationSettlement,
)
from mission_control.domain.execution.journal import OperationJournalSettlement
from mission_control.domain.execution.lane_turns import ClosingFacts
from mission_control.domain.policies.boundary_commands import boundary_target_for
from mission_control.domain.policies.contracts import (
    BoundaryCommandReceipt,
    BoundaryCommandRecord,
    BudgetApplicability,
    BudgetState,
    CancelAction,
    ReceiptState,
    RunPhase,
    RunProjection,
)
from mission_control.domain.programs.contracts import (
    StageExecutionIdentity,
    StageGraphAcceptedProjection,
    StageGraphDecisionMutation,
)


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise MissionControlRejected("recovery_liability", reason)


def metadata_digest(value: object) -> str:
    """asyncpg UUID/time values need JSON primitives before canonical hashing."""
    return sha256_digest(to_jsonable_python(value))


def command_allows_cancelled_terminalization(row: dict, run: RunProjection) -> bool:
    """Only the exact accepted cancel may await the normal terminalizing commit.

    Run control records its applied receipt atomically with cancellation terminality.
    Requiring that receipt here creates a cycle. Other pending commands still fail
    closed; this predicate neither writes a receipt nor claims provider cancellation.
    """
    if row["lifecycle"] in {"applied", "rejected", "expired", "failed", "superseded"}:
        return True
    if run.phase != RunPhase.CANCELLING or row["lifecycle"] not in {"accepted", "delivered"}:
        return False
    try:
        payload = mc.load(row["payload"])
        record = BoundaryCommandRecord.model_validate(payload["record"])
        first = BoundaryCommandReceipt.model_validate(payload["initial_receipt"])
        return (
            record.kind == "cancel"
            and isinstance(record.action, CancelAction)
            and row["command_kind"] == "cancel"
            and record.request_scope == run.request_scope
            and record.run_id == run.run_id
            and record.target_sequence > 0
            and record.accepted_run_version <= run.version
            and record.payload_digest == contract_fingerprint(record.action)
            and record.payload_digest == row["payload_digest"]
            and record.target == boundary_target_for(run, record.action)
            and record.target.kind in {"root", "family"}
            and row["target_kind"] == record.target.kind
            and row["target_ref"] == record.target.target_ref
            and row["target_generation"] == record.target.execution_generation
            and row["target_version"] == record.accepted_run_version
            and row["target_sequence"] == record.target_sequence
            and row["sequence_space"] == record.target.sequence_space
            and first.state == ReceiptState.ACCEPTED
            and first.ordinal == 1
            and first.command_id == record.command_id
            and first.idempotency_issuer == record.idempotency_issuer
            and first.request_scope == record.request_scope
            and first.run_id == record.run_id
        )
    except (KeyError, TypeError, ValueError):
        return False


def validate_dispatches(native: dict, generation: int) -> None:
    raw = native.get("mc_dispatch", {})
    require(isinstance(raw, dict), "native dispatch evidence is malformed")
    for key, value in raw.items():
        try:
            record = DispatchRecord.model_validate(value)
        except ValueError:
            raise MissionControlRejected(
                "recovery_liability", "native dispatch evidence is malformed"
            ) from None
        require(
            key == record.key
            and record.expected_generation == generation
            and record.phase in {"acknowledged", "declined", "not_received"}
            and record.resolved_at is not None,
            "a native dispatch remains unresolved",
        )
        require(
            record.phase != "acknowledged" or record.native_ref is not None,
            "acknowledged dispatch has no native identity",
        )


class PostgresClosedWorkflowAuthority:
    def __init__(self, pool: asyncpg.Pool, *, results: ArtifactPayloadReader | None = None) -> None:
        self._pool = pool
        self._results = results

    async def _unknown_usage_proof(
        self,
        binding: OperationExecutionBinding,
        journal: OperationJournalSettlement,
        native_turn_ref: str,
        budget: BudgetState,
    ) -> str:
        """Unknown billing is not unknown settled usage of admitted dimensions.

        Read the same digest-bound manifest/output chain as the journal coordinator.
        This exception never creates financial usage, changes a receipt or relaxes
        native identity/terminality and run-budget guards.
        """
        results = self._results
        require(results is not None, "unknown usage requires a trusted result reader")
        assert results is not None

        async def read(ref: str | None, digest: str | None, size: int | None) -> bytes:
            require(
                bool(ref and digest) and size is not None and 0 < size <= 8_000_000,
                "terminal usage payload address is absent or exceeds bound",
            )
            assert ref is not None and digest is not None and size is not None
            content = await results.retrieve(
                ArtifactPayloadAddress(
                    object_ref=ref,
                    content_digest=digest,
                    size_bytes=size,
                )
            )
            require(
                len(content) == size and "sha256:" + hashlib.sha256(content).hexdigest() == digest,
                "terminal usage payload digest or size differs",
            )
            return content

        manifest = OperationSettlement.model_validate_json(
            await read(
                journal.result_manifest_ref,
                journal.result_manifest_digest,
                journal.result_manifest_size_bytes,
            )
        )
        require(
            manifest.binding_id == binding.binding_id
            and manifest.settlement_id == journal.settlement_id
            and manifest.provider_run_id == native_turn_ref
            and manifest.status == journal.status
            and manifest.usage.amounts == journal.usage
            and manifest.usage.pending_external_amounts == journal.pending_external_usage
            and not any(manifest.usage.pending_external_amounts.values()),
            "terminal usage manifest differs from exact settlement/native turn",
        )
        output = json.loads(
            await read(
                manifest.output_payload_ref,
                manifest.output_payload_digest,
                manifest.output_payload_size_bytes,
            )
        )
        require(
            isinstance(output, dict) and isinstance(output.get("event_payloads"), list),
            "terminal usage output has no closing facts",
        )
        closing = [
            item["lane_closing_facts"]
            for item in output["event_payloads"]
            if isinstance(item, dict) and "lane_closing_facts" in item
        ]
        require(len(closing) == 1, "terminal usage requires one exact closing fact")
        facts = ClosingFacts.model_validate(closing[0])
        require(
            facts.terminal and facts.usage.disposition in {"estimated", "settled"},
            "terminal attributable token usage remains unknown",
        )
        # Exact native status/disposition correspondence, without interpreting
        # FINISHED as provider acknowledgement of cancellation.
        statuses = {
            "finished": {"completed", "failed"},
            "error": {"failed"},
            "expired": {"failed"},
            "cancelled": {"cancelled", "failed"},
        }
        require(
            manifest.status in statuses.get(facts.native_status, set()),
            "terminal closing status differs from settlement",
        )
        require(
            budget.run_id == binding.run_id
            and not budget.reservations
            and not any(budget.reserved.values())
            and not any(budget.pending_settlement.values())
            and not budget.outstanding_usage_ids,
            "admitted run usage or reservations remain unsettled",
        )
        dimensions = frozenset(
            limit.dimension
            for limit in budget.limits
            if limit.applicability != BudgetApplicability.NOT_APPLICABLE
        )
        expected = lane_usage_amounts(binding, facts, dimensions)
        require(
            all(journal.usage.get(key) == amount for key, amount in expected.items()),
            "settlement does not cover admitted token usage",
        )
        recorded = budget.usage_records.get(journal.settlement_id)
        require(
            recorded is not None
            and recorded.authority_ref == binding.binding_id
            and recorded.reservation_id == binding.budget_reservation_id
            and recorded.actual_amounts == journal.usage
            and not any(recorded.pending_external_amounts.values()),
            "admitted usage record differs from terminal settlement",
        )
        # A financial dimension actually admitted must have an attributable amount;
        # an absent currency reservation is never replaced by an invented one.
        currency = {
            key
            for key, value in binding.budget_limits.items()
            if key.startswith("currency.") and value > 0
        }
        require(
            not currency
            or (
                facts.usage.cost_micros_usd is not None
                and facts.cost_disposition == "settled"
                and all(journal.usage.get(key) == facts.usage.cost_micros_usd for key in currency)
            ),
            "admitted financial usage remains unknown",
        )
        return metadata_digest(
            {
                "manifest": journal.result_manifest_digest,
                "output": manifest.output_payload_digest,
                "budget": budget.model_dump(mode="json"),
            }
        )

    async def read(self, run: RunProjection) -> ProducerAuthority:
        try:
            return await self._read(run)
        except MissionControlRejected:
            raise
        except Exception:
            raise MissionControlRejected(
                "unavailable", "scoped producer authority is unavailable"
            ) from None

    async def _read(self, run: RunProjection) -> ProducerAuthority:
        target = run.execution_target
        require(
            target is not None and target.family == "StageGraph",
            "an exact StageGraph target is required",
        )
        assert target is not None
        async with (
            self._pool.acquire() as connection,
            connection.transaction(isolation="repeatable_read", readonly=True),
        ):
            args = await mc.begin(connection, run.request_scope)
            current = await mc.require_run(connection, args, run.run_id)
            require(current["version"] == run.version, "run advanced during producer inspection")
            commands = await connection.fetch(
                f"""SELECT command_id,lifecycle,command_kind,payload,payload_digest,
                    target_kind,target_ref,target_generation,target_version,
                    target_sequence,sequence_space FROM mission_control.command
                WHERE {mc.SCOPE} AND run_id=$4 AND target_kind IN ('root','family')
                ORDER BY command_id LIMIT 257""",
                *args,
                current["run_id"],
            )
            require(
                len(commands) <= 256
                and all(command_allows_cancelled_terminalization(row, run) for row in commands),
                "a boundary command remains pending or unacknowledged",
            )
            raw = await connection.fetchval(
                f"""SELECT mutation
                FROM mission_control.family_admission_head
                WHERE {mc.SCOPE} AND run_key=$4 AND family_kind='stagegraph'""",
                *args,
                run.run_id,
            )
            require(raw is not None, "accepted family authority is absent")
            head = StageGraphDecisionMutation.model_validate(mc.load(raw))
            require(
                head.request_scope == run.request_scope and head.run_id == run.run_id,
                "family scope differs",
            )
            family = TypeAdapter(StageGraphAcceptedProjection).validate_python(
                head.decision_payload.get("projection")
            )
            require(
                family.digest == head.next_projection_digest, "family projection digest differs"
            )
            producer_refs = []
            current_producers = set()
            for stage in family.stages.values():
                if stage.admitted_operation_request_ref is None:
                    continue
                identity = StageExecutionIdentity(
                    run.run_id, target.execution_epoch, stage.candidate, stage.semantic_attempt
                )
                expected_ref = "operation-request:" + sha256_digest(identity.semantic_key)[7:]
                require(
                    stage.semantic_attempt > 0
                    and stage.admitted_operation_request_ref == expected_ref,
                    "admitted producer request does not match its exact semantic identity",
                )
                current_producers.add(identity.semantic_key)
                producer_refs.append(expected_ref)
            producer_refs.sort()
            require(bool(producer_refs), "no exact admitted producer request exists")
            claims = await connection.fetch(
                f"""SELECT claim_key,status,semantic_binding_key,semantic_attempt_key
                FROM mission_control.operation_claim
                WHERE {mc.SCOPE} AND run_key=$4
                ORDER BY claim_key LIMIT 65""",
                *args,
                run.run_id,
            )
            require(0 < len(claims) <= 64, "producer claims are absent or exceed the bound")
            require(
                {row["semantic_attempt_key"] for row in claims} == set(family.producer_liabilities),
                "an adopted, external or unjournaled producer requires separate reconciliation",
            )
            require(
                current_producers <= {row["semantic_attempt_key"] for row in claims},
                "admitted request has no matching settled journal binding",
            )
            producer_ids = []
            expected_harnesses = set()
            producers = {}
            usage_proofs = {}
            settlements = []
            for row in claims:
                # PG journal rejects further terminal-claim mutations; only a
                # reconciliation_required settlement may gain another revision.
                require(
                    row["status"] in {"settled", "cancelled"},
                    "a producer claim remains active or ambiguous",
                )
                raw_settlement = await connection.fetchval(
                    f"""SELECT settlement_payload
                    FROM mission_control.operation_settlement
                    WHERE {mc.SCOPE} AND claim_key=$4
                    ORDER BY settlement_revision DESC LIMIT 1""",
                    *args,
                    row["claim_key"],
                )
                require(raw_settlement is not None, "terminal producer has no settlement")
                settlement = OperationJournalSettlement.model_validate(mc.load(raw_settlement))
                require(
                    settlement.request_scope == run.request_scope
                    and settlement.effect_claim_id == row["claim_key"]
                    and settlement.status != "reconciliation_required"
                    and not settlement.pending_external_usage
                    and settlement.failure_code != "in_doubt_abandoned",
                    "producer usage/effect disposition remains unresolved",
                )
                raw_binding = await connection.fetchrow(
                    f"""SELECT payload,digest
                    FROM mission_control.runtime_document
                    WHERE {mc.SCOPE} AND contract='operation.binding/1' AND identity=$4""",
                    *args,
                    row["semantic_attempt_key"],
                )
                require(raw_binding is not None, "producer binding is absent")
                binding_payload = mc.load(raw_binding["payload"])
                require(
                    sha256_digest(binding_payload) == raw_binding["digest"],
                    "producer binding digest differs",
                )
                binding = OperationExecutionBinding.model_validate(binding_payload)
                require(
                    binding.request_scope == run.request_scope
                    and binding.run_id == run.run_id
                    and binding.binding_id == row["semantic_binding_key"]
                    and binding.semantic_attempt_key == row["semantic_attempt_key"]
                    and binding.effective_configuration_digest == run.effective_configuration_digest
                    and binding.runtime_unit is not None
                    and binding.runtime_unit.execution_epoch == target.execution_epoch
                    and binding.runtime_unit.request_scope == run.request_scope
                    and binding.runtime_unit.belllabs_run_id == run.run_id,
                    "producer binding differs from exact run/epoch",
                )
                producer_ids.append(
                    mission_operation_id(
                        run.request_scope, run.run_id, binding.semantic_attempt_key
                    )
                )
                require(
                    binding.execution_runtime in {"claude", "codex", "cursor"}
                    and binding.lane_profile is not None,
                    "only admitted native session-lane producers are supported",
                )
                assert binding.runtime_unit is not None and binding.lane_profile is not None
                heid = harness_execution_id(
                    request_scope=run.request_scope,
                    run_key=run.run_id,
                    activation_key=binding.runtime_unit.unit_key,
                    attempt_no=target.execution_generation,
                    lane=binding.lane_profile,
                )
                expected_harnesses.add(heid)
                producers[heid] = (binding, settlement)
                settlements.append(settlement.model_dump(mode="json"))
            harnesses = await connection.fetch(
                f"""SELECT harness_execution_id,generation,lifecycle,usage_disposition,
                native_session_ref,native_turn_ref,
                native_identity
                FROM mission_control.harness_execution
                WHERE {mc.SCOPE} AND run_id=$4
                ORDER BY harness_execution_id LIMIT 65""",
                *args,
                current["run_id"],
            )
            require(
                len(harnesses) <= 64
                and {row["harness_execution_id"] for row in harnesses} == expected_harnesses,
                "harnesses do not exactly match admitted journal producers",
            )
            for harness in harnesses:
                native = mc.load(harness["native_identity"]) or {}
                require(
                    harness["generation"] == target.execution_generation
                    and harness["lifecycle"] == "ended"
                    and bool(harness["native_session_ref"])
                    and bool(harness["native_turn_ref"])
                    and not native.get("open_turn"),
                    "a native harness/turn or usage disposition remains unresolved",
                )
                validate_dispatches(native, target.execution_generation)
                if harness["usage_disposition"] == "unknown":
                    budget = await mc.budget_state(connection, args, run_key=run.run_id)
                    require(budget is not None, "admitted run budget is absent")
                    assert budget is not None
                    binding, settlement = producers[harness["harness_execution_id"]]
                    usage_proofs[
                        str(harness["harness_execution_id"])
                    ] = await self._unknown_usage_proof(
                        binding, settlement, harness["native_turn_ref"], budget
                    )
                else:
                    require(
                        harness["usage_disposition"] in {"settled", "estimated"},
                        "native usage disposition is absent",
                    )
            harness_ids = [row["harness_execution_id"] for row in harnesses]
            sessions = await connection.fetch(
                f"""SELECT session_id,harness_execution_id,native_session_ref,state,ended_at
                FROM mission_control.agent_session
                WHERE {mc.SCOPE} AND harness_execution_id=ANY($4::uuid[])
                ORDER BY session_id LIMIT 65""",
                *args,
                harness_ids,
            )
            require(
                len(sessions) <= 64
                and all(
                    row["state"] == "closed" and row["ended_at"] is not None for row in sessions
                ),
                "a native session remains open",
            )
            require(
                {row["harness_execution_id"] for row in sessions} == expected_harnesses,
                "a journal producer has no retained native session",
            )
            for harness in harnesses:
                native = mc.load(harness["native_identity"]) or {}
                require(
                    any(
                        row["harness_execution_id"] == harness["harness_execution_id"]
                        and row["native_session_ref"] == harness["native_session_ref"]
                        for row in sessions
                    ),
                    "native session identity differs from its harness",
                )
            turns = await connection.fetch(
                f"""SELECT turn_id,session_id,native_turn_ref,execution_generation,
                execution_outcome,ended_frame_id
                FROM mission_control.session_turn
                WHERE {mc.SCOPE} AND session_id=ANY($4::uuid[])
                ORDER BY turn_id LIMIT 257""",
                *args,
                [row["session_id"] for row in sessions],
            )
            require(
                len(turns) <= 256
                and all(
                    row["execution_generation"] == target.execution_generation
                    and row["execution_outcome"] in {"succeeded", "failed", "interrupted"}
                    and row["ended_frame_id"] is not None
                    for row in turns
                ),
                "a native turn has no terminal evidence",
            )
            require(
                {row["session_id"] for row in turns} == {row["session_id"] for row in sessions},
                "a native session has no retained terminal turn",
            )
            for harness in harnesses:
                session_ids = {
                    row["session_id"]
                    for row in sessions
                    if row["harness_execution_id"] == harness["harness_execution_id"]
                    and row["native_session_ref"] == harness["native_session_ref"]
                }
                require(
                    any(
                        row["session_id"] in session_ids
                        and row["native_turn_ref"] == harness["native_turn_ref"]
                        for row in turns
                    ),
                    "current native turn has no exact retained terminal session turn",
                )
        fingerprint = metadata_digest(
            {
                "head": head.model_dump(mode="json"),
                "commands": [dict(row) for row in commands],
                "claims": [dict(row) for row in claims],
                "settlements": settlements,
                "harnesses": [dict(row) for row in harnesses],
                "sessions": [dict(row) for row in sessions],
                "turns": [dict(row) for row in turns],
                "usage_proofs": usage_proofs,
            }
        )
        return ProducerAuthority(family, producer_refs[0], tuple(sorted(producer_ids)), fingerprint)
