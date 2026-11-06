"""Exact export snapshots written inside ordinary chain release; no network in the transaction."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from uuid import UUID, uuid5

import asyncpg

from mission_control.adapters.postgres.chains.goal_findings import load_goal_findings
from mission_control.adapters.postgres.documents import PostgresDocumentStore
from mission_control.adapters.postgres.run_control import canonical as mc
from mission_control.application.chains.reducer import MemberRun, link_satisfied
from mission_control.application.chains.relay import ChainIntent
from mission_control.domain.composition.chain import (
    ChainBinding,
    ChainLink,
    MissionChain,
)
from mission_control.domain.context.transfer import LinkedExport, LinkedOutputRef

EXPORT_CONTRACT = "linked.export/1"
_NAMESPACE = UUID("fc48d4aa-b787-48aa-a90c-10952811c814")
POLICY_FIELDS = ("receiving_purpose", "placement", "alternatives", "evidence_required", "selector")


def transfer_policy(link: ChainLink) -> dict:
    return link.model_dump(mode="json", include=set(POLICY_FIELDS))


def exact_link(link: ChainLink) -> bool:
    """Old persisted bindings without exact canonical positions retain their legacy route."""
    return link.has_exact_bindings


async def _snapshot(
    connection: asyncpg.Connection,
    args: tuple,
    scope: str,
    source: MemberRun,
    binding: ChainBinding,
    *,
    repair: bool,
) -> tuple[LinkedOutputRef, ...]:
    await mc.advisory_lock(connection, f"output_run:{scope}:{source.run_key}")
    promise = await connection.fetchrow(
        "SELECT revision.revision, revision.owner_position FROM "
        "mission_control.output_obligation_head head JOIN "
        "mission_control.output_obligation_revision revision USING "
        "(installation_id, application_id, tenant_id, run_id, obligation_key) "
        "WHERE head.installation_id=$1 AND head.application_id=$2 AND head.tenant_id=$3 "
        "AND head.run_id=$4::uuid AND head.obligation_key=$5 "
        "AND revision.revision=head.active_revision",
        *args,
        source.run_key,
        binding.output_key,
    )
    if promise is None or promise["owner_position"] != binding.source_position:
        raise ValueError("linked export has no exact owned active source promise")
    if repair:
        rows = await connection.fetch(
            "SELECT DISTINCT ON (output.deliverable_id) output.*, NULL::bigint AS generation, "
            "submission.operation_ref, submission.operation_attempt, "
            "submission.execution_generation "
            "FROM mission_control.output_revision output "
            "JOIN mission_control.output_submission submission USING "
            "(installation_id, application_id, tenant_id, submission_id) "
            "JOIN mission_control.invocation_finalization finalization ON "
            "finalization.installation_id=submission.installation_id AND "
            "finalization.application_id=submission.application_id AND "
            "finalization.tenant_id=submission.tenant_id AND "
            "finalization.invocation_ref=submission.invocation_ref "
            "WHERE output.installation_id=$1 AND output.application_id=$2 AND output.tenant_id=$3 "
            "AND output.run_id=$4::uuid AND output.obligation_key=$5 "
            "AND output.obligation_revision=$6 AND finalization.outcome_basis <> 'attempt_failed' "
            "ORDER BY output.deliverable_id, output.revision DESC",
            *args,
            source.run_key,
            binding.output_key,
            promise["revision"],
        )
    else:
        rows = await connection.fetch(
            "SELECT output.*, head.generation FROM mission_control.output_accepted_head head "
            "JOIN mission_control.output_revision output USING "
            "(installation_id, application_id, tenant_id, output_revision_id) "
            "WHERE head.installation_id=$1 AND head.application_id=$2 AND head.tenant_id=$3 "
            "AND head.run_id=$4::uuid AND head.obligation_key=$5 "
            "AND output.obligation_revision=$6 ORDER BY output.deliverable_id",
            *args,
            source.run_key,
            binding.output_key,
            promise["revision"],
        )
    if not rows:
        raise ValueError("linked export has no eligible exact source revisions")
    selected = []
    for row in rows:
        findings = (
            await load_goal_findings(
                connection,
                args,
                scope=scope,
                run_id=source.run_key,
                operation_ref=row["operation_ref"],
                operation_attempt=row["operation_attempt"],
                execution_generation=row["execution_generation"],
            )
            if repair
            else None
        )
        selected.append(
            LinkedOutputRef(
                obligation_key=row["obligation_key"],
                obligation_revision=row["obligation_revision"],
                owner_position=binding.source_position,
                revision_id=str(row["output_revision_id"]),
                content_digest=row["content_digest"],
                goal_findings=findings,
                acceptance_ref=None
                if repair
                else (
                    f"mc-accepted-head:{source.run_key}/{row['obligation_key']}/"
                    f"{row['deliverable_id']}@{row['generation']}#"
                    f"revision={row['output_revision_id']}&digest={row['content_digest']}"
                ),
            )
        )
    return tuple(selected)


async def seal_link_exports(
    connection: asyncpg.Connection,
    args: tuple,
    *,
    chain: MissionChain,
    links: Sequence[ChainLink],
    sources: Mapping[UUID, MemberRun],
    receiver: MemberRun,
    scope: str,
    caller_ref: str,
    cause_event_ref: str,
    at: datetime,
) -> tuple[LinkedExport, ...]:
    sealed = []
    for link in sorted(links, key=lambda item: str(item.link_id)):
        if not exact_link(link):
            continue
        source = None if link.from_mission_id is None else sources.get(link.from_mission_id)
        if source is None or not link_satisfied(link, source):
            raise ValueError("linked export source release gate is not satisfied")
        for binding in link.bindings:
            repair = link.receiving_purpose == "repair"
            outputs = await _snapshot(connection, args, scope, source, binding, repair=repair)
            export = LinkedExport(
                export_id=str(
                    uuid5(
                        _NAMESPACE,
                        json.dumps(
                            [
                                str(chain.chain_id),
                                str(link.link_id),
                                receiver.run_key,
                                binding.receiver_position,
                                binding.input_name,
                            ]
                        ),
                    )
                ),
                request_scope=scope,
                chain_id=str(chain.chain_id),
                link_id=str(link.link_id),
                release_event_ref=cause_event_ref,
                caller_ref=caller_ref,
                source_mission_id=str(source.mission_id),
                source_run_id=source.run_key,
                receiver_mission_id=str(receiver.mission_id),
                receiver_run_id=receiver.run_key,
                receiver_position=binding.receiver_position,
                input_name=binding.input_name,
                purpose=link.receiving_purpose,
                admission="subject" if repair else "accepted",
                release_gate=link.on.kind,
                source_goal=link.on.goal_key,
                gate_ref=f"{cause_event_ref}#frontier={source.evidence_frontier_digest}",
                outputs=outputs,
                required=binding.required,
                placement=link.placement,
                alternatives=link.alternatives,
                evidence_required=link.evidence_required,
            )
            await PostgresDocumentStore.put_on(
                connection,
                request_scope=scope,
                contract=EXPORT_CONTRACT,
                identity=export.export_id,
                payload=export.model_dump(mode="json"),
                recorded_at=at,
            )
            sealed.append(export)
    return tuple(sealed)


class PostgresLinkedExports:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def released_for(
        self, scope: str, receiver_run_id: str, receiver_position: str
    ) -> tuple[LinkedExport, ...]:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            identities = await connection.fetch(
                f"SELECT identity FROM mission_control.runtime_document WHERE {mc.SCOPE} "
                "AND contract=$4 AND payload->>'receiver_run_id'=$5 "
                "AND payload->>'receiver_position'=$6 ORDER BY identity",
                *args,
                EXPORT_CONTRACT,
                receiver_run_id,
                receiver_position,
            )
        result = []
        for row in identities:
            export = await self.get_export(scope, row["identity"])
            if export is None:
                raise ValueError("released linked export authority is unavailable")
            result.append(export)
        return tuple(result)

    async def get_export(self, scope: str, export_id: str) -> LinkedExport | None:
        record = await PostgresDocumentStore(self._pool).get(
            request_scope=scope,
            contract=EXPORT_CONTRACT,
            identity=export_id,
        )
        if record is None:
            return None
        export = LinkedExport.model_validate(record.payload)
        if export.export_id != export_id or export.request_scope != scope:
            raise ValueError("linked export document scope or identity differs")
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            released = await connection.fetchval(
                "SELECT EXISTS(SELECT 1 FROM mission_control.chain_link link JOIN "
                "mission_control.mission_run receiver ON "
                "receiver.installation_id=link.installation_id "
                "AND receiver.application_id=link.application_id "
                "AND receiver.tenant_id=link.tenant_id "
                "AND receiver.run_id=link.released_run_id "
                "WHERE link.installation_id=$1 AND link.application_id=$2 AND link.tenant_id=$3 "
                "AND link.chain_id=$4::uuid AND link.link_id=$5::uuid "
                "AND link.from_mission_id=$6::uuid AND link.to_mission_id=$7::uuid "
                "AND link.state IN ('released','detached') "
                "AND receiver.projection->>'run_id'=$8)",
                *args,
                export.chain_id,
                export.link_id,
                export.source_mission_id,
                export.receiver_mission_id,
                export.receiver_run_id,
            )
        return export if released else None


class PostgresChainStartGate:
    """A queued release does not authorize a pending consumer after source cancellation."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def ensure_startable(self, intent: ChainIntent) -> None:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, intent.request_scope)
            consumer = await connection.fetchval(
                f"SELECT projection FROM mission_control.mission_run WHERE {mc.SCOPE} "
                "AND run_id=$4 AND mission_id=$5",
                *args,
                intent.run_id,
                intent.mission_id,
            )
            if consumer is None:
                raise ValueError("chain receiver admission is unavailable")
            projection = mc.load(consumer)
            if projection["phase"] == "cancelling" or (
                projection["phase"] == "terminal"
                and projection.get("terminal_outcome") == "cancelled"
            ):
                raise ValueError("chain receiver was cancelled before relay delivery")
            if projection["phase"] != "pending":
                return  # already-running independent consumers retain valid sealed inputs
            rows = await connection.fetch(
                "SELECT link.state, source.projection FROM mission_control.chain_link link "
                "JOIN LATERAL (SELECT run.projection FROM mission_control.mission_run run "
                "WHERE run.installation_id=link.installation_id "
                "AND run.application_id=link.application_id AND run.tenant_id=link.tenant_id "
                "AND run.mission_id=link.from_mission_id "
                "AND run.projection->>'run_id'=COALESCE((SELECT document.payload->>'source_run_id' "
                "FROM mission_control.runtime_document document WHERE "
                "document.installation_id=link.installation_id "
                "AND document.application_id=link.application_id "
                "AND document.tenant_id=link.tenant_id AND document.contract='linked.export/1' "
                "AND document.payload->>'link_id'=link.link_id::text "
                "AND document.payload->>'receiver_run_id'=$6 LIMIT 1), "
                "run.projection->>'run_id') "
                "ORDER BY run.created_at DESC, run.run_id DESC LIMIT 1) source ON true "
                "WHERE link.installation_id=$1 AND link.application_id=$2 AND link.tenant_id=$3 "
                "AND link.chain_id=$4 AND link.to_mission_id=$5",
                *args,
                intent.chain_id,
                intent.mission_id,
                intent.run_key,
            )
            if not rows or len(rows) != len(intent.link_ids):
                raise ValueError("chain receiver release set is unavailable")
            if any(
                row["state"] != "released"
                or mc.load(row["projection"]).get("terminal_outcome") == "cancelled"
                or mc.load(row["projection"]).get("phase") == "cancelling"
                for row in rows
            ):
                raise ValueError("chain source cancellation or detachment blocks pending launch")
