"""Actual 1.6.0 installer proof (Sprint V SV-16): durable knowledge handles, the assessment
handoff, the finalization basis and repairable delivery receipts with the readiness guard.
Prior releases and their proof remain immutable."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from mission_control_db_contract.deployment import verify_release
from tests.integration.postgres.test_run2_release_141 import (
    PACKAGE,
    VERSIONS,
    assert_runtime_security,
    disposable,
    install,
    release_at,
)
from tests.integration.postgres.test_sprint_v_release_150 import (
    as_role,
    create_tenant,
    raises_sqlstate,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.common_db]
SUCCESSOR = PACKAGE / "releases/1.6.0/component"
PREVIOUS = PACKAGE / "releases/1.5.0/component"
MIGRATION = "0055_knowledge_handles_assessment_delivery_attempts"
DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
RUN_ID = uuid4()
MISSION_ID = uuid4()
HANDLE_INSERT = (
    "INSERT INTO mission_control.knowledge_operation_handle (installation_id,application_id,"
    "tenant_id,handle_id,binding_id,operation,request_id,remote_operation_id,protocol_version,"
    "handle,effect_key,mission_id,run_id,operation_ref,operation_attempt,execution_generation,"
    "invocation_ref,caller_origin,state,remote_revision,version,recorded_at,updated_at,"
    "created_at,created_by_actor_ref) VALUES ($1::uuid,$2,$3,$4,'aiengineer-postgres',$5,$6,$7,"
    "'ks.knowledge_operation.v2',$8::jsonb,$9,$10,$11,'stage:draft',1,1,'invocation:1',"
    "'{\"kind\":\"mission_invocation\"}'::jsonb,$12,$13,1,now(),now(),now(),'fixture:sprint-v') "
    "RETURNING handle_id"
)
HANDLE_UPDATE = (
    "UPDATE mission_control.knowledge_operation_handle SET state=$2, remote_revision=$3, "
    "pending_review_ref=$4, cancel_request_id=COALESCE(cancel_request_id, $5), error_code=$6, "
    "version=version+1, updated_at=now() WHERE handle_id=$1"
)
SUBMISSION = (
    "INSERT INTO mission_control.output_submission (installation_id,application_id,"
    "tenant_id,submission_id,run_id,operation_ref,operation_attempt,"
    "execution_generation,invocation_ref,obligation_id,submission_key,revision,"
    "selection,selection_digest,assessment_state,version,submitted_at,updated_at,"
    "created_at,created_by_actor_ref) VALUES ($1::uuid,$2,$3,gen_random_uuid(),$4,"
    "'stage:draft',1,1,$5,'report','call:1',1,'{}'::jsonb,$6,'pending',1,now(),"
    "now(),now(),'fixture:sprint-v') RETURNING submission_id"
)
PLAN = (
    "INSERT INTO mission_control.context_transfer_plan (installation_id,application_id,"
    "tenant_id,transfer_plan_id,run_id,boundary,target_operation_ref,plan,plan_digest,"
    "required_items,budget_bytes,state,version,planned_at,updated_at,created_at,"
    "created_by_actor_ref) VALUES ($1::uuid,$2,$3,$4,$5,$6,'stage:review',$7::jsonb,$8,$9,"
    "65536,'planned',1,now(),now(),now(),'fixture:sprint-v')"
)
PLAN_UPDATE = (
    "UPDATE mission_control.context_transfer_plan SET state=$2, blocked_reason=$3, "
    "version=version+1, updated_at=now() WHERE transfer_plan_id=$1"
)
RECEIPT = (
    "INSERT INTO mission_control.context_delivery_receipt (installation_id,application_id,"
    "tenant_id,delivery_receipt_id,transfer_plan_id,receiver_invocation_ref,item_key,handle,"
    "delivered_path,required_digest,delivered_digest,delivered,readable,budget_fit,attempt,"
    "received_at,created_at,created_by_actor_ref) VALUES ($1::uuid,$2,$3,gen_random_uuid(),$4,"
    "'invocation:2',$5,'kh:aiengineer-postgres/report/r1@1','/inputs/r1/body.md',$6,$7,$8,$9,"
    "true,$10,now(),now(),'fixture:sprint-v') RETURNING attempt, outcome_code"
)


def wire_handle(operation_id: str) -> str:
    return json.dumps(
        {
            "protocolVersion": "ks.knowledge_operation.v2",
            "tenant": "t",
            "application": "biotech",
            "binding": "aiengineer-postgres",
            "operationId": operation_id,
        }
    )


@pytest.mark.parametrize("upgrade", [None, "1.5.0"], ids=["fresh", "upgrade-from-150"])
async def test_release_160_installs_handles_assessment_basis_and_attempts(tmp_path, upgrade):
    successor = release_at(SUCCESSOR, tmp_path / "successor-lock", "biotech")
    async with disposable(tmp_path, "biotech") as (target, connection):
        before = []
        tenant = None
        if upgrade:
            previous = release_at(PREVIOUS, tmp_path / "previous-lock", "biotech")
            await install(target, previous)
            before = await connection.fetch(
                "SELECT * FROM mission_control.component_release ORDER BY migration_key"
            )
            assert (
                await connection.fetchval(
                    "SELECT to_regclass('mission_control.knowledge_operation_handle')"
                )
                is None
            )
            # A 1.5.0 receipt and finalization survive the upgrade with their meaning.
            tenant = await create_tenant(connection, target)
            scope = (target["installation_id"], target["application_id"], tenant)
            plan_id = uuid4()
            async with as_role(connection, target, tenant):
                await connection.execute(
                    PLAN,
                    *scope,
                    plan_id,
                    RUN_ID,
                    "stage:draft->stage:review",
                    json.dumps({"items": [{"item_key": "body"}]}),
                    DIGEST_A,
                    1,
                )
                await connection.execute(PLAN_UPDATE, plan_id, "delivering", None)
                await connection.execute(
                    RECEIPT.replace(",attempt,", ",")
                    .replace("true,$10,", "true,")
                    .replace(" RETURNING attempt, outcome_code", ""),
                    *scope,
                    plan_id,
                    "body",
                    DIGEST_A,
                    DIGEST_A,
                    True,
                    True,
                )

        result = await install(target, successor)
        assert result["component_version"] == "1.6.0"
        if upgrade:
            assert result["applied_migrations"] == [MIGRATION]
        else:
            assert result["applied_migrations"][-1] == MIGRATION
        for row in before:
            assert (
                await connection.fetchrow(
                    "SELECT * FROM mission_control.component_release WHERE migration_key=$1",
                    row["migration_key"],
                )
                == row
            )
        if tenant is not None:
            assert tuple(
                await connection.fetchrow(
                    "SELECT attempt, outcome_code FROM mission_control.context_delivery_receipt "
                    "WHERE tenant_id=$1",
                    tenant,
                )
            ) == (1, "delivered")
        table = "mission_control.knowledge_operation_handle"
        assert await connection.fetchval(
            "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE oid=$1::regclass",
            table,
        )
        assert await connection.fetchval(
            "SELECT obj_description($1::regclass, 'pg_class') IS NOT NULL", table
        )
        assert not await connection.fetchval(
            "SELECT has_table_privilege('mission_control_runtime', $1, 'DELETE')", table
        )
        assert await connection.fetchval(
            "SELECT has_table_privilege('mission_control_readonly', $1, 'SELECT')", table
        )
        assert not await connection.fetchval(
            "SELECT count(*) FROM information_schema.columns WHERE table_schema='mission_control' "
            "AND table_name='knowledge_operation_handle' "
            "AND (column_name LIKE '%credential%' OR column_name LIKE '%token%')"
        )
        assert (await verify_release(target, successor, **VERSIONS))["status"] == "verified"
        assert (await install(target, successor))["applied_migrations"] == []
        await assert_runtime_security(connection, target)


async def test_release_160_handle_status_is_monotonic_and_cancel_is_idempotent(tmp_path):
    successor = release_at(SUCCESSOR, tmp_path / "successor-lock", "biotech")
    async with disposable(tmp_path, "biotech") as (target, connection):
        await install(target, successor)
        tenant = await create_tenant(connection, target)
        other = await create_tenant(connection, target)
        scope = (target["installation_id"], target["application_id"], tenant)
        reachable = "SELECT mission_control.knowledge_operation_state_reachable($1, $2)"
        assert await connection.fetchval(reachable, "waiting_review", "cancelled")
        assert await connection.fetchval(reachable, "queued", "succeeded")
        assert not await connection.fetchval(reachable, "succeeded", "running")
        assert not await connection.fetchval(reachable, "cancelled", "running")
        async with as_role(connection, target, tenant):
            assess = await connection.fetchval(
                HANDLE_INSERT,
                *scope,
                uuid4(),
                "report.assess",
                "assess:sub-1",
                "op-1",
                wire_handle("op-1"),
                None,
                MISSION_ID,
                RUN_ID,
                "queued",
                0,
            )
            # The same request id under the binding is one handle.
            await raises_sqlstate(
                connection,
                "23505",
                HANDLE_INSERT,
                *scope,
                uuid4(),
                "report.assess",
                "assess:sub-1",
                "op-2",
                wire_handle("op-2"),
                None,
                MISSION_ID,
                RUN_ID,
                "queued",
                0,
            )
            # A handle is recorded queued; an effect handle names its effect key.
            await raises_sqlstate(
                connection,
                "23000",
                HANDLE_INSERT,
                *scope,
                uuid4(),
                "report.assess",
                "assess:sub-9",
                "op-9",
                wire_handle("op-9"),
                None,
                MISSION_ID,
                RUN_ID,
                "running",
                3,
            )
            await raises_sqlstate(
                connection,
                "23514",
                HANDLE_INSERT,
                *scope,
                uuid4(),
                "knowledge.apply",
                "apply:1",
                "op-3",
                wire_handle("op-3"),
                None,
                MISSION_ID,
                RUN_ID,
                "queued",
                0,
            )
            await connection.execute(HANDLE_UPDATE, assess, "running", 2, None, None, None)
            # A stale poll (same revision, other state) is refused; waiting_review names its review.
            await raises_sqlstate(
                connection, "23000", HANDLE_UPDATE, assess, "held", 2, None, None, None
            )
            await raises_sqlstate(
                connection, "23514", HANDLE_UPDATE, assess, "waiting_review", 3, None, None, None
            )
            await connection.execute(
                HANDLE_UPDATE, assess, "waiting_review", 3, "review-1", None, None
            )
            # Stop during review: the first cancel request id is stored and kept.
            cancel = (
                "UPDATE mission_control.knowledge_operation_handle SET cancel_request_id=$2, "
                "version=version+1, updated_at=now() WHERE handle_id=$1"
            )
            await connection.execute(cancel, assess, "cancel-1")
            await raises_sqlstate(connection, "23000", cancel, assess, "cancel-2")
            # waiting_review -> cancelled through the unobserved cancelling is a forward jump.
            await connection.execute(HANDLE_UPDATE, assess, "cancelled", 5, "review-1", None, None)
            await raises_sqlstate(
                connection, "23000", HANDLE_UPDATE, assess, "running", 6, None, None, None
            )
            await raises_sqlstate(
                connection,
                "42501",
                "UPDATE mission_control.knowledge_operation_handle SET request_id='x'",
            )
            await raises_sqlstate(
                connection, "42501", "DELETE FROM mission_control.knowledge_operation_handle"
            )
        async with as_role(connection, target, other):
            assert (
                await connection.fetchval(
                    "SELECT count(*) FROM mission_control.knowledge_operation_handle"
                )
                == 0
            )


async def test_release_160_assessment_handoff_and_finalization_basis(tmp_path):
    successor = release_at(SUCCESSOR, tmp_path / "successor-lock", "biotech")
    async with disposable(tmp_path, "biotech") as (target, connection):
        await install(target, successor)
        tenant = await create_tenant(connection, target)
        scope = (target["installation_id"], target["application_id"], tenant)
        async with as_role(connection, target, tenant):
            first = await connection.fetchval(SUBMISSION, *scope, RUN_ID, "invocation:1", DIGEST_A)
            start = (
                "UPDATE mission_control.output_submission SET assessment_state='assessing', "
                "assessment_operation_id=$2, assessment_binding='aiengineer-postgres', "
                "assessment_requested_at=now(), version=version+1, updated_at=now() "
                "WHERE submission_id=$1"
            )
            # assessing names its handle; a handle appears only when the assessment starts.
            await raises_sqlstate(
                connection,
                "23514",
                "UPDATE mission_control.output_submission SET assessment_state='assessing', "
                "version=version+1, updated_at=now() WHERE submission_id=$1",
                first,
            )
            await connection.execute(start, first, "op-assess-1")
            await raises_sqlstate(
                connection,
                "23000",
                "UPDATE mission_control.output_submission SET assessment_operation_id='op-x', "
                "version=version+1, updated_at=now() WHERE submission_id=$1",
                first,
            )
            decide = (
                "UPDATE mission_control.output_submission SET assessment_state=$2, "
                "assessment_ref=$3, assessed_at=now(), version=version+1, updated_at=now() "
                "WHERE submission_id=$1"
            )
            await connection.execute(decide, first, "held", "assessment:op-assess-1")
            await connection.execute(decide, first, "assessed", "assessment:review-1")
            row = await connection.fetchrow(
                "SELECT assessment_state, assessment_operation_id FROM "
                "mission_control.output_submission WHERE submission_id=$1",
                first,
            )
            assert tuple(row) == ("assessed", "op-assess-1")
            finalization = (
                "INSERT INTO mission_control.invocation_finalization (installation_id,"
                "application_id,tenant_id,finalization_id,run_id,operation_ref,operation_attempt,"
                "execution_generation,invocation_ref,outcome,outcome_basis,submission_ids,report,"
                "report_digest,finalized_at,created_at,created_by_actor_ref) VALUES ($1::uuid,$2,"
                "$3,gen_random_uuid(),$4,'stage:draft',1,1,$5,'fulfilled',$6,ARRAY[$7::uuid],"
                "'{}',$8,now(),now(),'fixture:sprint-v') RETURNING outcome_basis"
            )
            assert (
                await connection.fetchval(
                    finalization, *scope, RUN_ID, "invocation:1", "assessed", first, DIGEST_A
                )
                == "assessed"
            )
            await raises_sqlstate(
                connection,
                "23514",
                finalization,
                *scope,
                RUN_ID,
                "invocation:9",
                "graded",
                first,
                DIGEST_A,
            )


async def test_release_160_delivery_repair_then_block_and_readiness_guard(tmp_path):
    successor = release_at(SUCCESSOR, tmp_path / "successor-lock", "biotech")
    async with disposable(tmp_path, "biotech") as (target, connection):
        await install(target, successor)
        tenant = await create_tenant(connection, target)
        scope = (target["installation_id"], target["application_id"], tenant)
        items = json.dumps(
            {
                "items": [
                    {"item_key": "body", "required": True},
                    {"item_key": "manifest", "required": True},
                    {"item_key": "notes", "required": False},
                ]
            }
        )
        async with as_role(connection, target, tenant):
            repaired = uuid4()
            await connection.execute(
                PLAN, *scope, repaired, RUN_ID, "draft->review", items, DIGEST_A, 2
            )
            # No receipt before delivery starts.
            await raises_sqlstate(
                connection,
                "23000",
                RECEIPT,
                *scope,
                repaired,
                "body",
                DIGEST_A,
                DIGEST_A,
                True,
                True,
                1,
            )
            await connection.execute(PLAN_UPDATE, repaired, "delivering", None)
            failed = await connection.fetchrow(
                RECEIPT, *scope, repaired, "body", DIGEST_A, DIGEST_B, True, True, 1
            )
            assert tuple(failed) == (1, "digest_mismatch")
            unreadable = await connection.fetchrow(
                RECEIPT, *scope, repaired, "manifest", DIGEST_A, DIGEST_A, True, False, 1
            )
            assert tuple(unreadable) == (1, "unreadable")
            # Not ready: required items lack a delivered receipt.
            await raises_sqlstate(connection, "23000", PLAN_UPDATE, repaired, "delivered", None)
            # Blocking needs a failed repair first.
            await raises_sqlstate(
                connection, "23000", PLAN_UPDATE, repaired, "blocked", "delivery_failed"
            )
            # One repair per item, only after its failed first attempt.
            await raises_sqlstate(
                connection,
                "23000",
                RECEIPT,
                *scope,
                repaired,
                "notes",
                DIGEST_A,
                DIGEST_A,
                True,
                True,
                2,
            )
            assert tuple(
                await connection.fetchrow(
                    RECEIPT, *scope, repaired, "body", DIGEST_A, DIGEST_A, True, True, 2
                )
            ) == (2, "delivered")
            assert tuple(
                await connection.fetchrow(
                    RECEIPT, *scope, repaired, "manifest", DIGEST_A, DIGEST_A, True, True, 2
                )
            ) == (2, "delivered")
            await raises_sqlstate(
                connection,
                "23505",
                RECEIPT,
                *scope,
                repaired,
                "body",
                DIGEST_A,
                DIGEST_A,
                True,
                True,
                2,
            )
            await raises_sqlstate(
                connection,
                "23514",
                RECEIPT,
                *scope,
                repaired,
                "body",
                DIGEST_A,
                DIGEST_A,
                True,
                True,
                3,
            )
            await connection.execute(PLAN_UPDATE, repaired, "delivered", None)

            blocked = uuid4()
            await connection.execute(
                PLAN, *scope, blocked, RUN_ID, "draft->review:2", items, DIGEST_B, 2
            )
            await connection.execute(PLAN_UPDATE, blocked, "delivering", None)
            await connection.fetchrow(
                RECEIPT, *scope, blocked, "body", DIGEST_A, None, False, False, 1
            )
            missing = await connection.fetchrow(
                RECEIPT, *scope, blocked, "body", DIGEST_A, None, False, False, 2
            )
            assert tuple(missing) == (2, "missing")
            await connection.execute(PLAN_UPDATE, blocked, "blocked", "delivery_failed:body")
            await raises_sqlstate(
                connection,
                "42501",
                "UPDATE mission_control.context_delivery_receipt SET attempt=1",
            )
