"""MO-79: restricted ingress -> normal admission -> isolated Temporal, with lost receipt.

The catalog, model/sandbox bindings and actor grant are explicitly disposable fixtures.
No provider is called or qualified. PostgreSQL uses the authorized mct_* fixture and the
1.4.2 SQL release; its fixture attestation is not an installed-release qualification.
The technical stack uses belllabs-run/{run_key} roots through the normal governed handlers;
this is not proof of the scoped deployment root identity or AWS/outside-network access.
Temporal requires an explicitly selected existing CLI, a fresh SQLite file and a free
loopback port. The proof concerns admission/start, never accepted mission completion.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import socket
from contextlib import AsyncExitStack
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import asyncpg
import httpx
import pytest

from mission_control.adapters.auth.jwt import ActorGrant, ApplicationAuthentication
from mission_control.adapters.postgres.ingress import (
    PostgresIngressStore,
    PostgresMintedCredentialStore,
)
from mission_control.adapters.postgres.ingress_drainer import PostgresIngressDrainStore
from mission_control.adapters.postgres.run_control.canonical import begin
from mission_control.adapters.postgres.run_control.cluster_bindings import (
    PostgresRunClusterBindings,
)
from mission_control.adapters.postgres.subscriptions.store import PostgresSubscriptionStore
from mission_control.adapters.storage.control_plane_payloads import InMemoryPayloadStore
from mission_control.application.capabilities.catalog import CatalogService
from mission_control.application.installations.registry import ApplicationBinding
from mission_control.application.secrets.minting import CredentialMinter, LaunchBinding
from mission_control.application.signals.drainer import IngressDrainer
from mission_control.application.signals.service import IngressKeys, SignalIngressService
from mission_control.application.subscriptions.service import SubscriptionService
from mission_control.bootstrap.ingress_drainer import compose_ingress_drainer
from mission_control.bootstrap.manifests import (
    compose_manifest_launch_inputs,
    compose_manifest_service,
)
from mission_control.bootstrap.technical_api import api
from mission_control.contracts.identities import parse_request_scope
from mission_control.domain.authoring.extensions import ExtensionRegistry
from mission_control.domain.authoring.manifest import canonical_manifest_bytes, load_manifest_yaml
from mission_control.interfaces.http.ingress import create_ingress_app
from tests.fixtures.catalog.fast_track_catalog import fast_track_catalog, publish_output_schemas
from tests.fixtures.db_env import db_env_name
from tests.fixtures.manifest_runtime import AUTHOR, ChainScript, chain_components
from tests.fixtures.mission_control_common_db import catalog_scope, ingress_login
from tests.fixtures.mission_control_production_stack import open_postgres_production_stack
from tests.fixtures.rrm009_production_stack import SCOPE, technical_binding
from tests.integration.postgres.test_signal_ingress_postgres import FakeOidc, FakeUploads
from tests.integration.temporal.test_manifest_launch_production import (
    MISSION_2,
    OUTPUT_SCHEMAS,
    evaluable,
    host_pins,
    root_executions,
    write_bindings,
)
from tests.unit.authoring.manifest_launch_fixture import deep_agents_chain

pytestmark = pytest.mark.common_db
ROOT = Path(__file__).resolve().parents[3]
RELEASE = ROOT / "packages/mission-control-db-contract/releases/1.4.2/component"
KEY = parse_request_scope(SCOPE)
PERMISSIONS = AUTHOR.permissions | {"catalog.read"}
PREFIX = f"/v1/ingress/{KEY.application_id}/missions:request"


class LostDrainReceipt(BaseException):
    """Process loss after normal admission/start, before the claim transaction commits."""


def local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def manifest(*, unbound: bool = False) -> str:
    document = load_manifest_yaml(
        evaluable(deep_agents_chain(MISSION_2.read_text(encoding="utf-8")))
    )
    mission = document["missions"][0]
    mission["key"] = "remote-unbound" if unbound else "remote-admission"
    if unbound:
        mission["environment"]["model"]["profile"] = "fixture.unbound"
    return canonical_manifest_bytes({"manifest": "mission/v1", "mission": mission}).decode()


def selected_cli() -> tuple[Path, str]:
    selected = os.environ.get("MISSION_CONTROL_TEMPORAL_CLI", "")
    assert selected and Path(selected).is_file(), "select the existing authorized Temporal CLI"
    executable = Path(selected).resolve()
    return executable, hashlib.sha256(executable.read_bytes()).hexdigest()


async def test_remote_admission_crash_replay_and_current_authority(
    tmp_path, monkeypatch, record_property
):
    executable, executable_digest = await asyncio.to_thread(selected_cli)
    record_property("temporal_cli", str(executable))
    record_property("temporal_cli_sha256", executable_digest)
    monkeypatch.setenv("MISSION_CONTROL_TEMPORAL_CLI", str(executable))
    monkeypatch.setenv("MISSION_CONTROL_E2E_KEEP_DATABASE", "0")
    port = local_port()
    record_property("temporal_loopback_port", port)
    assert not (tmp_path / "temporal.sqlite").exists()
    technical = technical_binding()
    model_log = []
    components = chain_components(technical, ChainScript(request_scope=SCOPE), model_log)
    bindings = tmp_path / "launch-bindings.json"
    await write_bindings(bindings, technical)
    migrations = sorted((RELEASE / "migrations").glob("*.sql"))
    assert migrations and migrations[-1].name.startswith("0044_")
    async with open_postgres_production_stack(
        root=tmp_path,
        monkeypatch=monkeypatch,
        technical_override=technical,
        components=components,
        model_log=model_log,
        migration_paths=migrations,
        component_version="1.4.2",
        temporal_port=port,
        extra_environment={
            "TEMPORAL_TARGET": "local",
            "MANIFEST_LAUNCH_BINDINGS_PATH": str(bindings),
            "CAPABILITY_PINS_PATH": str(host_pins(tmp_path / "capability-pins.json")),
        },
    ) as stack:
        database = stack.database
        assert database is not None
        installed = ApplicationBinding.seal(
            application_id=database.application_id,
            installation_id=database.installation_id,
            binding_version="1",
            supabase_project_ref=database.project_ref,
            database_secret_ref=db_env_name(database.application_id, "RUNTIME_DSN"),
            accepted_issuers={"https://fixture.invalid"},
            accepted_audiences={"mission-control"},
            required_component_version="1.4.2",
        )
        authentication = ApplicationAuthentication(
            binding=installed,
            issuer="https://fixture.invalid",
            audience="mission-control",
            public_jwks_file=tmp_path / "unused-jwks.json",
            grants=(
                ActorGrant(
                    subject="fixture-operator",
                    actor_id=AUTHOR.actor_id,
                    tenant_ids=frozenset({KEY.tenant_id}),
                    permissions=PERMISSIONS,
                    authority_refs=AUTHOR.authority_refs,
                    sponsorship_refs=frozenset({"sponsorship:test"}),
                ),
            ),
        )
        definitions, search = await fast_track_catalog()
        await publish_output_schemas(definitions, OUTPUT_SCHEMAS)
        author = compose_manifest_launch_inputs(
            stack.worker_pool,
            settings=stack.settings,
            application_id=database.application_id,
            run_control=api.state.run_control_service,
            control_plane=stack.control_plane,
            additional=components,
        )
        assert author is not None
        service = compose_manifest_service(
            stack.worker_pool,
            request_scope=SCOPE,
            catalog=CatalogService(
                SCOPE, catalog_scope(database.application_id), definitions, search
            ),
            extensions=ExtensionRegistry(),
            payload_store=InMemoryPayloadStore(),
            run_control=api.state.run_control_service,
            admission_policies=api.state.admission_policy_registry,
            launches=api.state.run_launch_service,
            subscriptions=SubscriptionService(PostgresSubscriptionStore(stack.worker_pool, SCOPE)),
            launch_inputs=author,
            settings=stack.settings,
            application_binding=installed,
        )
        trusted = {"fixture:remote": manifest(), "fixture:unbound": manifest(unbound=True)}
        preflight = await service.preflight(
            trusted["fixture:remote"],
            actor_id=AUTHOR.actor_id,
            permissions=PERMISSIONS,
        )
        assert preflight.ready, preflight.blockers
        async with AsyncExitStack() as resources:
            edge = await asyncpg.create_pool(
                await ingress_login(database),
                min_size=1,
                max_size=3,
                statement_cache_size=0,
            )
            resources.push_async_callback(edge.close)
            claim_pool = await database.pool("mission_control_runtime", max_size=2)
            resources.push_async_callback(claim_pool.close)
            ingress_services = [
                SignalIngressService(
                    PostgresIngressStore(
                        edge, installation_id=database.installation_id, application_id=application
                    ),
                    keys=IngressKeys(
                        environment_key_master=b"fixture-environment-key",
                        cursor_webhook_master=b"fixture-cursor-key",
                        webhook_secrets={},
                    ),
                    oidc=FakeOidc(),
                    uploads=FakeUploads(),
                )
                for application in (database.application_id, "ai-engineer")
            ]
            http = await resources.enter_async_context(
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=create_ingress_app(ingress_services)),
                    base_url="http://offline-ingress",
                )
            )
            credential_store = PostgresMintedCredentialStore(
                stack.worker_pool,
                SCOPE,
                actor_ref=AUTHOR.actor_id,
            )
            minter = CredentialMinter(credential_store)
            token = await minter.mint(
                "mission_request", LaunchBinding(SCOPE), context={"manifest_refs": list(trusted)}
            )
            headers = {"authorization": f"Bearer {token.value}"}
            drainer = compose_ingress_drainer(
                claim_pool=claim_pool,
                runtime_pool=stack.worker_pool,
                request_scope=SCOPE,
                authentication=authentication,
                manifest_services={SCOPE: service},
                manifests=trusted,
                temporal_client=stack.client,
            )

            async def send(key, *, ref="fixture:remote", auth=None, path=PREFIX, inputs=None):
                return await http.post(
                    path,
                    headers=headers if auth is None else auth,
                    json={
                        "idempotency_key": key,
                        "manifest_ref": ref,
                        "inputs": inputs or {},
                    },
                )

            async def queue(key, **kwargs):
                response = await send(key, **kwargs)
                assert response.status_code == 202, response.text
                return UUID(response.json()["request_id"])

            async def status(request_id):
                response = await http.get(f"{PREFIX}/{request_id}", headers=headers)
                assert response.status_code == 200, response.text
                return response.json()

            async def inbox(request_id):
                async with stack.owner_pool.acquire() as connection:
                    return await connection.fetchrow(
                        "SELECT state,attempts,outcome FROM mission_control.ingress_inbox "
                        "WHERE ingress_id=$1",
                        request_id,
                    )

            async def runs():
                async with stack.owner_pool.acquire() as connection:
                    return await connection.fetch(
                        "SELECT run_key,mission_id FROM mission_control.mission_run "
                        "WHERE installation_id=$1 AND application_id=$2 AND tenant_id=$3",
                        KEY.installation_id,
                        KEY.application_id,
                        KEY.tenant_id,
                    )

            forged = await send("forged", auth={"authorization": f"Bearer {token.value}x"})
            assert forged.status_code == 401
            wrong_app = await send("wrong-app", path=PREFIX.replace("biotech", "ai-engineer"))
            assert wrong_app.status_code in {401, 403}
            expired = await CredentialMinter(
                credential_store,
                clock=lambda: datetime.now(UTC) - timedelta(days=30),
            ).mint(
                "mission_request", LaunchBinding(SCOPE), context={"manifest_refs": list(trusted)}
            )
            assert (
                await send(
                    "expired",
                    auth={
                        "authorization": f"Bearer {expired.value}",
                    },
                )
            ).status_code == 401
            assert await runs() == [] and model_log == []

            # Credential authority is re-read by the worker, not frozen by edge acceptance.
            revocable = await minter.mint(
                "mission_request", LaunchBinding(SCOPE), context={"manifest_refs": list(trusted)}
            )
            revoked_id = await queue("revoked", auth={"authorization": f"Bearer {revocable.value}"})
            async with stack.worker_pool.acquire() as connection, connection.transaction():
                await begin(connection, SCOPE)
                await connection.execute(
                    "UPDATE mission_control.ingress_credential SET revoked_at=clock_timestamp() "
                    "WHERE credential_id=$1",
                    UUID(revocable.record.credential_id),
                )
            assert await drainer.drain_once() == 1
            assert (await inbox(revoked_id))["state"] == "rejected"

            # Current installation readiness changes after queueing; no cached success is used.
            stale_id = await queue("stale-prerequisite")
            async with stack.owner_pool.acquire() as connection:
                await connection.execute(
                    "UPDATE mission_control.application_installation SET state='disabled' "
                    "WHERE installation_id=$1",
                    database.installation_id,
                )
            try:
                assert await drainer.drain_once() == 1
            finally:
                async with stack.owner_pool.acquire() as connection:
                    await connection.execute(
                        "UPDATE mission_control.application_installation SET state='active' "
                        "WHERE installation_id=$1",
                        database.installation_id,
                    )
            assert await status(stale_id) == {
                "state": "refused",
                "reason": "launch_prerequisites_unmet",
            }
            assert await runs() == [] and model_log == []

            unbound_id = await queue("unbound", ref="fixture:unbound")
            assert await drainer.drain_once() == 1
            assert await status(unbound_id) == {
                "state": "refused",
                "reason": "launch_binding_unavailable",
            }
            unbound_runs = await runs()
            assert len(unbound_runs) == 1 and model_log == []
            assert await root_executions(stack, unbound_runs[0]["run_key"]) == []
            assert await drainer.drain_once() == 0  # terminal refusal consumes no retry budget

            admitted_id = await queue("admit-once")
            assert (await status(admitted_id))["state"] == "queued"
            assert await queue("admit-once") == admitted_id
            conflict = await send("admit-once", ref="fixture:unbound")
            assert conflict.status_code == 409
            effects = drainer._effects

            class CrashAfterStart:
                async def persist(self, item):
                    await effects.persist(item)
                    raise LostDrainReceipt

                async def wake(self, item):
                    pytest.fail("process already crashed before settlement")

            crashed = IngressDrainer(
                PostgresIngressDrainStore(claim_pool, SCOPE), CrashAfterStart()
            )
            with pytest.raises(LostDrainReceipt):
                await crashed.drain_once()
            crashed_row = await inbox(admitted_id)
            assert (crashed_row["state"], crashed_row["attempts"]) == ("pending", 0)
            after_crash = await runs()
            new_runs = [row for row in after_crash if row not in unbound_runs]
            assert len(new_runs) == 1
            run_key = new_runs[0]["run_key"]
            async with asyncio.timeout(20):
                while not (execution_ids := await root_executions(stack, run_key)):  # noqa: ASYNC110
                    await asyncio.sleep(0.1)
            assert len(execution_ids) == 1
            bound = await PostgresRunClusterBindings(stack.worker_pool).get(SCOPE, run_key)
            assert bound is not None and bound.workflow_id == f"belllabs-run/{run_key}"
            assert bound.cluster.target == "local" and bound.cluster.address == f"127.0.0.1:{port}"
            actual = await stack.client.get_workflow_handle(
                bound.workflow_id,
                run_id=execution_ids[0],
            ).describe()
            assert actual.id == bound.workflow_id and actual.run_id == execution_ids[0]
            assert await drainer.drain_once() == 1
            admitted = await status(admitted_id)
            assert admitted["state"] == "admitted"
            assert admitted["mission_id"] == str(new_runs[0]["mission_id"])
            assert admitted["lifecycle"]
            assert await runs() == after_crash
            assert await queue("admit-once") == admitted_id
            assert await drainer.drain_once() == 0
            assert await root_executions(stack, run_key) == execution_ids
            assert (await inbox(admitted_id))["state"] == "drained"
