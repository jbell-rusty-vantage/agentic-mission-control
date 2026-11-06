"""Actual 1.5.0 installer proof (Sprint V SV-13): the knowledge operation journal, content
lineage, source bindings and retained reads, submissions, transfer plans and delivery receipts.
Prior releases and their proof remain immutable."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from uuid import uuid4

import asyncpg
import pytest

from mission_control_db_contract.deployment import verify_release
from tests.integration.postgres.test_run2_release_141 import (
    PACKAGE,
    VERSIONS,
    assert_runtime_security,
    context,
    disposable,
    install,
    release_at,
)
from tests.integration.postgres.test_run2_release_142 import preserve_document

pytestmark = [pytest.mark.asyncio, pytest.mark.common_db]
SUCCESSOR = PACKAGE / "releases/1.5.0/component"
PREVIOUS = PACKAGE / "releases/1.4.4/component"
MIGRATIONS = [
    "0050_knowledge_operations",
    "0051_content_lineage",
    "0052_source_bindings_retained_observations",
    "0053_submissions",
    "0054_transfer_plans_delivery_receipts",
]
TABLES = (
    "knowledge_operation_journal",
    "knowledge_operation_transition",
    "content_lineage",
    "context_source_binding",
    "retained_read_observation",
    "output_submission",
    "invocation_finalization",
    "context_transfer_plan",
    "context_delivery_receipt",
    "context_delivery_outbox",
)
DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
RUN_ID = uuid4()
MISSION_ID = uuid4()


async def create_tenant(connection, target):
    tenant = uuid4()
    await connection.execute(
        "INSERT INTO mission_control.tenant "
        "(installation_id,application_id,tenant_id,external_tenant_ref,state,"
        "qualification_fixture,created_at,created_by_actor_ref) "
        "VALUES ($1::uuid,$2,$3,$4,'active',true,now(),'fixture:sprint-v')",
        target["installation_id"],
        target["application_id"],
        tenant,
        f"sprint-v-{tenant}",
    )
    return tenant


@asynccontextmanager
async def as_role(connection, target, tenant, role="mission_control_runtime"):
    async with connection.transaction():
        await connection.execute(f"SET LOCAL ROLE {role}")
        await context(connection, target, tenant)
        yield


def origin(attempt=1):
    return {
        "issuer": "mc-installation",
        "run_id": str(RUN_ID),
        "operation_id": "goal-iteration/1/executor",
        "attempt": attempt,
    }


def candidate(target, tenant, effect_key, digest=DIGEST_A, **updates):
    row = {
        "installation_id": target["installation_id"],
        "application_id": target["application_id"],
        "tenant_id": str(tenant),
        "knowledge_operation_id": str(uuid4()),
        "effect_key": effect_key,
        "semantic_payload_digest": DIGEST_A,
        "bound_effect_digest": digest,
        "originating_origin": origin(),
        "current_caller_origin": origin(),
        "mission_id": str(MISSION_ID),
        "run_id": str(RUN_ID),
        "operation_ref": "goal-iteration/1/executor",
        "operation_attempt": 1,
        "execution_generation": 1,
        "capability_pin": "ai-engineer.research@1:report.publish",
        "binding_id": "ai-engineer.research@1",
        "state": "prepared",
        "reconciled": False,
        "version": 1,
        "prepared_at": "2026-10-24T00:00:00Z",
        "updated_at": "2026-10-24T00:00:00Z",
        "created_at": "2026-10-24T00:00:00Z",
        "created_by_actor_ref": "fixture:sprint-v",
        **updates,
    }
    return json.dumps(row)


async def admit(connection, target, tenant, effect_key, digest=DIGEST_A, **updates):
    return await connection.fetchrow(
        "SELECT * FROM mission_control.admit_knowledge_operation($1::jsonb)",
        candidate(target, tenant, effect_key, digest, **updates),
    )


async def raises_sqlstate(connection, sqlstate, query, *args):
    with pytest.raises(asyncpg.PostgresError) as caught:
        async with connection.transaction():
            await connection.execute(query, *args)
    assert caught.value.sqlstate == sqlstate, caught.value
    return caught.value


@pytest.mark.parametrize("upgrade", [None, "1.4.4"], ids=["fresh", "upgrade-from-144"])
async def test_release_150_installs_the_knowledge_boundary_records(tmp_path, upgrade):
    successor = release_at(SUCCESSOR, tmp_path / "successor-lock", "biotech")
    async with disposable(tmp_path, "biotech") as (target, connection):
        before_receipts = []
        document = None
        if upgrade:
            previous = release_at(PREVIOUS, tmp_path / "previous-lock", "biotech")
            await install(target, previous)
            before_receipts = await connection.fetch(
                "SELECT * FROM mission_control.component_release ORDER BY migration_key"
            )
            _tenant, document = await preserve_document(connection, target)
            for table in TABLES:
                regclass = f"SELECT to_regclass('mission_control.{table}')"
                assert await connection.fetchval(regclass) is None

        result = await install(target, successor)
        assert result["component_version"] == "1.5.0"
        if upgrade:
            assert result["applied_migrations"] == MIGRATIONS
        else:
            assert result["applied_migrations"][-5:] == MIGRATIONS
            assert "0049_frame_body_refs" in result["applied_migrations"]
        for row in before_receipts:
            assert (
                await connection.fetchrow(
                    "SELECT * FROM mission_control.component_release WHERE migration_key=$1",
                    row["migration_key"],
                )
                == row
            )
        if document is not None:
            assert (
                await connection.fetchrow(
                    "SELECT * FROM mission_control.runtime_document WHERE runtime_document_id=$1",
                    document["runtime_document_id"],
                )
                == document
            )
        for table in TABLES:
            assert await connection.fetchval(
                "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class "
                "WHERE oid=$1::regclass",
                "mission_control." + table,
            ), table
            assert await connection.fetchval(
                "SELECT obj_description($1::regclass, 'pg_class') IS NOT NULL",
                "mission_control." + table,
            ), table
            assert not await connection.fetchval(
                "SELECT has_table_privilege('mission_control_runtime', $1, 'DELETE')",
                "mission_control." + table,
            ), table
            assert await connection.fetchval(
                "SELECT has_table_privilege('mission_control_readonly', $1, 'SELECT')",
                "mission_control." + table,
            ), table
        # Credential bytes have no column anywhere in the journal.
        assert not await connection.fetchval(
            "SELECT count(*) FROM information_schema.columns WHERE table_schema='mission_control' "
            "AND table_name LIKE 'knowledge_operation%' "
            "AND (column_name LIKE '%credential%' OR column_name LIKE '%token%')"
        )
        assert (await verify_release(target, successor, **VERSIONS))["status"] == "verified"
        assert (await install(target, successor))["applied_migrations"] == []
        await assert_runtime_security(connection, target)


async def test_release_150_journal_identity_conflict_transitions_and_isolation(tmp_path):
    successor = release_at(SUCCESSOR, tmp_path / "successor-lock", "biotech")
    async with disposable(tmp_path, "biotech") as (target, connection):
        await install(target, successor)
        tenant = await create_tenant(connection, target)
        other = await create_tenant(connection, target)

        async with as_role(connection, target, tenant):
            first = await admit(connection, target, tenant, "effect:1")
            assert first["state"] == "prepared" and first["version"] == 1
            # A tool retry with the same bound effect returns the same journal row.
            again = await admit(connection, target, tenant, "effect:1")
            assert again["knowledge_operation_id"] == first["knowledge_operation_id"]
            # Same scoped key, different bound effect: EFFECT_CONFLICT, through the function
            # and through a direct insert.
            error = await raises_sqlstate(
                connection,
                "MCE01",
                "SELECT mission_control.admit_knowledge_operation($1::jsonb)",
                candidate(target, tenant, "effect:1", DIGEST_B),
            )
            assert str(error).startswith("EFFECT_CONFLICT")
            await raises_sqlstate(
                connection,
                "MCE01",
                "INSERT INTO mission_control.knowledge_operation_journal "
                "SELECT * FROM jsonb_populate_record("
                "NULL::mission_control.knowledge_operation_journal, $1::jsonb)",
                candidate(target, tenant, "effect:1", DIGEST_B),
            )
            # No credential material in an origin.
            await raises_sqlstate(
                connection,
                "23514",
                "SELECT mission_control.admit_knowledge_operation($1::jsonb)",
                candidate(
                    target,
                    tenant,
                    "effect:credential",
                    originating_origin={**origin(), "credential": "bytes"},
                ),
            )

            operation_id = first["knowledge_operation_id"]
            update = (
                "UPDATE mission_control.knowledge_operation_journal SET {} "
                "WHERE knowledge_operation_id=$1"
            )
            await connection.execute(
                update.format(
                    "state='dispatched', dispatch_id=gen_random_uuid(), envelope_digest=$2, "
                    "protocol_version='knowledge-operation-envelope.v1', dispatched_at=now(), "
                    "version=2, updated_at=now()"
                ),
                operation_id,
                DIGEST_B,
            )
            # Originating origin is frozen after dispatch; identity is always fixed.
            await raises_sqlstate(
                connection,
                "23000",
                update.format(
                    'originating_origin=\'{"issuer":"forged"}\', version=3, updated_at=now()'
                ),
                operation_id,
            )
            # Illegal edge: dispatched -> prepared.
            await raises_sqlstate(
                connection,
                "23000",
                update.format("state='prepared', version=3, updated_at=now()"),
                operation_id,
            )
            # Uncertain, then a retry dispatch from a later caller, then applied with a receipt.
            await connection.execute(
                update.format("state='uncertain', version=3, updated_at=now()"), operation_id
            )
            await connection.execute(
                update.format(
                    "state='dispatched', dispatch_id=gen_random_uuid(), "
                    "current_caller_origin=$2::jsonb, version=4, updated_at=now()"
                ),
                operation_id,
                json.dumps(origin(attempt=2)),
            )
            await connection.execute(
                update.format(
                    "state='applied', operation_id='ks-op-1', terminal_receipt_ref='receipt:1', "
                    "receipt_digest=$2, reconciled=true, settled_at=now(), version=5, "
                    "updated_at=now()"
                ),
                operation_id,
                DIGEST_A,
            )
            # A settled operation keeps its state and receipt.
            await raises_sqlstate(
                connection,
                "23000",
                update.format("state='uncertain', settled_at=NULL, version=6, updated_at=now()"),
                operation_id,
            )
            await raises_sqlstate(
                connection,
                "23000",
                update.format("terminal_receipt_ref='receipt:other', version=6, updated_at=now()"),
                operation_id,
            )
            # The runtime cannot rewrite identity columns at all, nor delete.
            await raises_sqlstate(
                connection,
                "42501",
                update.format("effect_key='effect:other'"),
                operation_id,
            )
            await raises_sqlstate(
                connection,
                "42501",
                "DELETE FROM mission_control.knowledge_operation_journal",
            )
            history = await connection.fetch(
                "SELECT transition_version, from_state, to_state "
                "FROM mission_control.knowledge_operation_transition "
                "WHERE knowledge_operation_id=$1 ORDER BY transition_version",
                operation_id,
            )
            assert [tuple(row) for row in history] == [
                (1, None, "prepared"),
                (2, "prepared", "dispatched"),
                (3, "dispatched", "uncertain"),
                (4, "uncertain", "dispatched"),
                (5, "dispatched", "applied"),
            ]
            await raises_sqlstate(
                connection,
                "42501",
                "UPDATE mission_control.knowledge_operation_transition SET to_state='noop'",
            )

        # Owner mutations still meet the immutable guards.
        await raises_sqlstate(
            connection,
            "23001",
            "DELETE FROM mission_control.knowledge_operation_transition",
        )
        await raises_sqlstate(
            connection,
            "23001",
            "DELETE FROM mission_control.knowledge_operation_journal",
        )
        await raises_sqlstate(
            connection,
            "23000",
            "UPDATE mission_control.knowledge_operation_journal "
            "SET effect_key='x', version=version+1",
        )

        # Another tenant sees nothing, may reuse the same effect key, and cannot write into
        # the first tenant's scope.
        async with as_role(connection, target, other):
            assert (
                await connection.fetchval(
                    "SELECT count(*) FROM mission_control.knowledge_operation_journal"
                )
                == 0
            )
            assert (
                await connection.fetchval(
                    "SELECT count(*) FROM mission_control.knowledge_operation_transition"
                )
                == 0
            )
            reused = await admit(connection, target, other, "effect:1", DIGEST_B)
            assert reused["tenant_id"] == other
            await raises_sqlstate(
                connection,
                "42501",
                "SELECT mission_control.admit_knowledge_operation($1::jsonb)",
                candidate(target, tenant, "effect:cross-tenant"),
            )


async def test_release_150_lineage_submissions_reads_and_delivery(tmp_path):
    successor = release_at(SUCCESSOR, tmp_path / "successor-lock", "biotech")
    async with disposable(tmp_path, "biotech") as (target, connection):
        await install(target, successor)
        tenant = await create_tenant(connection, target)
        scope = (target["installation_id"], target["application_id"], tenant)

        lineage = (
            "INSERT INTO mission_control.content_lineage (installation_id,application_id,"
            "tenant_id,lineage_id,subject_handle,subject_kind,role,actor_kind,actor_ref,"
            "actor_origin,fact,recorded_at,created_at,created_by_actor_ref) VALUES "
            "($1::uuid,$2,$3,gen_random_uuid(),$4,'report',$5,$6,$7,$8::jsonb,$9::jsonb,now(),"
            "now(),'fixture:sprint-v')"
        )
        handle = "kh:ai-engineer.research@1/report_revision/r1@v1"
        origin_json = json.dumps(origin())
        async with as_role(connection, target, tenant):
            await connection.execute(
                lineage, *scope, handle, "producer", "origin", "invocation:1", origin_json, "{}"
            )
            await connection.execute(
                lineage,
                *scope,
                handle,
                "adopter",
                "obligation",
                "obligation:report",
                None,
                json.dumps({"act": "adoption"}),
            )
            # A second producer, an adoption recorded as producer, a role/actor mismatch.
            await raises_sqlstate(
                connection,
                "23505",
                lineage,
                *scope,
                handle,
                "producer",
                "external",
                "external",
                None,
                "{}",
            )
            await raises_sqlstate(
                connection,
                "23514",
                lineage,
                *scope,
                "kh:other@1/report/r2@v1",
                "producer",
                "origin",
                "invocation:1",
                origin_json,
                json.dumps({"act": "adoption"}),
            )
            await raises_sqlstate(
                connection,
                "23514",
                lineage,
                *scope,
                handle,
                "adopter",
                "origin",
                "invocation:1",
                origin_json,
                "{}",
            )
            await raises_sqlstate(
                connection, "42501", "UPDATE mission_control.content_lineage SET actor_ref='x'"
            )

            # Source binding and the retained read of the first dependent invocation.
            binding_id = uuid4()
            await connection.execute(
                "INSERT INTO mission_control.context_source_binding (installation_id,"
                "application_id,tenant_id,source_binding_id,run_id,operation_ref,"
                "operation_attempt,execution_generation,invocation_ref,binding_pin,handle,"
                "handle_kind,native_kind,exact_revision,content_digest,bound_at,created_at,"
                "created_by_actor_ref) VALUES ($1::uuid,$2,$3,$4,$5,'stage:review',1,1,"
                "'invocation:2','ai-engineer.research@1',$6,'report','report_revision','v1',$7,"
                "now(),now(),'fixture:sprint-v')",
                *scope,
                binding_id,
                RUN_ID,
                handle,
                DIGEST_A,
            )
            observation = (
                "INSERT INTO mission_control.retained_read_observation (installation_id,"
                "application_id,tenant_id,observation_id,source_binding_id,run_id,"
                "invocation_ref,handle,read_observation_ref,expected_digest,observed_digest,"
                "readable,observed_at,created_at,created_by_actor_ref) VALUES ($1::uuid,$2,$3,"
                "gen_random_uuid(),$4,$5,'invocation:2',$6,$7,$8,$9,$10,now(),now(),"
                "'fixture:sprint-v') RETURNING digest_verified"
            )
            assert await connection.fetchval(
                observation, *scope, binding_id, RUN_ID, handle, "read:1", DIGEST_A, DIGEST_A, True
            )
            assert not await connection.fetchval(
                observation, *scope, binding_id, RUN_ID, handle, "read:2", DIGEST_A, DIGEST_B, True
            )
            await raises_sqlstate(
                connection,
                "23514",
                observation,
                *scope,
                binding_id,
                RUN_ID,
                handle,
                "read:3",
                DIGEST_A,
                None,
                True,
            )

            # submit_output: a stable key is one submission; a revision is a new one.
            submission = (
                "INSERT INTO mission_control.output_submission (installation_id,application_id,"
                "tenant_id,submission_id,run_id,operation_ref,operation_attempt,"
                "execution_generation,invocation_ref,obligation_id,submission_key,revision,"
                "selection,selection_digest,assessment_state,version,submitted_at,updated_at,"
                "created_at,created_by_actor_ref) VALUES ($1::uuid,$2,$3,gen_random_uuid(),$4,"
                "'stage:draft',1,1,'invocation:1','report',$5,$6,$7::jsonb,$8,'pending',1,now(),"
                "now(),now(),'fixture:sprint-v') "
                "ON CONFLICT (installation_id,application_id,tenant_id,invocation_ref,"
                "obligation_id,submission_key) DO NOTHING RETURNING submission_id"
            )
            selection = json.dumps({"handles": [handle]})
            submitted = await connection.fetchval(
                submission, *scope, RUN_ID, "call:1", 1, selection, DIGEST_A
            )
            assert submitted is not None
            assert (
                await connection.fetchval(
                    submission, *scope, RUN_ID, "call:1", 1, selection, DIGEST_A
                )
                is None
            )
            await raises_sqlstate(
                connection, "MCE02", submission, *scope, RUN_ID, "call:1", 2, selection, DIGEST_B
            )
            assert await connection.fetchval(
                submission, *scope, RUN_ID, "call:2", 2, selection, DIGEST_B
            )
            assess = (
                "UPDATE mission_control.output_submission SET assessment_state=$2, "
                "assessment_ref=$3, assessed_at=now(), version=version+1, updated_at=now() "
                "WHERE submission_id=$1"
            )
            await connection.execute(assess, submitted, "held", "assessment:1")
            await connection.execute(assess, submitted, "assessed", "assessment:2")
            await raises_sqlstate(
                connection, "23000", assess, submitted, "rejected", "assessment:3"
            )
            await raises_sqlstate(
                connection,
                "42501",
                "UPDATE mission_control.output_submission SET selection='{}'::jsonb",
            )

            # Transfer plan, its delivery outbox row and a delivery receipt.
            plan_id = uuid4()
            await connection.execute(
                "INSERT INTO mission_control.context_transfer_plan (installation_id,"
                "application_id,tenant_id,transfer_plan_id,run_id,boundary,target_operation_ref,"
                "plan,plan_digest,required_items,budget_bytes,state,version,planned_at,"
                "updated_at,created_at,created_by_actor_ref) VALUES ($1::uuid,$2,$3,$4,$5,"
                "'stage:draft->stage:review','stage:review',$6::jsonb,$7,1,65536,'planned',1,"
                "now(),now(),now(),'fixture:sprint-v')",
                *scope,
                plan_id,
                RUN_ID,
                json.dumps({"items": [{"handle": handle, "digest": DIGEST_A}]}),
                DIGEST_A,
            )
            await connection.execute(
                "INSERT INTO mission_control.context_delivery_outbox (installation_id,"
                "application_id,tenant_id,delivery_outbox_id,transfer_plan_id,delivery_key,"
                "payload,delivery_state,attempts,next_attempt_at,version,created_at,"
                "created_by_actor_ref) VALUES ($1::uuid,$2,$3,gen_random_uuid(),$4,'deliver:1',"
                "'{}','pending',0,now(),1,now(),'fixture:sprint-v')",
                *scope,
                plan_id,
            )
            plan_update = (
                "UPDATE mission_control.context_transfer_plan SET state=$2, version=version+1, "
                "updated_at=now() WHERE transfer_plan_id=$1"
            )
            await connection.execute(plan_update, plan_id, "delivering")
            await raises_sqlstate(connection, "23000", plan_update, plan_id, "planned")
            receipt = await connection.fetchrow(
                "INSERT INTO mission_control.context_delivery_receipt (installation_id,"
                "application_id,tenant_id,delivery_receipt_id,transfer_plan_id,"
                "receiver_invocation_ref,item_key,handle,delivered_path,required_digest,"
                "delivered_digest,delivered,readable,budget_fit,received_at,created_at,"
                "created_by_actor_ref) VALUES ($1::uuid,$2,$3,gen_random_uuid(),$4,"
                "'invocation:2','item:1',$5,'/inputs/report.md',$6,$6,true,true,true,now(),now(),"
                "'fixture:sprint-v') RETURNING digest_verified, delivered, readable, budget_fit",
                *scope,
                plan_id,
                handle,
                DIGEST_A,
            )
            assert tuple(receipt) == (True, True, True, True)
            await raises_sqlstate(
                connection,
                "42501",
                "UPDATE mission_control.context_delivery_receipt SET readable=false",
            )
            await connection.execute(
                "INSERT INTO mission_control.invocation_finalization (installation_id,"
                "application_id,tenant_id,finalization_id,run_id,operation_ref,operation_attempt,"
                "execution_generation,invocation_ref,outcome,submission_ids,report,report_digest,"
                "finalized_at,created_at,created_by_actor_ref) VALUES ($1::uuid,$2,$3,"
                "gen_random_uuid(),$4,'stage:draft',1,1,'invocation:1','fulfilled',ARRAY[$5::uuid],"
                "'{}',$6,now(),now(),'fixture:sprint-v')",
                *scope,
                RUN_ID,
                submitted,
                DIGEST_A,
            )
            await raises_sqlstate(
                connection,
                "23505",
                "INSERT INTO mission_control.invocation_finalization (installation_id,"
                "application_id,tenant_id,finalization_id,run_id,operation_ref,operation_attempt,"
                "execution_generation,invocation_ref,outcome,report,report_digest,finalized_at,"
                "created_at,created_by_actor_ref) VALUES ($1::uuid,$2,$3,gen_random_uuid(),$4,"
                "'stage:draft',1,1,'invocation:1','unfulfilled','{}',$5,now(),now(),'fixture:x')",
                *scope,
                RUN_ID,
                DIGEST_A,
            )

        # The delivery relay leases and acknowledges only.
        async with as_role(connection, target, tenant, "mission_control_outbox_worker"):
            leased = await connection.execute(
                "UPDATE mission_control.context_delivery_outbox SET delivery_state='leased', "
                "lease_owner='worker-1', lease_expires_at=now() + interval '1 minute', "
                "attempts=attempts+1, version=version+1"
            )
            assert leased == "UPDATE 1"
            await raises_sqlstate(
                connection,
                "42501",
                "UPDATE mission_control.context_delivery_outbox SET payload='{}'::jsonb",
            )
            await raises_sqlstate(
                connection,
                "42501",
                "UPDATE mission_control.context_transfer_plan SET state='delivered'",
            )
