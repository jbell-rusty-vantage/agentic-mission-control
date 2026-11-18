"""Cleanup startup is explicitly scoped, bounded and secret-free."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from mission_control.bootstrap import cursor_bridges
from tests.fixtures.isolated_settings import isolated_settings

PREFIX = "mc/00000000-0000-0000-0000-000000000001/ai-engineer"
SCOPE = PREFIX + "/00000000-0000-0000-0000-000000000002"


async def test_default_does_not_query_or_stop_bridges(tmp_path, monkeypatch):
    monkeypatch.setattr(
        cursor_bridges, "PostgresWorkspaceLeaseStore", lambda _: pytest.fail("query path")
    )
    assert (
        await cursor_bridges.recover_released_cursor_bridges(
            isolated_settings(), None, default_root=tmp_path
        )
        == ()
    )


async def test_selected_scope_and_host_are_forwarded_once(tmp_path, monkeypatch):
    sweep = AsyncMock(return_value=())
    monkeypatch.setattr(cursor_bridges, "sweep_released_cursor_bridges", sweep)
    monkeypatch.setattr(cursor_bridges, "PostgresWorkspaceLeaseStore", lambda pool: pool)
    settings = isolated_settings(
        mission_control_cursor_bridge_sweep_scopes=(SCOPE, SCOPE),
        mission_control_catalog_scope=PREFIX + "/catalog",
        cursor_lease_root=tmp_path,
    )
    await cursor_bridges.recover_released_cursor_bridges(settings, None, default_root=tmp_path)
    sweep.assert_awaited_once()
    values = sweep.call_args.kwargs
    assert values["request_scope"] == SCOPE
    assert values["root"] == tmp_path
    assert values["limit"] == 64
    assert values["allocator_ref"] == cursor_bridges.GitWorkspaceBackend(tmp_path).owner_ref


@pytest.mark.parametrize("scope", ["invalid", SCOPE.replace("ai-engineer", "another-app")])
async def test_wrong_scope_refuses_before_access(scope, tmp_path, monkeypatch):
    monkeypatch.setattr(
        cursor_bridges, "PostgresWorkspaceLeaseStore", lambda _: pytest.fail("query path")
    )
    settings = isolated_settings(
        mission_control_cursor_bridge_sweep_scopes=(scope,),
        mission_control_catalog_scope=PREFIX + "/catalog",
    )
    with pytest.raises(ValueError):
        await cursor_bridges.recover_released_cursor_bridges(settings, None, default_root=tmp_path)


async def test_timeout_is_bounded_and_does_not_log_native_errors(tmp_path, monkeypatch, caplog):
    async def blocked(*args, **kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(cursor_bridges, "sweep_released_cursor_bridges", blocked)
    monkeypatch.setattr(cursor_bridges, "PostgresWorkspaceLeaseStore", lambda pool: pool)
    monkeypatch.setattr(cursor_bridges, "STARTUP_TIMEOUT_S", 0.01)
    settings = isolated_settings(
        mission_control_cursor_bridge_sweep_scopes=(SCOPE,),
        mission_control_catalog_scope=PREFIX + "/catalog",
    )
    assert (
        await cursor_bridges.recover_released_cursor_bridges(settings, None, default_root=tmp_path)
        == ()
    )
    assert "cleanup remains pending" in caplog.text


def test_scope_count_is_bounded():
    with pytest.raises(ValidationError):
        isolated_settings(mission_control_cursor_bridge_sweep_scopes=(SCOPE,) * 17)


@pytest.mark.parametrize("cancelled", [False, True])
async def test_native_error_is_sanitized_but_cancellation_propagates(
    cancelled, tmp_path, monkeypatch, caplog
):
    error = asyncio.CancelledError() if cancelled else RuntimeError("private-fixture-token")
    monkeypatch.setattr(
        cursor_bridges, "sweep_released_cursor_bridges", AsyncMock(side_effect=error)
    )
    monkeypatch.setattr(cursor_bridges, "PostgresWorkspaceLeaseStore", lambda pool: pool)
    settings = isolated_settings(
        mission_control_cursor_bridge_sweep_scopes=(SCOPE,),
        mission_control_catalog_scope=PREFIX + "/catalog",
    )
    with pytest.raises(asyncio.CancelledError if cancelled else RuntimeError) as caught:
        await cursor_bridges.recover_released_cursor_bridges(settings, None, default_root=tmp_path)
    assert "private-fixture-token" not in str(caught.value) + caplog.text
