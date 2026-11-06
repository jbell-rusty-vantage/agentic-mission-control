"""Read-only adoption context from exact Temporal inputs and scoped durable authority.

Trusted composition supplies validated workflow inputs and an exact cancellation
issuer/command. HTTP callers cannot supply operation prompts, blueprints or facts.
The historical family projection is located by digest, never replaced by the head.
"""

from typing import Any
from uuid import UUID

import asyncpg
from pydantic import TypeAdapter

from mission_control.adapters.postgres.closed_workflow import validate_dispatches
from mission_control.adapters.postgres.run_control import canonical as mc
from mission_control.adapters.postgres.run_control.run_control_repository import _boundary_command
from mission_control.adapters.temporal.terminal_adoption_inputs import TerminalWorkflowInputs
from mission_control.application.execution.harness.dispatch import DispatchRecord, SessionOwner
from mission_control.application.execution.harness.lane_turns import LaneExecutionIdentity
from mission_control.application.execution.operations.operation_execution import (
    bind_operation_execution_request,
)
from mission_control.application.recovery.terminal_evidence_adoption import TerminalAdoptionContext
from mission_control.application.recovery.terminal_lane_adoption import (
    AdoptionAuthority,
    AdoptionIdentity,
    AdoptionInspectionRefused,
)
from mission_control.domain.authoring.canonical import contract_fingerprint, sha256_digest
from mission_control.domain.authoring.contracts import StageGraphBlueprint
from mission_control.domain.execution.contracts import OperationExecutionBinding
from mission_control.domain.frames.contracts import FrameScope, HarnessExecutionHandle
from mission_control.domain.policies.boundary_commands import boundary_target_for
from mission_control.domain.policies.contracts import CancelAction, RunProjection
from mission_control.domain.programs.contracts import (
    LateResultFacts,
    StageExecutionIdentity,
    StageGraphAcceptedProjection,
    StageGraphDecisionMutation,
    StageGraphResultActivityRequest,
    StageResultObservation,
)


def need(value: object, reason: str) -> None:
    if not value:
        raise AdoptionInspectionRefused(reason)


def family_projection(
    raw: Any, scope: str, run_id: str
) -> tuple[StageGraphDecisionMutation, StageGraphAcceptedProjection]:
    mutation = StageGraphDecisionMutation.model_validate(mc.load(raw))
    projection = TypeAdapter(StageGraphAcceptedProjection).validate_python(
        mutation.decision_payload["projection"]
    )
    need(
        mutation.request_scope == scope
        and mutation.run_id == run_id
        and projection.digest == mutation.next_projection_digest,
        "family projection scope or digest differs",
    )
    return mutation, projection


class PostgresTerminalAdoptionContextReader:
    def __init__(
        self,
        pool: asyncpg.Pool,
        *,
        identity: AdoptionIdentity,
        inputs: TerminalWorkflowInputs,
        cancel_issuer: str,
        cancel_command_id: str,
    ) -> None:
        self._pool, self._identity, self._inputs = pool, identity, inputs
        self._cancel_issuer, self._cancel_id = cancel_issuer, cancel_command_id

    async def read(self, identity: AdoptionIdentity, family_digest: str) -> TerminalAdoptionContext:
        need(identity == self._identity, "context identity is outside approved composition")
        scope, public = identity.request_scope, identity.public_run_key
        operation, family_input = self._inputs.operation.operation, self._inputs.family
        expected = bind_operation_execution_request(operation)
        need(
            operation.runtime_unit is not None
            and operation.request_scope == scope
            and operation.identity.run_id == public
            and family_input.request_scope == scope
            and family_input.run_id == public
            and sha256_digest(StageGraphBlueprint.model_validate(family_input.blueprint))
            == family_input.blueprint_digest,
            "exact workflow inputs differ from approved context",
        )
        derived = LaneExecutionIdentity.of(operation, "cursor_local", identity.generation)
        need(
            str(derived.harness_execution_id) == identity.harness_execution_id,
            "harness does not derive from admitted operation",
        )
        async with (
            self._pool.acquire() as connection,
            connection.transaction(isolation="repeatable_read", readonly=True),
        ):
            args = await mc.begin(connection, scope)
            row = await mc.require_run(connection, args, public)
            need(str(row["run_id"]) == identity.internal_run_id, "internal run identity differs")
            run = RunProjection.model_validate(mc.load(row["projection"]))
            need(
                run.version == row["version"]
                and run.request_scope == scope
                and run.run_id == public
                and run.execution_target is not None
                and run.execution_target.execution_epoch == family_input.execution_epoch
                and run.execution_target.execution_generation == identity.generation
                and run.effective_configuration_digest == operation.effective_configuration_digest
                and family_input.effective_configuration_digest
                == operation.effective_configuration_digest,
                "run execution frontier differs",
            )
            raw = await connection.fetchrow(
                f"""SELECT payload,digest FROM mission_control.runtime_document
                WHERE {mc.SCOPE} AND contract='operation.binding/1' AND identity=$4""",
                *args,
                expected.semantic_attempt_key,
            )
            need(
                raw is not None and sha256_digest(mc.load(raw["payload"])) == raw["digest"],
                "persisted operation binding missing or corrupt",
            )
            assert raw is not None
            binding = OperationExecutionBinding.model_validate(mc.load(raw["payload"]))
            need(binding == expected, "exact Temporal operation differs from admitted binding")
            claims = await connection.fetch(
                f"""SELECT claim_key,status FROM mission_control.operation_claim
                WHERE {mc.SCOPE} AND run_key=$4 AND semantic_binding_key=$5 LIMIT 2""",
                *args,
                public,
                binding.binding_id,
            )
            need(len(claims) == 1, "one exact operation claim is required")
            harness = await connection.fetchrow(
                f"""SELECT h.*,a.activation_id,a.attempt_no
                FROM mission_control.harness_execution h JOIN mission_control.attempt a
                  ON a.attempt_id=h.attempt_id
                WHERE {mc.scoped("h")} AND h.harness_execution_id=$4 AND h.run_id=$5""",
                *args,
                UUID(identity.harness_execution_id),
                row["run_id"],
            )
            need(
                harness is not None
                and harness["generation"] == identity.generation
                and harness["native_session_ref"] == identity.native_session_ref
                and harness["native_turn_ref"] == identity.native_turn_ref
                and harness["lane_profile"] == "cursor_local",
                "native execution identity differs",
            )
            assert harness is not None
            native = mc.load(harness["native_identity"]) or {}
            validate_dispatches(native, identity.generation)
            dispatches = [
                DispatchRecord.model_validate(value)
                for value in native.get("mc_dispatch", {}).values()
            ]
            need(
                any(
                    item.kind == "create"
                    and item.phase == "acknowledged"
                    and item.native_ref == identity.native_session_ref
                    for item in dispatches
                )
                and any(
                    item.kind == "send"
                    and item.phase == "acknowledged"
                    and item.native_ref == identity.native_turn_ref
                    for item in dispatches
                ),
                "exact native create/send acknowledgements missing",
            )
            owner = SessionOwner.model_validate(native["mc_session_owner"])
            historical = await connection.fetch(
                f"""SELECT mutation,mutation_fingerprint
                FROM mission_control.family_admission_journal WHERE {mc.SCOPE}
                AND run_key=$4 AND family_kind='stagegraph'
                AND mutation->>'next_projection_digest'=$5 LIMIT 2""",
                *args,
                public,
                family_digest,
            )
            need(len(historical) == 1, "original accepted family digest is absent or ambiguous")
            mutation, projection = family_projection(historical[0]["mutation"], scope, public)
            need(
                contract_fingerprint(mutation, exclude={"decided_at"})
                == historical[0]["mutation_fingerprint"],
                "historical family mutation fingerprint differs",
            )
            candidates = [
                StageExecutionIdentity(
                    public, family_input.execution_epoch, stage.candidate, stage.semantic_attempt
                )
                for stage in projection.stages.values()
                if stage.semantic_attempt > 0
            ]
            exact = [
                item for item in candidates if item.semantic_key == binding.semantic_attempt_key
            ]
            need(
                len(exact) == 1 and exact[0].semantic_key in projection.producer_liabilities,
                "accepted family has no exact producer liability",
            )
            need(
                mutation.next_projection_digest == family_digest
                and mutation.exact_operation_request_ref
                == "operation-request:" + sha256_digest(exact[0].semantic_key)[7:],
                "historical family is not this producer admission",
            )
            head = await connection.fetchval(
                f"""SELECT mutation FROM mission_control.family_admission_head
                WHERE {mc.SCOPE} AND run_key=$4 AND family_kind='stagegraph'""",
                *args,
                public,
            )
            _, current = family_projection(head, scope, public)
            cancel = await _boundary_command(
                connection, args, public, self._cancel_issuer, self._cancel_id
            )
            need(
                cancel is not None
                and isinstance(cancel.command.action, CancelAction)
                and cancel.command.kind == "cancel"
                and cancel.command.request_scope == scope
                and cancel.command.run_id == public
                and cancel.command.command_id == self._cancel_id
                and cancel.command.idempotency_issuer == self._cancel_issuer
                and cancel.command.payload_digest == contract_fingerprint(cancel.command.action)
                and cancel.command.target == boundary_target_for(run, cancel.command.action),
                "exact current cancel authority differs",
            )
            assert cancel is not None
            budget = await mc.budget_state(connection, args, run_key=public)
            need(budget is not None, "admitted budget authority missing")
            assert budget is not None
            currency = sum(
                value
                for key, value in binding.budget_limits.items()
                if key.startswith("currency.") and value > 0
            )
            retained = sum(
                value
                for key, value in budget.reservations.get(binding.budget_reservation_id, {}).items()
                if key.startswith("currency.")
            ) + sum(
                value
                for key, value in budget.pending_settlement.items()
                if key.startswith("currency.")
            )
            authority = AdoptionAuthority(
                identity,
                run.version,
                run.phase.value,
                harness["lifecycle"],
                claims[0]["status"],
                binding.binding_id,
                sha256_digest(binding),
                claims[0]["claim_key"],
                harness["version"],
                owner.epoch,
                harness["version"],
                sha256_digest(native.get("mc_dispatch", {})),
                True,
                current.digest,
                cancel.command.command_id,
                cancel.receipts[-1].ordinal,
                cancel.state.value,
                bool(currency and retained >= currency),
                currency,
            )
            handle = HarnessExecutionHandle(
                harness_execution_id=UUID(identity.harness_execution_id),
                scope=FrameScope.from_request_scope(scope),
                run_id=row["run_id"],
                activation_id=harness["activation_id"],
                attempt_no=harness["attempt_no"],
                generation=identity.generation,
                lane_profile="cursor_local",
                native_session_ref=identity.native_session_ref,
            )
            family = StageGraphResultActivityRequest(
                public,
                scope,
                projection,
                StageResultObservation(exact[0], {}, False, False, False, False, 1),
                LateResultFacts(),
                family_input.blueprint,
                family_input.max_concurrency,
                mutation.decided_at,
                "terminal-evidence-adoption",
                family_input.correlation_id,
            )
            pending = self._inputs.pending_family_result
            if pending is not None:
                need(
                    pending.operation_temporal_run_id == self._inputs.operation_temporal_run_id
                    and pending.family_temporal_run_id == self._inputs.family_temporal_run_id
                    and pending.request.request_scope == scope
                    and pending.request.run_id == public
                    and pending.request.projection.digest == projection.digest
                    and pending.request.observation.identity == exact[0]
                    and pending.request.blueprint == family_input.blueprint,
                    "pending family input differs from durable admitted context",
                )
                family = pending.request
            return TerminalAdoptionContext(authority, operation, handle, family, pending)
