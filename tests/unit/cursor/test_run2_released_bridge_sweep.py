# ruff: noqa: ASYNC240, C408
"""Released bridge recovery refuses uncertain ownership; no provider or database calls."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from mission_control.adapters.cursor import bridge_spawn
from mission_control.adapters.cursor.bridge_recovery import (
    sweep_released_cursor_bridges,
)
from mission_control.adapters.postgres.lanes import workspace_leases
from mission_control.application.agentic_components.placement import STATE_ROOT
from mission_control.application.execution.harness.leases import WorkspaceLease
from mission_control.application.workspaces.policy import slot_path

SCOPE = "installation/application/tenant"


def lease(root, **updates):
    now = datetime.now(UTC)
    values = dict(
        lease_id=uuid4(),
        request_scope=SCOPE,
        lease_key="cursor:released",
        lane_profile="cursor_local",
        harness_execution_id=uuid4(),
        generation=1,
        run_id="run",
        attempt_no=1,
        path=str(slot_path(root, SCOPE, "slot")),
        base_ref="HEAD",
        base_commit="a" * 40,
        fence=1,
        expires_at=now - timedelta(hours=1),
        released_at=now,
        slot="slot",
        allocator_ref="owner",
        observed_state="released",
    )
    values.update(updates)
    return WorkspaceLease(**values)


class Store:
    def __init__(self, candidates, protected=False):
        self.candidates = candidates
        self.protected = protected
        self.guarded = []

    async def released_bridge_candidates(self, request_scope, *, allocator_ref, limit):
        assert request_scope == SCOPE and allocator_ref == "owner" and limit <= 64
        return self.candidates

    async def guard_released_bridge(self, candidate, *, allocator_ref, shutdown):
        self.guarded.append(candidate.lease_id)
        if self.protected:
            return False
        await shutdown(candidate)
        return True


async def test_released_only_shutdown_is_bounded_and_retains_files(tmp_path):
    candidate = lease(tmp_path)
    workspace = Path(candidate.path)
    workspace.mkdir(parents=True)
    retained = workspace / "state-receipt"
    retained.write_text("retained")
    calls = []

    async def shutdown(*, workspace, timeout_s):
        calls.append((workspace, timeout_s))
        return "stopped"

    result = await sweep_released_cursor_bridges(
        Store((candidate,)),
        request_scope=SCOPE,
        root=tmp_path,
        allocator_ref="owner",
        shutdown=shutdown,
    )
    assert result[0].disposition == "stopped"
    assert calls == [(workspace, 5)] and retained.read_text() == "retained"


@pytest.mark.parametrize(
    "changes",
    [
        {"released_at": None},
        {"allocator_ref": "foreign"},
        {"path": "/arbitrary/workspace"},
        {"participants": {"helper": "active"}},
        {"request_scope": "foreign"},
        {"slot": None},
    ],
)
async def test_unsafe_or_active_expired_holder_is_never_shutdown(tmp_path, changes):
    candidate = lease(tmp_path, **changes)
    store = Store((candidate,))

    async def forbidden(**kwargs):
        pytest.fail("unsafe shutdown")

    result = await sweep_released_cursor_bridges(
        store,
        request_scope=SCOPE,
        root=tmp_path,
        allocator_ref="owner",
        shutdown=forbidden,
    )
    assert result[0].disposition == "unsafe_path" and not store.guarded


async def test_persistence_refusal_and_native_errors_are_sanitized(tmp_path):
    candidate = lease(tmp_path)

    async def broken(**kwargs):
        raise RuntimeError("secret-token-and-endpoint")

    for protected, disposition in [(True, "protected"), (False, "unavailable")]:
        result = await sweep_released_cursor_bridges(
            Store((candidate,), protected),
            request_scope=SCOPE,
            root=tmp_path,
            allocator_ref="owner",
            shutdown=broken,
        )
        assert result[0].disposition == disposition
        assert "secret-token" not in repr(result)


def row(candidate, desired="released"):
    return dict(
        workspace_lease_id=candidate.lease_id,
        lease_key=candidate.lease_key,
        native_workspace_ref=candidate.path,
        base_commit=candidate.base_commit,
        fencing_token=candidate.fence,
        lease_expires_at=candidate.expires_at,
        patch_ref=None,
        desired_state=desired,
        observed_state=candidate.observed_state,
        cleanup_status="pending",
        detail={
            **workspace_leases._detail(candidate),
            "released_at": candidate.released_at.isoformat() if candidate.released_at else None,
            "participants": candidate.participants,
        },
    )


@pytest.mark.parametrize("completion", ["stopped", "already_absent"])
@pytest.mark.parametrize("protection", ["active", "newer", "participant", "overflow", "none"])
async def test_postgres_guard_rereads_holders_under_acquisition_lock(
    tmp_path,
    monkeypatch,
    protection,
    completion,
):
    candidate = lease(tmp_path)
    other = candidate.model_copy(update={"lease_id": uuid4()})
    desired = "released"
    if protection == "active":
        other = other.model_copy(update={"released_at": None})
        desired = "active"
    elif protection == "newer":
        other = other.model_copy(update={"fence": 2})
    elif protection == "participant":
        other = other.model_copy(update={"participants": {"helper": "active"}})
    events = []

    class Connection:
        @asynccontextmanager
        async def transaction(self):
            yield

        async def fetchrow(self, query, *args):
            assert events == ["lock"]
            return row(candidate)

        async def fetchval(self, query, *args):
            assert events == ["lock", "shutdown"]
            assert "fencing_token=$5" in query and "desired_state='released'" in query
            assert args == ("i", "a", "t", candidate.lease_id, candidate.fence, "owner", completion)
            events.append("receipt")
            return candidate.lease_id

        async def fetch(self, query, *args):
            assert events == ["lock"]
            assert "LIMIT 65" in query and "native_workspace_ref" in query
            return [row(other, desired)] * (65 if protection == "overflow" else 1)

    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield Connection()

    async def begin(*args):
        return ("i", "a", "t")

    async def lock(connection, key):
        assert key == f"workspace_lease:{SCOPE}:slot"
        events.append("lock")

    async def shutdown(locked):
        assert events == ["lock"] and locked.lease_id == candidate.lease_id
        events.append("shutdown")
        return completion

    monkeypatch.setattr(workspace_leases, "begin", begin)
    monkeypatch.setattr(workspace_leases, "advisory_lock", lock)
    stopped = await workspace_leases.PostgresWorkspaceLeaseStore(Pool()).guard_released_bridge(
        candidate,
        allocator_ref="owner",
        shutdown=shutdown,
    )
    assert stopped == (protection == "none")
    assert events == (["lock", "shutdown", "receipt"] if stopped else ["lock"])


async def test_endpoint_shutdown_keeps_discovery_and_never_kills_pid(tmp_path, monkeypatch):
    state = tmp_path / STATE_ROOT
    state.mkdir(parents=True)
    discovery = state / bridge_spawn.DISCOVERY_FILE
    discovery.write_text("private retained discovery")
    calls = []

    class Endpoint:
        url = "http://127.0.0.1:1"
        auth_token = "private-token"

    def load(path, workspace, state_root, *, canonical_identity=False):
        assert canonical_identity is True
        assert path == discovery and workspace == tmp_path and state_root == state
        return Endpoint()

    class Client:
        async def shutdown(self, grace_seconds):
            calls.append("shutdown")

        async def aclose(self):
            calls.append("close")

    monkeypatch.setattr(bridge_spawn, "_load_endpoint", load)
    monkeypatch.setattr(bridge_spawn.AsyncClient, "connect", lambda *args, **kwargs: Client())
    assert await bridge_spawn.shutdown_released_bridge(workspace=tmp_path) == "stopped"
    assert calls == ["shutdown", "close"] and discovery.is_file()


async def test_bad_discovery_and_state_symlink_refuse_before_connect(tmp_path, monkeypatch):
    state = tmp_path / STATE_ROOT
    state.mkdir(parents=True)
    (state / bridge_spawn.DISCOVERY_FILE).write_text("not-json")
    monkeypatch.setattr(
        bridge_spawn.AsyncClient,
        "connect",
        lambda *a, **k: pytest.fail("invalid discovery"),
    )
    with pytest.raises(ValueError):
        await bridge_spawn.shutdown_released_bridge(workspace=tmp_path)


async def test_missing_discovery_is_explicit_absence(tmp_path):
    assert await bridge_spawn.shutdown_released_bridge(workspace=tmp_path) == "already_absent"
    candidate = lease(tmp_path)
    result = await sweep_released_cursor_bridges(
        Store((candidate,)),
        request_scope=SCOPE,
        root=tmp_path,
        allocator_ref="owner",
        shutdown=bridge_spawn.shutdown_released_bridge,
    )
    assert result[0].disposition == "already_absent"


async def test_workspace_redirect_after_enumeration_refuses_even_absent_discovery(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "canonical"
    foreign = tmp_path / "foreign"
    workspace.mkdir()
    foreign.mkdir()
    original = Path.resolve

    def redirected(path, *args, **kwargs):
        return foreign if path == workspace else original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", redirected)
    monkeypatch.setattr(
        bridge_spawn.AsyncClient,
        "connect",
        lambda *a, **k: pytest.fail("foreign endpoint"),
    )
    with pytest.raises(ValueError, match="workspace"):
        await bridge_spawn.shutdown_released_bridge(workspace=workspace)


def test_discovery_foreign_alias_refuses_canonical_identity(tmp_path, monkeypatch):
    import json

    state = tmp_path / STATE_ROOT
    state.mkdir(parents=True)
    discovery = state / bridge_spawn.DISCOVERY_FILE
    endpoint = bridge_spawn.BridgeEndpoint("http://127.0.0.1:1", "private-token")
    bridge_spawn._save_endpoint(discovery, endpoint, tmp_path, state)
    record = json.loads(discovery.read_text())
    foreign_alias = tmp_path / "foreign-alias"
    record["workspace"] = str(foreign_alias)
    discovery.write_text(json.dumps(record))
    original = Path.resolve

    def resolves_same(path, *args, **kwargs):
        return tmp_path if path == foreign_alias else original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolves_same)
    with pytest.raises(RuntimeError, match="another workspace"):
        bridge_spawn._load_endpoint(discovery, tmp_path, state, canonical_identity=True)
