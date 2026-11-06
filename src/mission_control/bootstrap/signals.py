"""Signal ingress for a trusted installation binding and its dedicated restricted pool."""

from __future__ import annotations

from urllib.parse import urlsplit
from uuid import UUID

import asyncpg

from mission_control.adapters.postgres.ingress import PostgresIngressStore
from mission_control.application.signals.service import IngressKeys, SignalIngressService
from mission_control.bootstrap.settings import Settings
from mission_control.domain.execution.network_policy import NetworkHosts


def configured_network_hosts(settings: Settings | None) -> NetworkHosts:
    origin = settings.mission_control_signal_ingress_origin if settings is not None else None
    if origin is None:
        return NetworkHosts()
    target = urlsplit(origin)
    if (
        target.scheme != "https"
        or not target.hostname
        or target.username is not None
        or target.password is not None
        or target.query
        or target.fragment
        or target.path not in {"", "/"}
    ):
        raise ValueError("signal ingress origin must be a credential-free HTTPS origin")
    return NetworkHosts(signal_ingress=target.hostname)


async def verify_signal_ingress_pool(pool: asyncpg.Pool) -> None:
    """The edge login has the ingress role and no table-reader or privileged fallback."""

    async with pool.acquire() as connection:
        row = await connection.fetchrow(
            "SELECT rolsuper, rolbypassrls, "
            "pg_has_role(current_user, 'mission_control_ingress', 'MEMBER') AS ingress, "
            "has_table_privilege(current_user, 'mission_control.ingress_credential', 'SELECT') "
            "AS credential_reader FROM pg_roles WHERE rolname = current_user"
        )
    if (
        row is None
        or row["rolsuper"]
        or row["rolbypassrls"]
        or not row["ingress"]
        or row["credential_reader"]
    ):
        raise RuntimeError("signal ingress requires its dedicated restricted ingress login")


def compose_signal_ingress(
    pool: asyncpg.Pool, *, installation_id: UUID, application_id: str
) -> SignalIngressService:
    """Serve run-token ingress; unconfigured provider signing tiers fail closed."""

    return SignalIngressService(
        PostgresIngressStore(pool, installation_id=installation_id, application_id=application_id),
        keys=IngressKeys(),
    )
