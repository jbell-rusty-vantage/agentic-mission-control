"""Schema guards of the newest built release on a real disposable cluster A.

Pure catalog checks with no Mission Control code: which tables are tenant scoped with forced
row-level security and one scope policy, which records are append-only, which capability role
holds which table and column privilege (least privilege, nothing for PUBLIC, no DELETE or
TRUNCATE for any login capability), and that the lane profile registry is immutable reference
data. Each test installs the newest built `releases/<x.y.z>/component` (what the next deployment
lock selects) into a fresh database.

Moved from the Mission Control integration suite (OVE-238): `test_mission_chain_tables`
(migration 0028), `test_pre_stage3_database_authority_integration` (0010-0017) and
`test_release_0033` (0033). Their row-level guard behaviour (forward-only chain links, MP-11 and
MP-15 guards) needs Mission Control seeds and stays there.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from conftest import PACKAGE, Database, build_and_lock, copy_component, run, write_target
from test_install import install

from mission_control_db_contract.integrity import Release
from mission_control_db_contract.target import load_target

RUNTIME = "mission_control_runtime"
FAMILY = "mission_control_family_writer"
READONLY = "mission_control_readonly"
CATALOG = "mission_control_catalog_writer"
OUTBOX = "mission_control_outbox_worker"
SCOPE_COLUMNS = ["installation_id", "application_id", "tenant_id"]
TABLE_PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")

S, SI, SIU = (
    frozenset({"SELECT"}),
    frozenset({"SELECT", "INSERT"}),
    frozenset({"SELECT", "INSERT", "UPDATE"}),
)
NONE: frozenset[str] = frozenset()


def _newest_built_component() -> Path:
    built = [
        path / "component"
        for path in (PACKAGE / "releases").iterdir()
        if path.is_dir()
        and (path / "component" / "manifest.json").is_file()
        and all(part.isdigit() for part in path.name.split("."))
    ]
    return max(built, key=lambda item: tuple(int(part) for part in item.parent.name.split(".")))


@pytest.fixture(scope="module")
def newest(tmp_path_factory: pytest.TempPathFactory) -> Release:
    """The newest built release, rebuilt from its committed inputs on cluster A."""

    work = tmp_path_factory.mktemp("newest-release")
    root = copy_component(work, source=_newest_built_component())
    return build_and_lock(work, root, "biotech")


@pytest.fixture
def db(make_db, newest, tmp_path, monkeypatch) -> Iterator[Database]:  # type: ignore[no-untyped-def]
    database = make_db("A")
    target = load_target(write_target(tmp_path, database, monkeypatch=monkeypatch))
    result, _plan = install(target, newest)
    assert result["component_version"] == newest.manifest["component_version"]
    yield database


async def _fetch(db: Database, query: str, *args: Any) -> list[asyncpg.Record]:
    connection = await db.connect()
    try:
        return await connection.fetch(query, *args)
    finally:
        await connection.close()


def fetch(db: Database, query: str, *args: Any) -> list[asyncpg.Record]:
    return run(_fetch(db, query, *args))


def table_privileges(db: Database, role: str, table: str) -> frozenset[str]:
    rows = fetch(
        db,
        "SELECT privilege FROM unnest($3::text[]) AS privilege "
        "WHERE has_table_privilege($1, 'mission_control.' || $2, privilege)",
        role,
        table,
        list(TABLE_PRIVILEGES),
    )
    return frozenset(row["privilege"] for row in rows)


def update_columns(db: Database, role: str, table: str) -> set[str]:
    rows = fetch(
        db,
        "SELECT a.attname FROM pg_attribute a "
        "WHERE a.attrelid = ('mission_control.' || $2)::regclass AND a.attnum > 0 "
        "AND NOT a.attisdropped AND has_column_privilege($1, a.attrelid, a.attnum, 'UPDATE')",
        role,
        table,
    )
    return {row["attname"] for row in rows}


def table_shape(db: Database, tables: list[str]) -> dict[str, asyncpg.Record]:
    """Per table: RLS flags, its PERMISSIVE policies (USING / WITH CHECK), a tenant FK, the
    leading columns, PUBLIC ACL entries and whether `reject_mutation` guards it."""

    rows = fetch(
        db,
        """
        SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
               (SELECT array_agg(coalesce(pg_get_expr(p.polqual, p.polrelid), '') || ' / '
                                 || coalesce(pg_get_expr(p.polwithcheck, p.polrelid), ''))
                FROM pg_policy p WHERE p.polrelid = c.oid AND p.polpermissive) AS policies,
               EXISTS (SELECT 1 FROM pg_constraint k WHERE k.conrelid = c.oid
                       AND k.contype = 'f'
                       AND k.confrelid = 'mission_control.tenant'::regclass) AS tenant_fk,
               (SELECT array_agg(a.attname ORDER BY a.attnum) FROM pg_attribute a
                WHERE a.attrelid = c.oid AND a.attnum IN (1, 2, 3)) AS scope_columns,
               (SELECT count(*) FROM aclexplode(c.relacl) x WHERE x.grantee = 0) AS public_acl,
               EXISTS (SELECT 1 FROM pg_trigger t JOIN pg_proc f ON f.oid = t.tgfoid
                       WHERE t.tgrelid = c.oid AND f.proname = 'reject_mutation') AS immutable
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'mission_control' AND c.relname = ANY($1::text[])
        """,
        tables,
    )
    shapes = {row["relname"]: row for row in rows}
    assert set(shapes) == set(tables)
    return shapes


def assert_tenant_scoped(name: str, row: asyncpg.Record) -> str:
    """Forced RLS, a tenant FK, the three scope columns first and exactly one permissive scope
    policy (restrictive policies may only narrow it further). Returns that policy."""

    assert (row["relrowsecurity"], row["relforcerowsecurity"]) == (True, True), name
    assert row["tenant_fk"], name
    assert row["scope_columns"] == SCOPE_COLUMNS, name
    (policy,) = row["policies"]
    for column in SCOPE_COLUMNS:
        assert column in policy, (name, policy)
    return str(policy)


# --------------------------------------------------------------- runtime authority (0010-0017)

# Support table -> (runtime, family writer, readonly) table-level privileges.
SUPPORT_TABLES: dict[str, tuple[frozenset[str], frozenset[str], frozenset[str]]] = {
    "run_lifecycle_transition": (SI, SI, S),
    # FT-D2 (ADR-0029, migration 0028): the chain reducer admits the consumer run inside the
    # family writer's append_events transaction, so the family writer may INSERT ledgers.
    "effect_ledger": (SIU, SIU, S),
    "effect_ledger_entry": (SI, SI, S),
    "family_admission_head": (S, SIU, S),
    "family_admission_journal": (S, SI, S),
    "family_admission_result": (S, SI, S),
    "operation_claim": (SI, NONE, S),
    "operation_journal_mutation": (SI, NONE, S),
    "operation_technical_attempt": (SI, NONE, S),
    "operation_settlement": (SI, NONE, S),
    "runtime_unit_generation": (SI, NONE, S),
    "cognitive_namespace": (SI, NONE, S),
    "activity_attempt_observation": (SI, NONE, S),
    "checkpoint_transition": (SI, NONE, S),
    "unit_result_observation": (SI, NONE, S),
    "lineage_write_rejection": (SI, NONE, S),
    "run_snapshot": (SI, NONE, S),
    "fork_request": (SIU, NONE, S),
    "fork_reuse_decision": (SI, NONE, S),
    "execution_lineage_record": (SI, NONE, S),
    "execution_lineage_edge": (SI, NONE, S),
    "run_composition_link": (SI, NONE, S),
    "run_dependency_revision": (SI, NONE, S),
    "linked_result_decision": (SI, NONE, S),
    "linked_child_terminal": (SI, NONE, S),
    # 0069: the family writer's chain release hook seals one `linked.export/1` document in its
    # admission transaction (a restrictive INSERT policy limits it to that contract).
    "runtime_document": (SI, SI, S),
    "subordinate_admission": (SIU, NONE, S),
    "subordinate_message": (SI, NONE, S),
    "async_provider_run": (SIU, NONE, S),
    "subordinate_contract": (SI, NONE, S),
    "subordinate_execution_detail": (SI, NONE, S),
    "subordinate_link_detail": (SI, NONE, S),
    "coordinator_launch_ticket": (SIU, NONE, NONE),
    "coordinator_audit_event": (SI, NONE, NONE),
    "coordinator_workflow_result": (SI, NONE, NONE),
    "runtime_execution_binding": (SIU, NONE, S),
    "runtime_execution_attempt": (SI, NONE, S),
    "runtime_intervention": (SIU, NONE, S),
}
APPEND_ONLY = {
    "run_lifecycle_transition",
    "effect_ledger_entry",
    "family_admission_journal",
    "family_admission_result",
    "operation_journal_mutation",
    "operation_technical_attempt",
    "operation_settlement",
    "activity_attempt_observation",
    "checkpoint_transition",
    "unit_result_observation",
    "lineage_write_rejection",
    "run_snapshot",
    "fork_reuse_decision",
    "execution_lineage_record",
    "execution_lineage_edge",
    "run_composition_link",
    "run_dependency_revision",
    "linked_result_decision",
    "linked_child_terminal",
    "runtime_document",
    "subordinate_message",
    "subordinate_contract",
    "coordinator_audit_event",
    "coordinator_workflow_result",
    "runtime_execution_attempt",
}
# Column-level UPDATE grants (table-level UPDATE absent) per (role, table).
COLUMN_UPDATES = {
    (RUNTIME, "operation_claim"): {
        "status",
        "heartbeat_at",
        "lease_expires_at",
        "version",
        "updated_at",
    },
    (RUNTIME, "runtime_unit_generation"): {"lease_holder", "superseded", "updated_at"},
    (RUNTIME, "cognitive_namespace"): {
        "head_checkpoint",
        "head_checkpoint_key",
        "head_transition_key",
        "head_state_schema_digest",
        "head_version",
        "in_flight_unit_key",
        "in_flight_generation",
        "updated_at",
    },
    (RUNTIME, "subordinate_execution_detail"): {"execution_generation", "payload", "updated_at"},
    (RUNTIME, "subordinate_link_detail"): {"payload", "updated_at"},
    (RUNTIME, "attempt"): {"fencing_token", "lease_expires_at", "version", "updated_at"},
    (FAMILY, "command"): {"lifecycle", "outcome", "version", "updated_at"},
    (OUTBOX, "outbox"): {
        "delivery_state",
        "lease_owner",
        "lease_expires_at",
        "attempts",
        "next_attempt_at",
        "delivered_at",
        "version",
    },
}


def test_runtime_authority_tables_are_scoped_forced_rls_and_append_only(db: Database) -> None:
    for name, row in table_shape(db, list(SUPPORT_TABLES)).items():
        assert_tenant_scoped(name, row)
        assert row["immutable"] == (name in APPEND_ONLY), name


def test_capability_role_matrix_is_least_privilege(db: Database) -> None:
    for table, (runtime, family, readonly) in SUPPORT_TABLES.items():
        assert table_privileges(db, RUNTIME, table) == runtime, table
        assert table_privileges(db, FAMILY, table) == family, table
        assert table_privileges(db, READONLY, table) == readonly, table
        assert table_privileges(db, CATALOG, table) == NONE, table
        assert table_privileges(db, OUTBOX, table) == NONE, table
        assert table_privileges(db, "public", table) == NONE, table
    # No login capability may delete or truncate any mission_control record, except the
    # runtime's transcript projection (0048), which replaces a run's rows by delete and insert.
    deleters = fetch(
        db,
        """
        SELECT r.rolname, c.relname FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        CROSS JOIN (VALUES ($1), ($2), ($3), ($4), ($5)) AS r(rolname)
        WHERE n.nspname = 'mission_control' AND c.relkind = 'r'
          AND (has_table_privilege(r.rolname, c.oid, 'DELETE')
               OR has_table_privilege(r.rolname, c.oid, 'TRUNCATE'))
        """,
        RUNTIME,
        FAMILY,
        READONLY,
        CATALOG,
        OUTBOX,
    )
    assert {(row["rolname"], row["relname"]) for row in deleters} == {
        (RUNTIME, "transcript_entry"),
        (RUNTIME, "transcript_projection_state"),
    }
    assert table_privileges(db, RUNTIME, "transcript_entry") == SI | {"DELETE"}
    for (role, table), columns in COLUMN_UPDATES.items():
        assert update_columns(db, role, table) == columns, (role, table)
    # The runtime capability never inherits the family writer or catalog authority, and the
    # immutable canonical records stay insert-only for it.
    (memberships,) = fetch(
        db,
        "SELECT pg_has_role($1, $2, 'MEMBER') AS family, pg_has_role($1, $3, 'MEMBER') AS catalog",
        RUNTIME,
        FAMILY,
        CATALOG,
    )
    assert dict(memberships) == {"family": False, "catalog": False}
    for table in (
        "definition_snapshot",
        "mission_revision",
        "compiled_program",
        "ledger_commit",
        "mission_event",
        "budget_entry",
        "delivery_report",
        "operation_receipt",
        "continuation_checkpoint",
        "fork_lineage",
        "human_resolution",
        "native_observation",
    ):
        assert table_privileges(db, RUNTIME, table) == SI, table
    (sequence,) = fetch(
        db,
        """
        SELECT has_sequence_privilege($1, 'mission_control.outbox_global_position', 'USAGE')
                 AS runtime,
               has_sequence_privilege($2, 'mission_control.outbox_global_position', 'USAGE')
                 AS family,
               has_sequence_privilege($3, 'mission_control.outbox_global_position', 'USAGE')
                 AS readonly
        """,
        RUNTIME,
        FAMILY,
        READONLY,
    )
    assert dict(sequence) == {"runtime": True, "family": True, "readonly": False}


# --------------------------------------------------------------------- mission chains (0028)

CHAIN_TABLES = ["mission_chain", "chain_link", "authoring_provenance"]


def test_chain_tables_force_rls_and_grant_least_privilege(db: Database) -> None:
    for name, row in table_shape(db, CHAIN_TABLES).items():
        assert (row["relrowsecurity"], row["relforcerowsecurity"]) == (True, True), name
    privileges = {
        (role, table): table_privileges(db, role, table) & {"SELECT", "INSERT", "UPDATE", "DELETE"}
        for role in (RUNTIME, READONLY)
        for table in CHAIN_TABLES
    }
    assert privileges[(READONLY, "mission_chain")] == {"SELECT"}
    assert privileges[(RUNTIME, "authoring_provenance")] == {"INSERT", "SELECT"}
    # Column-limited UPDATE: identity columns are not updatable by the runtime.
    runtime_link_updates = update_columns(db, RUNTIME, "chain_link")
    assert "state" in runtime_link_updates and "bindings" not in runtime_link_updates
    (kinds,) = fetch(
        db,
        "SELECT pg_get_constraintdef(oid) AS definition FROM pg_constraint "
        "WHERE conname = 'mission_relationship_kind_check'",
    )
    for kind in (
        "composition",
        "fork",
        "dependency",
        "supplies",
        "depends_on",
        "parent_of",
        "adopted_from",
        "successor_of",
        "forked_from",
    ):
        assert f"'{kind}'" in kinds["definition"]


# ---------------------------------------------------- approvals and coordinator inbox (0033)

APPROVAL_INBOX_UPDATE_COLUMNS: dict[str, set[str]] = {
    "approval_correlation": {
        "state",
        "reply",
        "reply_digest",
        "close_reason",
        "replayed_from",
        "closed_at",
        "version",
    },
    "governed_effect_intent": {
        "state",
        "reason",
        "claimant_ref",
        "claimed_at",
        "receipt",
        "receipt_digest",
        "version",
        "updated_at",
    },
    "coordinator_inbox": {"next_inbox_seq", "acked_inbox_seq", "version", "updated_at"},
    "coordinator_notification": {
        "inbox_seq",
        "state",
        "actionable",
        "seq_from",
        "seq_to",
        "event_count",
        "anchor_event_id",
        "depth",
        "suppressed_reason",
        "body",
        "sealed_at",
        "acknowledged_at",
        "acknowledged_by_actor_ref",
        "prompt_request_id",
        "prompt_state",
        "prompt_request",
        "prompt_detail",
        "prompted_at",
        "version",
        "updated_at",
    },
    "coordinator_causation": set(),
}


def test_approval_and_inbox_tables_are_scoped_forced_rls_with_declared_grants(
    db: Database,
) -> None:
    tables = list(APPROVAL_INBOX_UPDATE_COLUMNS)
    for name, row in table_shape(db, tables).items():
        policy = assert_tenant_scoped(name, row)
        assert row["public_acl"] == 0, name
        for function in ("ctx_installation_id", "ctx_application_id", "ctx_tenant_id"):
            assert policy.count(function) == 2, (name, policy)  # USING and WITH CHECK
    for table, columns in APPROVAL_INBOX_UPDATE_COLUMNS.items():
        assert table_privileges(db, RUNTIME, table) == SI, table
        assert update_columns(db, RUNTIME, table) == columns, table
        assert table_privileges(db, READONLY, table) == S, table
        assert update_columns(db, READONLY, table) == set(), table
        for role in (FAMILY, CATALOG, OUTBOX, "public"):
            assert table_privileges(db, role, table) == NONE, (role, table)
            assert update_columns(db, role, table) == set(), (role, table)
    # Every foreign key is covered by an index whose leading columns are the FK columns.
    uncovered = fetch(
        db,
        """
        SELECT k.conrelid::regclass::text AS relation, k.conname
        FROM pg_constraint k
        WHERE k.contype = 'f' AND k.conrelid = ANY(
            SELECT ('mission_control.' || t)::regclass FROM unnest($1::text[]) AS t)
          AND NOT EXISTS (
              SELECT 1 FROM pg_index i
              WHERE i.indrelid = k.conrelid
                AND (i.indkey::int2[])[0:cardinality(k.conkey) - 1] = k.conkey)
        """,
        tables,
    )
    assert [dict(row) for row in uncovered] == []
    # The guard functions are not executable by PUBLIC.
    for function in ("governed_effect_intent_guard", "approval_correlation_guard"):
        (row,) = fetch(
            db,
            "SELECT has_function_privilege('public', $1, 'EXECUTE') AS allowed",
            f"mission_control.{function}()",
        )
        assert not row["allowed"], function


# ------------------------------------------------------------------- lane profiles (0030)


async def _revise_lane_profile_as_owner(db: Database) -> None:
    connection = await db.connect()
    try:
        await connection.execute(
            "UPDATE mission_control.lane_profile SET describe = describe "
            "WHERE lane_profile = 'cursor_local'"
        )
    finally:
        await connection.close()


def test_lane_profiles_are_immutable_reference_data(db: Database) -> None:
    """FORCE RLS with one read policy and the `lane_profile_immutable` trigger as CREATE
    TRIGGER left it: even the owner cannot revise a row in place."""

    (table,) = fetch(
        db,
        "SELECT c.relrowsecurity, c.relforcerowsecurity, "
        "(SELECT t.tgenabled::text FROM pg_trigger t WHERE t.tgrelid = c.oid "
        " AND t.tgname = 'lane_profile_immutable') AS trigger_enabled, "
        "(SELECT array_agg(p.polname || ':' || p.polcmd::text) FROM pg_policy p "
        " WHERE p.polrelid = c.oid) AS policies "
        "FROM pg_class c WHERE c.oid = 'mission_control.lane_profile'::regclass",
    )
    assert (table["relrowsecurity"], table["relforcerowsecurity"]) == (True, True)
    # 'O' = enabled in origin and local mode.
    assert table["trigger_enabled"] == "O"
    assert table["policies"] == ["lane_profile_read:r"]
    assert table_privileges(db, RUNTIME, "lane_profile") == S
    with pytest.raises(asyncpg.RestrictViolationError, match="immutable"):
        run(_revise_lane_profile_as_owner(db))
