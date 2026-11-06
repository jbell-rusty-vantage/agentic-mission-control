"""Real Goal settlement waits and worker replacement, scoped to saved executor two."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Literal

from mission_control.adapters.postgres.knowledge.output_contracts import PostgresOutputContractStore
from mission_control.adapters.postgres.run_control import canonical as mc
from mission_control.application.knowledge.judgment import EvaluatorUnavailable
from mission_control.domain.knowledge.judgment import cited_decisions
from mission_control.domain.programs.runtime_units import goal_operation_id


def _document(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _target_calls(rows: list[dict[str, Any]], run_id: str, operation: str) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in rows
        if row.get("run_id") == run_id
        and row.get("operation_id", row.get("operation")) == operation
    ]


@dataclass
class GoalSettlementRecovery:
    mode: Literal["unavailable", "restart"]
    operation: str = field(default_factory=lambda: goal_operation_id(2, "executor"))
    entered: asyncio.Event = field(default_factory=asyncio.Event)
    released: bool = False
    paused: bool = False
    restarted: bool = False
    verified: bool = False
    target_run: str | None = None
    unavailable_attempts: list[dict[str, Any]] = field(default_factory=list)
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None

    def install(self, lane: Any) -> None:
        """Wrap only the fixture's existing trusted runner or saved-result settlement seam."""
        if self.mode == "unavailable":
            runner = lane.trusted._bridge._runner
            evaluate = runner.evaluate

            async def unavailable(evaluator: Any, subject: Any) -> Any:
                if subject.producer.operation_ref == self.operation and not self.released:
                    self.target_run = subject.run_id
                    self.unavailable_attempts.append(
                        {
                            "run_id": subject.run_id,
                            "operation_ref": self.operation,
                            "revision_id": subject.revision.revision_id,
                            "content_digest": subject.revision.content_digest,
                            "role": evaluator.role,
                            "billed": False,
                        }
                    )
                    self.entered.set()
                    raise EvaluatorUnavailable(
                        "fixture evaluator temporarily offline until durable wait is observed",
                        billed=False,
                        reason="evaluator_unavailable",
                    )
                return await evaluate(evaluator, subject)

            runner.evaluate = unavailable
            return
        if self.mode != "restart":
            raise ValueError("unsupported Goal recovery scenario")
        settle = lane.toolset.settle_saved

        async def paused_settlement(live: Any, *, fenced: bool = False) -> Any:
            if live.operation_id == self.operation and not fenced and not self.paused:
                self.target_run = live.run_id
                self.paused = True
                self.entered.set()
                # Worker shutdown cancels this activity; replacement retries the saved result.
                await asyncio.Event().wait()
            return await settle(live, fenced=fenced)

        lane.toolset.settle_saved = paused_settlement

    async def snapshot(self, stack: Any, scope: str, run_id: str, script: Any) -> dict[str, Any]:
        async with stack.worker_pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            saved = await connection.fetch(
                "SELECT settlement_id::text, binding_id, operation_attempt, execution_generation, "
                "saved_result_digest, settlement, reason, record, "
                "saved_result->'checkpoint' AS checkpoint "
                "FROM mission_control.invocation_settlement WHERE "
                "installation_id=$1 AND application_id=$2 AND tenant_id=$3 "
                "AND run_id=$4::uuid AND operation_ref=$5 ORDER BY binding_id",
                *args,
                run_id,
                self.operation,
            )
            outputs = await connection.fetch(
                "SELECT output.output_revision_id::text, output.content_digest, "
                "output.obligation_key, output.deliverable_id, output.revision, "
                "submission.submission_id::text, submission.invocation_ref "
                "FROM mission_control.output_revision output "
                "JOIN mission_control.output_submission submission ON "
                "submission.installation_id=output.installation_id AND "
                "submission.application_id=output.application_id AND "
                "submission.tenant_id=output.tenant_id AND "
                "submission.submission_id=output.submission_id "
                "WHERE output.installation_id=$1 AND output.application_id=$2 "
                "AND output.tenant_id=$3 AND output.run_id=$4::uuid "
                "AND submission.operation_ref=$5 ORDER BY output.output_revision_id",
                *args,
                run_id,
                self.operation,
            )
            effects = await connection.fetch(
                "SELECT effect_key, capability_pin, semantic_payload_digest, bound_effect_digest, "
                "terminal_receipt_ref, receipt_digest, state "
                "FROM mission_control.knowledge_operation_journal WHERE "
                "installation_id=$1 AND application_id=$2 AND tenant_id=$3 "
                "AND originating_origin#>>'{mission,runId}'=$4 "
                "AND originating_origin#>>'{mission,operationId}'=$5 ORDER BY effect_key",
                *args,
                run_id,
                self.operation,
            )
        contracts = PostgresOutputContractStore(stack.worker_pool)
        output_ids = {str(row["output_revision_id"]) for row in outputs}
        assessments = await contracts.output_assessments(scope, run_id)
        accepted = await contracts.accepted_outputs(scope, run_id)
        snapshot = {
            "request_scope": scope,
            "run_id": run_id,
            "operation_ref": self.operation,
            "model_calls": _target_calls(stack.model_log, run_id, self.operation),
            "tool_calls": _target_calls(script.calls, run_id, self.operation),
            "saved": [
                {
                    **dict(row),
                    "record": _document(row["record"]),
                    "checkpoint": _document(row["checkpoint"]),
                }
                for row in saved
            ],
            "outputs": [dict(row) for row in outputs],
            "effects": [dict(row) for row in effects],
            "assessments": [
                item.model_dump(mode="json")
                for item in assessments
                if item.subject_kind == "output_revision" and item.subject_id in output_ids
            ],
            "accepted": [
                item.model_dump(mode="json") for item in accepted if item.revision_id in output_ids
            ],
        }
        return json.loads(json.dumps(snapshot, default=str))

    async def progress(self, stack: Any, scope: str, run_id: str, script: Any) -> None:
        if not self.entered.is_set() or self.released or self.restarted:
            return
        assert self.target_run == run_id, "recovery gate belongs to another run"
        observed = await self.snapshot(stack, scope, run_id, script)
        if self.mode == "unavailable":
            if len(observed["saved"]) != 1:
                return
            saved = observed["saved"][0]
            if saved["settlement"] != "waiting" or saved["reason"] != "settlement_unavailable":
                return
            subjects = {
                (item["revision_id"], item["content_digest"]) for item in self.unavailable_attempts
            }
            waits = [
                item
                for item in observed["assessments"]
                if item["result"] == "unavailable"
                and (item["subject_id"], item["subject_digest"]) in subjects
                and any(finding["code"] == "evaluator_unavailable" for finding in item["findings"])
            ]
            if not waits:
                return
            accepted = {
                (item["revision_id"], item["content_digest"]) for item in observed["accepted"]
            }
            assert not (subjects & accepted), "unavailable subject must not be accepted"
            self.before = observed
            self.released = True
            return
        assert len(observed["saved"]) == 1, "executor cognition must already be durable"
        assert observed["saved"][0]["settlement"] != "settled"
        assert observed["outputs"] and observed["model_calls"]
        self.before = observed
        self.restarted = True
        from tests.fixtures.rrm009_cancellation import restart_workers

        await restart_workers(stack)

    async def verify(self, stack: Any, scope: str, run_id: str, script: Any) -> None:
        assert self.before is not None and (self.released or self.restarted)
        self.after = await self.snapshot(stack, scope, run_id, script)
        for key in ("model_calls", "tool_calls", "outputs"):
            assert self.after[key] == self.before[key], f"saved executor changed: {key}"
        assert len(self.after["saved"]) == 1
        before, after = self.before["saved"][0], self.after["saved"][0]
        for key in (
            "settlement_id",
            "binding_id",
            "operation_attempt",
            "execution_generation",
            "saved_result_digest",
            "checkpoint",
        ):
            assert before[key] == after[key], f"saved identity changed: {key}"
        assert after["settlement"] == "settled" and after["reason"] is None
        # Settlement may add real evaluator/seal effects. Existing producer effects stay exact.
        effects = {row["effect_key"]: row for row in self.after["effects"]}
        for row in self.before["effects"]:
            assert effects.get(row["effect_key"]) == row, "producer effect identity/receipt changed"
        registrations_before = [
            row
            for row in self.before["effects"]
            if row["capability_pin"] == "knowledge.report_register@1"
        ]
        registrations_after = [
            row
            for row in self.after["effects"]
            if row["capability_pin"] == "knowledge.report_register@1"
        ]
        assert len(registrations_before) == 1
        assert registrations_after == registrations_before, "report registration repeated"
        assert sum(row["tool"] == "report_register" for row in self.after["tool_calls"]) == 1
        assert self.after["accepted"], "normal trusted settlement must eventually accept executor2"
        if self.mode == "unavailable":
            assert self.released and self.unavailable_attempts
            subjects = {
                (item["revision_id"], item["content_digest"]) for item in self.unavailable_attempts
            }
            accepted = {
                (item["revision_id"], item["content_digest"]) for item in self.after["accepted"]
            }
            passed = {
                (row["subject_id"], row["subject_digest"])
                for row in self.after["assessments"]
                if row["result"] == "pass" and cited_decisions(row["evidence_refs"])
            }
            assert subjects <= accepted, "exact recovered subject must be accepted"
            assert subjects <= passed, "exact recovered subject needs its native passing decision"
        else:
            assert self.restarted
        self.verified = True

    def evidence(self) -> dict[str, Any]:
        """Self-contained observed receipts; failed probes retain their partial evidence too."""
        return {
            "scenario": self.mode,
            "operation_ref": self.operation,
            "released": self.released,
            "restarted": self.restarted,
            "verified": self.verified,
            "unavailable_attempts": list(self.unavailable_attempts),
            "before": self.before,
            "after": self.after,
        }
