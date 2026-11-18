"""`ProductionLaunchResolver` over a minted launch credential on the disposable database.

A remote mission request names a `mission_request` credential. The resolver reads that
credential on the restricted runtime role and takes the launching actor from the deployment's
grant for the credential's creator, never from the request payload; a revoked credential, a
creator without a grant or a manifest the credential does not allow is refused. The launch
service is a real `ManifestSubmitService`. Moved from
tests/unit/runtime/test_run2_ingress_composition.py, which faked the asyncpg pool and
half-constructed the service with `object.__new__` (OVE-238).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace

import asyncpg
import pytest
import pytest_asyncio

from mission_control.adapters.auth.jwt import ActorGrant, ApplicationAuthentication
from mission_control.adapters.postgres.ingress import PostgresMintedCredentialStore
from mission_control.application.secrets.minting import CredentialMinter, LaunchBinding
from mission_control.application.signals.drainer import DrainItem, DrainRejected
from mission_control.bootstrap.ingress_drainer import ProductionLaunchResolver
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.support.integration.postgres.manifest_submit import Stack
from tests.support.integration.postgres.mission_socket_postgres import ISSUER, binding
from tests.support.unit.signals.drainer import item

pytestmark = pytest.mark.common_db

OPERATOR = "operator"


@dataclass
class Launch:
    db: CommonDatabase
    pool: asyncpg.Pool
    resolver: ProductionLaunchResolver
    item: DrainItem
    credential_id: str

    async def revoke(self) -> None:
        connection = await asyncpg.connect(self.db.owner_dsn)
        try:
            await connection.execute(
                "UPDATE mission_control.ingress_credential SET revoked_at=clock_timestamp() "
                "WHERE credential_id=$1::uuid",
                self.credential_id,
            )
        finally:
            await connection.close()

    async def minted(
        self, *, actor_ref: str = OPERATOR, manifest_refs: tuple[str, ...] = ("probe",)
    ) -> DrainItem:
        """The request naming another credential, minted by `actor_ref` for `manifest_refs`."""

        scope = self.db.scope()
        store = PostgresMintedCredentialStore(self.pool, scope, actor_ref=actor_ref)
        token = await CredentialMinter(store).mint(
            "mission_request", LaunchBinding(scope), context={"manifest_refs": list(manifest_refs)}
        )
        return replace(self.item, credential_ref=f"credential:{token.record.credential_id}")


@pytest_asyncio.fixture
async def launch(common_db: CommonDatabase, tmp_path: Path) -> AsyncIterator[Launch]:
    pool = await common_db.pool("mission_control_runtime")
    try:
        scope = common_db.scope()
        service = await Stack(common_db, pool).build()
        authentication = ApplicationAuthentication(
            binding=binding(common_db),
            issuer=ISSUER,
            audience="authenticated",
            public_jwks_file=tmp_path / "jwks.json",
            grants=(
                ActorGrant(
                    subject=OPERATOR,
                    actor_id=OPERATOR,
                    tenant_ids={common_db.tenants["tenant-1"]},
                    permissions=frozenset({"mission.author"}),
                    sponsorship_refs=frozenset({"sponsor"}),
                ),
            ),
        )
        minter = CredentialMinter(PostgresMintedCredentialStore(pool, scope, actor_ref=OPERATOR))
        token = await minter.mint(
            "mission_request", LaunchBinding(scope), context={"manifest_refs": ["probe"]}
        )
        resolver = ProductionLaunchResolver(
            pool,
            authentication,
            {scope: SimpleNamespace(lifecycle=service)},  # type: ignore[dict-item]
            {"probe": "trusted manifest"},
        )
        value = replace(
            item(),
            installation_id=common_db.installation_id,
            request_scope=scope,
            credential_ref=f"credential:{token.record.credential_id}",
            payload={
                "manifest_ref": "probe",
                "inputs": {},
                "actor_id": "attacker",
                "permissions": ["admin"],
            },
        )
        yield Launch(common_db, pool, resolver, value, token.record.credential_id)
    finally:
        await pool.close()


async def test_deployment_grants_not_the_payload_select_the_actor(launch: Launch) -> None:
    resolved = await launch.resolver.resolve(launch.item)
    assert resolved.actor.actor_id == OPERATOR
    assert resolved.actor.permissions == frozenset({"mission.author"})
    assert resolved.manifest_yaml == "trusted manifest"
    assert resolved.sponsorship_refs == frozenset({"sponsor"})


async def test_a_revoked_credential_is_refused(launch: Launch) -> None:
    await launch.revoke()
    with pytest.raises(DrainRejected, match="expired_or_revoked_launch"):
        await launch.resolver.resolve(launch.item)


async def test_a_creator_without_a_deployment_grant_is_refused(launch: Launch) -> None:
    removed = await launch.minted(actor_ref="removed")
    with pytest.raises(DrainRejected, match="launch_actor_grant_missing"):
        await launch.resolver.resolve(removed)


async def test_a_manifest_the_credential_does_not_allow_is_refused(launch: Launch) -> None:
    other = replace(launch.item, payload={**launch.item.payload, "manifest_ref": "other"})
    with pytest.raises(DrainRejected, match="manifest_not_allowed"):
        await launch.resolver.resolve(other)
    elsewhere = await launch.minted(manifest_refs=("other",))
    with pytest.raises(DrainRejected, match="manifest_not_allowed"):
        await launch.resolver.resolve(elsewhere)
