"""Loop iter-3 F1-G7: a lost database connection is retried, never settled as the unit's failure.

Live runs 4584570b and 0fc6e3b9 failed stages with `ConnectionDoesNotExistError` when the remote
pooler reset a pooled connection during a frame write."""

from __future__ import annotations

from mission_control.application.execution.operations.operation_execution import (
    transient_store_loss,
)


class ConnectionDoesNotExistError(Exception):
    """Same name as asyncpg's; the classifier matches by name (no driver import)."""


class UniqueViolationError(Exception):
    pass


def test_connection_losses_are_transient_anywhere_in_the_cause_chain() -> None:
    assert transient_store_loss(ConnectionDoesNotExistError("closed in the middle"))
    assert transient_store_loss(ConnectionResetError(10054, "forcibly closed"))
    outer = RuntimeError("frame write failed")
    outer.__cause__ = ConnectionResetError("reset")
    assert transient_store_loss(outer)


def test_query_and_application_errors_are_not_transient() -> None:
    assert not transient_store_loss(UniqueViolationError("duplicate key"))
    assert not transient_store_loss(ValueError("bad input"))
    loop = ValueError("self-referencing")
    loop.__context__ = loop
    assert not transient_store_loss(loop)
