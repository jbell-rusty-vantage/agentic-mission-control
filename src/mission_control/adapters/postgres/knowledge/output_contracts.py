"""``OutputContractStore`` over the release 1.7.0 output-contract tables.

One transaction per act under transaction-local tenant scope. Immutable facts are inserted;
the two pointers move by compare-and-set: ``output_obligation_head`` (``active_revision`` and
``version``, the successor's expected prior revision) and ``output_accepted_head`` (expected
head and generation). A submission act inserts its ``output_submission`` row and one
``output_revision`` per deliverable in the same transaction under the per-invocation advisory
lock, so an identical retry returns the stored receipt and the same key with other bytes is
``SUBMISSION_CONFLICT`` (SQLSTATE MCE02) before anything else is written.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from mission_control.adapters.postgres.knowledge.attention_events import (
    OUTPUT_ASSESSMENT_HELD,
    OUTPUT_ASSESSMENT_REJECTED,
    OUTPUT_FULFILLED,
    OUTPUT_FULFILLMENT_UNMET,
    emit_attention_event,
)
from mission_control.adapters.postgres.knowledge.submissions import (
    SUBMISSION_CONFLICT_SQLSTATE,
    PostgresOutputSubmissionStore,
)
from mission_control.adapters.postgres.run_control import canonical as mc
from mission_control.adapters.postgres.run_control.canonical import SCOPE
from mission_control.adapters.postgres.scope import apply_actor
from mission_control.application.ports.knowledge import SubmissionClosed, SubmissionConflict
from mission_control.application.ports.outputs import (
    AcceptedHead,
    AssessmentSupersessionConflict,
    OlderRevision,
    PromisesConflict,
    RecordedSubmission,
    StaleGeneration,
    StaleHead,
    StaleObligationRevision,
    SubmissionAct,
)
from mission_control.domain.outputs.contracts import (
    Assessment,
    ExactOutput,
    Finding,
    Fulfillment,
    OutputForm,
    OutputObligation,
    OutputPromiseSet,
    OutputSet,
    SubmittedRevision,
    membership_digest,
)

_PROMISES = "mission_control.output_promise_set"
_PIN = "mission_control.output_obligation_pin"
_REVISION = "mission_control.output_obligation_revision"
_HEAD = "mission_control.output_obligation_head"
_OUTPUT = "mission_control.output_revision"
_ACCEPTED = "mission_control.output_accepted_head"
_SET = "mission_control.output_set"
_MEMBER = "mission_control.output_set_member"
_ASSESSMENT = "mission_control.output_assessment"
_FULFILLMENT = "mission_control.obligation_fulfillment"
_STEP = "mission_control.obligation_association_step"
_SUBMISSION = "mission_control.output_submission"
_FINALIZATION = "mission_control.invocation_finalization"


def _dump(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _obligation(row: asyncpg.Record) -> OutputObligation:
    return OutputObligation.model_validate(mc.load(row["obligation"]))


async def _run_lock(connection: asyncpg.Connection, scope: str, run_id: str) -> None:
    """Every act that reads or moves a run's heads serializes here (one consistent snapshot)."""

    await mc.advisory_lock(connection, f"output_run:{scope}:{run_id}")


def _output(row: asyncpg.Record) -> ExactOutput:
    return ExactOutput(
        revision_id=str(row["output_revision_id"]),
        run_id=str(row["run_id"]),
        obligation_key=row["obligation_key"],
        obligation_revision=int(row["obligation_revision"]),
        deliverable_id=row["deliverable_id"],
        revision=int(row["revision"]),
        form=OutputForm(row["form"]),
        content_digest=row["content_digest"],
        candidate=mc.load(row["candidate"]),
        producer_origin_ref=row["producer_origin_ref"],
    )


def _head(row: asyncpg.Record) -> AcceptedHead:
    return AcceptedHead(
        obligation_key=row["obligation_key"],
        deliverable_id=row["deliverable_id"],
        revision_id=str(row["output_revision_id"]),
        version=int(row["version"]),
        generation=int(row["generation"]),
    )


def _assessment(row: asyncpg.Record) -> Assessment:
    return Assessment(
        assessment_id=str(row["assessment_id"]),
        subject_kind=row["subject_kind"],
        subject_id=row["subject_ref"],
        subject_digest=row["subject_digest"],
        requirement_results=mc.load(row["requirement_results"]),
        result=row["result"],
        assessor_origin_ref=row["assessor_origin_ref"],
        method_pin=row["method_pin"],
        policy_pin=row["policy_pin"],
        evidence_refs=tuple(mc.load(row["evidence_refs"])),
        findings=tuple(Finding.model_validate(item) for item in mc.load(row["findings"])),
        index_revision_id=str(row["output_revision_id"])
        if row["subject_kind"] == "member"
        else None,
        supersedes=None if row["supersedes"] is None else str(row["supersedes"]),
    )


def _uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except ValueError:
        return None


class PostgresOutputContractStore(PostgresOutputSubmissionStore):
    """Submissions, finalization and the 1.7.0 output-contract records for one runtime pool."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        super().__init__(pool)
        self._pool = pool

    # ------------------------------------------------------------------ promises

    async def register_promises(
        self,
        scope: str,
        run_id: str,
        promises: OutputPromiseSet,
        *,
        configuration_digest: str | None,
        actor_ref: str,
        at: datetime,
    ) -> tuple[OutputObligation, ...]:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            await apply_actor(connection, actor_ref)
            await _run_lock(connection, scope, run_id)
            existing = await connection.fetchval(
                f"SELECT promise_set_digest FROM {_PROMISES} WHERE {SCOPE} AND run_id = $4::uuid",
                *args,
                run_id,
            )
            if existing is not None:
                if existing != promises.digest:
                    raise PromisesConflict(f"run {run_id} registered other promises")
            else:
                await connection.execute(
                    f"INSERT INTO {_PROMISES} (installation_id, application_id, tenant_id, run_id, "
                    "promise_set, promise_set_digest, configuration_digest, created_at, "
                    "created_by_actor_ref) "
                    "VALUES ($1, $2, $3, $4::uuid, $5::jsonb, $6, $7, $8, $9)",
                    *args,
                    run_id,
                    _dump(promises.model_dump(mode="json")),
                    promises.digest,
                    configuration_digest,
                    at,
                    actor_ref,
                )
                for ordinal, item in enumerate(promises.obligations):
                    await connection.execute(
                        f"INSERT INTO {_REVISION} (installation_id, application_id, tenant_id, "
                        "obligation_revision_id, run_id, obligation_key, revision, ordinal, "
                        "owner_position, form, enforcement, evaluation_scope, obligation, "
                        "obligation_digest, promise_set_digest, configuration_digest, "
                        "created_at, created_by_actor_ref) VALUES ($1, $2, $3, $4, $5::uuid, $6, "
                        "$7, $8, $9, $10, $11, $12, $13::jsonb, $14, $15, $16, $17, $18)",
                        *args,
                        uuid4(),
                        run_id,
                        item.key,
                        item.revision,
                        ordinal,
                        item.owner_position,
                        item.form.value,
                        item.enforcement.value,
                        item.evaluation_scope.value,
                        _dump(item.document()),
                        item.digest,
                        promises.digest,
                        configuration_digest,
                        at,
                        actor_ref,
                    )
                    await connection.execute(
                        f"INSERT INTO {_HEAD} (installation_id, application_id, tenant_id, run_id, "
                        "obligation_key, ordinal, active_revision, version, updated_at, "
                        "updated_by_actor_ref) VALUES ($1, $2, $3, $4::uuid, $5, $6, 1, 1, $7, $8)",
                        *args,
                        run_id,
                        item.key,
                        ordinal,
                        at,
                        actor_ref,
                    )
        return await self.active_obligations(scope, run_id)

    async def promise_set(self, scope: str, run_id: str) -> OutputPromiseSet | None:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            row = await connection.fetchrow(
                f"SELECT promise_set FROM {_PROMISES} WHERE {SCOPE} AND run_id = $4::uuid",
                *args,
                run_id,
            )
        return None if row is None else OutputPromiseSet.model_validate(mc.load(row["promise_set"]))

    async def pin_invocation(
        self, scope: str, run_id: str, invocation_ref: str, *, actor_ref: str, at: datetime
    ) -> Mapping[str, int]:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            await apply_actor(connection, actor_ref)
            await _run_lock(connection, scope, run_id)
            await connection.execute(
                f"INSERT INTO {_PIN} (installation_id, application_id, tenant_id, run_id, "
                "invocation_ref, obligation_key, revision, pinned_at, created_by_actor_ref) "
                "SELECT installation_id, application_id, tenant_id, run_id, $5, obligation_key, "
                f"active_revision, $6, $7 FROM {_HEAD} WHERE {SCOPE} AND run_id = $4::uuid "
                "ON CONFLICT DO NOTHING",
                *args,
                run_id,
                invocation_ref,
                at,
                actor_ref,
            )
        return await self.invocation_pins(scope, invocation_ref)

    async def invocation_pins(self, scope: str, invocation_ref: str) -> Mapping[str, int]:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            rows = await connection.fetch(
                f"SELECT obligation_key, revision FROM {_PIN} WHERE {SCOPE} "
                "AND invocation_ref = $4",
                *args,
                invocation_ref,
            )
        return {row["obligation_key"]: int(row["revision"]) for row in rows}

    async def active_obligations(self, scope: str, run_id: str) -> tuple[OutputObligation, ...]:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            rows = await connection.fetch(
                f"SELECT revision.obligation FROM {_HEAD} head JOIN {_REVISION} revision "
                "ON revision.installation_id = head.installation_id "
                "AND revision.application_id = head.application_id "
                "AND revision.tenant_id = head.tenant_id AND revision.run_id = head.run_id "
                "AND revision.obligation_key = head.obligation_key "
                "AND revision.revision = head.active_revision "
                "WHERE head.installation_id = $1 AND head.application_id = $2 "
                "AND head.tenant_id = $3 AND head.run_id = $4::uuid ORDER BY head.ordinal",
                *args,
                run_id,
            )
        return tuple(_obligation(row) for row in rows)

    async def obligation_revision(
        self, scope: str, run_id: str, obligation_key: str, revision: int
    ) -> OutputObligation | None:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            row = await connection.fetchrow(
                f"SELECT obligation FROM {_REVISION} WHERE {SCOPE} AND run_id = $4::uuid "
                "AND obligation_key = $5 AND revision = $6",
                *args,
                run_id,
                obligation_key,
                revision,
            )
        return None if row is None else _obligation(row)

    async def propose_successor(
        self,
        scope: str,
        run_id: str,
        successor: OutputObligation,
        *,
        expected_prior_revision: int,
        proposal: Mapping[str, Any],
        boundary: str,
        actor_ref: str,
        at: datetime,
    ) -> OutputObligation:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            await apply_actor(connection, actor_ref)
            await _run_lock(connection, scope, run_id)
            head = await connection.fetchrow(
                f"SELECT ordinal, active_revision FROM {_HEAD} WHERE {SCOPE} "
                "AND run_id = $4::uuid AND obligation_key = $5",
                *args,
                run_id,
                successor.key,
            )
            pending = await connection.fetchval(
                f"SELECT 1 FROM {_REVISION} WHERE {SCOPE} AND run_id = $4::uuid "
                "AND obligation_key = $5 AND revision = $6",
                *args,
                run_id,
                successor.key,
                successor.revision,
            )
            if head is None or head["active_revision"] != expected_prior_revision or pending:
                raise StaleObligationRevision(
                    "promise head moved or a successor is pending",
                    current=None if head is None else int(head["active_revision"]),
                )
            prior = await connection.fetchrow(
                f"SELECT promise_set_digest, configuration_digest FROM {_REVISION} "
                f"WHERE {SCOPE} AND run_id = $4::uuid AND obligation_key = $5 AND revision = $6",
                *args,
                run_id,
                successor.key,
                expected_prior_revision,
            )
            assert prior is not None  # the head's foreign key guarantees it
            await connection.execute(
                f"INSERT INTO {_REVISION} (installation_id, application_id, tenant_id, "
                "obligation_revision_id, run_id, obligation_key, revision, ordinal, "
                "owner_position, form, enforcement, evaluation_scope, obligation, "
                "obligation_digest, promise_set_digest, configuration_digest, proposal, "
                "activation_boundary, created_at, created_by_actor_ref) VALUES ($1, $2, $3, $4, "
                "$5::uuid, $6, $7, $8, $9, $10, $11, $12, $13::jsonb, $14, $15, $16, $17::jsonb, "
                "$18, $19, $20)",
                *args,
                uuid4(),
                run_id,
                successor.key,
                successor.revision,
                head["ordinal"],
                successor.owner_position,
                successor.form.value,
                successor.enforcement.value,
                successor.evaluation_scope.value,
                _dump(successor.document()),
                successor.digest,
                prior["promise_set_digest"],
                prior["configuration_digest"],
                _dump(dict(proposal)),
                boundary,
                at,
                actor_ref,
            )
        return successor

    async def activate_pending(
        self,
        scope: str,
        run_id: str,
        *,
        boundary: str,
        boundary_ref: str,
        actor_ref: str,
        at: datetime,
    ) -> tuple[OutputObligation, ...]:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            await apply_actor(connection, actor_ref)
            await _run_lock(connection, scope, run_id)
            rows = await connection.fetch(
                f"UPDATE {_HEAD} head SET active_revision = head.active_revision + 1, "
                "version = head.version + 1, activated_boundary_ref = $6, "
                "updated_at = GREATEST($7::timestamptz, head.updated_at), "
                f"updated_by_actor_ref = $8 FROM {_REVISION} successor "
                "WHERE head.installation_id = $1 AND head.application_id = $2 "
                "AND head.tenant_id = $3 AND head.run_id = $4::uuid "
                "AND successor.installation_id = head.installation_id "
                "AND successor.application_id = head.application_id "
                "AND successor.tenant_id = head.tenant_id AND successor.run_id = head.run_id "
                "AND successor.obligation_key = head.obligation_key "
                "AND successor.revision = head.active_revision + 1 "
                "AND successor.activation_boundary = $5 RETURNING successor.obligation",
                *args,
                run_id,
                boundary,
                f"{boundary}:{boundary_ref}",
                at,
                actor_ref,
            )
        return tuple(_obligation(row) for row in rows)

    # ------------------------------------------------------------------ submissions

    async def record_submission(self, act: SubmissionAct) -> RecordedSubmission:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, act.scope)
            await apply_actor(connection, act.actor_ref)
            await mc.advisory_lock(
                connection, f"output_submission:{act.scope}:{act.invocation_ref}"
            )
            stored = await connection.fetchrow(
                f"SELECT submission_id, selection_digest FROM {_SUBMISSION} WHERE {SCOPE} "
                "AND invocation_ref = $4 AND obligation_id = $5 AND submission_key = $6",
                *args,
                act.invocation_ref,
                act.obligation_key,
                act.submission_key,
            )
            if stored is not None:
                if stored["selection_digest"] != act.selection_digest:
                    raise SubmissionConflict(f"SUBMISSION_CONFLICT {act.submission_key}")
                rows = await connection.fetch(
                    f"SELECT * FROM {_OUTPUT} WHERE {SCOPE} AND submission_id = $4 "
                    "ORDER BY item_index",
                    *args,
                    stored["submission_id"],
                )
                return RecordedSubmission(
                    str(stored["submission_id"]),
                    tuple(_submitted(row) for row in rows),
                    replayed=True,
                )
            # Replay first: an identical retry gets its receipt even after finalization.
            if await connection.fetchval(
                f"SELECT 1 FROM {_FINALIZATION} WHERE {SCOPE} AND invocation_ref = $4",
                *args,
                act.invocation_ref,
            ):
                raise SubmissionClosed(f"invocation {act.invocation_ref} is finalized")
            # Serialize the expected-head check with promotion until this transaction commits.
            # Replay above wins even when that original request's head has since moved.
            expected = act.selection.get("submit", {}).get("expected_head")
            if expected is not None:
                await _run_lock(connection, act.scope, act.run_id)
                for item in act.items:
                    current = await connection.fetchval(
                        f"SELECT output_revision_id FROM {_ACCEPTED} WHERE {SCOPE} "
                        "AND run_id = $4::uuid AND obligation_key = $5 AND deliverable_id = $6",
                        *args,
                        act.run_id,
                        act.obligation_key,
                        item.deliverable_id,
                    )
                    if (None if current is None else str(current)) != expected:
                        raise StaleHead(
                            "accepted head changed",
                            current=None if current is None else str(current),
                        )
            # Lock every deliverable in one global order before numbering (no lock cycles).
            for deliverable in sorted({item.deliverable_id for item in act.items}):
                await mc.advisory_lock(
                    connection,
                    f"output_revision:{act.scope}:{act.run_id}:{act.obligation_key}:{deliverable}",
                )
            submission_id = uuid4()
            revision = await connection.fetchval(
                f"SELECT COALESCE(max(revision), 0) + 1 FROM {_SUBMISSION} "
                f"WHERE {SCOPE} AND invocation_ref = $4 AND obligation_id = $5",
                *args,
                act.invocation_ref,
                act.obligation_key,
            )
            try:
                await connection.execute(
                    f"INSERT INTO {_SUBMISSION} (installation_id, application_id, tenant_id, "
                    "submission_id, run_id, operation_ref, operation_attempt, "
                    "execution_generation, unit_key, invocation_ref, obligation_id, "
                    "submission_key, revision, selection, selection_digest, assessment_state, "
                    "version, submitted_at, updated_at, created_at, created_by_actor_ref) "
                    "VALUES ($1, $2, $3, $4, $5::uuid, $6, $7, $8, $9, $10, $11, $12, $13, "
                    "$14::jsonb, $15, 'pending', 1, $16, $16, $16, $17)",
                    *args,
                    submission_id,
                    act.run_id,
                    act.operation_ref,
                    act.operation_attempt,
                    act.execution_generation,
                    act.unit_key,
                    act.invocation_ref,
                    act.obligation_key,
                    act.submission_key,
                    revision,
                    _dump(dict(act.selection)),
                    act.selection_digest,
                    act.at,
                    act.actor_ref,
                )
            except asyncpg.PostgresError as error:  # pragma: no cover - guarded above
                if getattr(error, "sqlstate", None) == SUBMISSION_CONFLICT_SQLSTATE:
                    raise SubmissionConflict(f"SUBMISSION_CONFLICT {act.submission_key}") from None
                raise
            submitted: list[SubmittedRevision] = []
            for index, item in enumerate(act.items):
                number = await connection.fetchval(
                    f"SELECT COALESCE(max(revision), 0) + 1 FROM {_OUTPUT} WHERE {SCOPE} "
                    "AND run_id = $4::uuid AND obligation_key = $5 AND deliverable_id = $6",
                    *args,
                    act.run_id,
                    act.obligation_key,
                    item.deliverable_id,
                )
                row = await connection.fetchrow(
                    f"INSERT INTO {_OUTPUT} (installation_id, application_id, tenant_id, "
                    "output_revision_id, run_id, submission_id, item_index, obligation_key, "
                    "obligation_revision, deliverable_id, revision, form, candidate, "
                    "content_digest, producer_origin_ref, caller_origin_ref, submitted_at, "
                    "created_at, created_by_actor_ref) VALUES ($1, $2, $3, $4, $5::uuid, $6, $7, "
                    "$8, $9, $10, $11, $12, $13::jsonb, $14, $15, $16, $17, $17, $18) "
                    "RETURNING *",
                    *args,
                    uuid4(),
                    act.run_id,
                    submission_id,
                    index,
                    act.obligation_key,
                    act.obligation_revision,
                    item.deliverable_id,
                    number,
                    item.form,
                    _dump(dict(item.candidate)),
                    item.content_digest,
                    act.producer_origin_ref,
                    act.caller_origin_ref,
                    act.at,
                    act.actor_ref,
                )
                submitted.append(_submitted(row))
        return RecordedSubmission(str(submission_id), tuple(submitted))

    async def output_revision(self, scope: str, revision_id: str) -> ExactOutput | None:
        parsed = _uuid(revision_id)
        if parsed is None:
            return None
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            row = await connection.fetchrow(
                f"SELECT * FROM {_OUTPUT} WHERE {SCOPE} AND output_revision_id = $4",
                *args,
                parsed,
            )
        return None if row is None else _output(row)

    # ------------------------------------------------------------------ accepted heads

    async def accepted_head(
        self, scope: str, run_id: str, obligation_key: str, deliverable_id: str
    ) -> AcceptedHead | None:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            row = await connection.fetchrow(
                f"SELECT * FROM {_ACCEPTED} WHERE {SCOPE} AND run_id = $4::uuid "
                "AND obligation_key = $5 AND deliverable_id = $6",
                *args,
                run_id,
                obligation_key,
                deliverable_id,
            )
        return None if row is None else _head(row)

    async def promote(
        self,
        scope: str,
        run_id: str,
        revision: ExactOutput,
        *,
        expected_head: str | None,
        generation: int,
        actor_ref: str,
        at: datetime,
    ) -> AcceptedHead:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            await apply_actor(connection, actor_ref)
            await _run_lock(connection, scope, run_id)
            newer = await connection.fetchval(
                f"SELECT output.revision FROM {_ACCEPTED} head JOIN {_OUTPUT} output "
                "ON output.installation_id = head.installation_id "
                "AND output.application_id = head.application_id "
                "AND output.tenant_id = head.tenant_id "
                "AND output.output_revision_id = head.output_revision_id "
                "WHERE head.installation_id = $1 AND head.application_id = $2 "
                "AND head.tenant_id = $3 AND head.run_id = $4::uuid AND head.obligation_key = $5 "
                "AND head.deliverable_id = $6 AND head.output_revision_id = $7",
                *args,
                run_id,
                revision.obligation_key,
                revision.deliverable_id,
                _uuid(expected_head) if expected_head is not None else None,
            )
            if newer is not None and int(newer) > revision.revision:
                raise OlderRevision("an older revision cannot replace a newer accepted head")
            if expected_head is None:
                row = await connection.fetchrow(
                    f"INSERT INTO {_ACCEPTED} (installation_id, application_id, tenant_id, run_id, "
                    "obligation_key, deliverable_id, output_revision_id, generation, version, "
                    "promoted_at, promoted_by_actor_ref) VALUES ($1, $2, $3, $4::uuid, $5, $6, "
                    "$7, $8, 1, $9, $10) ON CONFLICT DO NOTHING RETURNING *",
                    *args,
                    run_id,
                    revision.obligation_key,
                    revision.deliverable_id,
                    UUID(revision.revision_id),
                    generation,
                    at,
                    actor_ref,
                )
            else:
                current = await connection.fetchrow(
                    f"SELECT generation FROM {_ACCEPTED} WHERE {SCOPE} AND run_id = $4::uuid "
                    "AND obligation_key = $5 AND deliverable_id = $6 AND output_revision_id = $7",
                    *args,
                    run_id,
                    revision.obligation_key,
                    revision.deliverable_id,
                    _uuid(expected_head),
                )
                if current is not None and generation < current["generation"]:
                    raise StaleGeneration(
                        f"generation {generation} is older than {current['generation']}"
                    )
                row = await connection.fetchrow(
                    f"UPDATE {_ACCEPTED} SET output_revision_id = $7, generation = $8, "
                    "version = version + 1, promoted_at = GREATEST($9::timestamptz, promoted_at), "
                    f"promoted_by_actor_ref = $10 WHERE {SCOPE} AND run_id = $4::uuid "
                    "AND obligation_key = $5 AND deliverable_id = $6 AND output_revision_id = $11 "
                    "RETURNING *",
                    *args,
                    run_id,
                    revision.obligation_key,
                    revision.deliverable_id,
                    UUID(revision.revision_id),
                    generation,
                    at,
                    actor_ref,
                    _uuid(expected_head),
                )
            if row is None:
                latest = await connection.fetchval(
                    f"SELECT output_revision_id FROM {_ACCEPTED} WHERE {SCOPE} "
                    "AND run_id = $4::uuid AND obligation_key = $5 AND deliverable_id = $6",
                    *args,
                    run_id,
                    revision.obligation_key,
                    revision.deliverable_id,
                )
                raise StaleHead(
                    "accepted head moved", current=None if latest is None else str(latest)
                )
        return _head(row)

    async def accepted_outputs(self, scope: str, run_id: str) -> tuple[ExactOutput, ...]:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            rows = await connection.fetch(
                f"SELECT output.* FROM {_ACCEPTED} head JOIN {_OUTPUT} output "
                "ON output.installation_id = head.installation_id "
                "AND output.application_id = head.application_id "
                "AND output.tenant_id = head.tenant_id "
                "AND output.output_revision_id = head.output_revision_id "
                "WHERE head.installation_id = $1 AND head.application_id = $2 "
                "AND head.tenant_id = $3 AND head.run_id = $4::uuid "
                "ORDER BY head.obligation_key, head.deliverable_id",
                *args,
                run_id,
            )
        return tuple(_output(row) for row in rows)

    async def submitted_outputs(
        self,
        scope: str,
        run_id: str,
        obligation_key: str,
        *,
        operation_ref: str,
        operation_attempt: int | None = None,
        execution_generation: int | None = None,
    ) -> tuple[ExactOutput, ...]:
        """WI-02: the newest revision of each deliverable of ``obligation_key`` whose producing
        invocation was finalized (not a failed attempt); never a draft of a running attempt."""

        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            rows = await connection.fetch(
                f"SELECT DISTINCT ON (output.deliverable_id) output.* FROM {_OUTPUT} output "
                f"JOIN {_SUBMISSION} submission ON submission.installation_id = "
                "output.installation_id AND submission.application_id = output.application_id "
                "AND submission.tenant_id = output.tenant_id "
                "AND submission.submission_id = output.submission_id "
                f"JOIN {_FINALIZATION} finalization ON finalization.installation_id = "
                "submission.installation_id AND finalization.application_id = "
                "submission.application_id AND finalization.tenant_id = submission.tenant_id "
                "AND finalization.invocation_ref = submission.invocation_ref "
                "WHERE output.installation_id = $1 AND output.application_id = $2 "
                "AND output.tenant_id = $3 AND output.run_id = $4::uuid "
                "AND output.obligation_key = $5 AND submission.operation_ref = $6 "
                "AND ($7::integer IS NULL OR submission.operation_attempt = $7) "
                "AND ($8::integer IS NULL OR submission.execution_generation = $8) "
                "AND finalization.outcome_basis <> 'attempt_failed' "
                # A rejected (fail) or held (review) revision is never a fallback input.
                f"AND NOT EXISTS (SELECT 1 FROM {_ASSESSMENT} assessment "
                "WHERE assessment.installation_id = output.installation_id "
                "AND assessment.application_id = output.application_id "
                "AND assessment.tenant_id = output.tenant_id "
                "AND assessment.subject_kind = 'output_revision' "
                "AND assessment.subject_ref = output.output_revision_id::text "
                "AND assessment.subject_digest = output.content_digest "
                "AND assessment.result IN ('fail', 'review')) "
                "ORDER BY output.deliverable_id, output.revision DESC",
                *args,
                run_id,
                obligation_key,
                operation_ref,
                operation_attempt,
                execution_generation,
            )
        return tuple(_output(row) for row in rows)

    async def finalized_subject_outputs(
        self,
        scope: str,
        run_id: str,
        obligation_key: str,
        *,
        operation_ref: str,
        operation_attempt: int,
        execution_generation: int,
    ) -> tuple[ExactOutput, ...]:
        """Exact finalized attempt subjects, including held/rejected; never accepted use."""

        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            rows = await connection.fetch(
                f"SELECT DISTINCT ON (output.deliverable_id) output.* FROM {_OUTPUT} output "
                f"JOIN {_SUBMISSION} submission ON submission.installation_id = "
                "output.installation_id AND submission.application_id = output.application_id "
                "AND submission.tenant_id = output.tenant_id "
                "AND submission.submission_id = output.submission_id "
                f"JOIN {_FINALIZATION} finalization ON finalization.installation_id = "
                "submission.installation_id AND finalization.application_id = "
                "submission.application_id AND finalization.tenant_id = submission.tenant_id "
                "AND finalization.invocation_ref = submission.invocation_ref "
                "WHERE output.installation_id = $1 AND output.application_id = $2 "
                "AND output.tenant_id = $3 AND output.run_id = $4::uuid "
                "AND output.obligation_key = $5 AND submission.operation_ref = $6 "
                "AND submission.operation_attempt = $7 "
                "AND submission.execution_generation = $8 "
                "AND finalization.outcome_basis <> 'attempt_failed' "
                "ORDER BY output.deliverable_id, output.revision DESC",
                *args,
                run_id,
                obligation_key,
                operation_ref,
                operation_attempt,
                execution_generation,
            )
        return tuple(_output(row) for row in rows)

    async def finalized_outputs(self, scope: str, run_id: str) -> tuple[ExactOutput, ...]:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            rows = await connection.fetch(
                f"SELECT output.* FROM {_OUTPUT} output "
                f"JOIN {_SUBMISSION} submission ON submission.installation_id = "
                "output.installation_id AND submission.application_id = output.application_id "
                "AND submission.tenant_id = output.tenant_id "
                "AND submission.submission_id = output.submission_id "
                f"JOIN {_FINALIZATION} finalization ON finalization.installation_id = "
                "submission.installation_id AND finalization.application_id = "
                "submission.application_id AND finalization.tenant_id = submission.tenant_id "
                "AND finalization.invocation_ref = submission.invocation_ref "
                "WHERE output.installation_id = $1 AND output.application_id = $2 "
                "AND output.tenant_id = $3 AND output.run_id = $4::uuid "
                "AND finalization.outcome_basis <> 'attempt_failed' "
                "ORDER BY output.obligation_key, output.deliverable_id, output.revision",
                *args,
                run_id,
            )
        return tuple(_output(row) for row in rows)

    # ------------------------------------------------------------------ sets

    async def pin_set(self, scope: str, run_id: str, *, actor_ref: str, at: datetime) -> OutputSet:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            await apply_actor(connection, actor_ref)
            await _run_lock(connection, scope, run_id)
            heads = await connection.fetch(
                f"SELECT obligation_key, active_revision FROM {_HEAD} WHERE {SCOPE} "
                "AND run_id = $4::uuid ORDER BY ordinal",
                *args,
                run_id,
            )
            refs = tuple((row["obligation_key"], int(row["active_revision"])) for row in heads)
            members = tuple(
                _output(row)
                for row in await connection.fetch(
                    f"SELECT output.* FROM {_ACCEPTED} head JOIN {_OUTPUT} output "
                    "ON output.installation_id = head.installation_id "
                    "AND output.application_id = head.application_id "
                    "AND output.tenant_id = head.tenant_id "
                    "AND output.output_revision_id = head.output_revision_id "
                    "WHERE head.installation_id = $1 AND head.application_id = $2 "
                    "AND head.tenant_id = $3 AND head.run_id = $4::uuid "
                    "ORDER BY head.obligation_key, head.deliverable_id",
                    *args,
                    run_id,
                )
            )
            digest = membership_digest(refs, members)
            latest = await connection.fetchrow(
                f"SELECT output_set_id, revision, membership_digest FROM {_SET} WHERE {SCOPE} "
                "AND run_id = $4::uuid ORDER BY revision DESC LIMIT 1",
                *args,
                run_id,
            )
            if latest is not None and latest["membership_digest"] == digest:
                set_id = str(latest["output_set_id"])
            else:
                set_id = str(uuid4())
                await connection.execute(
                    f"INSERT INTO {_SET} (installation_id, application_id, tenant_id, "
                    "output_set_id, run_id, revision, obligation_refs, membership_digest, "
                    "prior_set_id, created_at, created_by_actor_ref) VALUES ($1, $2, $3, $4, "
                    "$5::uuid, $6, $7::jsonb, $8, $9, $10, $11)",
                    *args,
                    UUID(set_id),
                    run_id,
                    1 if latest is None else int(latest["revision"]) + 1,
                    _dump([[key, revision] for key, revision in refs]),
                    digest,
                    None if latest is None else latest["output_set_id"],
                    at,
                    actor_ref,
                )
                for member in members:
                    await connection.execute(
                        f"INSERT INTO {_MEMBER} (installation_id, application_id, tenant_id, "
                        "output_set_id, output_revision_id, obligation_key, deliverable_id, "
                        "content_digest) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
                        *args,
                        UUID(set_id),
                        UUID(member.revision_id),
                        member.obligation_key,
                        member.deliverable_id,
                        member.content_digest,
                    )
        pinned = await self.output_set(scope, set_id)
        assert pinned is not None
        return pinned

    async def output_set(self, scope: str, set_id: str) -> OutputSet | None:
        parsed = _uuid(set_id)
        if parsed is None:
            return None
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            row = await connection.fetchrow(
                f"SELECT * FROM {_SET} WHERE {SCOPE} AND output_set_id = $4", *args, parsed
            )
            if row is None:
                return None
            members = await connection.fetch(
                f"SELECT output.* FROM {_MEMBER} member JOIN {_OUTPUT} output "
                "ON output.installation_id = member.installation_id "
                "AND output.application_id = member.application_id "
                "AND output.tenant_id = member.tenant_id "
                "AND output.output_revision_id = member.output_revision_id "
                "WHERE member.installation_id = $1 AND member.application_id = $2 "
                "AND member.tenant_id = $3 AND member.output_set_id = $4 "
                "ORDER BY member.obligation_key, member.deliverable_id",
                *args,
                parsed,
            )
        return OutputSet(
            set_id=str(row["output_set_id"]),
            revision=int(row["revision"]),
            obligation_refs=tuple(
                (str(key), int(rev)) for key, rev in mc.load(row["obligation_refs"])
            ),
            members=tuple(_output(item) for item in members),
            membership_digest=row["membership_digest"],
            prior_set_id=None if row["prior_set_id"] is None else str(row["prior_set_id"]),
        )

    # ------------------------------------------------------------------ assessments, decisions

    async def record_output_assessment(
        self, scope: str, run_id: str, assessment: Assessment, *, actor_ref: str, at: datetime
    ) -> Assessment:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            await apply_actor(connection, actor_ref)
            if assessment.supersedes is not None or assessment.result == "unavailable":
                # W1 fix G S1: supersession, and a first unavailable wait, are a compare-and-set
                # on the subject's standing row. The transaction-scoped advisory lock (one key per
                # exact subject) serializes the writers, so the rival check below cannot
                # interleave with a rival's insert.
                await connection.execute(
                    "SELECT pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended($1, 0))",
                    f"mc.output_assessment.standing:{scope}:{assessment.subject_kind}:"
                    f"{assessment.subject_id}:{assessment.subject_digest}",
                )
                if assessment.supersedes is not None:
                    rival = await connection.fetchval(
                        f"SELECT assessment_id FROM {_ASSESSMENT} WHERE {SCOPE} "
                        "AND supersedes = $4 AND assessment_id <> $5",
                        *args,
                        _uuid(assessment.supersedes),
                        UUID(assessment.assessment_id),
                    )
                else:
                    # A first wait: no other standing (unsuperseded) unavailable row of the subject.
                    rival = await connection.fetchval(
                        f"SELECT a.assessment_id FROM {_ASSESSMENT} AS a WHERE "
                        "a.installation_id = $1 AND a.application_id = $2 AND a.tenant_id = $3 "
                        "AND a.subject_kind = $4 AND a.subject_ref = $5 AND a.subject_digest = $6 "
                        "AND a.result = 'unavailable' AND a.assessment_id <> $7 "
                        f"AND NOT EXISTS (SELECT 1 FROM {_ASSESSMENT} AS b WHERE "
                        "b.installation_id = a.installation_id AND b.application_id = "
                        "a.application_id AND b.tenant_id = a.tenant_id "
                        "AND b.supersedes = a.assessment_id)",
                        *args,
                        assessment.subject_kind,
                        assessment.subject_id,
                        assessment.subject_digest,
                        UUID(assessment.assessment_id),
                    )
                if rival is not None:
                    raise AssessmentSupersessionConflict(
                        f"the standing assessment of {assessment.subject_id} moved (rival {rival})",
                        prior=assessment.supersedes or "",
                        rival=str(rival),
                    )
            inserted = await connection.fetchval(
                f"INSERT INTO {_ASSESSMENT} (installation_id, application_id, tenant_id, "
                "assessment_id, run_id, subject_kind, subject_ref, output_revision_id, "
                "output_set_id, subject_digest, requirement_results, result, "
                "assessor_origin_ref, method_pin, policy_pin, evidence_refs, findings, "
                "supersedes, created_at, created_by_actor_ref) VALUES ($1, $2, $3, $4, $5::uuid, "
                "$6, $7, $8, $9, $10, $11::jsonb, $12, $13, $14, $15, $16::jsonb, $17::jsonb, "
                "$18, $19, $20) ON CONFLICT DO NOTHING RETURNING assessment_id",
                *args,
                UUID(assessment.assessment_id),
                run_id,
                assessment.subject_kind,
                assessment.subject_id,
                _uuid(assessment.subject_id)
                if assessment.subject_kind == "output_revision"
                else _uuid(assessment.index_revision_id or "")
                if assessment.subject_kind == "member"
                else None,
                _uuid(assessment.subject_id) if assessment.subject_kind == "output_set" else None,
                assessment.subject_digest,
                _dump(dict(assessment.requirement_results)),
                assessment.result,
                assessment.assessor_origin_ref,
                assessment.method_pin,
                assessment.policy_pin,
                _dump(list(assessment.evidence_refs)),
                _dump([item.model_dump(mode="json") for item in assessment.findings]),
                None if assessment.supersedes is None else _uuid(assessment.supersedes),
                at,
                actor_ref,
            )
            if inserted is not None and assessment.result in {"fail", "review"}:
                # WI-19: a held or rejected judgment is a default actionable notice.
                await emit_attention_event(
                    connection,
                    args,
                    run_id=run_id,
                    event_type=OUTPUT_ASSESSMENT_REJECTED
                    if assessment.result == "fail"
                    else OUTPUT_ASSESSMENT_HELD,
                    source_ref=assessment.assessment_id,
                    payload={
                        "assessment_id": assessment.assessment_id,
                        "subject_ref": assessment.subject_id,
                        "result": assessment.result,
                        "reason": assessment.subject_kind,
                    },
                    actor_ref=actor_ref,
                )
            row = await connection.fetchrow(
                f"SELECT * FROM {_ASSESSMENT} WHERE {SCOPE} AND assessment_id = $4",
                *args,
                UUID(assessment.assessment_id),
            )
        assert row is not None  # inserted, or the same deterministic judgment already stored
        return _assessment(row)

    async def output_assessments(self, scope: str, run_id: str) -> tuple[Assessment, ...]:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            rows = await connection.fetch(
                f"SELECT * FROM {_ASSESSMENT} WHERE {SCOPE} AND run_id = $4::uuid "
                "ORDER BY recorded_seq",
                *args,
                run_id,
            )
        return tuple(_assessment(row) for row in rows)

    async def latest_fulfillment(
        self, scope: str, run_id: str, obligation_key: str, obligation_revision: int
    ) -> tuple[str, Fulfillment] | None:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            row = await connection.fetchrow(
                f"SELECT output_set_id, decision FROM {_FULFILLMENT} WHERE {SCOPE} "
                "AND run_id = $4::uuid AND obligation_key = $5 AND obligation_revision = $6 "
                "ORDER BY created_at DESC, fulfillment_id DESC LIMIT 1",
                *args,
                run_id,
                obligation_key,
                obligation_revision,
            )
        return (
            None
            if row is None
            else (str(row["output_set_id"]), Fulfillment.model_validate(mc.load(row["decision"])))
        )

    async def record_fulfillment(
        self,
        scope: str,
        run_id: str,
        set_id: str,
        fulfillment: Fulfillment,
        *,
        actor_ref: str,
        at: datetime,
    ) -> str:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            await apply_actor(connection, actor_ref)
            prior = await connection.fetchval(
                f"SELECT disposition FROM {_FULFILLMENT} WHERE {SCOPE} AND run_id = $4::uuid "
                "AND obligation_key = $5 ORDER BY created_at DESC, fulfillment_id LIMIT 1",
                *args,
                run_id,
                fulfillment.obligation_key,
            )
            fulfillment_id = uuid4()
            inserted = await connection.fetchval(
                f"INSERT INTO {_FULFILLMENT} (installation_id, application_id, tenant_id, "
                "fulfillment_id, run_id, output_set_id, obligation_key, obligation_revision, "
                "enforcement, disposition, distinct_count, decision, decision_digest, "
                "created_at, created_by_actor_ref) VALUES ($1, $2, $3, $4, $5::uuid, $6, $7, $8, "
                "$9, $10, $11, $12::jsonb, $13, $14, $15) ON CONFLICT DO NOTHING "
                "RETURNING fulfillment_id",
                *args,
                fulfillment_id,
                run_id,
                UUID(set_id),
                fulfillment.obligation_key,
                fulfillment.obligation_revision,
                fulfillment.enforcement.value,
                fulfillment.disposition,
                fulfillment.distinct_count,
                _dump(fulfillment.model_dump(mode="json")),
                fulfillment.digest,
                at,
                actor_ref,
            )
            unmet = fulfillment.disposition in {"unfulfilled", "blocked"}
            if (
                inserted is not None
                and prior != fulfillment.disposition
                and (fulfillment.disposition == "fulfilled" or unmet)
                and not (unmet and fulfillment.enforcement.value == "optional")
            ):
                # WI-19: a changed disposition (unmet only when required or expected) wakes the
                # coordinator; the run's final evaluation is how an unmet promise reaches it.
                await emit_attention_event(
                    connection,
                    args,
                    run_id=run_id,
                    event_type=OUTPUT_FULFILLED if not unmet else OUTPUT_FULFILLMENT_UNMET,
                    source_ref=str(fulfillment_id),
                    payload={
                        "obligation_key": fulfillment.obligation_key,
                        "disposition": fulfillment.disposition,
                        "enforcement": fulfillment.enforcement.value,
                        "output_set_id": set_id,
                        "reason": ",".join(item.code for item in fulfillment.unmet)[:256] or None,
                    },
                    actor_ref=actor_ref,
                )
        return fulfillment.digest

    async def association_steps(
        self, scope: str, invocation_ref: str, obligation_key: str
    ) -> frozenset[str]:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            rows = await connection.fetch(
                f"SELECT step FROM {_STEP} WHERE {SCOPE} AND invocation_ref = $4 "
                "AND obligation_key = $5",
                *args,
                invocation_ref,
                obligation_key,
            )
        return frozenset(row["step"] for row in rows)

    async def record_association_step(
        self,
        scope: str,
        run_id: str,
        invocation_ref: str,
        obligation_key: str,
        step: str,
        detail: Mapping[str, Any],
        *,
        actor_ref: str,
        at: datetime,
    ) -> bool:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            await apply_actor(connection, actor_ref)
            inserted = await connection.fetchval(
                f"INSERT INTO {_STEP} (installation_id, application_id, tenant_id, run_id, "
                "invocation_ref, obligation_key, step, detail, created_at, created_by_actor_ref) "
                "VALUES ($1, $2, $3, $4::uuid, $5, $6, $7, $8::jsonb, $9, $10) "
                "ON CONFLICT DO NOTHING RETURNING 1",
                *args,
                run_id,
                invocation_ref,
                obligation_key,
                step,
                _dump(dict(detail)),
                at,
                actor_ref,
            )
        return inserted is not None


def _submitted(row: asyncpg.Record) -> SubmittedRevision:
    return SubmittedRevision(
        revision_id=str(row["output_revision_id"]),
        deliverable_id=row["deliverable_id"],
        revision=int(row["revision"]),
        content_digest=row["content_digest"],
    )


__all__ = ["PostgresOutputContractStore"]
