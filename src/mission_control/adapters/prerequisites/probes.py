"""Read-only provider checks and scoped durable probe receipts; no caller-supplied evidence."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import asyncpg
import httpx
from pydantic import SecretStr

from mission_control.adapters.anthropic_managed.client import ManagedAgentsClient
from mission_control.adapters.openai_agents.client import AgentsApiClient
from mission_control.adapters.postgres.scope import apply_scope
from mission_control.adapters.prerequisites.claude_native import verify_native_claude
from mission_control.adapters.prerequisites.codex_native import verify_native_codex
from mission_control.adapters.prerequisites.cursor_native import verify_native_cursor
from mission_control.adapters.prerequisites.oauth import validate_managed_oauth
from mission_control.application.prerequisites.probes import OwnerProbeBinding, ProbeObservation
from mission_control.application.prerequisites.setup import ProbeUnavailable
from mission_control.application.secrets.broker import SecretBroker
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.prerequisites import OwnerPrerequisiteRecord


class ProviderOwnerProbeExecutor:
    def __init__(
        self,
        broker: SecretBroker,
        pool: asyncpg.Pool,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._broker, self._pool, self._transport = broker, pool, transport

    async def check(
        self, binding: OwnerProbeBinding, record: OwnerPrerequisiteRecord
    ) -> ProbeObservation:
        try:
            async with asyncio.timeout(25):
                return await self._check(binding, record)
        except ProbeUnavailable:
            raise
        except Exception as error:
            # SDK exceptions can contain provider response bodies. Never expose those or keys.
            raise ProbeUnavailable(
                f"trusted {binding.operation} probe failed ({type(error).__name__})"
            ) from None

    async def _check(
        self, binding: OwnerProbeBinding, record: OwnerPrerequisiteRecord
    ) -> ProbeObservation:
        operation = binding.operation
        code = record.prerequisite.verify.probe
        allowed = {
            "managed_agents_access": {"prerequisite:ma1"},
            "agents_api_access": {"prerequisite:oa1"},
            "github_readonly_repository": {"prerequisite:ma4"},
            "github_publication_repository": {"prerequisite:m2", "prerequisite:m3"},
            "broker_names": {"prerequisite:m4", "secret-broker-store: names only"},
            "signed_webhook": {
                "prerequisite:ma2",
                "prerequisite:oa2",
                "missions/probes/claude-managed-webhook@1",
                "missions/probes/codex-agents-webhook@1",
            },
            "signal_receipt": {"prerequisite:m1"},
            "codex_native_auth": {"prerequisite:x4"},
            "codex_native_cli": {"prerequisite:x6"},
            "claude_native_host": {"prerequisite:a8"},
            "cursor_native_host": {"prerequisite:c9"},
        }
        if (
            operation not in {"exercised_environment", "managed_mcp_oauth"}
            and code not in allowed[operation]
        ):
            raise ProbeUnavailable("the probe operation does not prove this prerequisite")
        if operation == "exercised_environment":
            # A generic successful turn does not prove privacy mode, billing or envVars support.
            if code not in {
                "missions/probes/claude-cloud-env@1",
                "missions/probes/codex-cloud-env@1",
            }:
                raise ProbeUnavailable("this prerequisite needs its specific provider probe")
        if operation in {"signed_webhook", "exercised_environment", "signal_receipt"}:
            return await self._receipt(binding, record)
        if operation == "cursor_native_host":
            return verify_native_cursor(binding, record)
        if operation == "claude_native_host":
            return verify_native_claude(binding, record)
        if operation in {"codex_native_auth", "codex_native_cli"}:
            return verify_native_codex(binding, record)
        values = await self._broker.resolve(binding.credentials)
        if len(values) != len(binding.credentials):
            raise ProbeUnavailable("required Secret Broker names are unavailable")
        if operation == "broker_names":
            return self._evidence(binding)
        if len(values) != 1:
            raise ProbeUnavailable("an API probe requires exactly one credential reference")
        key = SecretStr(next(iter(values.values())))
        if operation == "managed_mcp_oauth":
            oauth_client = ManagedAgentsClient(key, transport=self._transport, timeout_s=10)
            try:
                return await validate_managed_oauth(oauth_client, binding, record)
            finally:
                await oauth_client.aclose()
        if operation == "managed_agents_access":
            client = ManagedAgentsClient(key, transport=self._transport, timeout_s=10)
            try:
                await client.list_agents()
            finally:
                await client.aclose()
        elif operation == "agents_api_access":
            agents = AgentsApiClient(key, transport=self._transport, timeout_s=10)
            try:
                document = await agents.retrieve("/agents", operation="owner access probe")
                if not isinstance(document.get("data"), list):
                    raise ProbeUnavailable("Agents API did not return the expected list shape")
            finally:
                await agents.aclose()
        else:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=10, follow_redirects=False
            ) as client_http:
                response = await client_http.get(
                    f"https://api.github.com/repos/{binding.repository}",
                    headers={
                        "Authorization": f"Bearer {key.get_secret_value()}",
                        "Accept": "application/vnd.github+json",
                    },
                )
            response.raise_for_status()
            document = response.json()
            permissions = document.get("permissions", {})
            if document.get("full_name", "").lower() != (binding.repository or "").lower():
                raise ProbeUnavailable("GitHub returned a different repository")
            if not permissions.get("pull"):
                raise ProbeUnavailable("the credential cannot read the selected repository")
            wants_write = operation == "github_publication_repository"
            if bool(permissions.get("push")) != wants_write:
                raise ProbeUnavailable("repository permissions do not match the selected purpose")
        return self._evidence(binding)

    @staticmethod
    def _evidence(binding: OwnerProbeBinding) -> ProbeObservation:
        observed_at = datetime.now(UTC)
        identity = sha256_digest(binding)
        digest = sha256_digest({"binding": identity, "observed_at": observed_at.isoformat()})
        return ProbeObservation(
            f"api-probe:{binding.operation}:binding:{identity}:observation:{digest}", observed_at
        )

    async def _receipt(
        self, binding: OwnerProbeBinding, record: OwnerPrerequisiteRecord
    ) -> ProbeObservation:
        profile = record.prerequisite.blocks[0].lane.value
        async with self._pool.acquire() as connection, connection.transaction():
            await apply_scope(connection, binding.request_scope)
            prepared = await connection.fetchrow(
                "SELECT p.preparation_id, p.readiness, p.generation, p.created_at, "
                "p.updated_at, h.native_identity, u.activation_key "
                "FROM mission_control.environment_preparation p "
                "JOIN mission_control.harness_execution h "
                "ON h.harness_execution_id = p.harness_execution_id "
                "AND h.generation = p.generation "
                "AND h.intended_binding_digest = p.binding_digest "
                "JOIN mission_control.attempt a ON a.attempt_id = h.attempt_id "
                "JOIN mission_control.activation u ON u.activation_id = a.activation_id "
                "JOIN mission_control.mission_run r ON r.run_id = h.run_id "
                "WHERE p.run_key=$1 AND p.binding_digest=$2 AND p.lane_profile=$3 "
                "AND r.run_key=p.run_key AND h.lane_profile=p.lane_profile "
                "AND p.updated_at >= clock_timestamp()-($4 * interval '1 second') "
                "AND p.readiness IN ('discovered','exercised') "
                "ORDER BY p.updated_at DESC LIMIT 1",
                binding.run_key,
                binding.binding_digest,
                profile,
                binding.max_age_seconds,
            )
            if prepared is None:
                raise ProbeUnavailable("no fresh scoped probe run proves the exact sealed binding")
            if binding.operation == "exercised_environment":
                if prepared["readiness"] != "exercised":
                    raise ProbeUnavailable("the probe environment has not been exercised")
                return ProbeObservation(
                    f"preparation:{prepared['preparation_id']}", prepared["updated_at"]
                )
            if binding.operation == "signed_webhook":
                identity = json.loads(prepared["native_identity"] or "{}")
                resource = identity.get("native_session_ref")
                provider = "anthropic" if profile == "claude_managed" else "openai"
                receipt = await connection.fetchrow(
                    "SELECT ingress_id, received_at FROM mission_control.ingress_inbox "
                    "WHERE kind=$1 AND trust_tier='provider_signed' "
                    "AND payload->>'resource_ref'=$2 "
                    "AND received_at>=clock_timestamp()-($3 * interval '1 second') "
                    "AND received_at >= $4 "
                    "AND state IN ('pending','drained') ORDER BY received_at DESC LIMIT 1",
                    f"webhook.{provider}",
                    resource,
                    binding.max_age_seconds,
                    prepared["created_at"],
                )
            else:
                receipt = await connection.fetchrow(
                    "SELECT ingress_id, received_at FROM mission_control.ingress_inbox "
                    "WHERE run_key=$1 AND kind='signal.materialization.observed' "
                    "AND unit_key=$3 AND generation=$4 "
                    "AND trust_tier IN ('run_token','provider_oidc') "
                    "AND received_at>=clock_timestamp()-($2 * interval '1 second') "
                    "AND state IN ('pending','drained') ORDER BY received_at DESC LIMIT 1",
                    binding.run_key,
                    binding.max_age_seconds,
                    prepared["activation_key"],
                    prepared["generation"],
                )
            if receipt is None:
                raise ProbeUnavailable("the probe run has no matching verified ingress delivery")
            return ProbeObservation(
                f"ingress:{receipt['ingress_id']}:preparation:{prepared['preparation_id']}",
                min(receipt["received_at"], prepared["updated_at"]),
            )
