"""W1 D22 (OVE-169): the handle table's operation check is the exact set MC records handles for.

Release 1.6.0 (0055) allowed only six operations, so the trusted path's KS-accepted
``report.observe`` handle (and every seal, decision, review and resolution) was refused by
``knowledge_operation_handle_operation_check``. Release 1.9.0's 0067 replaces the check; this test
binds its SQL to the code that writes the table (``application/knowledge/gateway.py``) and, when
the Knowledge Services checkout is beside this one, to the K01 protocol's handle operations. The
PostgreSQL proof is ``tests/integration/postgres/test_sprint_oc_release_190.py``.
"""

from __future__ import annotations

import os
import re
import typing
from pathlib import Path

import pytest

from mission_control.application.knowledge.operations import (
    NON_EFFECT_HANDLE_OPERATIONS,
    RECORDED_HANDLE_OPERATIONS,
)
from mission_control.contracts.knowledge_assessment import ASSESSMENT_CONTRACTS
from mission_control.contracts.knowledge_protocol import (
    EFFECTFUL_OPERATIONS,
    RESULT_OPERATIONS,
    OperationName,
)

ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "scripts/release_190/0067_knowledge_handle_trusted_operations.sql"
RELEASED = (
    ROOT
    / "packages/mission-control-db-contract/releases/1.8.0/component/migrations"
    / "0055_knowledge_handles_assessment_delivery_attempts.sql"
)
EXPECTED = frozenset(
    {
        "knowledge.read",
        "knowledge.apply",
        "report.register",
        "report.assess",
        "report.derive",
        "verify.claims",
        "report.observe",
        "report.seal",
        "report.decide",
        "report.review",
        "decision.resolve",
    }
)
CONTROL = frozenset({"knowledge.describe", "operation.get", "operation.cancel", "receipt.get"})


def check_set(sql: str, marker: str) -> frozenset[str]:
    """The quoted names of the `operation IN (...)` list following ``marker``."""

    start = sql.index(marker)
    listed = sql[start : sql.index("))", start)]
    return frozenset(re.findall(r"'([a-z]+\.[a-z]+)'", listed.split("IN (", 1)[1]))


def test_the_recorded_set_is_every_writer_path_of_the_handle_table() -> None:
    # `_effect` (effects that answer a handle), `_handle_operation` (non-effect handles) and
    # `trusted` (`knowledge.read` context plus every assessment contract).
    trusted = frozenset(ASSESSMENT_CONTRACTS) | {"knowledge.read"}
    writers = EFFECTFUL_OPERATIONS | NON_EFFECT_HANDLE_OPERATIONS | trusted
    assert writers == RECORDED_HANDLE_OPERATIONS
    assert RECORDED_HANDLE_OPERATIONS == EXPECTED
    # Only the control operations and the result operations (answered in the call: the W1
    # `knowledge.plan_preview`), which never answer a handle, stay outside the table.
    assert (
        frozenset(typing.get_args(OperationName)) - RECORDED_HANDLE_OPERATIONS
        == CONTROL | RESULT_OPERATIONS
    )


def test_migration_0067_checks_exactly_the_recorded_set_and_widens_0055() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "DROP CONSTRAINT knowledge_operation_handle_operation_check" in sql
    added = check_set(sql, "ADD CONSTRAINT knowledge_operation_handle_operation_check")
    assert added == RECORDED_HANDLE_OPERATIONS
    released = check_set(RELEASED.read_text(encoding="utf-8"), "operation text NOT NULL CHECK")
    assert released < added  # additive: every stored row still satisfies the new check
    assert {"report.observe", "report.seal", "report.decide"} <= added - released


def _ks_envelope() -> Path | None:
    """The K01 protocol source: ``MC_KS_CHECKOUT`` (a Knowledge Services checkout, e.g. a
    worktree carrying an unmerged protocol change), else the checkout beside this one."""

    configured = os.environ.get("MC_KS_CHECKOUT")
    if configured:
        return Path(configured) / "packages/knowledge-operation-protocol/src/envelope.ts"
    return next(
        (
            parent / "knowledge-services/packages/knowledge-operation-protocol/src/envelope.ts"
            for parent in ROOT.parents
            if (parent / "knowledge-services/packages/knowledge-operation-protocol").is_dir()
        ),
        None,
    )


def test_the_recorded_set_is_the_k01_protocols_handle_and_receipt_operations() -> None:
    envelope = _ks_envelope()
    if envelope is None or not envelope.is_file():
        pytest.skip("the Knowledge Services checkout is not beside this one")
    text = envelope.read_text(encoding="utf-8")

    def ts_set(name: str) -> frozenset[str]:
        found = re.search(rf"export const {name}[^=]*= new Set\(\[(.*?)\]\)", text, re.DOTALL)
        assert found, name
        return frozenset(re.findall(r'"([a-z]+\.[a-z]+)"', found.group(1)))

    assert ts_set("HANDLE_OPERATIONS") | ts_set("RECEIPT_OPERATIONS") == RECORDED_HANDLE_OPERATIONS


def test_mc_operations_and_result_operations_are_the_k01_protocols() -> None:
    """W1 native write: MC's operation names and its result operations (answered in the call)
    are exactly K01's `OPERATIONS` and `RESULT_OPERATIONS`."""

    envelope = _ks_envelope()
    if envelope is None or not envelope.is_file():
        pytest.skip("the Knowledge Services checkout is not beside this one")
    text = envelope.read_text(encoding="utf-8")
    listed = re.search(r"export const OPERATIONS = \[(.*?)\] as const", text, re.DOTALL)
    assert listed
    operations = frozenset(re.findall(r'"([a-z_]+\.[a-z_]+)"', listed.group(1)))
    if "knowledge.plan_preview" not in operations:
        pytest.xfail(
            "this Knowledge Services checkout predates knowledge.plan_preview (KS f457e8f on "
            "sprint-oc-w1fix-n is unmerged); set MC_KS_CHECKOUT to that worktree"
        )
    results = re.search(
        r"export const RESULT_OPERATIONS[^=]*= new Set\(\[(.*?)\]\)", text, re.DOTALL
    )
    assert results
    assert operations == frozenset(typing.get_args(OperationName))
    assert frozenset(re.findall(r'"([a-z_]+\.[a-z_]+)"', results.group(1))) == RESULT_OPERATIONS
