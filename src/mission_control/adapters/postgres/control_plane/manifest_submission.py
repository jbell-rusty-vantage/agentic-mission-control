"""PostgreSQL Mission Manifest submit (SPEC-05 "Submit and start", FT-E3).

One application transaction per submit: the idempotency receipt, every mission's revision (the
typed ``MissionDefinition@1`` as the definition snapshot, the Compiled Program summary, the
typed ``goal``/``objective``/``success_criterion``/``program_node`` rows), the manifest bytes and
resolution as ``authoring_provenance``, then either the admitted Run of the single mission or,
for a chain, the ``mission_chain`` and ``chain_link`` rows, the first member's Run and the frozen
admissions of the later members. Nothing is started: start is the separate authorized call.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from typing import Any
from uuid import UUID, uuid5

import asyncpg

from mission_control.adapters.postgres.chains.store import insert_chain
from mission_control.adapters.postgres.control_plane.mission_revisions import (
    admit_run_for_revision,
    insert_definition_rows,
    insert_revision,
    lock_or_create_mission,
)
from mission_control.adapters.postgres.documents import PostgresDocumentStore
from mission_control.adapters.postgres.run_control import canonical as mc
from mission_control.application.authoring.manifest_fork_admission import (
    SubmittedManifestConfiguration,
)
from mission_control.application.authoring.manifest_submit import (
    ManifestSubmissionReceipt,
    MissionSubmission,
    SubmissionPlan,
    SubmittedMission,
    TenantNotProvisioned,
)
from mission_control.application.execution.service import accepted_admission_mutation
from mission_control.contracts.identities import parse_request_scope, uuid7
from mission_control.domain.authoring.canonical import sha256_digest, stable_json_dump
from mission_control.domain.composition.chain import (
    ChainMemberAdmission,
    ChainResolution,
    ChainScope,
    build_mission_chain,
)
from mission_control.domain.execution.contracts import OperationExecutionRequest
from mission_control.domain.policies.errors import IdempotencyConflict

SUBMIT_ACTION = "mc.manifest.submit"
SUBMIT_ISSUER = "mc.manifest_submit.v1"
DEFINITION_CONTRACT = "mc.mission_definition.v1"
PROGRAM_CONTRACT = "mc.manifest-compiled-program/1"
_CHAIN_NAMESPACE = UUID("2e5b7d10-6c4a-5f2e-9b31-0a8d7c6e5f41")
_SCOPE = mc.SCOPE
_TENANT_PRESENT = (
    f"SELECT EXISTS (SELECT 1 FROM mission_control.tenant WHERE {_SCOPE} AND state = 'active')"
)


def chain_key(resolution: ChainResolution, manifest_digest: str) -> str:
    digest = manifest_digest.removeprefix("sha256:")[:12]
    return f"{resolution.order[0]}.{resolution.order[-1]}.{digest}"


class PostgresManifestSubmissionRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def receipt(
        self, request_scope: str, actor_ref: str, request_id: str
    ) -> tuple[str, ManifestSubmissionReceipt] | None:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, request_scope)
            row = await mc.receipt_row(
                connection,
                args,
                actor_ref=_issuer(actor_ref),
                action=SUBMIT_ACTION,
                request_key=request_id,
            )
        if row is None:
            return None
        return row["payload_digest"], ManifestSubmissionReceipt.model_validate(
            mc.load(row["result"])
        )

    async def tenant_provisioned(self, request_scope: str) -> bool:
        async with self._pool.acquire() as connection, connection.transaction(readonly=True):
            args = await mc.begin(connection, request_scope)
            return bool(await connection.fetchval(_TENANT_PRESENT, *args))

    async def commit(self, plan: SubmissionPlan) -> ManifestSubmissionReceipt:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, plan.request_scope)
            await mc.advisory_lock(connection, f"manifest-submit:{plan.request_id}")
            prior = await mc.receipt_row(
                connection,
                args,
                actor_ref=_issuer(plan.actor_ref),
                action=SUBMIT_ACTION,
                request_key=plan.request_id,
            )
            if prior is not None:
                if prior["payload_digest"] != plan.manifest_digest:
                    raise IdempotencyConflict(
                        "submit request_id was reused with a different manifest digest"
                    )
                return ManifestSubmissionReceipt.model_validate(mc.load(prior["result"]))
            await _require_tenant(connection, args)
            receipt = await self._commit(connection, args, plan)
            await mc.insert_receipt(
                connection,
                args,
                actor_ref=_issuer(plan.actor_ref),
                action=SUBMIT_ACTION,
                request_key=plan.request_id,
                payload_digest=plan.manifest_digest,
                state="completed",
                resource_ref=str(receipt.chain_id or receipt.missions[0].mission_id),
                result=receipt.model_dump(mode="json"),
                recorded_at=plan.at,
            )
            return receipt

    async def _commit(
        self, connection: asyncpg.Connection, args: tuple[Any, ...], plan: SubmissionPlan
    ) -> ManifestSubmissionReceipt:
        heads = [
            await lock_or_create_mission(
                connection,
                args,
                mission_key=item.mission_key,
                title=item.title,
                actor_ref=plan.actor_ref,
                at=plan.at,
            )
            for item in plan.missions
        ]
        if all(
            head.head_definition_digest == item.definition.digest
            for head, item in zip(heads, plan.missions, strict=True)
        ):
            return await self._unchanged(connection, args, plan, heads)
        submitted: list[SubmittedMission] = []
        revisions = []
        for index, (head, item) in enumerate(zip(heads, plan.missions, strict=True)):
            program = {
                "contract": PROGRAM_CONTRACT,
                "family": item.family,
                "effective_configuration_digest": item.effective_configuration_digest,
                "workflow_type_ref": stable_json_dump(item.workflow_type_ref),
                "lowering": dict(item.lowering),
                "definition_digest": item.definition.digest,
            }
            revision = await insert_revision(
                connection,
                args,
                mission_id=head.mission_id,
                definition_contract=DEFINITION_CONTRACT,
                definition=item.definition.model_dump(mode="json"),
                definition_digest=item.definition.digest,
                compiler_version=item.lowering.get("lowering_version", "mc.manifest-lowering/1"),
                program_schema_version=PROGRAM_CONTRACT,
                program=program,
                program_digest=sha256_digest(program),
                policy_digest=item.effective_configuration_digest,
                binding_digest=sha256_digest(
                    {
                        "workflow_type_ref": stable_json_dump(item.workflow_type_ref),
                        "input_manifest": stable_json_dump(item.run_request.input_manifest),
                    }
                ),
                actor_ref=plan.actor_ref,
                at=plan.at,
            )
            revisions.append(revision)
            await insert_definition_rows(
                connection, args, revision.revision_id, item.definition, plan.actor_ref, plan.at
            )
            admit = plan.chain is None or index == 0
            run_uuid: UUID | None = None
            run_key: str | None = None
            if admit:
                mutation = accepted_admission_mutation(item.run_request, item.verified)
                run_uuid = await admit_run_for_revision(
                    connection,
                    args,
                    mutation,
                    mission_id=head.mission_id,
                    revision_id=revision.revision_id,
                    created_by=plan.actor_ref,
                )
                run_key = mutation.decision.run_id
            submitted.append(
                SubmittedMission(
                    mission_key=item.mission_key,
                    mission_id=head.mission_id,
                    revision_id=revision.revision_id,
                    revision_no=revision.revision_no,
                    family=item.family,
                    effective_configuration_digest=item.effective_configuration_digest,
                    run_id=run_key,
                    run_uuid=run_uuid,
                )
            )
        chain_id: UUID | None = None
        if plan.chain is not None:
            chain_id = uuid5(_CHAIN_NAMESPACE, f"{plan.request_scope}:{plan.request_id}")
            scope = parse_request_scope(plan.request_scope)
            chain = build_mission_chain(
                resolution=plan.chain,
                chain_id=chain_id,
                scope=ChainScope(
                    installation_id=scope.installation_id,
                    application_id=scope.application_id,
                    tenant_id=scope.tenant_id,
                ),
                chain_key=chain_key(plan.chain, plan.manifest_digest),
                title=plan.chain_title or " + ".join(plan.chain.order),
                manifest_digest=plan.manifest_digest,
                members={
                    item.mission_key: (item.mission_id, item.revision_id) for item in submitted
                },
                created_at=plan.at,
                created_by_actor_ref=plan.actor_ref,
            )
            by_key = {item.mission_key: item for item in submitted}
            await insert_chain(
                connection,
                args,
                chain,
                [
                    ChainMemberAdmission(
                        chain_id=chain_id,
                        mission_id=by_key[item.mission_key].mission_id,
                        mission_key=item.mission_key,
                        revision_id=by_key[item.mission_key].revision_id,
                        family=item.family,
                        initial_goal=item.initial_goal if item.family == "GoalDirected" else None,
                        autostart=item.autostart,
                        run_request=item.run_request,
                        verified_configuration=item.verified,
                    )
                    for item in plan.missions[1:]
                ],
            )
        for revision, item in zip(revisions, plan.missions, strict=True):
            await _insert_provenance(connection, args, plan, revision.revision_id, item, chain_id)
        return ManifestSubmissionReceipt(
            request_id=plan.request_id,
            manifest_digest=plan.manifest_digest,
            chain_id=chain_id,
            missions=tuple(submitted),
        )

    async def _unchanged(
        self,
        connection: asyncpg.Connection,
        args: tuple[Any, ...],
        plan: SubmissionPlan,
        heads: Sequence[Any],
    ) -> ManifestSubmissionReceipt:
        missions: list[SubmittedMission] = []
        chain_id: UUID | None = None
        for head, item in zip(heads, plan.missions, strict=True):
            revision = await connection.fetchrow(
                f"""
                SELECT revision_id, revision_no FROM mission_control.mission_revision
                WHERE {_SCOPE} AND revision_id = $4
                """,
                *args,
                head.head_revision_id,
            )
            run = await connection.fetchrow(
                f"""
                SELECT run_id, run_key FROM mission_control.mission_run
                WHERE {_SCOPE} AND mission_id = $4 AND revision_id = $5
                ORDER BY created_at DESC LIMIT 1
                """,
                *args,
                head.mission_id,
                head.head_revision_id,
            )
            provenance_chain = await connection.fetchval(
                f"""
                SELECT chain_id FROM mission_control.authoring_provenance
                WHERE {_SCOPE} AND revision_id = $4
                """,
                *args,
                head.head_revision_id,
            )
            chain_id = chain_id or provenance_chain
            missions.append(
                SubmittedMission(
                    mission_key=item.mission_key,
                    mission_id=head.mission_id,
                    revision_id=revision["revision_id"],
                    revision_no=int(revision["revision_no"]),
                    family=item.family,
                    effective_configuration_digest=item.effective_configuration_digest,
                    run_id=run["run_key"] if run is not None else None,
                    run_uuid=run["run_id"] if run is not None else None,
                )
            )
        return ManifestSubmissionReceipt(
            request_id=plan.request_id,
            manifest_digest=plan.manifest_digest,
            unchanged=True,
            chain_id=chain_id,
            missions=tuple(missions),
        )

    async def provenance(self, request_scope: str, revision_id: UUID) -> dict[str, Any] | None:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, request_scope)
            row = await connection.fetchrow(
                f"""
                SELECT revision_id, mission_key, chain_id, manifest_digest, manifest_yaml,
                       resolution, created_at, created_by_actor_ref
                FROM mission_control.authoring_provenance
                WHERE {_SCOPE} AND revision_id = $4
                """,
                *args,
                revision_id,
            )
        if row is None:
            return None
        return {
            "revision_id": str(row["revision_id"]),
            "mission_key": row["mission_key"],
            "chain_id": str(row["chain_id"]) if row["chain_id"] else None,
            "manifest_digest": row["manifest_digest"],
            "manifest_yaml": row["manifest_yaml"],
            "resolution": mc.load(row["resolution"]),
            "created_at": row["created_at"].isoformat(),
            "actor_ref": row["created_by_actor_ref"],
        }

    async def head_run(self, request_scope: str, mission_id: UUID) -> str | None:
        """The run of the mission's scheduling head revision (pending first)."""

        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, request_scope)
            value = await connection.fetchval(
                f"""
                SELECT run.run_key FROM mission_control.mission_run AS run
                JOIN mission_control.mission AS mission
                  ON mission.mission_id = run.mission_id
                 AND mission.installation_id = run.installation_id
                 AND mission.application_id = run.application_id
                 AND mission.tenant_id = run.tenant_id
                WHERE {mc.scoped("run")} AND run.mission_id = $4
                  AND run.revision_id = mission.scheduling_head_revision_id
                ORDER BY (run.phase = 'pending') DESC, run.created_at DESC
                LIMIT 1
                """,
                *args,
                mission_id,
            )
        return str(value) if value is not None else None

    async def run_subscriptions(self, request_scope: str, run_key: str) -> dict[str, Any] | None:
        """The run's mission, revision and the ``controls`` of its committed definition."""

        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, request_scope)
            row = await connection.fetchrow(
                f"""
                SELECT run.run_id, run.mission_id, run.revision_id, snapshot.definition
                FROM mission_control.mission_run AS run
                JOIN mission_control.mission_revision AS revision
                  ON revision.revision_id = run.revision_id
                 AND revision.installation_id = run.installation_id
                 AND revision.application_id = run.application_id
                 AND revision.tenant_id = run.tenant_id
                JOIN mission_control.definition_snapshot AS snapshot
                  ON snapshot.definition_snapshot_id = revision.definition_snapshot_id
                 AND snapshot.installation_id = revision.installation_id
                 AND snapshot.application_id = revision.application_id
                 AND snapshot.tenant_id = revision.tenant_id
                WHERE {mc.scoped("run")} AND run.run_key = $4
                """,
                *args,
                run_key,
            )
        if row is None:
            return None
        definition = mc.load(row["definition"])
        return {
            "run_uuid": row["run_id"],
            "mission_id": row["mission_id"],
            "revision_id": row["revision_id"],
            "definition": definition if isinstance(definition, dict) else {},
        }

    async def submitted_configurations(
        self,
        request_scope: str,
        configuration_digest: str,
    ) -> tuple[SubmittedManifestConfiguration, ...]:
        """Only actual atomic manifest submissions, scoped and pinned to the exact ERC."""
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, request_scope)
            rows = await connection.fetch(
                f"""
                SELECT run.run_key, origin.created_by_actor_ref AS actor_ref,
                       program.created_by_actor_ref AS program_actor_ref,
                       origin.manifest_digest, program.program, program.program_digest
                FROM mission_control.mission_run AS run
                JOIN mission_control.compiled_program AS program
                  ON program.revision_id = run.revision_id
                 AND program.installation_id = run.installation_id
                 AND program.application_id = run.application_id
                 AND program.tenant_id = run.tenant_id
                JOIN mission_control.authoring_provenance AS origin
                  ON origin.revision_id = run.revision_id
                 AND origin.installation_id = run.installation_id
                 AND origin.application_id = run.application_id
                 AND origin.tenant_id = run.tenant_id
                WHERE {mc.scoped("run")}
                  AND program.program_schema_version = 'mc.manifest-compiled-program/1'
                  AND program.program->>'effective_configuration_digest' = $4
                ORDER BY run.run_key LIMIT 2
                """,
                *args,
                configuration_digest,
            )
        return tuple(
            SubmittedManifestConfiguration(
                run_id=row["run_key"],
                actor_id=row["actor_ref"],
                program_actor_id=row["program_actor_ref"],
                manifest_digest=row["manifest_digest"],
                program=mc.load(row["program"]),
                program_digest=row["program_digest"],
            )
            for row in rows
        )

    async def runtime_templates(
        self, request_scope: str, reference: str
    ) -> tuple[OperationExecutionRequest, ...]:
        documents = PostgresDocumentStore(self._pool)
        groups = await asyncio.gather(
            *(
                documents.list(request_scope=request_scope, contract=contract)
                for contract in ("stagegraph.template/1", "goal.template/1")
            )
        )
        operations = []
        for group in groups:
            for document in group:
                binding, _ = json.loads(document.identity)
                if binding != reference:
                    continue
                template = OperationExecutionRequest.model_validate(document.payload)
                if template.request_scope != request_scope:
                    raise ValueError("native template differs from admitted run scope")
                operations.append(template)
        return tuple(operations)


async def _require_tenant(connection: asyncpg.Connection, args: tuple[Any, ...]) -> None:
    """Refuse a submit whose tenant row is absent (W1 D8) instead of failing on the mission
    foreign key. The runtime role reads ``tenant`` under the scope ``mc.begin`` applied."""

    if not await connection.fetchval(_TENANT_PRESENT, *args):
        raise TenantNotProvisioned(
            f"tenant {args[2]} is not provisioned (active) in installation {args[0]} "
            f"application {args[1]}; run mission-db tenant-apply for this deployment"
        )


def _issuer(actor_ref: str) -> str:
    return json.dumps([SUBMIT_ISSUER, actor_ref], separators=(",", ":"))


async def _insert_provenance(
    connection: asyncpg.Connection,
    args: tuple[Any, ...],
    plan: SubmissionPlan,
    revision_id: UUID,
    item: MissionSubmission,
    chain_id: UUID | None,
) -> None:
    await connection.execute(
        """
        INSERT INTO mission_control.authoring_provenance (installation_id, application_id,
            tenant_id, authoring_provenance_id, revision_id, mission_key, chain_id,
            manifest_digest, manifest_yaml, resolution, created_at, created_by_actor_ref)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, $11, $12)
        """,
        *args,
        uuid7(),
        revision_id,
        item.mission_key,
        chain_id,
        plan.manifest_digest,
        plan.manifest_yaml,
        json.dumps(plan.resolution, sort_keys=True),
        plan.at,
        plan.actor_ref,
    )
