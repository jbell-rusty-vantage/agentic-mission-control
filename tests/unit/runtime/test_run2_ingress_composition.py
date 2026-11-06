from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from mission_control.application.authoring.manifest_submit import ManifestSubmitService
from mission_control.application.signals.drainer import DrainDeferred, DrainRejected
from mission_control.bootstrap.ingress_drainer import (
    ProductionLaunchResolver,
    compose_ingress_drainer,
)
from mission_control.contracts.identities import mission_operation_id
from tests.unit.signals.test_drainer import item


class Connection:
    def __init__(self, row):
        self.row = row

    def is_in_transaction(self):
        return True

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, *args):
        pass

    async def fetchrow(self, *args):
        return self.row


class Pool:
    def __init__(self, row):
        self.connection = Connection(row)

    @asynccontextmanager
    async def acquire(self):
        yield self.connection


def setup():
    installation, tenant, credential = uuid4(), uuid4(), uuid4()
    scope = f"mc/{installation}/ai-engineer/{tenant}"
    lifecycle = object.__new__(ManifestSubmitService)
    lifecycle._scope = scope
    service = SimpleNamespace(lifecycle=lifecycle)
    grant = SimpleNamespace(
        actor_id="operator",
        tenant_ids={tenant},
        permissions=frozenset({"mission.author"}),
        authority_refs=frozenset(),
        sponsorship_refs=frozenset({"sponsor"}),
        approval_refs=frozenset(),
    )
    auth = SimpleNamespace(
        binding=SimpleNamespace(installation_id=installation, application_id="ai-engineer"),
        grants=[grant],
    )
    row = {
        "purpose": "mission_request",
        "scopes": ["mission:request"],
        "context": {"manifest_refs": ["probe"]},
        "expires_at": datetime.now(UTC) + timedelta(minutes=1),
        "revoked_at": None,
        "created_by_actor_ref": "operator",
    }
    pool = Pool(row)
    resolver = ProductionLaunchResolver(pool, auth, {scope: service}, {"probe": "trusted manifest"})
    value = replace(
        item(),
        installation_id=installation,
        request_scope=scope,
        credential_ref=f"credential:{credential}",
        payload={
            "manifest_ref": "probe",
            "inputs": {},
            "actor_id": "attacker",
            "permissions": ["admin"],
        },
    )
    return resolver, value, row, pool, auth


@pytest.mark.asyncio
async def test_deployment_grants_not_payload_select_actor():
    resolver, value, _, _, _ = setup()
    launch = await resolver.resolve(value)
    assert launch.actor.actor_id == "operator"
    assert launch.actor.permissions == frozenset({"mission.author"})
    assert launch.manifest_yaml == "trusted manifest"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("revoked_at", datetime.now(UTC), "expired_or_revoked_launch"),
        ("created_by_actor_ref", "removed", "launch_actor_grant_missing"),
        ("context", {"manifest_refs": ["other"]}, "manifest_not_allowed"),
    ],
)
async def test_credential_negatives(field, value, reason):
    resolver, item_value, row, _, _ = setup()
    row[field] = value
    with pytest.raises(DrainRejected, match=reason):
        await resolver.resolve(item_value)


def test_separate_pool_required():
    _, _, _, pool, auth = setup()
    with pytest.raises(ValueError, match="separate pool"):
        compose_ingress_drainer(
            claim_pool=pool,
            runtime_pool=pool,
            request_scope="scope",
            authentication=auth,
            manifest_services={},
            manifests={},
            temporal_client=None,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("product", "generation_current", "reason"),
    [
        ("wrong_api", True, "webhook_product_version_unbound"),
        ("claude_managed", False, "webhook_stale_generation"),
    ],
)
async def test_webhook_product_and_stale_generation_refusal(product, generation_current, reason):
    from unittest.mock import AsyncMock

    from mission_control.bootstrap.ingress_drainer import ProductionIngressEffects

    _resolver, value, _, _, _ = setup()
    row = {
        "run_key": "run",
        "generation": 1,
        "context": {
            "product": product,
            "pins": {"schema": "version"},
            "harness_execution_id": str(uuid4()),
            "operation_workflow_id": mission_operation_id(value.request_scope, "run", "attempt"),
        },
    }
    effects = ProductionIngressEffects(Pool(row), None, None, (value.request_scope,))
    effects._frames = SimpleNamespace(
        existing_execution=AsyncMock(
            return_value=SimpleNamespace(
                native_session_ref="session", lane_profile="claude_managed"
            )
            if generation_current
            else None
        )
    )
    value = replace(value, kind="webhook.anthropic", payload={"resource_ref": "session"})
    with pytest.raises(DrainRejected, match=reason):
        await effects.persist(value)


@pytest.mark.asyncio
async def test_duplicate_webhook_only_wakes_reconciliation():
    from unittest.mock import AsyncMock

    from mission_control.bootstrap.ingress_drainer import ProductionIngressEffects

    _, value, _, _, _ = setup()
    row = {
        "run_key": "run",
        "generation": 1,
        "context": {
            "product": "claude_managed",
            "pins": {"schema": "version"},
            "harness_execution_id": str(uuid4()),
            "operation_workflow_id": mission_operation_id(value.request_scope, "run", "attempt"),
        },
    }
    signal = AsyncMock()
    client = SimpleNamespace(get_workflow_handle=lambda workflow: SimpleNamespace(signal=signal))
    effects = ProductionIngressEffects(Pool(row), None, client, (value.request_scope,))
    effects._frames = SimpleNamespace(
        existing_execution=AsyncMock(
            return_value=SimpleNamespace(
                native_session_ref="session", lane_profile="claude_managed"
            )
        )
    )
    value = replace(
        value,
        kind="webhook.anthropic",
        payload={"resource_ref": "session", "status": "completed", "approved": True},
    )
    from uuid import UUID

    from mission_control.application.execution.harness.state import (
        InMemoryLaneExecutionStateStore,
        LaneExecutionUpdate,
    )
    from mission_control.domain.execution.history_reconciliation import HistoryRequest

    row["session_binding_id"] = uuid4()
    states = InMemoryLaneExecutionStateStore()
    execution = UUID(row["context"]["harness_execution_id"])
    owner = await states.claim_owner(
        value.request_scope,
        execution,
        owner_ref="owner",
        generation=1,
        now=value.received_at,
        lease=timedelta(minutes=5),
    )
    await states.record(
        value.request_scope,
        execution,
        LaneExecutionUpdate(native_session_ref="session", native_turn_ref="turn"),
    )
    effects._states = states
    with pytest.raises(DrainDeferred) as pending:
        await effects.persist(value)
    assert pending.value.after_commit is not None
    value = replace(value, outcome=pending.value.outcome)
    await pending.value.after_commit()
    with pytest.raises(DrainDeferred):
        await effects.persist(value)
    with pytest.raises(DrainDeferred):
        await effects.wake(value)
    assert signal.await_count == 0
    request = HistoryRequest.model_validate(value.outcome["reconciliation_request"])
    await states.acknowledge_history(
        request, owner=owner, cursor="native-event", at=value.received_at
    )
    # Binding revocation after persistence still permits the exact original receipt.
    effects._pool.connection.row = None
    outcome = await effects.persist(value)
    assert outcome["reconciliation_applied"] and outcome["persisted_cursor"] == "native-event"
    tampered = replace(value, ingress_id=uuid4())
    with pytest.raises(DrainRejected, match="receipt_invalid"):
        await effects.persist(tampered)
    await effects.wake(value)
    await effects.wake(value)
    assert signal.await_count == 2
    assert signal.call_args.args == ("ingress_wake", str(value.ingress_id))


@pytest.mark.parametrize("present", [(), ("MC_INGRESS_STORAGE_URL",)])
def test_optional_quarantine_storage_is_all_or_none(monkeypatch, present):
    from mission_control.bootstrap.ingress import quarantine_store

    for name in (
        "MC_INGRESS_STORAGE_URL",
        "MC_INGRESS_QUARANTINE_BUCKET",
        "MC_INGRESS_STORAGE_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    for name in present:
        monkeypatch.setenv(name, "https://fixture.invalid")
    if present:
        with pytest.raises(RuntimeError, match="together"):
            quarantine_store(None)
    else:
        assert quarantine_store(None) is None


def test_slim_ingress_lock_covers_external_imports():
    import runpy
    import tomllib
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    deploy = root / "deployments" / "ingress-vercel"
    vendor = runpy.run_path(str(deploy / "scripts" / "vendor_closure.py"))
    files = vendor["closure"]()
    lock = tomllib.loads((deploy / "uv.lock").read_text())
    assert "yaml" in vendor["external_imports"](files)
    vendor["validate_external_dependencies"](files, lock)
    # Reproduce the deployed failure even though the full test environment has PyYAML.
    missing_yaml = {**lock, "package": [p for p in lock["package"] if p["name"] != "pyyaml"]}
    with pytest.raises(ValueError, match="unlocked external imports.*yaml"):
        vendor["validate_external_dependencies"](files, missing_yaml)
