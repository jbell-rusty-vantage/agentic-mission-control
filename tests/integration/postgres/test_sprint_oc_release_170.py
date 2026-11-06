"""Actual 1.7.0 installer proof (Sprint OC WI-01 / OVE-163, WI-02 / OVE-164, WI-04 / OVE-166).

WI-01: output-contract tables. WI-02 (0057): the M04 plan/receipt/outbox tables are dropped and
the sealed ``transfer_plan``, ``transfer_delivery_receipt`` and ``transfer_member_delivery`` exist
with their guards (immutable rows, ready only with headroom, files probed through the backend).
WI-04 (0058): ``invocation_settlement`` exists under forced row security without DELETE (its
guard is proven through the store in ``test_wi04_saved_settlement_postgres.py``).

Fresh install and upgrade from 1.6.0 with preserved receipts and finalizations, verify and an
idempotent re-apply, forced row security, comments and runtime grants without DELETE on every
new table, the finalization basis vocabulary, and the head guards (a promise head advances only
to the next revision). Behaviour through the handlers is proven in
``test_output_contracts_postgres.py``. Prior releases and their proof remain immutable.
"""

from __future__ import annotations

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
SUCCESSOR = PACKAGE / "releases/1.7.0/component"
PREVIOUS = PACKAGE / "releases/1.6.0/component"
MIGRATION = "0056_output_contracts_and_fulfillment"
TRANSFER_MIGRATION = "0057_sealed_transfer_attempts"
SETTLEMENT_MIGRATION = "0058_saved_execution_settlement"
USE_DECISION_MIGRATION = "0059_recorded_use_decisions"
HOOK_INSTALL_MIGRATION = "0060_hook_candidate_installs"
RETIRED = (
    "context_transfer_plan",
    "context_delivery_receipt",
    "context_delivery_outbox",
)
TABLES = (
    "output_promise_set",
    "output_obligation_revision",
    "output_obligation_head",
    "output_obligation_pin",
    "output_revision",
    "output_accepted_head",
    "output_set",
    "output_set_member",
    "output_assessment",
    "obligation_fulfillment",
    "obligation_association_step",
    "transfer_plan",
    "transfer_delivery_receipt",
    "transfer_member_delivery",
    "invocation_settlement",
    "invocation_settlement_event",
)
DIGEST = "sha256:" + "a" * 64
OBLIGATION = (
    '{"key": "draft.report", "revision": %d, "owner_position": "draft", '
    '"enforcement": "required", "contract": {"form": "text"}}'
)
REVISION_INSERT = (
    "INSERT INTO mission_control.output_obligation_revision (installation_id, application_id, "
    "tenant_id, obligation_revision_id, run_id, obligation_key, revision, ordinal, "
    "owner_position, form, enforcement, evaluation_scope, obligation, obligation_digest, "
    "promise_set_digest, proposal, activation_boundary, created_at, created_by_actor_ref) "
    "VALUES "
    "($1::uuid, $2, $3, gen_random_uuid(), $4, 'draft.report', $5, 0, 'draft', 'text', "
    "'required', 'invocation', $6::jsonb, $7, $7, $8::jsonb, $9, now(), 'fixture:oc')"
)
PROMISE_SET_INSERT = (
    "INSERT INTO mission_control.output_promise_set (installation_id, application_id, "
    "tenant_id, run_id, promise_set, promise_set_digest, created_at, created_by_actor_ref) "
    'VALUES ($1::uuid, $2, $3, $4, \'{"completion": {"op": "all"}}\', $5, now(), '
    "'fixture:oc')"
)
PROPOSAL = '{"reason": "tighten", "delegation_ref": "d", "expected_prior_revision": 1}'
HEAD_INSERT = (
    "INSERT INTO mission_control.output_obligation_head (installation_id, application_id, "
    "tenant_id, run_id, obligation_key, ordinal, active_revision, version, updated_at, "
    "updated_by_actor_ref) VALUES ($1::uuid, $2, $3, $4, 'draft.report', 0, $5, 1, now(), "
    "'fixture:oc')"
)


@pytest.mark.parametrize("upgrade", [None, "1.6.0"], ids=["fresh", "upgrade-from-160"])
async def test_release_170_installs_output_contract_records(tmp_path, upgrade):
    successor = release_at(SUCCESSOR, tmp_path / "successor-lock", "biotech")
    async with disposable(tmp_path, "biotech") as (target, connection):
        before = []
        if upgrade:
            await install(target, release_at(PREVIOUS, tmp_path / "previous-lock", "biotech"))
            before = await connection.fetch(
                "SELECT * FROM mission_control.component_release ORDER BY migration_key"
            )
            assert (
                await connection.fetchval("SELECT to_regclass('mission_control.output_revision')")
                is None
            )
        result = await install(target, successor)
        assert result["component_version"] == "1.7.0"
        if upgrade:
            assert result["applied_migrations"] == [
                MIGRATION,
                TRANSFER_MIGRATION,
                SETTLEMENT_MIGRATION,
                USE_DECISION_MIGRATION,
                HOOK_INSTALL_MIGRATION,
            ]
        else:
            assert result["applied_migrations"][-5:] == [
                MIGRATION,
                TRANSFER_MIGRATION,
                SETTLEMENT_MIGRATION,
                USE_DECISION_MIGRATION,
                HOOK_INSTALL_MIGRATION,
            ]
        for name in RETIRED:
            assert (
                await connection.fetchval("SELECT to_regclass($1)", f"mission_control.{name}")
                is None
            ), name
        for row in before:
            assert (
                await connection.fetchrow(
                    "SELECT * FROM mission_control.component_release WHERE migration_key=$1",
                    row["migration_key"],
                )
                == row
            )
        for name in TABLES:
            table = f"mission_control.{name}"
            assert await connection.fetchval(
                "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class "
                "WHERE oid=$1::regclass",
                table,
            ), table
            assert await connection.fetchval(
                "SELECT obj_description($1::regclass, 'pg_class') IS NOT NULL", table
            ), table
            assert not await connection.fetchval(
                "SELECT has_table_privilege('mission_control_runtime', $1, 'DELETE')", table
            ), table
            assert await connection.fetchval(
                "SELECT has_table_privilege('mission_control_readonly', $1, 'SELECT')", table
            ), table
        assert (
            await connection.fetchval(
                "SELECT pg_get_expr(adbin, adrelid) FROM pg_attrdef WHERE adrelid = "
                "'mission_control.invocation_finalization'::regclass AND adnum = (SELECT attnum "
                "FROM pg_attribute WHERE attrelid = adrelid AND attname = 'outcome_basis')"
            )
            == "'declared_obligations'::text"
        )
        assert (await verify_release(target, successor, **VERSIONS))["status"] == "verified"
        assert (await install(target, successor))["applied_migrations"] == []
        await assert_runtime_security(connection, target)


async def test_release_170_promise_heads_advance_only_to_the_next_revision(tmp_path):
    successor = release_at(SUCCESSOR, tmp_path / "successor-lock", "biotech")
    async with disposable(tmp_path, "biotech") as (target, connection):
        await install(target, successor)
        tenant = await create_tenant(connection, target)
        scope = (target["installation_id"], target["application_id"], tenant)
        run_id = uuid4()
        async with as_role(connection, target, tenant):
            await connection.execute(PROMISE_SET_INSERT, *scope, run_id, DIGEST)
            # Revision 1 carries no proposal; a successor must name its proposal and boundary.
            await raises_sqlstate(
                connection,
                "23514",
                REVISION_INSERT,
                *scope,
                run_id,
                1,
                OBLIGATION % 1,
                DIGEST,
                PROPOSAL,
                "between_iterations",
            )
            await connection.execute(
                REVISION_INSERT, *scope, run_id, 1, OBLIGATION % 1, DIGEST, None, None
            )
            await connection.execute(HEAD_INSERT, *scope, run_id, 1)
            await connection.execute(
                REVISION_INSERT,
                *scope,
                run_id,
                2,
                OBLIGATION % 2,
                DIGEST,
                PROPOSAL,
                "between_iterations",
            )
            # A successor without its delegation and reason is refused.
            await raises_sqlstate(
                connection,
                "23514",
                REVISION_INSERT,
                *scope,
                run_id,
                3,
                OBLIGATION % 3,
                DIGEST,
                '{"reason": "x"}',
                "between_iterations",
            )
            # Skipping back or standing still is refused; activation at another boundary kind
            # is refused; the declared boundary activates the next revision.
            await raises_sqlstate(
                connection,
                "23000",
                "UPDATE mission_control.output_obligation_head SET version = version + 1, "
                "updated_at = now() WHERE run_id = $1",
                run_id,
            )
            for reached in ("between_stages:s", "betweenXiterations:iteration:2"):
                # Another kind, or a lookalike (``_`` is no wildcard: a literal prefix check).
                await raises_sqlstate(
                    connection,
                    "23000",
                    "UPDATE mission_control.output_obligation_head SET active_revision = 2, "
                    "version = 2, activated_boundary_ref = $2, updated_at = now() "
                    "WHERE run_id = $1",
                    run_id,
                    reached,
                )
            await connection.execute(
                "UPDATE mission_control.output_obligation_head SET active_revision = 2, "
                "version = 2, activated_boundary_ref = 'between_iterations:iteration:2', "
                "updated_at = now() WHERE run_id = $1",
                run_id,
            )
            await raises_sqlstate(
                connection,
                "42501",
                "DELETE FROM mission_control.output_obligation_head WHERE run_id = $1",
                run_id,
            )


PLAN_INSERT = (
    "INSERT INTO mission_control.transfer_plan (installation_id, application_id, tenant_id, "
    "transfer_plan_id, receiver_key, run_id, receiver_operation_ref, receiver_position, boundary, "
    "isolation, configuration_ref, selection_authority_ref, host_state_ref, profile_pin, plan, "
    "plan_digest, member_count, total_tokens, context_window_tokens, file_bytes, sealed_at, "
    "created_at, created_by_actor_ref) VALUES ($1::uuid, $2, $3, $4, $5, $6, 'op-review', "
    "'review', 'dependent_stage', 'shared', 'erc:x', $5, NULL, 'report-review@v1', $7::jsonb, "
    "$5, 0, $8, 1000, 0, now(), now(), 'fixture:oc')"
)
RECEIPT_INSERT = (
    "INSERT INTO mission_control.transfer_delivery_receipt (installation_id, application_id, "
    "tenant_id, delivery_receipt_id, transfer_plan_id, plan_digest, sequence, operation_attempt, "
    "execution_generation, receiver_invocation_ref, realized_backend, result, total_tokens, "
    "headroom_tokens, receipt, correlation_id, received_at, created_at, created_by_actor_ref) "
    "VALUES ($1::uuid, $2, $3, $4, $5, $6, 1, 1, 1, 'inv-1', 'fake:a', $7, 10, $8, $9::jsonb, "
    "'c', now(), now(), 'fixture:oc')"
)


async def test_release_170_transfer_plans_are_sealed_and_receipts_need_feasibility(tmp_path):
    import json

    successor = release_at(SUCCESSOR, tmp_path / "successor-lock", "biotech")
    async with disposable(tmp_path, "biotech") as (target, connection):
        await install(target, successor)
        tenant = await create_tenant(connection, target)
        scope = (target["installation_id"], target["application_id"], tenant)
        plan_id, run_id = uuid4(), uuid4()

        def plan(total: int, identity=None) -> str:
            return json.dumps(
                {
                    "schema_version": "mc.sealed_transfer_plan.v1",
                    "plan_id": str(identity or plan_id),
                    "digest": DIGEST,
                    "receiver_key": DIGEST,
                    "boundary": "dependent_stage",
                    "selection_authority_ref": DIGEST,
                    "exact_sources": [],
                    "placements": [],
                    "resource_plan": {
                        "total_tokens": total,
                        "file_bytes": 0,
                        "bounds": {"window_tokens": 1000},
                    },
                }
            )

        def receipt(receipt_id, result: str) -> str:
            return json.dumps(
                {
                    "schema_version": "mc.transfer_delivery_receipt.v1",
                    "receipt_id": str(receipt_id),
                    "plan_id": str(plan_id),
                    "plan_digest": DIGEST,
                    "result": result,
                    "realized_backend": "fake:a",
                    "sequence": 1,
                }
            )

        async with as_role(connection, target, tenant):
            # A plan whose aggregate does not fit its receiver's window is never sealed.
            await raises_sqlstate(
                connection, "23514", PLAN_INSERT, *scope, plan_id, DIGEST, run_id, plan(2000), 2000
            )
            await connection.execute(PLAN_INSERT, *scope, plan_id, DIGEST, run_id, plan(10), 10)
            # One plan per receiver key.
            other = uuid4()
            await raises_sqlstate(
                connection, "23505", PLAN_INSERT, *scope, other, DIGEST, run_id, plan(10, other), 10
            )
            # Ready needs measured headroom.
            refused_id = uuid4()
            await raises_sqlstate(
                connection,
                "23514",
                RECEIPT_INSERT,
                *scope,
                refused_id,
                plan_id,
                DIGEST,
                "ready",
                -1,
                receipt(refused_id, "ready"),
            )
            receipt_id = uuid4()
            await connection.execute(
                RECEIPT_INSERT,
                *scope,
                receipt_id,
                plan_id,
                DIGEST,
                "ready",
                5,
                receipt(receipt_id, "ready"),
            )
            # The positive path: a member written in its receipt's transaction is accepted.
            await connection.execute(
                "INSERT INTO mission_control.transfer_member_delivery (installation_id, "
                "application_id, tenant_id, delivery_receipt_id, member_key, source_ref, "
                "placement, path_or_handle, required_digest, observed_digest, probe, readable, "
                "access_ok, created_at) VALUES ($1::uuid, $2, $3, $4, 'r/value', 'rev', "
                "'inline', 'prompt', $5, $5, 'prompt', true, true, now())",
                *scope,
                receipt_id,
                DIGEST,
            )
            # A file is readable only through the receiving backend's read.
            await raises_sqlstate(
                connection,
                "23514",
                "INSERT INTO mission_control.transfer_member_delivery (installation_id, "
                "application_id, tenant_id, delivery_receipt_id, member_key, source_ref, "
                "placement, path_or_handle, required_digest, observed_digest, probe, readable, "
                "access_ok, created_at) VALUES ($1::uuid, $2, $3, $4, 'r/body', 'rev', 'file', "
                "'/inputs/r/1/body.md', $5, $5, 'prompt', true, true, now())",
                *scope,
                receipt_id,
                DIGEST,
            )
            # The runtime role can neither rewrite nor delete a sealed plan or a receipt.
            for table in ("transfer_plan", "transfer_delivery_receipt"):
                assert not await connection.fetchval(
                    "SELECT has_table_privilege('mission_control_runtime', $1, 'UPDATE')",
                    f"mission_control.{table}",
                ), table
        # A member is never appended to an earlier receipt (another transaction).
        async with as_role(connection, target, tenant):
            await raises_sqlstate(
                connection,
                "23000",
                "INSERT INTO mission_control.transfer_member_delivery (installation_id, "
                "application_id, tenant_id, delivery_receipt_id, member_key, source_ref, "
                "placement, path_or_handle, required_digest, observed_digest, probe, readable, "
                "access_ok, created_at) VALUES ($1::uuid, $2, $3, $4, 'r/manifest', 'rev', "
                "'inline', 'prompt', $5, $5, 'prompt', true, true, now())",
                *scope,
                receipt_id,
                DIGEST,
            )
        # Even the owner cannot mutate them (reject_mutation).
        await raises_sqlstate(
            connection,
            "23001",
            "UPDATE mission_control.transfer_plan SET total_tokens = 1",
        )
