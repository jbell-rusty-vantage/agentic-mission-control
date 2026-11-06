"""Slim public ingress: restricted PostgreSQL only; no scheduler or provider runtime."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlsplit
from uuid import UUID

import asyncpg
import httpx
from fastapi import FastAPI

from mission_control.adapters.auth.provider_oidc import CursorOidcVerifier, HttpJwks
from mission_control.adapters.postgres.ingress import PostgresIngressStore
from mission_control.adapters.supabase_storage.ingress import SupabaseQuarantineStore
from mission_control.application.signals.service import IngressKeys, SignalIngressService
from mission_control.interfaces.http.ingress import create_ingress_app


def configured_ingress_app() -> FastAPI:
    """Only explicit edge environment inputs are read, and only during startup."""
    app = create_ingress_app(())

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        if os.environ.get("VERCEL_ENV") not in {None, "production"}:
            raise RuntimeError("ingress credentials are production-only")
        installation = UUID(os.environ["MC_INGRESS_INSTALLATION_ID"])
        application_id = os.environ["MC_INGRESS_APPLICATION_ID"]
        origin = os.environ["MC_INGRESS_ORIGIN"]
        parsed = urlsplit(origin)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise RuntimeError("ingress requires a credential-free HTTPS origin")
        pool = await asyncpg.create_pool(
            os.environ["MC_INGRESS_DSN"],
            min_size=1,
            max_size=2,
            statement_cache_size=0,
            command_timeout=10,
            ssl="verify-full",
        )
        try:
            async with pool.acquire() as connection:
                role = await connection.fetchrow(
                    "SELECT rolsuper, rolbypassrls, "
                    "pg_has_role(current_user, 'mission_control_ingress', 'MEMBER') AS ingress, "
                    "has_table_privilege(current_user, 'mission_control.ingress_credential', "
                    "'SELECT') AS credential_reader FROM pg_roles WHERE rolname = current_user"
                )
            if (
                role is None
                or role["rolsuper"]
                or role["rolbypassrls"]
                or not role["ingress"]
                or role["credential_reader"]
            ):
                raise RuntimeError("ingress requires its dedicated restricted role")
            keys = IngressKeys(
                environment_key_master=_bytes("MC_INGRESS_ENVIRONMENT_MASTER"),
                cursor_webhook_master=_bytes("MC_INGRESS_CURSOR_MASTER"),
                webhook_secrets={
                    provider: value
                    for provider in ("anthropic", "openai", "github")
                    if (value := os.environ.get(f"MC_INGRESS_{provider.upper()}_WEBHOOK_SECRET"))
                },
            )
            async with httpx.AsyncClient(timeout=10, follow_redirects=False) as http:
                uploads = quarantine_store(http)
                service = SignalIngressService(
                    PostgresIngressStore(
                        pool, installation_id=installation, application_id=application_id
                    ),
                    keys=keys,
                    uploads=uploads,
                    oidc=CursorOidcVerifier(audience=origin.rstrip("/"), keys=HttpJwks(http)),
                )
                # Router was mounted before startup; install services without duplicating routes.
                application.state.mission_control_ingress = {application_id: service}
                yield
        finally:
            await pool.close()

    app.router.lifespan_context = lifespan
    return app


def _bytes(name: str) -> bytes | None:
    value = os.environ.get(name)
    return value.encode("utf-8") if value else None


def quarantine_store(http: httpx.AsyncClient) -> SupabaseQuarantineStore | None:
    values = tuple(
        os.environ.get(name)
        for name in (
            "MC_INGRESS_STORAGE_URL",
            "MC_INGRESS_QUARANTINE_BUCKET",
            "MC_INGRESS_STORAGE_KEY",
        )
    )
    if not any(values):
        return None
    url, bucket, key = values
    if not url or not bucket or not key:
        raise RuntimeError("ingress upload storage requires URL, bucket and key together")
    return SupabaseQuarantineStore(http, project_url=url, bucket=bucket, credential=key)
