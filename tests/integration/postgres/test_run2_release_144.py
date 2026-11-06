"""Actual 1.4.4 installer proof (transcript joinability, transcript projection tables, the
frame-body scheme); prior releases and their proof remain immutable."""

from __future__ import annotations

import pytest

from mission_control_db_contract.deployment import verify_release
from tests.integration.postgres.test_run2_release_141 import (
    PACKAGE,
    VERSIONS,
    assert_runtime_security,
    disposable,
    install,
    release_at,
    retained_release_130,
)
from tests.integration.postgres.test_run2_release_142 import preserve_document

pytestmark = [pytest.mark.asyncio, pytest.mark.common_db]
SUCCESSOR = PACKAGE / "releases/1.4.4/component"
PREVIOUS = PACKAGE / "releases/1.4.3/component"
MIGRATIONS = ["0047_transcript_joinability", "0048_transcript_entry", "0049_frame_body_refs"]
NEW_KINDS = (
    "model_request",
    "environment_materialized",
    "subagent_started",
    "subagent_ended",
    "progress_note",
)


async def column_exists(connection, table: str, column: str) -> bool:
    return await connection.fetchval(
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema="
        "'mission_control' AND table_name=$1 AND column_name=$2)",
        table,
        column,
    )


async def constraint_definition(connection, name: str) -> str:
    return await connection.fetchval(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = $1 "
        "AND conrelid = 'mission_control.provider_frame'::regclass",
        name,
    )


@pytest.mark.parametrize(
    "upgrade", [None, "1.4.3", "1.3.0"], ids=["fresh", "upgrade-from-143", "upgrade-from-130"]
)
async def test_release_144_installs_joinability_projection_and_body_scheme(tmp_path, upgrade):
    app = "ai-engineer" if upgrade == "1.3.0" else "biotech"
    successor = release_at(SUCCESSOR, tmp_path / "successor-lock", app)
    async with disposable(tmp_path, app) as (target, connection):
        before_receipts = []
        document = None
        if upgrade:
            component = (
                retained_release_130(tmp_path / "retained-130") if upgrade == "1.3.0" else PREVIOUS
            )
            previous = release_at(component, tmp_path / "previous-lock", app)
            await install(target, previous)
            before_receipts = await connection.fetch(
                "SELECT * FROM mission_control.component_release ORDER BY migration_key"
            )
            _tenant, document = await preserve_document(connection, target)
            assert not await column_exists(connection, "mission_event", "unit_key")
            assert not await column_exists(connection, "provider_frame", "retention_class")
            assert await connection.fetchval(
                "SELECT to_regclass('mission_control.transcript_entry') IS NULL"
            )

        result = await install(target, successor)
        assert result["component_version"] == "1.4.4"
        if upgrade == "1.4.3":
            assert result["applied_migrations"] == MIGRATIONS
        else:
            assert result["applied_migrations"][-3:] == MIGRATIONS
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

        # 0047: joinability columns, point columns, frame kinds, retention class and policy.
        for table, column in (
            ("mission_event", "unit_key"),
            ("mission_event", "point_ref"),
            ("cognition_point", "subordinate_ref"),
            ("cognition_point", "restore_level"),
            ("cognition_point", "pruned_at"),
            ("cognition_point", "prune_policy"),
            ("provider_frame", "retention_class"),
            ("frame_retention_policy", "step_retain_days"),
            ("frame_retention_policy", "prune_mode"),
        ):
            assert await column_exists(connection, table, column), (table, column)
        kind_rule = await constraint_definition(connection, "provider_frame_kind_check")
        assert all(f"'{kind}'" in kind_rule for kind in NEW_KINDS)
        closing_rule = await constraint_definition(connection, "provider_frame_closing_rule")
        assert "'subagent_ended'" in closing_rule
        assert (
            await connection.fetchval(
                "SELECT count(*) FROM pg_constraint WHERE contype = 'c' "
                "AND conrelid = 'mission_control.provider_frame'::regclass "
                "AND pg_get_constraintdef(oid) LIKE '%closing = (kind%'"
            )
            == 1
        )
        assert await connection.fetchval(
            "SELECT attgenerated = 's' FROM pg_attribute WHERE attrelid = "
            "'mission_control.provider_frame'::regclass AND attname = 'retention_class'"
        )
        for column in ("subordinate_ref", "restore_level", "pruned_at", "prune_policy"):
            assert await connection.fetchval(
                "SELECT has_column_privilege('mission_control_runtime', "
                "'mission_control.cognition_point', $1, 'UPDATE')",
                column,
            )
        for column in ("temporal_workflow_id", "temporal_run_id"):
            assert await connection.fetchval(
                "SELECT has_column_privilege('mission_control_runtime', "
                "'mission_control.mission_run', $1, 'UPDATE')",
                column,
            )
        for table in ("completion_candidate", "completion_decision"):
            for role in ("mission_control_runtime", "mission_control_family_writer"):
                assert await connection.fetchval(
                    "SELECT has_table_privilege($1, $2, 'INSERT')",
                    role,
                    f"mission_control.{table}",
                )
            assert not await connection.fetchval(
                "SELECT has_table_privilege('mission_control_runtime', $1, 'DELETE')",
                f"mission_control.{table}",
            )
        assert await connection.fetchval(
            "SELECT has_function_privilege('mission_control_runtime', "
            "'mission_control.expire_step_provider_frames(timestamptz)', 'EXECUTE')"
        )
        assert await connection.fetchval(
            "SELECT has_table_privilege('mission_control_family_writer', "
            "'mission_control.activation', 'SELECT')"
        )
        # 0048: the projection tables with forced RLS and replace-by-run grants.
        for table in ("transcript_entry", "transcript_projection_state"):
            assert await connection.fetchval(
                "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class "
                "WHERE oid = $1::regclass",
                f"mission_control.{table}",
            )
            assert await connection.fetchval(
                "SELECT has_table_privilege('mission_control_runtime', $1, 'INSERT')",
                f"mission_control.{table}",
            )
            assert await connection.fetchval(
                "SELECT has_table_privilege('mission_control_runtime', $1, 'DELETE')",
                f"mission_control.{table}",
            )
            assert await connection.fetchval(
                "SELECT has_table_privilege('mission_control_readonly', $1, 'SELECT')",
                f"mission_control.{table}",
            )
            assert not await connection.fetchval(
                "SELECT has_table_privilege('mission_control_readonly', $1, 'INSERT')",
                f"mission_control.{table}",
            )
        assert not await connection.fetchval(
            "SELECT has_table_privilege('mission_control_runtime', "
            "'mission_control.transcript_entry', 'UPDATE')"
        )
        # 0049: the scheme is documented on the column.
        comment = await connection.fetchval(
            "SELECT col_description('mission_control.provider_frame'::regclass, attnum) "
            "FROM pg_attribute WHERE attrelid = 'mission_control.provider_frame'::regclass "
            "AND attname = 'body_artifact_ref'"
        )
        assert "frame-body://sha256:<hex>?bytes=<n>&type=<media>" in comment

        assert (await verify_release(target, successor, **VERSIONS))["status"] == "verified"
        assert (await install(target, successor))["applied_migrations"] == []
        await assert_runtime_security(connection, target)


async def test_release_144_retention_class_and_delta_expiry(tmp_path):
    """The class derives from the kind; the narrowed expiry deletes deltas only; the step
    expiry restricts itself to terminal runs."""

    successor = release_at(SUCCESSOR, tmp_path / "successor-lock", "biotech")
    async with disposable(tmp_path, "biotech") as (target, connection):
        await install(target, successor)
        expression = await connection.fetchval(
            "SELECT pg_get_expr(adbin, adrelid) FROM pg_attrdef WHERE adrelid = "
            "'mission_control.provider_frame'::regclass AND adnum = (SELECT attnum FROM "
            "pg_attribute WHERE attrelid = 'mission_control.provider_frame'::regclass "
            "AND attname = 'retention_class')"
        )
        for kind in ("message_delta", "thinking_delta", "tool_call_delta", "heartbeat", "status"):
            assert f"'{kind}'" in expression
        assert "'delta'" in expression and "'step'" in expression
        definition = await connection.fetchval(
            "SELECT pg_get_functiondef("
            "'mission_control.expire_provider_frames(timestamptz, boolean)'::regprocedure)"
        )
        assert "retention_class = 'delta'" in definition
        step_definition = await connection.fetchval(
            "SELECT pg_get_functiondef("
            "'mission_control.expire_step_provider_frames(timestamptz)'::regprocedure)"
        )
        assert "lifecycle = 'completed'" in step_definition
        assert "retention_class = 'step'" in step_definition
